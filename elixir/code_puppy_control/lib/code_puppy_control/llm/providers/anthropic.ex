defmodule CodePuppyControl.LLM.Providers.Anthropic do
  @moduledoc """
  Anthropic messages provider.

  Implements `CodePuppyControl.LLM.Provider` for Anthropic's `/v1/messages` API.

  ## Features

  - Non-streaming chat completions
  - SSE streaming with `event:` / `data:` format
  - Tool use blocks
  - System message extraction (Anthropic uses a top-level `system` field)

  ## Configuration

  Accepts these options:
  - `:api_key` — Anthropic API key (required)
  - `:base_url` — API base URL (default: `"https://api.anthropic.com"`)
  - `:model` — Model name (default: `"claude-sonnet-4-20250514"`)
  - `:max_tokens` — Maximum tokens to generate (required by Anthropic)
  - `:temperature` — Sampling temperature
  - `:http_client` — HTTP client module (default: `CodePuppyControl.HttpClient`)
  """

  @behaviour CodePuppyControl.LLM.Provider

  alias CodePuppyControl.LLM.Provider

  @default_base_url "https://api.anthropic.com"
  @default_model "claude-sonnet-4-20250514"
  @api_version "2023-06-01"

  # ── Provider Callbacks ────────────────────────────────────────────────────

  @impl Provider
  def chat(messages, tools, opts \\ []) do
    http_client = Keyword.get(opts, :http_client, CodePuppyControl.HttpClient)
    {url, headers, body} = build_request(messages, tools, opts)

    case http_client.request(:post, url, headers: headers, body: Jason.encode!(body)) do
      {:ok, %{status: status, body: resp_body}} when status in 200..299 ->
        parse_chat_response(resp_body)

      {:ok, %{status: status, body: resp_body}} ->
        {:error, %{status: status, body: parse_error_body(resp_body)}}

      {:error, reason} ->
        {:error, reason}
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
      id: nil,
      model: nil,
      content_blocks: %{},
      tool_uses: %{},
      usage: nil,
      stop_reason: nil
    }

    {result, _acc} =
      Enum.reduce(stream, {:ok, initial_acc}, fn
        {:data, chunk}, {:ok, acc} ->
          {events, acc} = parse_anthropic_sse_chunk(chunk, acc)

          Enum.reduce_while(events, {:ok, acc}, fn {event_type, data}, {:ok, acc} ->
            case handle_sse_event(event_type, data, acc, callback_fn) do
              {:ok, acc} -> {:cont, {:ok, acc}}
              {:error, reason} -> {:halt, {:error, reason}}
            end
          end)

        {:done, _metadata}, {:ok, acc} ->
          emit_done(acc, callback_fn)
          {:ok, acc}

        {:error, msg}, {:ok, _acc} ->
          {:error, msg}

        _event, {:error, reason} ->
          {:error, reason}
      end)

    result
  end

  @impl Provider
  def supports_tools?, do: true

  @impl Provider
  def supports_vision?, do: true

  # ── Private: Request Building ─────────────────────────────────────────────

  defp build_request(messages, tools, opts) do
    base_url = Keyword.get(opts, :base_url, @default_base_url)
    model = Keyword.get(opts, :model, @default_model)
    api_key = Keyword.get(opts, :api_key) || resolve_api_key()
    stream = Keyword.get(opts, :stream, false)
    max_tokens = Keyword.get(opts, :max_tokens, 4096)

    url = "#{base_url}/v1/messages"

    headers =
      [
        {"x-api-key", api_key},
        {"anthropic-version", @api_version},
        {"content-type", "application/json"}
      ]
      |> merge_extra_headers(opts)

    {system_text, chat_messages} = extract_system_messages(messages)

    body =
      %{
        "model" => model,
        "max_tokens" => max_tokens,
        "messages" => Enum.map(chat_messages, &format_message/1),
        "stream" => stream
      }
      |> maybe_put("system", system_text)
      |> maybe_put("temperature", Keyword.get(opts, :temperature))
      |> maybe_put_tools(tools)

    {url, headers, body}
  end

  defp extract_system_messages(messages) do
    {system_msgs, chat_msgs} =
      Enum.split_with(messages, fn
        %{role: role} -> role == "system"
        %{"role" => role} -> role == "system"
      end)

    system_text =
      system_msgs
      |> Enum.map_join("\n\n", fn
        %{content: content} -> content || ""
        %{"content" => content} -> content || ""
      end)
      |> then(fn text -> if text == "", do: nil, else: text end)

    {system_text, chat_msgs}
  end

  defp format_message(%{role: role, content: content} = msg) do
    %{"role" => role, "content" => format_content(content, msg)}
  end

  defp format_message(%{"role" => role, "content" => content} = msg) do
    %{"role" => role, "content" => format_content(content, msg)}
  end

  defp format_content(content, msg) when is_binary(content) do
    case {Map.get(msg, :tool_calls) || Map.get(msg, "tool_calls"),
          Map.get(msg, :tool_call_id) || Map.get(msg, "tool_call_id")} do
      {nil, nil} ->
        content

      {tool_calls, nil} when is_list(tool_calls) ->
        Enum.map(tool_calls, fn tc ->
          %{
            "type" => "tool_use",
            "id" => tc[:id] || tc["id"] || "",
            "name" => get_in(tc, [:function, :name]) || get_in(tc, ["function", "name"]) || "",
            "input" =>
              parse_tool_input(
                get_in(tc, [:function, :arguments]) || get_in(tc, ["function", "arguments"]) ||
                  "{}"
              )
          }
        end)

      {nil, tool_call_id} when is_binary(tool_call_id) ->
        [
          %{
            "type" => "tool_result",
            "tool_use_id" => tool_call_id,
            "content" => content
          }
        ]
    end
  end

  defp format_content(content, _msg) when is_list(content), do: content
  defp format_content(nil, _msg), do: ""

  defp parse_tool_input(args) when is_binary(args) do
    case Jason.decode(args) do
      {:ok, parsed} -> parsed
      _ -> %{}
    end
  end

  defp parse_tool_input(args) when is_map(args), do: args
  defp parse_tool_input(_), do: %{}

  defp maybe_put(body, _key, nil), do: body
  defp maybe_put(body, key, value), do: Map.put(body, key, value)

  defp maybe_put_tools(body, []), do: body
  defp maybe_put_tools(body, nil), do: body

  defp maybe_put_tools(body, tools) when is_list(tools) do
    Map.put(
      body,
      "tools",
      Enum.map(tools, fn
        %{type: _type, function: func} ->
          %{
            "name" => func.name,
            "description" => func.description,
            "input_schema" => func.parameters
          }

        %{"type" => _type, "function" => func} ->
          %{
            "name" => func["name"],
            "description" => func["description"],
            "input_schema" => func["parameters"]
          }
      end)
    )
  end

  # ── Private: Response Parsing ─────────────────────────────────────────────

  defp parse_chat_response(body) do
    case Jason.decode(body) do
      {:ok, resp} ->
        content_blocks = resp["content"] || []
        {text_content, tool_calls} = extract_content(content_blocks)

        {:ok,
         %{
           id: resp["id"] || "",
           model: resp["model"] || "",
           content: text_content,
           tool_calls: tool_calls,
           finish_reason: resp["stop_reason"],
           usage: parse_usage(resp["usage"])
         }}

      {:error, reason} ->
        {:error, {:json_decode_error, reason}}
    end
  end

  defp extract_content(blocks) do
    {texts, tools} =
      Enum.split_with(blocks, fn
        %{"type" => "text"} -> true
        _ -> false
      end)

    text =
      texts
      |> Enum.map_join(fn block -> block["text"] || "" end)
      |> then(fn t -> if t == "", do: nil, else: t end)

    tool_calls =
      Enum.map(tools, fn
        %{"type" => "tool_use", "id" => id, "name" => name, "input" => input} ->
          %{id: id, name: name, arguments: input}

        _ ->
          nil
      end)
      |> Enum.reject(&is_nil/1)

    {text, tool_calls}
  end

  defp parse_usage(nil), do: %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}

  defp parse_usage(usage) do
    %{
      prompt_tokens: usage["input_tokens"] || 0,
      completion_tokens: usage["output_tokens"] || 0,
      total_tokens: (usage["input_tokens"] || 0) + (usage["output_tokens"] || 0)
    }
  end

  defp parse_error_body(body) do
    case Jason.decode(body) do
      {:ok, %{"error" => error}} -> error
      _ -> body
    end
  end

  # ── Private: SSE Streaming ────────────────────────────────────────────────

  # Anthropic SSE format:
  #   event: content_block_start
  #   data: {...}
  #
  # Line-based parser that tracks current event type and data lines.
  defp parse_anthropic_sse_chunk(chunk, acc) do
    lines = String.split(acc.line_buf <> chunk, "\n")

    {complete, remaining} =
      case List.last(lines) do
        "" -> {lines, ""}
        _ -> {Enum.drop(lines, -1), List.last(lines)}
      end

    {events, state} =
      Enum.reduce(complete, {[], %{event: acc.current_event, data: ""}}, fn line,
                                                                            {events, state} ->
        case line do
          "" ->
            # Event boundary — yield completed event if we have both event type and data
            cond do
              state.event != nil and state.data != "" ->
                case Jason.decode(state.data) do
                  {:ok, data} -> {[{state.event, data} | events], %{event: nil, data: ""}}
                  _ -> {events, %{event: nil, data: ""}}
                end

              state.event != nil ->
                # Event type set but no data — might be a ping
                {[{state.event, %{}} | events], %{event: nil, data: ""}}

              true ->
                {events, state}
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

    {Enum.reverse(events), %{acc | line_buf: remaining, current_event: state.event}}
  end

  defp handle_sse_event("message_start", data, acc, _callback_fn) do
    message = data["message"] || %{}
    {:ok, %{acc | id: message["id"] || acc.id, model: message["model"] || acc.model}}
  end

  defp handle_sse_event("content_block_start", data, acc, callback_fn) do
    index = data["index"] || 0
    block = data["content_block"] || %{}

    case block["type"] do
      "text" ->
        parts = Map.put(acc.content_blocks, index, %{type: :text, index: index, text_chunks: []})
        callback_fn.({:part_start, %{type: :text, index: index, id: nil}})
        {:ok, %{acc | content_blocks: parts}}

      "tool_use" ->
        id = block["id"] || ""
        name = block["name"] || ""

        parts =
          Map.put(acc.tool_uses, index, %{
            type: :tool_call,
            index: index,
            id: id,
            name: name,
            input_chunks: []
          })

        callback_fn.({:part_start, %{type: :tool_call, index: index, id: id}})

        callback_fn.(
          {:part_delta, %{type: :tool_call, index: index, text: nil, name: name, arguments: nil}}
        )

        {:ok, %{acc | tool_uses: parts}}

      _ ->
        {:ok, acc}
    end
  end

  defp handle_sse_event("content_block_delta", data, acc, callback_fn) do
    index = data["index"] || 0
    delta = data["delta"] || %{}

    case delta["type"] do
      "text_delta" ->
        text = delta["text"] || ""

        case Map.get(acc.content_blocks, index) do
          nil ->
            {:ok, acc}

          part ->
            part = %{part | text_chunks: [text | part.text_chunks]}
            parts = Map.put(acc.content_blocks, index, part)

            callback_fn.(
              {:part_delta, %{type: :text, index: index, text: text, name: nil, arguments: nil}}
            )

            {:ok, %{acc | content_blocks: parts}}
        end

      "input_json_delta" ->
        partial = delta["partial_json"] || ""

        case Map.get(acc.tool_uses, index) do
          nil ->
            {:ok, acc}

          part ->
            part = %{part | input_chunks: [partial | part.input_chunks]}
            parts = Map.put(acc.tool_uses, index, part)

            callback_fn.(
              {:part_delta,
               %{type: :tool_call, index: index, text: nil, name: nil, arguments: partial}}
            )

            {:ok, %{acc | tool_uses: parts}}
        end

      _ ->
        {:ok, acc}
    end
  end

  defp handle_sse_event("content_block_stop", data, acc, callback_fn) do
    index = data["index"] || 0

    cond do
      Map.has_key?(acc.content_blocks, index) ->
        _text = acc.content_blocks[index].text_chunks |> Enum.reverse() |> Enum.join()

        callback_fn.(
          {:part_end, %{type: :text, index: index, id: nil, name: nil, arguments: nil}}
        )

        {:ok, acc}

      Map.has_key?(acc.tool_uses, index) ->
        part = acc.tool_uses[index]
        input_json = part.input_chunks |> Enum.reverse() |> Enum.join()

        callback_fn.(
          {:part_end,
           %{type: :tool_call, index: index, id: part.id, name: part.name, arguments: input_json}}
        )

        {:ok, acc}

      true ->
        {:ok, acc}
    end
  end

  defp handle_sse_event("message_delta", data, acc, _callback_fn) do
    delta = data["delta"] || %{}

    acc =
      acc
      |> then(fn acc ->
        case delta["stop_reason"] do
          nil -> acc
          reason -> %{acc | stop_reason: reason}
        end
      end)
      |> then(fn acc ->
        case data["usage"] do
          nil -> acc
          usage -> %{acc | usage: parse_usage(usage)}
        end
      end)

    {:ok, acc}
  end

  defp handle_sse_event("message_stop", _data, acc, _callback_fn) do
    {:ok, acc}
  end

  defp handle_sse_event("ping", _data, acc, _callback_fn) do
    {:ok, acc}
  end

  defp handle_sse_event("error", data, _acc, _callback_fn) do
    {:error, data["error"] || %{"message" => "unknown error"}}
  end

  defp handle_sse_event(_event_type, _data, acc, _callback_fn) do
    {:ok, acc}
  end

  defp emit_done(acc, callback_fn) do
    tool_calls =
      acc.tool_uses
      |> Enum.sort_by(fn {idx, _} -> idx end)
      |> Enum.map(fn {_index, part} ->
        input_json = part.input_chunks |> Enum.reverse() |> Enum.join()

        %{
          id: part.id || "",
          name: part.name || "",
          arguments: parse_tool_input(input_json)
        }
      end)

    content =
      acc.content_blocks
      |> Enum.sort_by(fn {idx, _} -> idx end)
      |> Enum.map_join(fn {_index, part} ->
        part.text_chunks |> Enum.reverse() |> Enum.join()
      end)

    response = %{
      id: acc.id || "",
      model: acc.model || "",
      content: if(content == "", do: nil, else: content),
      tool_calls: tool_calls,
      finish_reason: acc.stop_reason,
      usage: acc.usage || %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}
    }

    callback_fn.({:done, response})
  end

  # ── Private: Config ───────────────────────────────────────────────────────

  # Merge extra_headers from opts into the header list.
  # extra_headers is a list of {key, value} tuples from Handle.to_provider_opts/1.
  defp merge_extra_headers(headers, opts) do
    case Keyword.get(opts, :extra_headers) do
      nil -> headers
      extra when is_list(extra) -> headers ++ extra
      _ -> headers
    end
  end

  defp resolve_api_key do
    System.get_env("ANTHROPIC_API_KEY") || ""
  end
end
