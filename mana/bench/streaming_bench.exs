defmodule Bench.StreamingBench do
  @moduledoc """
  Benchmarks for streaming components.

  Hot-path code in streaming:
  - SSE event parsing (Anthropic & OpenAI formats)
  - PartTracker state updates
  - Event handler processing
  - Stream event dispatch
  """

  alias Mana.Streaming.PartTracker

  # ---------------------------------------------------------------------------
  # Realistic SSE event data — Anthropic streaming format
  # ---------------------------------------------------------------------------

  @anthropic_sse_events (fn ->
                           sse_line = fn event_type, data ->
                             "event: " <> event_type <> "\ndata: " <> Jason.encode!(data) <> "\n\n"
                           end

                           parts = [
                             sse_line.("message_start", %{
                               "type" => "message_start",
                               "message" => %{
                                 "id" => "msg_bench",
                                 "type" => "message",
                                 "role" => "assistant",
                                 "content" => [],
                                 "model" => "claude-sonnet-4-20250514",
                                 "stop_reason" => nil,
                                 "usage" => %{"input_tokens" => 25, "output_tokens" => 1}
                               }
                             }),
                             sse_line.("content_block_start", %{
                               "type" => "content_block_start",
                               "index" => 0,
                               "content_block" => %{"type" => "text", "text" => ""}
                             })
                           ]

                           deltas =
                             Enum.map(1..100, fn i ->
                               text = "This is benchmark token number #{i} with some realistic content. "

                               sse_line.("content_block_delta", %{
                                 "type" => "content_block_delta",
                                 "index" => 0,
                                 "delta" => %{"type" => "text_delta", "text" => text}
                               })
                             end)

                           ending = [
                             sse_line.("content_block_stop", %{
                               "type" => "content_block_stop",
                               "index" => 0
                             }),
                             sse_line.("message_delta", %{
                               "type" => "message_delta",
                               "delta" => %{"stop_reason" => "end_turn", "stop_sequence" => nil},
                               "usage" => %{"output_tokens" => 102}
                             }),
                             sse_line.("message_stop", %{
                               "type" => "message_stop"
                             })
                           ]

                           parts ++ deltas ++ ending
                         end).()

  # ---------------------------------------------------------------------------
  # Realistic SSE event data — OpenAI streaming format
  # ---------------------------------------------------------------------------

  @openai_sse_events (fn ->
                        sse_data = fn data ->
                          "data: " <> Jason.encode!(data) <> "\n\n"
                        end

                        chunk_id = "chatcmpl-bench"
                        model = "gpt-4o"
                        now = System.system_time(:second)

                        header =
                          sse_data.(%{
                            "id" => chunk_id,
                            "object" => "chat.completion.chunk",
                            "created" => now,
                            "model" => model,
                            "choices" => [
                              %{
                                "index" => 0,
                                "delta" => %{"role" => "assistant", "content" => ""},
                                "finish_reason" => nil
                              }
                            ]
                          })

                        deltas =
                          Enum.map(1..100, fn i ->
                            text = "This is benchmark token number #{i} with some realistic content. "

                            sse_data.(%{
                              "id" => chunk_id,
                              "object" => "chat.completion.chunk",
                              "created" => now,
                              "model" => model,
                              "choices" => [
                                %{"index" => 0, "delta" => %{"content" => text}, "finish_reason" => nil}
                              ]
                            })
                          end)

                        footer =
                          sse_data.(%{
                            "id" => chunk_id,
                            "object" => "chat.completion.chunk",
                            "created" => now,
                            "model" => model,
                            "choices" => [
                              %{"index" => 0, "delta" => %{}, "finish_reason" => "stop"}
                            ]
                          })

                        trailer = "data: [DONE]\n\n"

                        [header | deltas] ++ [footer, trailer]
                      end).()

  @doc """
  Run all benchmarks.
  """
  def run do
    IO.puts("Running Streaming benchmarks...\n")

    Benchee.run(%{
      "SSE parsing — Anthropic (104 events)" => fn ->
        parse_sse_events(@anthropic_sse_events)
      end,
      "SSE parsing — OpenAI (102 events)" => fn ->
        parse_sse_events(@openai_sse_events)
      end,
      "PartTracker state updates (100 ops)" => fn ->
        tracker = PartTracker.new()

        Enum.reduce(1..100, tracker, fn i, acc ->
          part_id = "part-#{i}"

          acc
          |> PartTracker.start_part(part_id, :text)
          |> PartTracker.update_tokens(part_id, 10, 5)
          |> PartTracker.end_part(part_id)
        end)
      end,
      "PartTracker token accumulation" => fn ->
        tracker = PartTracker.new()
        part_id = "part-main"
        tracker = PartTracker.start_part(tracker, part_id, :text)

        Enum.reduce(1..1000, tracker, fn _, acc ->
          PartTracker.update_tokens(acc, part_id, 1, 1)
        end)
      end,
      "PartTracker full lifecycle (1000 parts)" => fn ->
        tracker = PartTracker.new()

        Enum.reduce(1..1000, tracker, fn i, acc ->
          part_id = "part-#{i}"

          acc
          |> PartTracker.start_part(part_id, :text)
          |> PartTracker.update_tokens(part_id, 5, 3)
          |> PartTracker.set_tool_name(part_id, "tool_#{i}")
          |> PartTracker.end_part(part_id)
        end)
      end,
      "event tuple creation (100 events)" => fn ->
        Enum.map(1..100, fn i ->
          {:part_delta, "part-#{i}", "Hello #{i}"}
        end)
      end
    })
  end

  # ---------------------------------------------------------------------------
  # Helper: SSE parsing that handles both Anthropic and OpenAI formats
  # ---------------------------------------------------------------------------

  defp parse_sse_events(events) do
    Enum.flat_map(events, fn event ->
      case Regex.run(~r/data: (.+)(?:\n|$)/, event, capture: :all_but_first) do
        [json_str] ->
          case json_str do
            "[DONE]" ->
              [{:done}]

            json ->
              case Jason.decode(json) do
                {:ok, data} -> [parse_event(data)]
                _ -> []
              end
          end

        _ ->
          []
      end
    end)
  end

  # Anthropic-style events
  defp parse_event(%{"type" => "message_start"}), do: {:message_start}

  defp parse_event(%{"type" => "content_block_start", "index" => idx}),
    do: {:content_block_start, idx}

  defp parse_event(%{"type" => "content_block_delta", "index" => idx, "delta" => delta}),
    do: {:content_block_delta, idx, delta["text"] || ""}

  defp parse_event(%{"type" => "content_block_stop", "index" => idx}),
    do: {:content_block_stop, idx}

  defp parse_event(%{"type" => "message_delta"}), do: {:message_delta}
  defp parse_event(%{"type" => "message_stop"}), do: {:message_stop}

  # OpenAI-style events
  defp parse_event(%{"choices" => choices}) when is_list(choices) do
    Enum.flat_map(choices, fn %{"delta" => delta, "finish_reason" => reason} ->
      content = delta["content"]
      events = if content, do: [{:content_delta, content}], else: []
      if reason == "stop", do: events ++ [{:done}], else: events
    end)
  end

  defp parse_event(_other), do: []
end

# Run benchmarks if this file is executed directly
if Code.ensure_loaded?(Benchee) do
  Bench.StreamingBench.run()
else
  IO.puts("Benchee not available. Run: mix deps.get")
end
