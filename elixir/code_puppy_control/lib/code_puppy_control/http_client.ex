defmodule CodePuppyControl.HttpClient do
  @moduledoc """
  HTTP client with connection pooling, retry logic, and reopenable semantics.

  This module provides a Finch-based HTTP client that handles:
  - Connection pooling via Finch (HTTP/1.1 and HTTP/2 support)
  - Exponential backoff retry for 429/502/503/504 status codes
  - Timeout management
  - Provider-specific handling (e.g., Cerebras ignores aggressive Retry-After)
  - Async-safe request tracking for rate limiting integration

  ## Architecture

  The client is a thin wrapper around Finch that adds:
  1. Retry logic with configurable backoff strategies
  2. Request/response interceptors for telemetry and rate limiting
  3. Connection lifecycle management via Finch pools

  ## Comparison with Python

  | Python (http_utils.py) | Elixir (HttpClient) |
  |------------------------|---------------------|
  | httpx.AsyncClient | Finch HTTP pools |
  | Tenacity/RetryingAsyncClient | Exponential backoff in `request/4` |
  | ReopenableAsyncClient | Automatic pool management via Finch |
  | ProxyConfig | `t:request_options/0` |
  | rate limiter notifications | Telemetry events |

  ## Usage

  Simple request:
      iex> HttpClient.request(:get, "https://api.example.com/data")
      {:ok, %{status: 200, body: "...", headers: [...]}}

  With options:
      iex> HttpClient.request(:post, "https://api.example.com/data",
      ...>   headers: [{"authorization", "Bearer token"}],
      ...>   body: ~s({"key": "value"}),
      ...>   retries: 3
      ...> )

  Streaming response:
      iex> HttpClient.stream(:get, "https://api.example.com/large-file")
      {:ok, stream}  # Returns a Stream that yields data chunks

  ## Configuration

  The Finch pool is started by the supervision tree with these defaults:
  - Pool size: 50 connections
  - Pool count: 1 per scheduler
  - Connect timeout: 30s
  - Receive timeout: 180s (configurable per request)

  See `CodePuppyControl.HttpClient.Config` for environment variable configuration.
  """

  require Logger

  alias CodePuppyControl.HttpClient.Config
  alias Finch.Response

  @default_retries 5
  @default_retry_status_codes [429, 502, 503, 504]
  @default_base_backoff_ms 1000
  @cerebras_base_backoff_ms 3000
  @max_backoff_ms 60_000

  @typedoc "HTTP method"
  @type method :: :get | :post | :put | :patch | :delete | :head | :options

  @typedoc "Request options"
  @type request_options :: [
          headers: [{String.t(), String.t()}],
          body: String.t() | nil,
          timeout: non_neg_integer(),
          retries: non_neg_integer(),
          retry_status_codes: [non_neg_integer()],
          model_name: String.t() | nil,
          ignore_retry_headers: boolean(),
          pool_timeout: non_neg_integer()
        ]

  @typedoc "Response structure"
  @type response :: %{
          status: non_neg_integer(),
          body: String.t(),
          headers: [{String.t(), String.t()}]
        }

  @typedoc "Client error - error tuple with descriptive message"
  @type error :: {:error, String.t()}

  # ============================================================================
  # Delegate config functions to Config module
  # ============================================================================

  defdelegate child_spec(opts \\ []), to: Config
  defdelegate default_pool_name(), to: Config
  defdelegate auth_headers(token), to: Config
  defdelegate json_headers(), to: Config
  defdelegate resolve_config_from_env(), to: Config

  # ============================================================================
  # HTTP Methods
  # ============================================================================

  @doc """
  Makes a GET request.

  ## Examples

      iex> HttpClient.get("https://api.example.com/users")
      {:ok, %{status: 200, body: "...", headers: []}}

      iex> HttpClient.get("https://api.example.com/users", headers: [{"accept", "application/json"}])
      {:ok, %{status: 200, body: "...", headers: []}}
  """
  @spec get(String.t(), keyword()) :: {:ok, response()} | error()
  def get(url, opts \\ []), do: request(:get, url, opts)

  @doc """
  Makes a POST request.

  ## Examples

      iex> HttpClient.post("https://api.example.com/users", body: ~s({"name": "Alice"}))
      {:ok, %{status: 201, body: "...", headers: []}}
  """
  @spec post(String.t(), keyword()) :: {:ok, response()} | error()
  def post(url, opts \\ []), do: request(:post, url, opts)

  @doc """
  Makes a PUT request.
  """
  @spec put(String.t(), keyword()) :: {:ok, response()} | error()
  def put(url, opts \\ []), do: request(:put, url, opts)

  @doc """
  Makes a PATCH request.
  """
  @spec patch(String.t(), keyword()) :: {:ok, response()} | error()
  def patch(url, opts \\ []), do: request(:patch, url, opts)

  @doc """
  Makes a DELETE request.
  """
  @spec delete(String.t(), keyword()) :: {:ok, response()} | error()
  def delete(url, opts \\ []), do: request(:delete, url, opts)

  @doc """
  Makes a HEAD request.
  """
  @spec head(String.t(), keyword()) :: {:ok, response()} | error()
  def head(url, opts \\ []), do: request(:head, url, opts)

  @doc """
  Makes an OPTIONS request.
  """
  @spec options(String.t(), keyword()) :: {:ok, response()} | error()
  def options(url, opts \\ []), do: request(:options, url, opts)

  # ============================================================================
  # Core Request with Retry Logic
  # ============================================================================

  @doc """
  Makes an HTTP request with automatic retry handling.

  ## Options

  - `:headers` - List of `{name, value}` tuples (default: `[]`)
  - `:body` - Request body as string (default: `nil`)
  - `:timeout` - Request timeout in milliseconds (default: `180_000`)
  - `:retries` - Maximum number of retries (default: `5`)
  - `:retry_status_codes` - Status codes to retry (default: `[429, 502, 503, 504]`)
  - `:model_name` - Model name for provider-specific handling (default: `nil`)
  - `:ignore_retry_headers` - Ignore Retry-After headers (default: auto-detected from model_name)
  - `:pool_timeout` - Pool checkout timeout in milliseconds (default: `5_000`)

  ## Retry Behavior

  - Exponential backoff: 1s, 2s, 4s, 8s, 16s...
  - Cerebras provider: Uses 3s base (3s, 6s, 12s...) and ignores Retry-After
  - Maximum wait: 60 seconds per attempt
  - Respects Retry-After headers (unless ignored)

  ## Examples

      iex> HttpClient.request(:get, "https://api.openai.com/v1/models", [
      ...>   headers: [{"authorization", "Bearer sk-..."}],
      ...>   model_name: "gpt-4"
      ...> ])

      iex> HttpClient.request(:post, "https://api.cerebras.ai/v1/chat/completions", [
      ...>   headers: [
      ...>     {"authorization", "Bearer ..."},
      ...>     {"content-type", "application/json"}
      ...>   ],
      ...>   body: ~s({"model": "llama3.1-70b"}),
      ...>   model_name: "cerebras-llama3.1-70b",
      ...>   retries: 3
      ...> ])
  """
  @spec request(method(), String.t(), keyword()) :: {:ok, response()} | error()
  def request(method, url, opts \\ []) do
    headers = Keyword.get(opts, :headers, [])
    body = Keyword.get(opts, :body, nil)
    timeout = Keyword.get(opts, :timeout, 180_000)
    pool_timeout = Keyword.get(opts, :pool_timeout, 5_000)
    max_retries = Keyword.get(opts, :retries, @default_retries)
    retry_codes = Keyword.get(opts, :retry_status_codes, @default_retry_status_codes)
    model_name = Keyword.get(opts, :model_name, "")

    # Auto-detect Cerebras special handling
    ignore_retry_headers =
      Keyword.get(opts, :ignore_retry_headers, cerebras?(model_name))

    req = build_finch_request(method, url, headers, body)

    do_request_with_retry(
      req,
      pool_timeout,
      timeout,
      max_retries,
      retry_codes,
      model_name,
      ignore_retry_headers,
      0
    )
  end

  @doc """
  Streams an HTTP request, yielding chunks as they arrive.

  Returns a `Stream` that yields elements according to this contract:

  - `{:data, chunk}` — Data chunk received from the server (**2xx only**)
  - `{:done, %{status: status, headers: headers}}` — Stream completed successfully (**2xx only**)
  - `{:error, reason}` — Transport error or non-2xx status

  For non-2xx responses, the stream yields a single `{:error, %{status: s, body: b, headers: h}}`
  element. No `{:data, ...}` or `{:done, ...}` elements are emitted for non-2xx.

  For transport errors (connection refused, timeout, etc.), the stream yields
  `{:error, "descriptive message"}`.

  ## Example

      stream = HttpClient.stream(:get, "https://api.example.com/sse")
      Enum.reduce(stream, "", fn
        {:data, chunk}, acc -> acc <> chunk
        {:done, _meta}, acc -> acc
        {:error, reason}, _acc -> raise "stream error: \#{inspect(reason)}"
      end)

  ## Options

  Same as `request/3` (minus `:retries`, `:retry_status_codes`, `:model_name`,
  and `:ignore_retry_headers` which are request-only).
  """
  @spec stream(method(), String.t(), keyword()) :: Enumerable.t()
  def stream(method, url, opts \\ []) do
    headers = Keyword.get(opts, :headers, [])
    body = Keyword.get(opts, :body, nil)
    timeout = Keyword.get(opts, :timeout, 180_000)
    pool_timeout = Keyword.get(opts, :pool_timeout, 5_000)

    Stream.resource(
      fn -> start_stream(method, url, headers, body, pool_timeout, timeout) end,
      &next_stream_element/1,
      &close_stream/1
    )
  end

  # ── Stream internals ─────────────────────────────────────────────────────

  # Spawns a process that runs Finch.stream and sends chunks to the caller.
  # This avoids the broken pattern of returning Stream-resource tuples from
  # inside the Finch callback — Finch callbacks must return {:cont, acc}.
  defp start_stream(method, url, headers, body, pool_timeout, timeout) do
    parent = self()
    ref = make_ref()

    pid =
      spawn(fn ->
        run_finch_stream(parent, ref, method, url, headers, body, pool_timeout, timeout)
      end)

    mon_ref = Process.monitor(pid)
    {pid, mon_ref, ref, timeout}
  end

  # Runs Finch.stream in a separate process, sending data chunks to the parent
  # via message passing. For 2xx responses, chunks are sent immediately.
  # For non-2xx, the body is accumulated and sent as a single error element.
  defp run_finch_stream(parent, ref, method, url, headers, body, pool_timeout, timeout) do
    pool_name = Config.default_pool_name()
    req = build_finch_request(method, url, headers, body)

    initial_acc = %{status: nil, headers: [], body_parts: []}

    result =
      Finch.stream(
        req,
        pool_name,
        initial_acc,
        fn
          {:status, status}, acc ->
            {:cont, %{acc | status: status}}

          {:headers, resp_headers}, acc ->
            {:cont, %{acc | headers: resp_headers}}

          {:data, data}, acc ->
            if acc.status in 200..299 do
              send(parent, {ref, {:data, data}})
              {:cont, acc}
            else
              # Non-2xx: accumulate body instead of streaming to parent
              {:cont, %{acc | body_parts: [data | acc.body_parts]}}
            end
        end,
        pool_timeout: pool_timeout,
        receive_timeout: timeout
      )

    case result do
      {:ok, %{status: status, headers: resp_headers}} when status in 200..299 ->
        send(parent, {ref, {:done, %{status: status, headers: resp_headers}}})

      {:ok, %{status: status, headers: resp_headers, body_parts: body_parts}} ->
        body = body_parts |> Enum.reverse() |> Enum.join()
        send(parent, {ref, {:error, %{status: status, headers: resp_headers, body: body}}})

      {:error, reason} ->
        send(parent, {ref, {:transport_error, reason}})
    end
  rescue
    e ->
      send(parent, {ref, {:transport_error, Exception.message(e)}})
  end

  # Receives the next element from the spawned stream process.
  defp next_stream_element({pid, mon_ref, ref, timeout} = state) do
    receive do
      {^ref, {:data, chunk}} ->
        {[{:data, chunk}], state}

      {^ref, {:done, metadata}} ->
        Process.demonitor(mon_ref, [:flush])
        {[{:done, metadata}], :done}

      {^ref, {:error, details}} ->
        Process.demonitor(mon_ref, [:flush])
        {[{:error, details}], :done}

      {^ref, {:transport_error, reason}} ->
        Process.demonitor(mon_ref, [:flush])
        {[{:error, format_error(reason)}], :done}

      {:DOWN, ^mon_ref, :process, ^pid, :normal} ->
        # Process exited normally; drain any final message
        drain_stream_completion(ref)

      {:DOWN, ^mon_ref, :process, ^pid, reason} ->
        {[{:error, "Stream process exited: #{inspect(reason)}"}], :done}
    after
      timeout ->
        Process.exit(pid, :kill)
        Process.demonitor(mon_ref, [:flush])
        {[{:error, "Stream receive timeout"}], :done}
    end
  end

  defp next_stream_element(:done), do: {:halt, :done}

  # After the stream process exits normally, give it a brief window to
  # deliver the final :done / :error / :transport_error message.
  defp drain_stream_completion(ref) do
    receive do
      {^ref, {:done, metadata}} ->
        {[{:done, metadata}], :done}

      {^ref, {:error, details}} ->
        {[{:error, details}], :done}

      {^ref, {:transport_error, reason}} ->
        {[{:error, format_error(reason)}], :done}
    after
      100 ->
        {[{:error, "Stream process exited without completion signal"}], :done}
    end
  end

  defp close_stream({pid, mon_ref, _ref, _timeout}) do
    Process.exit(pid, :kill)
    Process.demonitor(mon_ref, [:flush])
    :ok
  end

  defp close_stream(:done), do: :ok

  # ============================================================================
  # Request Building
  # ============================================================================

  @doc """
  Builds a Finch request struct from components.

  This is useful when you need to inspect or modify a request before sending.
  """
  @spec build_request(method(), String.t(), [{String.t(), String.t()}], String.t() | nil) ::
          Finch.Request.t()
  def build_request(method, url, headers \\ [], body \\ nil) do
    build_finch_request(method, url, headers, body)
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp build_finch_request(method, url, headers, body) do
    Finch.build(method, url, headers, body)
  end

  defp do_request_with_retry(
         req,
         pool_timeout,
         receive_timeout,
         max_retries,
         retry_codes,
         model_name,
         ignore_retry_headers,
         attempt
       ) do
    pool_name = Config.default_pool_name()

    case Finch.request(req, pool_name,
           pool_timeout: pool_timeout,
           receive_timeout: receive_timeout
         ) do
      {:ok, %Response{status: status} = response} when status in 200..299 ->
        # Success - notify any rate limiter tracking
        emit_telemetry(:success, %{model_name: model_name, status: status})
        {:ok, normalize_response(response)}

      {:ok, %Response{status: status} = response} ->
        if should_retry_status?(status, retry_codes) do
          # Retryable status - check retry count
          if attempt < max_retries do
            handle_retry(
              req,
              pool_timeout,
              receive_timeout,
              max_retries,
              retry_codes,
              model_name,
              ignore_retry_headers,
              attempt,
              response
            )
          else
            Logger.warning("HTTP #{status} after #{max_retries + 1} attempts: #{req.host}")
            {:ok, normalize_response(response)}
          end
        else
          # Non-retryable status - return as-is
          {:ok, normalize_response(response)}
        end

      {:error, %{reason: :timeout}} ->
        # Timeout - treat as retryable
        handle_connection_error(
          req,
          pool_timeout,
          receive_timeout,
          max_retries,
          retry_codes,
          model_name,
          ignore_retry_headers,
          attempt,
          :timeout
        )

      {:error, %{reason: :pool_timeout}} ->
        handle_connection_error(
          req,
          pool_timeout,
          receive_timeout,
          max_retries,
          retry_codes,
          model_name,
          ignore_retry_headers,
          attempt,
          :pool_timeout
        )

      {:error, %{reason: reason}} when reason in [:nxdomain, :econnrefused, :enetunreach] ->
        # Connection errors - treat as retryable
        handle_connection_error(
          req,
          pool_timeout,
          receive_timeout,
          max_retries,
          retry_codes,
          model_name,
          ignore_retry_headers,
          attempt,
          reason
        )

      {:error, reason} ->
        {:error, format_error(reason)}
    end
  end

  defp should_retry_status?(status, retry_codes) do
    status in retry_codes
  end

  defp handle_retry(
         req,
         pool_timeout,
         receive_timeout,
         max_retries,
         retry_codes,
         model_name,
         ignore_retry_headers,
         attempt,
         response
       ) do
    status = response.status

    # Emit rate limit event for 429
    if status == 429 do
      emit_telemetry(:rate_limited, %{model_name: model_name, status: status})
    end

    # Calculate wait time
    wait_ms =
      calculate_backoff(
        attempt,
        response.headers,
        ignore_retry_headers
      )

    provider_note = if ignore_retry_headers, do: " (ignoring header)", else: ""

    Logger.info(
      "HTTP retry: #{status} received#{provider_note}. " <>
        "Waiting #{wait_ms}ms (attempt #{attempt + 1}/#{max_retries})"
    )

    :timer.sleep(wait_ms)

    do_request_with_retry(
      req,
      pool_timeout,
      receive_timeout,
      max_retries,
      retry_codes,
      model_name,
      ignore_retry_headers,
      attempt + 1
    )
  end

  defp handle_connection_error(
         req,
         pool_timeout,
         receive_timeout,
         max_retries,
         retry_codes,
         model_name,
         ignore_retry_headers,
         attempt,
         reason
       ) do
    if attempt < max_retries do
      wait_ms = trunc(:math.pow(2, attempt) * 1000)
      wait_ms = min(wait_ms, @max_backoff_ms)

      Logger.warning("HTTP connection error: #{inspect(reason)}. Retrying in #{wait_ms}ms...")

      :timer.sleep(wait_ms)

      do_request_with_retry(
        req,
        pool_timeout,
        receive_timeout,
        max_retries,
        retry_codes,
        model_name,
        ignore_retry_headers,
        attempt + 1
      )
    else
      Logger.error("HTTP connection error after #{max_retries + 1} attempts: #{inspect(reason)}")
      {:error, format_error(reason)}
    end
  end

  defp calculate_backoff(attempt, headers, ignore_retry_headers) do
    base_ms =
      if ignore_retry_headers do
        @cerebras_base_backoff_ms
      else
        @default_base_backoff_ms
      end

    # Check Retry-After header (unless ignoring)
    retry_after_ms =
      if ignore_retry_headers do
        nil
      else
        get_retry_after_ms(headers)
      end

    wait_ms =
      if retry_after_ms do
        retry_after_ms
      else
        # Exponential backoff: base * 2^attempt
        trunc(base_ms * :math.pow(2, attempt))
      end

    # Ensure minimum 500ms and cap at max
    max(500, min(wait_ms, @max_backoff_ms))
  end

  defp get_retry_after_ms(headers) do
    case List.keyfind(headers, "retry-after", 0) do
      {_, value} ->
        # Try parsing as integer (seconds)
        case Integer.parse(value) do
          {seconds, ""} ->
            seconds * 1000

          _ ->
            # Try parsing as HTTP-date
            parse_http_date(value)
        end

      nil ->
        nil
    end
  end

  defp parse_http_date(date_string) do
    # RFC 7231 date format: Sun, 06 Nov 1994 08:49:37 GMT
    # Try to parse and calculate milliseconds until that time
    case DateTime.from_iso8601(date_string) do
      {:ok, datetime, _} ->
        now = DateTime.utc_now()
        diff = DateTime.diff(datetime, now, :millisecond)
        max(0, diff)

      _ ->
        nil
    end
  end

  defp normalize_response(%Response{status: status, body: body, headers: headers}) do
    %{
      status: status,
      body: body,
      headers: headers
    }
  end

  # format_error returns plain strings, not wrapped tuples.
  # Callers wrap with {:error, format_error(reason)}.
  defp format_error(%{reason: reason}), do: format_error(reason)
  defp format_error(:timeout), do: "Request timeout"
  defp format_error(:pool_timeout), do: "Pool checkout timeout"
  defp format_error(:nxdomain), do: "Domain not found"
  defp format_error(:econnrefused), do: "Connection refused"
  defp format_error(:enetunreach), do: "Network unreachable"
  defp format_error(:closed), do: "Connection closed"
  defp format_error(reason) when is_atom(reason), do: Atom.to_string(reason)
  defp format_error(reason) when is_binary(reason), do: reason
  defp format_error(reason), do: inspect(reason)

  defp cerebras?(model_name) do
    model_name |> String.downcase() |> String.contains?("cerebras")
  end

  defp emit_telemetry(event, metadata) do
    :telemetry.execute(
      [:code_puppy_control, :http_client, event],
      %{count: 1},
      metadata
    )
  end
end
