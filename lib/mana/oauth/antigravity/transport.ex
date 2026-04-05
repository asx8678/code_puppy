defmodule Mana.OAuth.Antigravity.Transport do
  @moduledoc """
  Custom Req-based transport for the Antigravity API.

  This module handles:
  - API request authentication with OAuth tokens
  - Antigravity envelope unwrapping for responses
  - SSE streaming with proper event parsing
  - Thinking signature handling for Claude models
  - Error handling and rate limit detection

  The Antigravity API uses a unique envelope format that wraps
  standard OpenAI-compatible responses with additional metadata.
  """

  alias Mana.OAuth.TokenStore

  require Logger

  @default_timeout 120_000
  @default_receive_timeout 60_000

  # Whitelist of known SSE content block types.
  # String.to_atom on untrusted data exhausts the BEAM atom table (~1M max, never GC'd).
  @known_block_types %{
    "text" => :text,
    "tool_use" => :tool_use,
    "tool_result" => :tool_result,
    "thinking" => :thinking,
    "image" => :image
  }

  @doc """
  Make an API request with Antigravity envelope handling.

  ## Parameters

  - `method` - HTTP method (:get, :post, :put, :delete)
  - `url` - Full API URL
  - `body` - Request body (will be JSON encoded)
  - `opts` - Request options
    - `:account` - Account ID for token lookup (required)
    - `:timeout` - Request timeout in milliseconds (default: 120000)
    - `:headers` - Additional headers to include

  ## Returns

  - `{:ok, response}` - Successful response with unwrapped envelope
  - `{:error, reason}` - Request failed

  ## Examples

      {:ok, response} = Transport.request(
        :post,
        "https://antigravity.googleapis.com/v1/chat/completions",
        %{"model" => "gemini-3-pro", "messages" => messages},
        account: "my-account"
      )
  """
  @spec request(atom(), String.t(), map(), keyword()) :: {:ok, map()} | {:error, term()}
  def request(method, url, body, opts \\ []) do
    account = opts[:account]

    case get_token(account) do
      {:ok, token} ->
        do_request(method, url, body, token, opts)

      {:error, reason} ->
        {:error, %{type: :token_error, reason: reason}}
    end
  end

  defp do_request(method, url, body, token, opts) do
    connect_timeout = Keyword.get(opts, :connect_timeout, @default_timeout)
    receive_timeout = Keyword.get(opts, :receive_timeout, @default_receive_timeout)
    extra_headers = Keyword.get(opts, :headers, [])

    headers =
      [
        {"authorization", "Bearer #{token}"},
        {"content-type", "application/json"},
        {"accept", "application/json"}
      ] ++ extra_headers

    req =
      Req.new(
        method: method,
        url: url,
        headers: headers,
        json: body,
        connect_options: [timeout: connect_timeout],
        receive_timeout: receive_timeout
      )

    case Req.request(req) do
      {:ok, %{status: 200, body: body}} ->
        {:ok, unwrap_envelope(body)}

      {:ok, %{status: 401, body: body}} ->
        Logger.error("Antigravity authentication failed: #{inspect(body)}")
        {:error, %{status: 401, body: body, reason: :authentication_failed}}

      {:ok, %{status: 429, body: body}} ->
        Logger.warning("Antigravity rate limited")
        {:error, %{status: 429, body: body, reason: :rate_limited}}

      {:ok, %{status: status, body: body}} ->
        {:error, %{status: status, body: body, reason: :http_error}}

      {:error, reason} ->
        {:error, %{reason: reason, type: :request_failed}}
    end
  end

  @doc """
  Stream API responses with SSE envelope unwrapping.

  Returns a Stream that yields parsed SSE events from the Antigravity API.

  ## Events

  - `{:part_start, index, type, metadata}` - Start of a content part
  - `{:part_delta, index, text}` - Text content delta
  - `{:part_end, index, metadata}` - End of a content part
  - `{:error, reason}` - Stream error
  - `{:done}` - Stream complete

  ## Parameters

  - `url` - API endpoint URL
  - `body` - Request body (will be JSON encoded)
  - `opts` - Options
    - `:account` - Account ID for token lookup (required)

  ## Examples

      Transport.stream(
        "https://antigravity.googleapis.com/v1/chat/completions",
        %{"model" => "gemini-3-pro", "messages" => messages, "stream" => true},
        account: "my-account"
      )
      |> Enum.each(fn event ->
        case event do
          {:part_delta, _index, text} -> IO.write(text)
          {:done} -> IO.puts("\\nDone!")
          _ -> :ok
        end
      end)
  """
  @spec stream(String.t(), map(), keyword()) :: Enumerable.t()
  def stream(url, body, opts \\ []) do
    account = opts[:account]

    if is_nil(account) do
      # Return a stream that yields an error
      Stream.resource(
        fn -> nil end,
        fn
          nil -> {[{:error, %{reason: :no_account, message: "No account specified"}}], :done}
          :done -> {:halt, :done}
        end,
        fn _ -> :ok end
      )
    else
      Stream.resource(
        fn -> init_stream_state(url, body, account) end,
        &stream_next/1,
        &cleanup_stream/1
      )
    end
  end

  # Initialize the stream state by making the initial request
  defp init_stream_state(url, body, account) do
    case get_token(account) do
      {:ok, token} ->
        headers = [
          {"authorization", "Bearer #{token}"},
          {"content-type", "application/json"},
          {"accept", "text/event-stream"}
        ]

        request =
          Req.new(
            method: :post,
            url: url,
            headers: headers,
            json: body,
            into: :self,
            receive_timeout: @default_receive_timeout
          )

        handle_stream_request(request)

      {:error, reason} ->
        {:error, %{reason: reason, type: :token_error}}
    end
  end

  # Handle the result of the initial stream request
  defp handle_stream_request(request) do
    case Req.request(request) do
      {:ok, %{status: 200} = resp} ->
        {:streaming, resp, ""}

      {:ok, %{status: status}} ->
        {:error, %{status: status, reason: :http_error}}

      {:error, reason} ->
        {:error, %{reason: reason, type: :request_failed}}
    end
  end

  # Process the next streaming chunk
  defp stream_next({:error, reason}) do
    {[{:error, reason}], :halt}
  end

  defp stream_next(:halt) do
    {:halt, :halt}
  end

  defp stream_next({:streaming, resp, buffer}) do
    receive do
      message ->
        handle_stream_message(resp, buffer, message)
    after
      60_000 -> {[{:error, :timeout}], :halt}
    end
  end

  # Handle a message from the stream
  defp handle_stream_message(resp, buffer, message) do
    case Req.parse_message(resp, message) do
      {:ok, [data: chunk]} ->
        process_stream_chunk(resp, buffer, chunk)

      {:ok, [:done]} ->
        {[], :halt}

      :unknown ->
        {[], {:streaming, resp, buffer}}
    end
  end

  # Process a chunk of stream data
  defp process_stream_chunk(resp, buffer, chunk) do
    chunk_str = if is_binary(chunk), do: chunk, else: to_string(chunk)
    {events, new_buffer} = process_sse_data(buffer <> chunk_str)
    done = Enum.any?(events, &match?({:done}, &1))

    if done do
      {events, :halt}
    else
      {events, {:streaming, resp, new_buffer}}
    end
  end

  # Cleanup the stream resources
  defp cleanup_stream({:streaming, resp, _}) do
    Req.cancel_async_response(resp)
  end

  defp cleanup_stream(_), do: :ok

  # ============================================================================
  # SSE Processing
  # ============================================================================

  @doc """
  Process SSE (Server-Sent Events) data and extract events.

  Returns `{events, remaining_buffer}` where events is a list of parsed
  stream events and remaining_buffer is any incomplete data for the next chunk.
  """
  @spec process_sse_data(String.t()) :: {[term()], String.t()}
  def process_sse_data(data) do
    lines = String.split(data, "\n")

    # Separate complete lines from potential partial line at end
    {complete_lines, remainder} =
      case List.last(lines) do
        nil ->
          {[], ""}

        last ->
          if String.ends_with?(data, "\n") do
            {lines, ""}
          else
            # Last line is incomplete, keep in buffer
            # Drop last element using reverse + tl + reverse
            all_but_last = lines |> Enum.reverse() |> tl() |> Enum.reverse()
            {all_but_last, last}
          end
      end

    events =
      complete_lines
      |> Enum.map(&String.trim/1)
      |> Enum.filter(&(String.starts_with?(&1, "data: ") || &1 != ""))
      |> Enum.flat_map(&parse_sse_line/1)

    {events, remainder}
  end

  defp parse_sse_line("data: [DONE]"), do: [{:done}]
  defp parse_sse_line("data: [DONE]" <> _), do: [{:done}]

  defp parse_sse_line("data: " <> data) do
    case Jason.decode(data) do
      {:ok, parsed} ->
        parse_sse_event(parsed)

      {:error, reason} ->
        Logger.warning("Failed to parse SSE data: #{inspect(reason)}")
        []
    end
  end

  defp parse_sse_line(_), do: []

  defp parse_sse_event(%{"envelope" => envelope} = event) do
    # Handle Antigravity envelope format
    content = Map.get(envelope, "content", [])
    tool_calls = Map.get(envelope, "tool_calls", [])

    events = []
    events = events ++ parse_envelope_content(content)
    events = events ++ parse_envelope_tool_calls(tool_calls)

    # Handle thinking signatures for Claude models
    thinking_events = parse_thinking_content(event)

    events ++ thinking_events
  end

  defp parse_sse_event(%{"choices" => choices}) when is_list(choices) do
    # Standard OpenAI-compatible format
    Enum.flat_map(choices, &parse_choice_delta/1)
  end

  defp parse_sse_event(%{"type" => "content_block_delta", "delta" => delta}) do
    # Anthropic-style streaming
    index = delta["index"] || 0
    text = delta["text"] || ""
    [{:part_delta, index, text}]
  end

  defp parse_sse_event(%{"type" => "message_start"}), do: []
  defp parse_sse_event(%{"type" => "message_stop"}), do: [{:part_end, 0, %{}}]

  defp parse_sse_event(%{"type" => "content_block_start", "index" => index, "content_block" => block}) do
    type = block["type"] || "text"
    [{:part_start, index || 0, safe_block_type(type), %{}}]
  end

  defp parse_sse_event(%{"type" => "content_block_stop", "index" => index}) do
    [{:part_end, index || 0, %{}}]
  end

  defp parse_sse_event(_other), do: []

  defp parse_choice_delta(choice) do
    delta = choice["delta"] || %{}
    finish_reason = choice["finish_reason"]

    events = []
    events = events ++ maybe_content_delta(delta["content"])
    events = events ++ maybe_tool_calls(delta["tool_calls"])
    events = events ++ maybe_finish_event(finish_reason)

    events
  end

  defp maybe_content_delta(nil), do: []
  defp maybe_content_delta(""), do: []
  defp maybe_content_delta(content), do: [{:part_delta, 0, content}]

  defp maybe_tool_calls(nil), do: []
  defp maybe_tool_calls([]), do: []

  defp maybe_tool_calls(tool_calls) when is_list(tool_calls) do
    Enum.flat_map(tool_calls, fn tool_call ->
      case tool_call["function"] do
        nil -> []
        func -> parse_tool_call_delta(func, tool_call["index"] || 0)
      end
    end)
  end

  defp parse_tool_call_delta(func, index) do
    events = []

    events =
      if func["name"] do
        events ++ [{:part_start, {:tool_call, index}, :tool_call, %{name: func["name"]}}]
      else
        events
      end

    events =
      if func["arguments"] do
        events ++ [{:part_delta, {:tool_call, index}, func["arguments"]}]
      else
        events
      end

    events
  end

  defp maybe_finish_event(nil), do: []
  defp maybe_finish_event("stop"), do: [{:part_end, 0, %{}}]
  defp maybe_finish_event("tool_calls"), do: [{:part_end, :tool_calls, %{}}]
  defp maybe_finish_event(_), do: []

  defp parse_envelope_content(content) when is_list(content) do
    Enum.with_index(content, fn item, index ->
      case item do
        %{"type" => "text", "text" => text} ->
          [{:part_start, index, :text, %{}}, {:part_delta, index, text}, {:part_end, index, %{}}]

        %{"text" => text} ->
          [{:part_start, index, :text, %{}}, {:part_delta, index, text}, {:part_end, index, %{}}]

        _other ->
          []
      end
    end)
    |> List.flatten()
  end

  defp parse_envelope_content(_), do: []

  defp parse_envelope_tool_calls(tool_calls) when is_list(tool_calls) do
    Enum.with_index(tool_calls, fn tool_call, index ->
      [{:part_start, {:tool_call, index}, :tool_call, tool_call}, {:part_end, {:tool_call, index}, %{}}]
    end)
    |> List.flatten()
  end

  defp parse_envelope_tool_calls(_), do: []

  defp parse_thinking_content(%{"thinking" => thinking}) when is_map(thinking) do
    # Handle Claude thinking content
    case thinking do
      %{"signature" => sig} when is_binary(sig) and byte_size(sig) > 1000 ->
        # Corrupted signature - bypass by not including thinking content
        Logger.debug("Bypassing corrupted thinking signature")
        []

      %{"content" => content} when is_binary(content) ->
        [{:part_start, :thinking, :thinking, %{}}, {:part_delta, :thinking, content}, {:part_end, :thinking, %{}}]

      _ ->
        []
    end
  end

  defp parse_thinking_content(_), do: []

  # ============================================================================
  # Envelope Unwrapping
  # ============================================================================

  @doc """
  Unwrap the Antigravity envelope format from API responses.

  The Antigravity API wraps responses in an envelope structure that
  contains additional metadata. This function extracts the core content
  while preserving useful metadata.

  ## Examples

      unwrap_envelope(%{
        "envelope" => %{"content" => [%{"text" => "Hello"}], "usage" => %{"tokens" => 10}},
        "model" => "gemini-3-pro"
      })
      # => %{content: "Hello", usage: %{"tokens" => 10}, model: "gemini-3-pro", ...}
  """
  @spec unwrap_envelope(map()) :: map()
  def unwrap_envelope(%{"envelope" => envelope} = response) do
    content = Map.get(envelope, "content", [])
    usage = Map.get(envelope, "usage", %{})
    tool_calls = Map.get(envelope, "tool_calls", [])
    model = response["model"] || envelope["model"]

    %{
      "content" => extract_text_content(content),
      "tool_calls" => tool_calls,
      "usage" => usage,
      "model" => model,
      "raw_envelope" => envelope
    }
  end

  def unwrap_envelope(%{"choices" => _} = response) do
    # Standard OpenAI-compatible format, pass through
    response
  end

  def unwrap_envelope(response), do: response

  defp extract_text_content(content) when is_list(content) do
    content
    |> Enum.filter(&(Map.get(&1, "type") == "text" || Map.has_key?(&1, "text")))
    |> Enum.map_join("", &Map.get(&1, "text", ""))
  end

  defp extract_text_content(%{"text" => text}), do: text
  defp extract_text_content(other), do: other

  # ============================================================================
  # Helper Functions
  # ============================================================================

  defp safe_block_type(type) when is_binary(type) do
    Map.get(@known_block_types, type, :unknown)
  end

  defp get_token(nil), do: {:error, :no_account}

  defp get_token(account) when is_binary(account) do
    provider_key = "antigravity_#{account}"

    case TokenStore.load(provider_key) do
      {:ok, %{"access_token" => token}} ->
        {:ok, token}

      {:ok, %{access_token: token}} ->
        {:ok, token}

      {:error, :not_found} ->
        {:error, :not_found}
    end
  end
end
