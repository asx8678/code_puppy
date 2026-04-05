defmodule Mana.Streaming.SSEParser do
  @moduledoc """
  Shared Server-Sent Events streaming parser for LLM providers.

  This module extracts the common SSE streaming infrastructure used by
  both Anthropic and OpenAI providers, keeping only provider-specific
  event handling in each provider module.
  """

  alias Mana.Models.Providers.SSE

  @doc """
  Creates a streaming response handler using Stream.resource.

  The `init_fn` is called to start the stream and should return:
  - `{:streaming, resp, buffer}` on success
  - `{:error, message}` on failure

  The `event_mapper` function receives parsed SSE events and should return
  a list of stream events (e.g., `{:part_delta, :content, text}`).

  ## Options

  - `:timeout` - Receive timeout in milliseconds (default: 60_000)

  ## Examples

      SSEParser.stream(
        fn ->
          case Req.request(request) do
            {:ok, %{status: 200} = resp} -> {:streaming, resp, ""}
            {:ok, %{status: 500}} -> {:error, "HTTP 500"}
            {:error, reason} -> {:error, inspect(reason)}
          end
        end,
        &my_event_mapper/1,
        timeout: 60_000
      )
  """
  @spec stream((-> {:streaming, term(), String.t()} | {:error, String.t()}), (term() -> [term()]), keyword()) ::
          Enumerable.t()
  def stream(init_fn, event_mapper, opts \\ []) when is_function(init_fn, 0) and is_function(event_mapper, 1) do
    timeout = Keyword.get(opts, :timeout, 60_000)

    Stream.resource(
      fn ->
        case init_fn.() do
          {:streaming, _resp, _buffer} = state -> state
          {:error, msg} -> {:error, msg}
          other -> {:error, "Invalid init result: #{inspect(other)}"}
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
                  {events, new_buffer} = SSE.parse_chunk(buffer <> chunk)
                  stream_events = Enum.flat_map(events, event_mapper)
                  {stream_events, {:streaming, resp, new_buffer}}

                {:ok, [:done]} ->
                  {[{:part_end, :done}], :halt}

                :unknown ->
                  {[], {:streaming, resp, buffer}}
              end
          after
            timeout -> {[{:error, :timeout}], :halt}
          end
      end,
      fn
        {:streaming, resp, _} -> Req.cancel_async_response(resp)
        _ -> :ok
      end
    )
  end

  @doc """
  Creates an error stream that yields a single error event.

  Used when stream initialization fails before the HTTP request.
  """
  @spec error_stream(String.t() | term()) :: Enumerable.t()
  def error_stream(error) when is_binary(error) do
    Stream.resource(
      fn -> {:error, error} end,
      fn
        nil -> {:halt, nil}
        {:error, _reason} = err -> {[err], nil}
        err -> {[{:error, err}], nil}
      end,
      fn _ -> :ok end
    )
  end

  def error_stream(error) do
    error_stream(inspect(error))
  end

  @doc """
  Builds a standard Req request for streaming.

  ## Options

  - `:method` - HTTP method (default: :post)
  - `:url` - Request URL (required)
  - `:headers` - List of {key, value} header tuples
  - `:body` - Request body (will be JSON encoded)
  - `:receive_timeout` - Timeout in milliseconds (default: 600_000)

  ## Examples

      SSEParser.build_request(
        url: "https://api.openai.com/v1/chat/completions",
        headers: [{"Authorization", "Bearer sk-xxx"}],
        body: %{"model" => "gpt-4", "messages" => [], "stream" => true}
      )
  """
  @spec build_request(keyword()) :: Req.Request.t()
  def build_request(opts \\ []) do
    method = Keyword.get(opts, :method, :post)
    url = Keyword.fetch!(opts, :url)
    headers = Keyword.get(opts, :headers, [])
    body = Keyword.fetch!(opts, :body)
    receive_timeout = Keyword.get(opts, :receive_timeout, 600_000)

    Req.new(
      method: method,
      url: url,
      headers: headers,
      json: body,
      into: :self,
      receive_timeout: receive_timeout
    )
  end

  @doc """
  Executes a streaming request and returns the appropriate stream state.

  Used by providers to standardize response handling for rate limits,
  errors, and successful streaming initiation.

  ## Examples

      SSEParser.init_stream_request(
        request,
        model,
        error_msg: "Rate limited (429)",
        format_fn: &format_error/1
      )
  """
  @spec init_stream_request(Req.Request.t(), String.t(), keyword()) ::
          {:streaming, term(), String.t()} | {:error, String.t()}
  def init_stream_request(request, model, opts \\ []) do
    error_prefix = Keyword.get(opts, :error_msg, "Request failed")
    format_fn = Keyword.get(opts, :format_fn, &SSE.format_error/1)
    report_rate_limit = Keyword.get(opts, :report_rate_limit, true)

    case Req.request(request) do
      {:ok, %{status: 200} = resp} ->
        {:streaming, resp, ""}

      {:ok, %{status: 429} = resp} ->
        if report_rate_limit do
          Mana.RateLimiter.report_rate_limit(model)
        end

        retry_after = SSE.parse_retry_after(resp)
        error_body = format_fn.(resp.body)
        {:error, "#{error_prefix} (429), retry after #{retry_after}s: #{error_body}"}

      {:ok, %{status: status, body: error_body}} ->
        formatted = format_fn.(error_body)
        {:error, "#{error_prefix} (#{status}): #{formatted}"}

      {:error, reason} ->
        {:error, "#{error_prefix}: #{inspect(reason)}"}
    end
  end
end
