defmodule Mana.OAuth.ClaudeCode do
  @moduledoc """
  Claude Code API access via OAuth.

  This module provides OAuth2 authentication with Anthropic's Claude Code API,
  supporting both completion and streaming requests with cache_control injection
  for prompt caching optimization.

  ## OAuth Configuration

  The module uses PKCE OAuth flow with the following endpoints:
  - Authorization: https://anthropic.com/oauth/authorize
  - Token exchange: https://anthropic.com/oauth/token
  - API base: https://api.anthropic.com/v1

  ## Beta Headers

  The following Anthropic beta features are enabled:
  - interleaved-thinking-2025-05-14
  - output-128k-2025-02-19
  - prompt-caching-2024-07-31

  ## Usage

  To authenticate and obtain tokens:

      {:ok, tokens} = Mana.OAuth.ClaudeCode.start_oauth()

  To use as a model provider:

      {:ok, response} = Mana.OAuth.ClaudeCode.complete(messages, "claude-sonnet-4-20250514")
      stream = Mana.OAuth.ClaudeCode.stream(messages, "claude-sonnet-4-20250514")

  ## Cache Control

  The module automatically injects cache_control for system messages to enable
  Anthropic's prompt caching feature, reducing costs for repeated context.
  """

  @behaviour Mana.Models.Provider

  require Logger

  alias Mana.OAuth.{Flow, RefreshManager, TokenStore}

  # Anthropic OAuth config
  @client_id "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
  @auth_url "https://anthropic.com/oauth/authorize"
  @token_url "https://anthropic.com/oauth/token"
  @api_base "https://api.anthropic.com/v1"
  @callback_ports 8765..8795
  @scopes "org:create_api_key user:profile user:inference"
  @default_timeout 300_000
  @default_max_tokens 4096

  @beta_headers [
    "interleaved-thinking-2025-05-14",
    "output-128k-2025-02-19",
    "prompt-caching-2024-07-31"
  ]

  @doc """
  Starts the Claude Code OAuth provider.

  This function exists for compatibility with other providers that may
  require process supervision. For Claude Code, this is currently a no-op.
  """
  @spec start_link(keyword()) :: :ignore | {:error, term()}
  def start_link(_opts \\ []) do
    :ignore
  end

  @doc """
  Initiates the OAuth flow for Claude Code authentication.

  This function:
  1. Finds an available port in the range 8765-8795
  2. Generates PKCE parameters
  3. Constructs the authorization URL
  4. Starts a local callback server
  5. Opens the browser for user authorization
  6. Waits for the callback and exchanges the code for tokens

  ## Options

  - `:timeout` - Timeout in milliseconds (default: 300000 = 5 minutes)

  ## Examples

      {:ok, tokens} = Mana.OAuth.ClaudeCode.start_oauth()
      {:ok, tokens} = Mana.OAuth.ClaudeCode.start_oauth(timeout: 600_000)
  """
  @spec start_oauth(keyword()) :: {:ok, map()} | {:error, term()}
  def start_oauth(opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_timeout)
    port = find_available_port()
    pkce = Flow.generate_pkce()

    auth_url =
      "#{@auth_url}?" <>
        URI.encode_query(%{
          client_id: @client_id,
          response_type: "code",
          redirect_uri: "http://localhost:#{port}/callback",
          scope: @scopes,
          code_challenge: pkce.code_challenge,
          code_challenge_method: "S256"
        })

    {:ok, server} = Flow.start_callback_server(port)
    Flow.launch_browser(auth_url)

    receive do
      {:oauth_callback, code} ->
        if Process.alive?(server), do: Process.exit(server, :normal)
        exchange_for_tokens(code, pkce.code_verifier, port)
    after
      timeout ->
        if Process.alive?(server), do: Process.exit(server, :normal)
        {:error, :timeout}
    end
  end

  # Provider behaviour implementation

  @impl true
  @doc """
  Returns the unique provider identifier.
  """
  def provider_id, do: "claude_code"

  @impl true
  @doc """
  Validates the provider configuration.

  Checks if valid Claude Code OAuth tokens exist and are not expired.
  If tokens are expired, attempts to refresh them.

  Returns `:ok` if valid tokens are available, or `{:error, reason}`
  if authentication is required.
  """
  def validate_config(_config) do
    case TokenStore.load("claude_code") do
      {:ok, tokens} ->
        validate_token_or_refresh(tokens)

      {:error, _} ->
        {:error, "No Claude Code token — run /oauth claude_code"}
    end
  end

  defp validate_token_or_refresh(tokens) do
    if TokenStore.expired?(tokens) do
      case refresh_token(tokens) do
        {:ok, _} -> :ok
        error -> error
      end
    else
      :ok
    end
  end

  @impl true
  @doc """
  Performs a completion request to the Claude Code API.

  ## Parameters

  - `messages` - List of message maps with `role` and `content` keys
  - `model` - The model name (e.g., "claude-sonnet-4-20250514")
  - `opts` - Optional keyword list of additional options

  ## Options

  - `:max_tokens` - Maximum tokens to generate (default: 4096)
  - `:temperature` - Sampling temperature (optional)
  - `:system` - System prompt (optional)

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      {:ok, response} = Mana.OAuth.ClaudeCode.complete(messages, "claude-sonnet-4-20250514")

      # Response format:
      # {:ok, %{content: "Hello! How can I help?", usage: %{}, model: "claude"}}
  """
  def complete(messages, model, opts \\ []) do
    case get_token() do
      {:ok, token} ->
        do_complete(messages, model, token, opts)

      error ->
        error
    end
  end

  defp do_complete(messages, model, token, opts) do
    max_tokens = Keyword.get(opts, :max_tokens, @default_max_tokens)

    body = %{
      "model" => model,
      "max_tokens" => max_tokens,
      "messages" => inject_cache_control(convert_messages(messages))
    }

    body = maybe_add_temperature(body, opts)
    body = maybe_add_system_prompt(body, opts)

    headers =
      [
        {"authorization", "Bearer #{token}"},
        {"content-type", "application/json"},
        {"anthropic-version", "2023-06-01"}
      ] ++ Enum.map(@beta_headers, &{"anthropic-beta", &1})

    case Req.post("#{@api_base}/messages", json: body, headers: headers) do
      {:ok, %{status: 200, body: resp}} ->
        {:ok, parse_response(resp)}

      {:ok, %{status: 401}} ->
        if Keyword.get(opts, :retried, false) do
          {:error, "Authentication failed after token refresh"}
        else
          refresh_and_retry(:complete, messages, model, Keyword.put(opts, :retried, true))
        end

      {:ok, %{status: status, body: body}} ->
        {:error, "Claude Code API error: #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, "Request failed: #{inspect(reason)}"}
    end
  end

  @impl true
  @doc """
  Performs a streaming completion request to the Claude Code API.

  Returns an `Enumerable.t()` that yields stream events:
  - `{:part_start, :message}` - Message stream starting
  - `{:part_start, :content}` - Content stream starting
  - `{:part_delta, :content, text}` - Content chunk
  - `{:part_end, :content}` - Content stream complete
  - `{:part_end, :message}` - Message stream complete
  - `{:part_end, :done}` - Entire response complete
  - `{:error, reason}` - Error occurred

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      stream = Mana.OAuth.ClaudeCode.stream(messages, "claude-sonnet-4-20250514")

      Enum.each(stream, fn event ->
        case event do
          {:part_delta, :content, text} -> IO.write(text)
          {:part_end, :done} -> IO.puts("\nDone!")
          {:error, reason} -> IO.puts("Error: \#{inspect(reason)}")
          _ -> :ok
        end
      end)
  """
  def stream(messages, model, opts \\ []) do
    case get_token() do
      {:ok, token} ->
        do_stream(messages, model, token, opts)

      error ->
        Stream.resource(
          fn -> error end,
          fn
            nil -> {:halt, nil}
            {:error, _} = err -> {[err], nil}
            err -> {[{:error, err}], nil}
          end,
          fn _ -> :ok end
        )
    end
  end

  # Private functions

  defp find_available_port do
    Enum.find(@callback_ports, fn port ->
      case :gen_tcp.listen(port, [:binary, active: false]) do
        {:ok, sock} ->
          :gen_tcp.close(sock)
          true

        {:error, _} ->
          false
      end
    end) || 8765
  end

  defp exchange_for_tokens(code, code_verifier, port) do
    body = %{
      grant_type: "authorization_code",
      code: code,
      redirect_uri: "http://localhost:#{port}/callback",
      client_id: @client_id,
      code_verifier: code_verifier
    }

    case Req.post(@token_url, json: body) do
      {:ok, %{status: 200, body: tokens}} ->
        tokens = add_expires_at(tokens)
        TokenStore.save("claude_code", tokens)
        {:ok, tokens}

      {:ok, %{status: status, body: body}} ->
        {:error, "Token exchange failed: HTTP #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp add_expires_at(tokens) do
    case Map.get(tokens, "expires_in") || Map.get(tokens, :expires_in) do
      nil -> tokens
      expires_in -> Map.put(tokens, "expires_at", System.os_time(:second) + expires_in)
    end
  end

  defp get_token do
    RefreshManager.refresh_if_needed("claude_code", fn tokens ->
      do_refresh_token_call(tokens)
      |> case do
        {:ok, refreshed} -> {:ok, Map.put(refreshed, "access_token", refreshed["access_token"])}
        error -> error
      end
    end)
    |> case do
      {:ok, tokens} -> {:ok, tokens["access_token"]}
      error -> error
    end
  end

  @doc """
  Refreshes the access token using the refresh token.

  This function is public to allow the Heartbeat GenServer to trigger
  token refreshes during long-running agent sessions. Uses RefreshManager
  to serialize refresh attempts and prevent race conditions.
  """
  @spec refresh_token(map()) :: {:ok, String.t()} | {:error, term()}
  def refresh_token(tokens) do
    # Save the provided tokens to the store first so RefreshManager can load them
    :ok = TokenStore.save("claude_code", tokens)

    RefreshManager.execute_refresh("claude_code", fn _loaded_tokens ->
      do_refresh_token_call(tokens)
    end)
    |> case do
      {:ok, new_tokens} -> {:ok, new_tokens["access_token"]}
      error -> error
    end
  end

  defp do_refresh_token_call(%{"refresh_token" => refresh}) do
    body = %{
      grant_type: "refresh_token",
      refresh_token: refresh,
      client_id: @client_id
    }

    case Req.post(@token_url, json: body) do
      {:ok, %{status: 200, body: tokens}} ->
        tokens = add_expires_at(tokens)
        TokenStore.save("claude_code", tokens)
        {:ok, tokens}

      {:ok, %{status: status, body: body}} ->
        {:error, "Refresh failed: HTTP #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp do_refresh_token_call(_), do: {:error, "No refresh token"}

  defp refresh_and_retry(fun_name, messages, model, opts) do
    case RefreshManager.refresh_if_needed("claude_code", fn tokens ->
           do_refresh_token_call(tokens)
         end) do
      {:ok, _tokens} ->
        apply(__MODULE__, fun_name, [messages, model, opts])

      error ->
        error
    end
  end

  defp do_stream(messages, model, token, opts) do
    max_tokens = Keyword.get(opts, :max_tokens, @default_max_tokens)

    body = %{
      "model" => model,
      "max_tokens" => max_tokens,
      "messages" => inject_cache_control(convert_messages(messages)),
      "stream" => true
    }

    body = maybe_add_temperature(body, opts)
    body = maybe_add_system_prompt(body, opts)

    headers =
      [
        {"authorization", "Bearer #{token}"},
        {"content-type", "application/json"},
        {"anthropic-version", "2023-06-01"},
        {"accept", "text/event-stream"}
      ] ++ Enum.map(@beta_headers, &{"anthropic-beta", &1})

    Stream.resource(
      fn ->
        request =
          Req.new(
            method: :post,
            url: "#{@api_base}/messages",
            headers: headers,
            json: body,
            into: :self
          )

        %{request: request, buffer: "", done: false}
      end,
      &stream_next/1,
      fn _state -> :ok end
    )
  end

  defp stream_next(%{done: true} = state), do: {:halt, state}

  defp stream_next(%{request: request} = state) do
    case Req.request(request) do
      {:ok, %{status: 200} = response} ->
        events = process_stream_body(response.body)
        done = stream_complete?(events)
        {events, %{state | done: done}}

      {:ok, %{status: 401}} ->
        {[{:error, "Unauthorized - token may be expired"}], %{state | done: true}}

      {:ok, %{status: status}} ->
        {[{:error, "HTTP #{status}"}], %{state | done: true}}

      {:error, reason} ->
        {[{:error, "Request failed: #{inspect(reason)}"}], %{state | done: true}}
    end
  end

  defp process_stream_body(body) when is_list(body) do
    body
    |> Enum.flat_map(&extract_sse_lines/1)
    |> Enum.map(&parse_sse_data/1)
    |> Enum.flat_map(&parse_anthropic_event/1)
  end

  defp process_stream_body(_), do: []

  defp extract_sse_lines(chunk) do
    chunk
    |> String.split("\n")
    |> Enum.filter(&String.starts_with?(&1, "data: "))
  end

  defp parse_sse_data(line) do
    case String.trim_leading(line, "data: ") do
      "[DONE]" -> :done
      json -> decode_sse_json(json)
    end
  end

  defp decode_sse_json(json) do
    case Jason.decode(json) do
      {:ok, decoded} -> decoded
      {:error, _} -> {:error, "Invalid JSON: #{json}"}
    end
  end

  defp parse_anthropic_event(:done), do: [{:part_end, :done}]
  defp parse_anthropic_event({:error, _} = err), do: [err]

  defp parse_anthropic_event(event) when is_map(event) do
    case event["type"] do
      "message_start" -> [{:part_start, :message}]
      "content_block_start" -> [{:part_start, :content}]
      "content_block_delta" -> parse_content_block_delta(event)
      "content_block_stop" -> [{:part_end, :content}]
      "message_delta" -> [{:part_end, :message}]
      "message_stop" -> [{:part_end, :done}]
      "error" -> parse_error_event(event)
      _ -> []
    end
  end

  defp parse_content_block_delta(event) do
    delta = event["delta"] || %{}

    case delta["text"] do
      nil -> []
      text -> [{:part_delta, :content, text}]
    end
  end

  defp parse_error_event(event) do
    error = event["error"] || %{}
    [{:error, error["message"] || "Unknown error"}]
  end

  defp stream_complete?(events) do
    Enum.any?(events, fn
      {:part_end, :done} -> true
      _ -> false
    end)
  end

  @doc """
  Injects cache_control for system messages to enable Anthropic prompt caching.

  This function adds `cache_control: %{type: "ephemeral"}` to any message
  with role "system" or :system, which enables Anthropic's prompt caching
  feature to reduce costs for repeated context.

  ## Examples

      messages = [%{"role" => "system", "content" => "You are helpful"}]
      cached = Mana.OAuth.ClaudeCode.inject_cache_control(messages)
      # => [%{"role" => "system", "content" => "You are helpful", "cache_control" => %{"type" => "ephemeral"}}]
  """
  @spec inject_cache_control([map()]) :: [map()]
  def inject_cache_control(messages) when is_list(messages) do
    Enum.map(messages, fn msg ->
      role = msg["role"] || msg[:role]

      if role == "system" or role == :system do
        Map.put(msg, "cache_control", %{"type" => "ephemeral"})
      else
        msg
      end
    end)
  end

  def inject_cache_control(messages), do: messages

  defp convert_messages(messages) when is_list(messages) do
    Enum.map(messages, fn msg ->
      case msg do
        %{"role" => role, "content" => content} ->
          %{"role" => to_string(role), "content" => content}

        %{role: role, content: content} ->
          %{"role" => to_string(role), "content" => content}

        _ ->
          msg
      end
    end)
  end

  defp convert_messages(messages), do: messages

  defp parse_response(%{"content" => [%{"text" => text} | _], "usage" => usage}) do
    %{
      content: text,
      usage: usage,
      model: "claude"
    }
  end

  defp parse_response(body) do
    %{
      content: inspect(body),
      usage: %{},
      model: "claude"
    }
  end

  defp maybe_add_temperature(body, opts) do
    case Keyword.get(opts, :temperature) do
      nil -> body
      temp -> Map.put(body, "temperature", temp)
    end
  end

  defp maybe_add_system_prompt(body, opts) do
    case Keyword.get(opts, :system) do
      nil -> body
      system -> Map.put(body, "system", system)
    end
  end
end
