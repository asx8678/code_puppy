defmodule CodePuppyControl.LLM.Providers.ResponsesAPI do
  @moduledoc """
  OpenAI Responses API provider for ChatGPT OAuth models.

  Implements `CodePuppyControl.LLM.Provider` for the Responses API wire format
  (`POST /responses`), used by ChatGPT Codex models authenticated via OAuth.

  ## Key Differences from Chat Completions

  - Endpoint: `/responses` instead of `/v1/chat/completions`
  - Request: `input` array instead of `messages`
  - Response: `output` array with `message` and `function_call` items
  - Codex default: `store: false`
  - Codex default: `stream: true` (forced — the backend requires streaming;
    `chat/3` forces `stream: true` internally and collects SSE events back
    into a final response, matching the Python ChatGPTCodexAsyncClient
    pattern. **`chat/3` does NOT call a native non-streaming endpoint.**)

  ## Supported Provider-Level Options

  The following options are accepted by `chat/3` and `stream_chat/4` when
  passed explicitly via the `opts` keyword list:


  - `:api_key` — OAuth access token (resolved by RuntimeConnection)
  - `:base_url` — API base URL (default: ChatGPT Codex endpoint)
  - `:model` — Model name (default: `"gpt-5.3-codex"`)
  - `:temperature` — Sampling temperature
  - `:max_output_tokens` — Maximum tokens to generate
  - `:reasoning_effort` — Reasoning effort (`"low"`, `"medium"`, `"high"`, `"xhigh"`)
  - `:reasoning_summary` — Reasoning summary mode (`"auto"`, `"concise"`, `"detailed"`)
  - `:text_verbosity` — Text verbosity (`"low"`, `"medium"`, `"high"`)
  - `:http_client` — HTTP client module (default: `CodePuppyControl.HttpClient`)
  - `:extra_headers` — Additional HTTP headers (from RuntimeConnection)

  ## Parity Status (Partial)

  This provider implements the Responses API wire format with **partial**
  parity to the Python ChatGPTCodexAsyncClient:

  | Feature | Status | Notes |
  |---------|--------|-------|
  | Forced `stream: true` + collect | ✓ | `chat/3` mirrors Python pattern |
  | Text output streaming | ✓ | Delta + done events |
  | Function call streaming | ✓ | Arguments delta + done events |
  | Duplicate `:part_end` prevention | ✓ | `ended_parts` MapSet dedup |
  | `reasoning_effort` in request | ✓ | Via `:reasoning_effort` opt |
  | `reasoning_summary` in request | ✓ | Via `:reasoning_summary` opt |
  | `text_verbosity` in request | ✓ | Via `:text_verbosity` opt |
  | Auto-wiring from `Config.Models` | ✓ | `LLM.resolve_provider` + `ModelFactory.build_handle` forward runtime settings |

  ## Settings Auto-Wiring for chatgpt_oauth

  For `chatgpt_oauth` models, three Responses API settings are
  **automatically forwarded** from `Config.Models` (puppy.cfg) into
  provider opts at two points:

  1. `LLM.resolve_provider/1` — when using the opts-based call path
  2. `ModelFactory.build_handle/3` — when using the handle-based call path

  Both read `Config.Models.openai_reasoning_effort/0`,
  `Config.Models.openai_reasoning_summary/0`, and
  `Config.Models.openai_verbosity/0`, then inject them into provider
  opts via `Keyword.put_new` (explicit opts take precedence).

  The `"supported_settings"` field in chatgpt_oauth model config is
  **informational metadata only** — it advertises what the Responses API
  endpoint accepts, but is NOT consulted for auto-wiring. The actual
  runtime values always come from `Config.Models`.
  """

  @behaviour CodePuppyControl.LLM.Provider

  alias CodePuppyControl.LLM.Provider
  alias CodePuppyControl.LLM.Providers.ResponsesAPI.SSE

  @default_base_url "https://chatgpt.com/backend-api/codex"
  @default_model "gpt-5.3-codex"

  # ── Provider Callbacks ────────────────────────────────────────────────────

  @impl Provider
  def chat(messages, tools, opts \\ []) do
    # The ChatGPT Codex backend REQUIRES stream=true (the Python reference
    # ChatGPTCodexAsyncClient forces it and converts SSE back to a final
    # response for non-stream callers). We mirror that: run stream_chat/4
    # with a collector callback, then return the aggregated response.
    #
    # NOTE: This is NOT a native non-streaming call — it forces stream=true
    # on the wire and collects SSE events back into a final response,
    # matching the Python parity pattern exactly.
    opts = Keyword.put(opts, :stream, true)

    case stream_chat_with_collector(messages, tools, opts) do
      {:ok, response} -> {:ok, response}
      {:error, reason} -> {:error, reason}
    end
  end

  @impl Provider
  def stream_chat(messages, tools, opts \\ [], callback_fn) do
    http_client = Keyword.get(opts, :http_client, CodePuppyControl.HttpClient)
    {url, headers, body} = build_request(messages, tools, Keyword.put(opts, :stream, true))

    stream =
      http_client.stream(:post, url,
        headers: headers,
        body: Jason.encode!(body)
      )

    initial_acc = %{
      line_buf: "",
      current_event: nil,
      current_data: "",
      id: nil,
      model: nil,
      content_parts: %{},
      tool_calls: %{},
      # Tracks output indices that already received a :part_end via
      # response.output_item.done, preventing duplicate emissions in emit_done/2.
      ended_parts: MapSet.new(),
      http_status: nil,
      usage: nil,
      status: nil
    }

    case Enum.reduce(stream, {:ok, initial_acc}, fn
           {:data, chunk}, {:ok, acc} ->
             {events, acc} = SSE.parse_sse_chunk(chunk, acc)

             Enum.reduce_while(events, {:ok, acc}, fn {event_type, data}, {:ok, acc} ->
               case SSE.handle_sse_event(event_type, data, acc, callback_fn) do
                 {:ok, acc} -> {:cont, {:ok, acc}}
                 {:error, reason} -> {:halt, {:error, reason}}
               end
             end)

           {:done, %{status: status}}, {:ok, _acc} when status >= 400 ->
             # Non-2xx HTTP response — surface the HTTP status as an error.
             {:error, %{status: status}}

           {:done, _metadata}, {:ok, acc} ->
             SSE.emit_done(acc, callback_fn)
             {:ok, acc}

           {:error, msg}, {:ok, _acc} ->
             {:error, msg}

           _event, {:error, reason} ->
             {:error, reason}
         end) do
      {:ok, _acc} -> :ok
      {:error, reason} -> {:error, reason}
    end
  end

  @impl Provider
  def supports_tools?, do: true

  @impl Provider
  def supports_vision?, do: true

  # ── Private: Non-stream collector (forced stream=true) ───────────────────

  # Collects all stream events and returns the final aggregated response.
  # Used by chat/3 because the Codex backend requires stream=true.
  # This mirrors the Python ChatGPTCodexAsyncClient pattern: force stream,
  # consume SSE, return final response.
  defp stream_chat_with_collector(messages, tools, opts) do
    {collector_pid, collector_ref} = start_collector()
    callback = fn event -> send(collector_pid, {:event, event}) end

    case stream_chat(messages, tools, opts, callback) do
      :ok ->
        # Stream completed successfully — signal collector to finalize.
        send(collector_pid, :stream_done)

        receive do
          {:collected_response, response} ->
            Process.demonitor(collector_ref, [:flush])
            {:ok, response}

          {:DOWN, ^collector_ref, :process, ^collector_pid, reason} ->
            {:error, {:collector_crashed, reason}}
        after
          5_000 ->
            Process.demonitor(collector_ref, [:flush])
            {:error, :collector_timeout}
        end

      {:error, reason} ->
        # Stream errored — kill collector and flush any stale messages.
        Process.exit(collector_pid, :shutdown)
        flush_collector_response(collector_ref)
        {:error, reason}
    end
  end

  defp start_collector do
    parent = self()
    # Use spawn_link so collector dies if parent dies (no orphan leaks).
    pid = spawn_link(fn -> collect_events(parent, nil) end)
    ref = Process.monitor(pid)
    {pid, ref}
  end

  defp flush_collector_response(collector_ref) do
    # Flush any stale messages from the dead collector process.
    # The collector may have sent {:collected_response, _} before we
    # killed it, so we must drain it to avoid mailbox pollution.
    receive do
      {:collected_response, _} ->
        Process.demonitor(collector_ref, [:flush])

      {:DOWN, ^collector_ref, :process, _pid, _reason} ->
        :ok
    after
      # Short timeout: collector is already dead (killed or linked),
      # so any pending message should arrive near-instantly.
      100 ->
        Process.demonitor(collector_ref, [:flush])
    end
  end

  defp collect_events(parent, response) do
    receive do
      {:event, {:done, resp}} ->
        collect_events(parent, resp)

      {:event, _event} ->
        collect_events(parent, response)

      :stream_done ->
        send(
          parent,
          {:collected_response,
           response ||
             %{
               id: "",
               model: "",
               content: nil,
               tool_calls: [],
               finish_reason: nil,
               usage: %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}
             }}
        )
    after
      # Hard safety timeout: only fires if caller never sends :stream_done
      # (e.g., caller crashed). Prevents infinite hangs.  Under normal
      # operation completion is driven by :stream_done, not this timeout.
      30_000 ->
        send(
          parent,
          {:collected_response,
           response ||
             %{
               id: "",
               model: "",
               content: nil,
               tool_calls: [],
               finish_reason: nil,
               usage: %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}
             }}
        )
    end
  end

  # ── Private: Request Building ─────────────────────────────────────────────

  defp build_request(messages, tools, opts) do
    base_url = Keyword.get(opts, :base_url, @default_base_url)
    model = Keyword.get(opts, :model, @default_model)
    api_key = Keyword.get(opts, :api_key)
    stream = Keyword.get(opts, :stream, false)

    url = build_url(base_url)

    headers =
      [
        {"content-type", "application/json"}
      ]
      |> maybe_put_auth(api_key)
      |> merge_extra_headers(opts)

    body =
      %{
        "model" => model,
        "input" => Enum.map(messages, &format_input_item/1),
        "store" => false,
        "stream" => stream
      }
      |> maybe_put("temperature", Keyword.get(opts, :temperature))
      |> maybe_put("max_output_tokens", Keyword.get(opts, :max_output_tokens))
      |> maybe_put_reasoning(opts)
      |> maybe_put_text_verbosity(opts)
      |> maybe_put_tools(tools)

    {url, headers, body}
  end

  defp format_input_item(%{role: role, content: content} = msg) do
    item = %{"role" => role, "content" => format_content(content)}

    item
    |> maybe_put_map("tool_calls", Map.get(msg, :tool_calls))
    |> maybe_put_map("tool_call_id", Map.get(msg, :tool_call_id))
  end

  defp format_input_item(%{"role" => role, "content" => content} = msg) do
    item = %{"role" => role, "content" => format_content(content)}

    item
    |> maybe_put_map("tool_calls", Map.get(msg, "tool_calls"))
    |> maybe_put_map("tool_call_id", Map.get(msg, "tool_call_id"))
  end

  defp format_content(content) when is_binary(content), do: content
  defp format_content(content) when is_list(content), do: content
  defp format_content(nil), do: ""

  defp maybe_put_auth(headers, nil), do: headers
  defp maybe_put_auth(headers, ""), do: headers

  defp maybe_put_auth(headers, api_key) do
    [{"authorization", "Bearer #{api_key}"} | headers]
  end

  defp maybe_put(body, _key, nil), do: body
  defp maybe_put(body, key, value), do: Map.put(body, key, value)

  defp maybe_put_map(body, _key, nil), do: body
  defp maybe_put_map(body, key, value), do: Map.put(body, key, value)

  defp maybe_put_text_verbosity(body, opts) do
    case Keyword.get(opts, :text_verbosity) do
      nil -> body
      verbosity -> Map.put(body, "text", %{"verbosity" => verbosity})
    end
  end

  defp maybe_put_reasoning(body, opts) do
    effort = Keyword.get(opts, :reasoning_effort)
    summary = Keyword.get(opts, :reasoning_summary)

    reasoning =
      case {effort, summary} do
        {nil, nil} -> nil
        {nil, s} when s != nil -> %{"summary" => s}
        {e, nil} when e != nil -> %{"effort" => e}
        {e, s} -> %{"effort" => e, "summary" => s}
      end

    case reasoning do
      nil -> body
      r -> Map.put(body, "reasoning", r)
    end
  end

  defp maybe_put_tools(body, []), do: body
  defp maybe_put_tools(body, nil), do: body

  defp maybe_put_tools(body, tools) when is_list(tools) do
    Map.put(body, "tools", Enum.map(tools, &format_tool/1))
  end

  defp format_tool(%{type: _type, function: func}) do
    %{
      "type" => "function",
      "name" => func.name,
      "description" => func.description,
      "parameters" => func.parameters
    }
  end

  defp format_tool(%{"type" => _type, "function" => func}) do
    %{
      "type" => "function",
      "name" => func["name"],
      "description" => func["description"],
      "parameters" => func["parameters"]
    }
  end

  # ── Private: URL Building ────────────────────────────────────────────────

  defp build_url(base_url) do
    normalized = String.trim_trailing(base_url, "/")
    "#{normalized}/responses"
  end

  defp merge_extra_headers(headers, opts) do
    case Keyword.get(opts, :extra_headers) do
      nil -> headers
      extra when is_list(extra) -> headers ++ extra
      _ -> headers
    end
  end
end
