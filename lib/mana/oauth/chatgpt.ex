defmodule Mana.OAuth.ChatGPT do
  @moduledoc """
  ChatGPT Codex API access via OAuth.

  This module provides OAuth2 authentication with ChatGPT's Codex API
  (OpenAI's internal API, not api.openai.com), supporting both
  completion and streaming requests via the Responses API format.

  ## OAuth Configuration

  The module uses PKCE OAuth flow with the following endpoints:
  - Authorization: https://auth.openai.com/oauth/authorize
  - Token exchange: https://auth.openai.com/oauth/token
  - API base: https://chatgpt.com/backend-api/codex

  ## Usage

  To authenticate and obtain tokens:

      {:ok, tokens} = Mana.OAuth.ChatGPT.start_oauth()

  To use as a model provider:

      {:ok, response} = Mana.OAuth.ChatGPT.complete(messages, "gpt-4o")
      stream = Mana.OAuth.ChatGPT.stream(messages, "gpt-4o")
  """

  @behaviour Mana.Models.Provider

  require Logger

  alias Mana.OAuth.{Flow, RefreshManager, TokenStore}

  # ChatGPT Codex OAuth config
  @client_id "app_EMoamEEZ73f0CkXaXp7hrann"
  @auth_url "https://auth.openai.com/oauth/authorize"
  @token_url "https://auth.openai.com/oauth/token"
  @api_base "https://chatgpt.com/backend-api/codex"
  @redirect_uri "http://localhost:1455/callback"
  @default_timeout 300_000

  @doc """
  Starts the ChatGPT OAuth provider (no-op for this provider).

  This function exists for compatibility with other providers that may
  require process supervision.
  """
  @spec start_link(keyword()) :: :ignore | {:error, term()}
  def start_link(_opts \\ []) do
    :ignore
  end

  @doc """
  Initiates the OAuth flow for ChatGPT authentication.

  This function:
  1. Generates PKCE parameters
  2. Constructs the authorization URL
  3. Starts a local callback server on port 1455
  4. Opens the browser for user authorization
  5. Waits for the callback and exchanges the code for tokens

  ## Options

  - `:timeout` - Timeout in milliseconds (default: 300000 = 5 minutes)

  ## Examples

      {:ok, tokens} = Mana.OAuth.ChatGPT.start_oauth()
      {:ok, tokens} = Mana.OAuth.ChatGPT.start_oauth(timeout: 600_000)
  """
  @spec start_oauth(keyword()) :: {:ok, map()} | {:error, term()}
  def start_oauth(opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_timeout)
    scopes = "openid profile email"
    pkce = Flow.generate_pkce()

    auth_url =
      "#{@auth_url}?" <>
        URI.encode_query(%{
          client_id: @client_id,
          response_type: "code",
          redirect_uri: @redirect_uri,
          scope: scopes,
          code_challenge: pkce.code_challenge,
          code_challenge_method: "S256",
          state: pkce.state
        })

    {:ok, server} = Flow.start_callback_server(1455, pkce.state)
    Flow.launch_browser(auth_url)

    receive do
      {:oauth_callback, code} ->
        if Process.alive?(server), do: Process.exit(server, :normal)
        exchange_for_tokens(code, pkce.code_verifier)
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
  def provider_id, do: "chatgpt"

  @impl true
  @doc """
  Validates the provider configuration.

  Checks if valid ChatGPT OAuth tokens exist and are not expired.
  If tokens are expired, attempts to refresh them.

  Returns `:ok` if valid tokens are available, or `{:error, reason}`
  if authentication is required.
  """
  def validate_config(_config) do
    case TokenStore.load("chatgpt") do
      {:ok, tokens} ->
        validate_token_or_refresh(tokens)

      {:error, _} ->
        {:error, "No ChatGPT token — run /oauth chatgpt"}
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
  Performs a completion request to the ChatGPT Codex API.

  ## Parameters

  - `messages` - List of message maps with `role` and `content` keys
  - `model` - The model name (e.g., "gpt-4o")
  - `opts` - Optional keyword list of additional options

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      {:ok, response} = Mana.OAuth.ChatGPT.complete(messages, "gpt-4o")

      # Response format:
      # {:ok, %{content: "Hello! How can I help?", usage: %{}, model: "gpt-4o"}}
  """
  def complete(messages, model, opts \\ []) do
    case get_token() do
      {:ok, token} ->
        body = %{
          "model" => model,
          "messages" => convert_messages(messages),
          "store" => false,
          "originator" => "codex_cli_rs"
        }

        req =
          Req.new(
            method: :post,
            url: "#{@api_base}/responses",
            json: body,
            headers: [
              {"authorization", "Bearer #{token}"},
              {"content-type", "application/json"},
              {"chatgpt-account-id", get_account_id(token)}
            ]
          )

        case Req.request(req) do
          {:ok, response} ->
            handle_codex_response(response, messages, model, opts)

          {:error, reason} ->
            {:error, "Request failed: #{inspect(reason)}"}
        end

      error ->
        error
    end
  end

  defp handle_codex_response(%{status: 200, body: body}, _messages, model, _opts) do
    {:ok, parse_codex_response(body, model)}
  end

  defp handle_codex_response(%{status: 401}, messages, model, opts) do
    if Keyword.get(opts, :retried, false) do
      {:error, "Authentication failed after token refresh"}
    else
      refresh_and_retry(:complete, messages, model, Keyword.put(opts, :retried, true))
    end
  end

  defp handle_codex_response(%{status: status, body: body}, _messages, _model, _opts) do
    {:error, "ChatGPT API error: #{status} - #{inspect(body)}"}
  end

  @impl true
  @doc """
  Performs a streaming completion request to the ChatGPT Codex API.

  Returns an `Enumerable.t()` that yields stream events:
  - `{:part_start, :content}` - Content stream starting
  - `{:part_delta, :content, text}` - Content chunk
  - `{:part_end, :content}` - Content stream complete
  - `{:part_end, :done}` - Entire response complete
  - `{:error, reason}` - Error occurred

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      stream = Mana.OAuth.ChatGPT.stream(messages, "gpt-4o")

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
        # Return a stream that yields just the error
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

  defp exchange_for_tokens(code, code_verifier) do
    body = %{
      grant_type: "authorization_code",
      code: code,
      redirect_uri: @redirect_uri,
      client_id: @client_id,
      code_verifier: code_verifier
    }

    case Req.post(@token_url, json: body) do
      {:ok, %{status: 200, body: tokens}} ->
        # Add expires_at if expires_in is present
        tokens =
          case Map.get(tokens, "expires_in") || Map.get(tokens, :expires_in) do
            nil -> tokens
            expires_in -> Map.put(tokens, "expires_at", System.os_time(:second) + expires_in)
          end

        TokenStore.save("chatgpt", tokens)
        {:ok, tokens}

      {:ok, %{status: status, body: body}} ->
        {:error, "Token exchange failed: HTTP #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp get_token do
    RefreshManager.refresh_if_needed("chatgpt", &do_refresh_token/1)
    |> case do
      {:ok, tokens} -> {:ok, tokens["access_token"]}
      error -> error
    end
  end

  defp refresh_token(tokens) do
    do_refresh_token(tokens)
    |> case do
      {:ok, tokens} -> {:ok, tokens["access_token"]}
      error -> error
    end
  end

  defp refresh_and_retry(fun_name, messages, model, opts) do
    # Use RefreshManager to serialize refresh attempts
    case RefreshManager.refresh_if_needed("chatgpt", &do_refresh_token/1) do
      {:ok, _new_tokens} ->
        # Retry the original call
        apply(__MODULE__, fun_name, [messages, model, opts])

      error ->
        error
    end
  end

  defp do_refresh_token(tokens) do
    body = %{
      grant_type: "refresh_token",
      refresh_token: tokens["refresh_token"],
      client_id: @client_id
    }

    case Req.post(@token_url, json: body) do
      {:ok, %{status: 200, body: new_tokens}} ->
        {:ok, new_tokens}

      {:ok, %{status: status}} ->
        {:error, "Token refresh failed: HTTP #{status}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp get_account_id(token) do
    case String.split(token, ".") do
      [_, payload, _] ->
        payload
        |> Base.url_decode64!(padding: false)
        |> Jason.decode!()
        |> Map.get("https://api.openai.com/account_id", "")

      _ ->
        ""
    end
  rescue
    _ -> ""
  end

  defp do_stream(messages, model, token, _opts) do
    body = %{
      "model" => model,
      "messages" => convert_messages(messages),
      "store" => false,
      "originator" => "codex_cli_rs",
      "stream" => true
    }

    headers = [
      {"authorization", "Bearer #{token}"},
      {"content-type", "application/json"},
      {"chatgpt-account-id", get_account_id(token)},
      {"accept", "text/event-stream"}
    ]

    Stream.resource(
      fn ->
        request =
          Req.new(
            method: :post,
            url: "#{@api_base}/responses",
            headers: headers,
            json: body,
            into: :self,
            receive_timeout: 600_000
          )

        case Req.request(request) do
          {:ok, %{status: 200} = resp} ->
            {:streaming, resp, ""}

          {:ok, %{status: 401}} ->
            {:error, "Unauthorized - token may be expired"}

          {:ok, %{status: status}} ->
            {:error, "HTTP #{status}"}

          {:error, reason} ->
            {:error, "Request failed: #{inspect(reason)}"}
        end
      end,
      fn
        {:error, msg} ->
          {[{:error, msg}], :halt}

        :halt ->
          {:halt, :halt}

        {:streaming, resp, buffer} ->
          receive do
            message ->
              case Req.parse_message(resp, message) do
                {:ok, [data: chunk]} ->
                  {events, new_buffer} = parse_chatgpt_sse_chunk(buffer <> chunk)
                  {events, {:streaming, resp, new_buffer}}

                {:ok, [:done]} ->
                  {[{:part_end, :done}], :halt}

                :unknown ->
                  {[], {:streaming, resp, buffer}}
              end
          after
            60_000 -> {[{:error, :timeout}], :halt}
          end
      end,
      fn
        {:streaming, resp, _} -> Req.cancel_async_response(resp)
        _ -> :ok
      end
    )
  end

  defp parse_chatgpt_sse_chunk(data) do
    lines = String.split(data, ~r/\r?\n/)

    {complete_lines, remainder} =
      case List.last(lines) do
        nil ->
          {[], ""}

        last ->
          if String.ends_with?(data, "\n") do
            {lines, ""}
          else
            all_but_last = lines |> Enum.reverse() |> tl() |> Enum.reverse()
            {all_but_last, last}
          end
      end

    events =
      complete_lines
      |> Enum.filter(&String.starts_with?(&1, "data: "))
      |> Enum.flat_map(fn line ->
        json = String.trim_leading(line, "data: ")

        case json do
          "[DONE]" ->
            [{:part_end, :done}]

          _ ->
            case Jason.decode(json) do
              {:ok, decoded} -> parse_codex_stream_event(decoded)
              {:error, _} -> [{:error, "Invalid JSON: #{json}"}]
            end
        end
      end)

    {events, remainder}
  end

  defp parse_codex_stream_event(%{"type" => "response.created"}), do: [{:part_start, :content}]

  defp parse_codex_stream_event(%{"type" => "response.output_item.added", "item" => item}) do
    parse_output_item(item)
  end

  defp parse_codex_stream_event(%{"type" => "response.output_text.delta", "delta" => delta}) do
    text = Map.get(delta, "text", "")
    [{:part_delta, :content, text}]
  end

  defp parse_codex_stream_event(%{"type" => "response.completed"}) do
    [{:part_end, :content}, {:part_end, :done}]
  end

  defp parse_codex_stream_event(%{"type" => "error", "error" => error}) do
    [{:error, Map.get(error, "message", "Unknown error")}]
  end

  defp parse_codex_stream_event(%{"type" => "error"}) do
    [{:error, "Unknown error"}]
  end

  defp parse_codex_stream_event(_event), do: []

  defp parse_output_item(%{"type" => "message"}) do
    [{:part_start, :content}]
  end

  defp parse_output_item(%{"type" => "output_text", "text" => text}) when is_binary(text) do
    [{:part_delta, :content, text}]
  end

  defp parse_output_item(_), do: []

  defp convert_messages(messages) when is_list(messages) do
    Enum.map(messages, fn msg ->
      case msg do
        %{"role" => role, "content" => content} ->
          %{"role" => role, "content" => content}

        %{role: role, content: content} ->
          %{"role" => to_string(role), "content" => content}

        _ ->
          msg
      end
    end)
  end

  defp convert_messages(messages), do: messages

  defp parse_codex_response(%{"output" => output} = body, model) when is_list(output) do
    text =
      output
      |> Enum.filter(&(&1["type"] == "message"))
      |> Enum.flat_map(&(&1["content"] || []))
      |> Enum.filter(&(&1["type"] == "output_text"))
      |> Enum.map_join("\n", &(&1["text"] || ""))

    usage = body["usage"] || %{}

    %{
      content: text,
      usage: usage,
      model: model
    }
  end

  defp parse_codex_response(body, _model) do
    %{content: inspect(body), usage: %{}, model: "unknown"}
  end
end
