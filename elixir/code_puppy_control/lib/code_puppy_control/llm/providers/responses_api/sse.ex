defmodule CodePuppyControl.LLM.Providers.ResponsesAPI.SSE do
  @moduledoc """
  SSE parsing and event handling for the Responses API stream format.

  The Responses API uses `event:` + `data:` SSE format (like Anthropic),
  not the simpler `data:`-only format of Chat Completions.
  """

  # ── Private: Response Helpers ─────────────────────────────────────────────

  @doc "Parse a JSON arguments string into a map, falling back to the raw string."
  @spec parse_arguments(binary() | term()) :: map() | term()
  def parse_arguments(args) when is_binary(args) do
    case Jason.decode(args) do
      {:ok, parsed} -> parsed
      _ -> args
    end
  end

  def parse_arguments(args), do: args

  @doc "Map Responses API status to standard finish reason."
  @spec map_status(String.t()) :: String.t()
  def map_status("completed"), do: "stop"
  def map_status("incomplete"), do: "length"
  def map_status(status), do: status

  @doc "Parse usage from Responses API format to standard format."
  @spec parse_usage(map() | nil) :: map()
  def parse_usage(nil), do: %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}

  def parse_usage(usage) do
    input_tokens = usage["input_tokens"] || 0
    output_tokens = usage["output_tokens"] || 0

    %{
      prompt_tokens: input_tokens,
      completion_tokens: output_tokens,
      total_tokens: input_tokens + output_tokens
    }
  end

  # ── Private: SSE Streaming ────────────────────────────────────────────────

  # The Responses API uses event: + data: SSE format (like Anthropic),
  # not the simpler data:-only format of Chat Completions.
  @doc """
  Parse a raw SSE chunk into a list of event type/data tuples.

  Handles line buffering across chunks and multi-line data fields.
  """
  @spec parse_sse_chunk(binary(), map()) :: {[{String.t(), map()}], map()}
  def parse_sse_chunk(chunk, acc) do
    combined = acc.line_buf <> chunk
    lines = :binary.split(combined, "\n", [:global])
    ends_with_newline = byte_size(combined) > 0 and :binary.last(combined) == ?\n

    {complete, remaining} =
      if ends_with_newline do
        {Enum.drop(lines, -1), ""}
      else
        {Enum.drop(lines, -1), List.last(lines)}
      end

    {events, state} =
      Enum.reduce(complete, {[], %{event: acc.current_event, data: acc.current_data}}, fn line,
                                                                                          {events,
                                                                                           state} ->
        case line do
          "" ->
            cond do
              state.event != nil and state.data != "" ->
                case Jason.decode(state.data) do
                  {:ok, data} -> {[{state.event, data} | events], %{event: nil, data: ""}}
                  _ -> {events, %{event: nil, data: ""}}
                end

              state.event != nil ->
                {[{state.event, %{}} | events], %{event: nil, data: ""}}

              true ->
                {events, %{state | data: ""}}
            end

          "event: " <> event_type ->
            {events, %{state | event: event_type}}

          "data: " <> data ->
            new_data = if state.data == "", do: data, else: state.data <> "\n" <> data
            {events, %{state | data: new_data}}

          _ ->
            {events, state}
        end
      end)

    {Enum.reverse(events),
     %{acc | line_buf: remaining, current_event: state.event, current_data: state.data}}
  end

  # ── SSE Event Handlers ────────────────────────────────────────────────────

  @doc """
  Handle a single SSE event, updating the accumulator and calling the callback.

  Returns the updated accumulator or an error.
  """
  @spec handle_sse_event(String.t(), map(), map(), function()) ::
          {:ok, map()} | {:error, term()}
  def handle_sse_event("response.created", data, acc, _callback_fn) do
    resp = data["response"] || data

    {:ok,
     %{
       acc
       | id: resp["id"] || acc.id,
         model: resp["model"] || acc.model,
         status: resp["status"] || acc.status
     }}
  end

  # A new output item (message or function_call) has been added.
  # IMPORTANT: If deltas arrived before this event (out-of-order delivery),
  # we preserve the already-accumulated chunks rather than wiping them.
  def handle_sse_event("response.output_item.added", data, acc, callback_fn) do
    output_index = data["output_index"] || 0
    item = data["item"] || %{}

    case item["type"] do
      "message" ->
        # Preserve existing chunks if this index already has content
        # (out-of-order delta arrived before output_item.added).
        existing = Map.get(acc.content_parts, output_index)
        existing_chunks = if existing, do: existing.text_chunks, else: []

        parts =
          Map.put(acc.content_parts, output_index, %{
            type: :text,
            index: output_index,
            text_chunks: existing_chunks
          })

        callback_fn.({:part_start, %{type: :text, index: output_index, id: nil}})
        {:ok, %{acc | content_parts: parts}}

      "function_call" ->
        fc_id = item["call_id"] || item["id"] || ""
        fc_name = item["name"] || ""

        # Preserve existing arg_chunks if this index already has content
        # (out-of-order delta arrived before output_item.added).
        existing = Map.get(acc.tool_calls, output_index)
        existing_chunks = if existing, do: existing.arg_chunks, else: []
        existing_id = if existing && existing.id, do: existing.id, else: fc_id
        existing_name = if existing && existing.name, do: existing.name, else: fc_name

        tc_parts =
          Map.put(acc.tool_calls, output_index, %{
            type: :tool_call,
            index: output_index,
            id: existing_id,
            name: existing_name,
            arg_chunks: existing_chunks
          })

        callback_fn.({:part_start, %{type: :tool_call, index: output_index, id: fc_id}})

        if fc_name != "" do
          callback_fn.(
            {:part_delta,
             %{
               type: :tool_call,
               index: output_index,
               text: nil,
               name: fc_name,
               arguments: nil
             }}
          )
        end

        {:ok, %{acc | tool_calls: tc_parts}}

      _ ->
        {:ok, acc}
    end
  end

  # A content part within a message output item.
  # Note: does NOT emit :part_start — that was already emitted by
  # response.output_item.added. This handler only ensures the content_parts
  # map has an entry if the event arrives before output_item.added.
  def handle_sse_event("response.content_part.added", data, acc, _callback_fn) do
    output_index = data["output_index"] || 0

    case Map.get(acc.content_parts, output_index) do
      nil ->
        parts =
          Map.put(acc.content_parts, output_index, %{
            type: :text,
            index: output_index,
            text_chunks: []
          })

        {:ok, %{acc | content_parts: parts}}

      _ ->
        {:ok, acc}
    end
  end

  # Text delta within an output_text content part.
  def handle_sse_event("response.output_text.delta", data, acc, callback_fn) do
    output_index = data["output_index"] || 0
    delta_text = data["delta"] || ""

    parts = acc.content_parts

    part =
      Map.get(parts, output_index, %{type: :text, index: output_index, text_chunks: []})

    part = %{part | text_chunks: [delta_text | part.text_chunks]}
    parts = Map.put(parts, output_index, part)
    acc = %{acc | content_parts: parts}

    callback_fn.(
      {:part_delta,
       %{type: :text, index: output_index, text: delta_text, name: nil, arguments: nil}}
    )

    {:ok, acc}
  end

  # Text done — full text available. If we have no accumulated chunks
  # (e.g., only a done event with no deltas), backfill from the final text.
  def handle_sse_event("response.output_text.done", data, acc, _callback_fn) do
    output_index = data["output_index"] || 0
    final_text = data["text"]

    case Map.get(acc.content_parts, output_index) do
      nil when is_binary(final_text) and final_text != "" ->
        # No content part yet — backfill from the done event.
        parts =
          Map.put(acc.content_parts, output_index, %{
            type: :text,
            index: output_index,
            text_chunks: [final_text]
          })

        {:ok, %{acc | content_parts: parts}}

      %{:text_chunks => []} = part when is_binary(final_text) and final_text != "" ->
        # Part exists but empty chunks — backfill from the done event.
        parts = Map.put(acc.content_parts, output_index, %{part | text_chunks: [final_text]})
        {:ok, %{acc | content_parts: parts}}

      _ ->
        # Chunks already accumulated from deltas — keep them.
        {:ok, acc}
    end
  end

  # Function call arguments delta.
  def handle_sse_event("response.function_call_arguments.delta", data, acc, callback_fn) do
    output_index = data["output_index"] || 0
    delta_args = data["delta"] || ""

    tc_parts = acc.tool_calls

    part =
      Map.get(tc_parts, output_index, %{
        type: :tool_call,
        index: output_index,
        id: nil,
        name: nil,
        arg_chunks: []
      })

    part = %{part | arg_chunks: [delta_args | part.arg_chunks]}
    tc_parts = Map.put(tc_parts, output_index, part)
    acc = %{acc | tool_calls: tc_parts}

    if delta_args != "" do
      callback_fn.(
        {:part_delta,
         %{type: :tool_call, index: output_index, text: nil, name: nil, arguments: delta_args}}
      )
    end

    {:ok, acc}
  end

  # Function call arguments done — full arguments available.
  # If we have no accumulated arg_chunks (e.g., only a done event with no
  # deltas), backfill from the final arguments string.
  def handle_sse_event("response.function_call_arguments.done", data, acc, _callback_fn) do
    output_index = data["output_index"] || 0
    final_args = data["arguments"]

    case Map.get(acc.tool_calls, output_index) do
      nil when is_binary(final_args) and final_args != "" ->
        # No tool call part yet — backfill from the done event.
        tc_parts =
          Map.put(acc.tool_calls, output_index, %{
            type: :tool_call,
            index: output_index,
            id: nil,
            name: nil,
            arg_chunks: [final_args]
          })

        {:ok, %{acc | tool_calls: tc_parts}}

      %{:arg_chunks => []} = part when is_binary(final_args) and final_args != "" ->
        # Part exists but empty chunks — backfill from the done event.
        tc_parts = Map.put(acc.tool_calls, output_index, %{part | arg_chunks: [final_args]})
        {:ok, %{acc | tool_calls: tc_parts}}

      _ ->
        # Chunks already accumulated from deltas — keep them.
        {:ok, acc}
    end
  end

  # Output item completed — emit :part_end and record the index in ended_parts
  # to prevent emit_done/2 from emitting a duplicate :part_end later.
  def handle_sse_event("response.output_item.done", data, acc, callback_fn) do
    output_index = data["output_index"] || 0
    item = data["item"] || %{}

    case item["type"] do
      "message" ->
        callback_fn.(
          {:part_end, %{type: :text, index: output_index, id: nil, name: nil, arguments: nil}}
        )

        {:ok, %{acc | ended_parts: MapSet.put(acc.ended_parts, output_index)}}

      "function_call" ->
        fc_id = item["call_id"] || item["id"] || ""
        fc_name = item["name"] || ""
        args = item["arguments"] || ""

        callback_fn.(
          {:part_end,
           %{type: :tool_call, index: output_index, id: fc_id, name: fc_name, arguments: args}}
        )

        {:ok, %{acc | ended_parts: MapSet.put(acc.ended_parts, output_index)}}

      _ ->
        {:ok, acc}
    end
  end

  # Response completed — includes full response with usage.
  def handle_sse_event("response.completed", data, acc, _callback_fn) do
    resp = data["response"] || data

    {:ok,
     %{
       acc
       | id: resp["id"] || acc.id,
         model: resp["model"] || acc.model,
         status: resp["status"] || acc.status,
         usage: merge_usage(acc.usage, resp["usage"])
     }}
  end

  # Error event
  def handle_sse_event("error", data, _acc, _callback_fn) do
    {:error, data["error"] || %{"message" => "unknown error"}}
  end

  # Ignore unknown events gracefully
  def handle_sse_event(_event_type, _data, acc, _callback_fn) do
    {:ok, acc}
  end

  # ── Private: Emit Done ────────────────────────────────────────────────────

  @doc """
  Emit final part_end events for any parts not already ended,
  then emit the done event with the full assembled response.
  """
  @spec emit_done(map(), function()) :: :ok
  def emit_done(acc, callback_fn) do
    # Emit part_end only for content parts not yet ended via output_item.done.
    # The ended_parts MapSet guarantees no duplicate :part_end emissions.
    Enum.each(acc.content_parts, fn {index, part} ->
      unless MapSet.member?(acc.ended_parts, index) do
        callback_fn.(
          {:part_end, %{type: :text, index: part.index, id: nil, name: nil, arguments: nil}}
        )
      end
    end)

    # Emit part_end only for tool calls not yet ended via output_item.done
    Enum.each(acc.tool_calls, fn {index, part} ->
      unless MapSet.member?(acc.ended_parts, index) do
        args = part.arg_chunks |> Enum.reverse() |> Enum.join()

        callback_fn.(
          {:part_end,
           %{
             type: :tool_call,
             index: part.index,
             id: part.id,
             name: part.name,
             arguments: args
           }}
        )
      end
    end)

    # Build final tool_calls list
    tool_calls =
      acc.tool_calls
      |> Enum.sort_by(fn {idx, _} -> idx end)
      |> Enum.map(fn {_index, part} ->
        args = part.arg_chunks |> Enum.reverse() |> Enum.join()

        %{
          id: part.id || "",
          name: part.name || "",
          arguments: parse_arguments(args)
        }
      end)

    content =
      acc.content_parts
      |> Enum.sort_by(fn {idx, _} -> idx end)
      |> Enum.map_join(fn {_index, part} ->
        part.text_chunks |> Enum.reverse() |> Enum.join()
      end)

    response = %{
      id: acc.id || "",
      model: acc.model || "",
      content: if(content == "", do: nil, else: content),
      tool_calls: tool_calls,
      finish_reason: map_status(acc.status),
      usage: acc.usage || %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}
    }

    callback_fn.({:done, response})
  end

  @doc "Merge two usage maps, summing token counts."
  @spec merge_usage(map() | nil, map()) :: map()
  def merge_usage(nil, usage) when is_map(usage), do: parse_usage(usage)

  def merge_usage(existing, usage) when is_map(usage) do
    parsed = parse_usage(usage)

    %{
      prompt_tokens: existing.prompt_tokens + parsed.prompt_tokens,
      completion_tokens: existing.completion_tokens + parsed.completion_tokens,
      total_tokens: existing.total_tokens + parsed.total_tokens
    }
  end
end
