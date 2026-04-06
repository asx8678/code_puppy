defmodule Mana.OAuth.Flow do
  @moduledoc """
  Shared PKCE OAuth2 authorization flow.

  This module provides utilities for:
  - Generating PKCE code verifiers and challenges
  - Starting a local callback server to capture authorization codes
  - Launching the browser for user authorization
  - Exchanging authorization codes for access tokens

  ## Example Usage

      {:ok, tokens} = Mana.OAuth.Flow.run_flow(
        "https://provider.com/oauth/authorize?client_id=...",
        "https://provider.com/oauth/token",
        client_id: "my-client-id"
      )
  """

  require Logger

  @default_port 1455
  @default_timeout 300_000

  @doc """
  Generate PKCE code verifier and challenge.

  Returns a map with:
  - `:code_verifier` - The random verifier (43-128 chars)
  - `:code_challenge` - The S256 hash of the verifier
  """
  @spec generate_pkce() :: %{code_verifier: String.t(), code_challenge: String.t(), state: String.t()}
  def generate_pkce do
    code_verifier = Base.url_encode64(:crypto.strong_rand_bytes(32), padding: false)
    code_challenge = Base.url_encode64(:crypto.hash(:sha256, code_verifier), padding: false)
    state = Base.url_encode64(:crypto.strong_rand_bytes(16), padding: false)
    %{code_verifier: code_verifier, code_challenge: code_challenge, state: state}
  end

  @doc """
  Start local callback server on given port.

  The server captures the authorization code from the OAuth callback
  and sends it to the calling process.

  Returns `{:ok, pid}` on success.
  """
  @spec start_callback_server(pos_integer(), String.t() | nil) :: {:ok, pid()} | {:error, term()}
  def start_callback_server(port \\ @default_port, expected_state \\ nil) do
    parent = self()

    # Start a simple TCP listener (bind to localhost only for security)
    case :gen_tcp.listen(port, [{:ip, {127, 0, 0, 1}}, :binary, packet: :line, active: false, reuseaddr: true]) do
      {:ok, listen_socket} ->
        pid =
          spawn_link(fn ->
            accept_loop(listen_socket, parent, expected_state)
          end)

        {:ok, pid}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp accept_loop(listen_socket, parent, expected_state) do
    case :gen_tcp.accept(listen_socket, @default_timeout) do
      {:ok, socket} ->
        handle_connection(socket, parent, expected_state)
        accept_loop(listen_socket, parent, expected_state)

      {:error, :timeout} ->
        Logger.warning("OAuth callback server timed out waiting for connection")
        :gen_tcp.close(listen_socket)

      {:error, _} ->
        :gen_tcp.close(listen_socket)
    end
  end

  defp handle_connection(socket, parent, expected_state) do
    case :gen_tcp.recv(socket, 0, 5000) do
      {:ok, data} ->
        handle_request_data(socket, parent, to_string(data), expected_state)

      {:error, reason} ->
        Logger.warning("Error receiving data from callback: #{inspect(reason)}")
        :gen_tcp.close(socket)
    end
  end

  defp handle_request_data(socket, parent, request, expected_state) do
    case extract_code(request, expected_state) do
      {:ok, code} ->
        send_success_response(socket, parent, code)

      :error ->
        handle_missing_code(socket, request)
    end
  end

  defp send_success_response(socket, parent, code) do
    response = success_html_response()
    :gen_tcp.send(socket, response)
    :gen_tcp.close(socket)
    send(parent, {:oauth_callback, code})
  end

  defp handle_missing_code(socket, request) do
    if String.contains?(request, "favicon") do
      send_not_found(socket)
    else
      send_error_response(socket, "Authorization code not found in callback")
    end
  end

  defp send_not_found(socket) do
    response = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
    :gen_tcp.send(socket, response)
    :gen_tcp.close(socket)
  end

  defp send_error_response(socket, message) do
    response = error_html_response(message)
    :gen_tcp.send(socket, response)
    :gen_tcp.close(socket)
  end

  defp extract_code(request, expected_state) do
    case Regex.run(~r/GET\s+\/callback\?([^\s]+)\s+HTTP/i, request) do
      [_, query_string] ->
        params = URI.decode_query(query_string)
        received_state = Map.get(params, "state")

        cond do
          is_nil(expected_state) ->
            # No state validation requested
            get_code_param(params)

          is_nil(received_state) ->
            Logger.warning("OAuth callback missing state parameter — possible CSRF")
            :error

          secure_compare(received_state, expected_state) ->
            get_code_param(params)

          true ->
            Logger.warning("OAuth state mismatch — possible CSRF attack")
            :error
        end

      _ ->
        :error
    end
  end

  defp get_code_param(params) do
    case Map.get(params, "code") do
      nil -> :error
      code -> {:ok, code}
    end
  end

  defp secure_compare(a, b) when is_binary(a) and is_binary(b) do
    byte_size(a) == byte_size(b) and :crypto.hash(:sha256, a) == :crypto.hash(:sha256, b)
  end

  defp success_html_response do
    body = """
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authorization Successful</title>
      <style>
        body { font-family: system-ui, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center; }
        .success { color: #22c55e; }
        h1 { font-size: 2rem; }
      </style>
    </head>
    <body>
      <h1 class="success">✓ Authorization Successful</h1>
      <p>You can close this window and return to the application.</p>
    </body>
    </html>
    """

    "HTTP/1.1 200 OK\r\n" <>
      "Content-Type: text/html\r\n" <>
      "Content-Length: #{byte_size(body)}\r\n" <>
      "\r\n" <>
      body
  end

  defp error_html_response(message) do
    body = """
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authorization Failed</title>
      <style>
        body { font-family: system-ui, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center; }
        .error { color: #ef4444; }
        h1 { font-size: 2rem; }
      </style>
    </head>
    <body>
      <h1 class="error">✗ Authorization Failed</h1>
      <p>#{escape_html(message)}</p>
      <p>Please try again.</p>
    </body>
    </html>
    """

    "HTTP/1.1 400 Bad Request\r\n" <>
      "Content-Type: text/html\r\n" <>
      "Content-Length: #{byte_size(body)}\r\n" <>
      "\r\n" <>
      body
  end

  defp escape_html(text) do
    text
    |> String.replace("&", "&amp;")
    |> String.replace("<", "&lt;")
    |> String.replace(">", "&gt;")
    |> String.replace("\"", "&quot;")
  end

  @doc """
  Launch browser for authorization.

  Opens the given authorization URL in the system default browser.
  Supports macOS, Linux, and Windows.
  """
  @spec launch_browser(String.t()) :: :ok | {:error, term()}
  def launch_browser(auth_url) do
    cmd =
      case :os.type() do
        {:unix, :darwin} -> "open"
        {:unix, _} -> "xdg-open"
        {:win32, _} -> "start"
      end

    case System.cmd(cmd, [auth_url], stderr_to_stdout: true) do
      {_, 0} -> :ok
      {_, exit_code} -> {:error, "Browser launch failed with exit code #{exit_code}"}
    end
  end

  @doc """
  Exchange authorization code for tokens.

  ## Options

  - `:code_verifier` - The PKCE code verifier (required)
  - `:client_id` - The OAuth client ID (required)
  - `:client_secret` - The OAuth client secret (optional)
  - `:redirect_uri` - The redirect URI (default: "http://localhost:1455/callback")

  ## Examples

      {:ok, tokens} = Mana.OAuth.Flow.exchange_code(
        "auth-code-123",
        "https://provider.com/oauth/token",
        code_verifier: "verifier-xyz",
        client_id: "my-client-id"
      )
  """
  @spec exchange_code(String.t(), String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def exchange_code(code, token_url, opts \\ []) do
    code_verifier = Keyword.fetch!(opts, :code_verifier)
    client_id = Keyword.fetch!(opts, :client_id)
    redirect_uri = Keyword.get(opts, :redirect_uri, "http://localhost:#{@default_port}/callback")

    body = %{
      grant_type: "authorization_code",
      code: code,
      redirect_uri: redirect_uri,
      client_id: client_id,
      code_verifier: code_verifier
    }

    # Add client_secret if provided
    body =
      case Keyword.get(opts, :client_secret) do
        nil -> body
        secret -> Map.put(body, :client_secret, secret)
      end

    case Req.post(token_url, json: body) do
      {:ok, %{status: 200, body: tokens}} ->
        # Add expires_at if expires_in is present
        tokens =
          case Map.get(tokens, "expires_in") || Map.get(tokens, :expires_in) do
            nil -> tokens
            expires_in -> Map.put(tokens, "expires_at", System.os_time(:second) + expires_in)
          end

        {:ok, tokens}

      {:ok, %{status: status, body: body}} ->
        {:error, "Token exchange failed: HTTP #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Run complete OAuth flow.

  This function orchestrates the entire OAuth flow:
  1. Generates PKCE parameters
  2. Starts the callback server
  3. Launches the browser for authorization
  4. Waits for the callback
  5. Exchanges the code for tokens

  ## Options

  - `:port` - Port for callback server (default: 1455)
  - `:timeout` - Timeout in milliseconds (default: 300000 = 5 minutes)
  - `:client_id` - OAuth client ID (required)
  - `:client_secret` - OAuth client secret (optional)
  - `:redirect_uri` - Redirect URI (optional)

  ## Examples

      {:ok, tokens} = Mana.OAuth.Flow.run_flow(
        "https://oauth.example.com/authorize?client_id=...&scope=read",
        "https://oauth.example.com/token",
        client_id: "my-client-id"
      )
  """
  @spec run_flow(String.t(), String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def run_flow(auth_url, token_url, opts \\ []) do
    pkce = generate_pkce()
    port = Keyword.get(opts, :port, @default_port)
    timeout = Keyword.get(opts, :timeout, @default_timeout)

    # Start callback server
    case start_callback_server(port, pkce.state) do
      {:ok, server_pid} ->
        try do
          # Build authorization URL with PKCE params
          auth_url_with_params = add_pkce_to_auth_url(auth_url, pkce.code_challenge, pkce.state)

          # Launch browser
          case launch_browser(auth_url_with_params) do
            :ok ->
              Logger.info("Browser launched for OAuth authorization")

              # Wait for callback
              receive do
                {:oauth_callback, code} ->
                  Logger.info("Received authorization code")

                  # Exchange code for tokens
                  exchange_opts =
                    opts
                    |> Keyword.put(:code_verifier, pkce.code_verifier)
                    |> Keyword.put_new(:redirect_uri, "http://localhost:#{port}/callback")

                  exchange_code(code, token_url, exchange_opts)
              after
                timeout ->
                  {:error, :timeout}
              end

            {:error, reason} ->
              {:error, reason}
          end
        after
          # Ensure server is stopped
          if Process.alive?(server_pid) do
            Process.exit(server_pid, :normal)
          end
        end

      {:error, reason} ->
        {:error, "Failed to start callback server: #{inspect(reason)}"}
    end
  end

  defp add_pkce_to_auth_url(auth_url, code_challenge, state) do
    uri = URI.parse(auth_url)
    existing_params = URI.decode_query(uri.query || "")

    params =
      existing_params
      |> Map.put("code_challenge", code_challenge)
      |> Map.put("code_challenge_method", "S256")
      |> Map.put("state", state)

    %{uri | query: URI.encode_query(params)} |> URI.to_string()
  end
end
