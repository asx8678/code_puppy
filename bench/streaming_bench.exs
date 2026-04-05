defmodule Bench.StreamingBench do
  @moduledoc """
  Benchmarks for streaming components.

  Hot-path code in streaming:
  - SSE event parsing
  - PartTracker state updates
  - Event handler processing
  - Stream event dispatch
  """

  alias Mana.Streaming.PartTracker

  # Sample SSE event data
  @sample_sse_events Enum.map(1..100, fn i ->
    """
    event: message
    data: #{Jason.encode!(%{"index" => i, "content" => "Hello #{i}", "type" => "delta"})}

    """
  end)

  @doc """
  Run all benchmarks.
  """
  def run do
    IO.puts("Running Streaming benchmarks...\n")

    Benchee.run(%{
      "SSE parsing (100 events)" => fn ->
        parse_sse_events(@sample_sse_events)
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

  # Helper functions

  defp parse_sse_events(events) do
    Enum.map(events, fn event ->
      # Simple SSE parsing simulation
      case Regex.run(~r/data: (.+)/, event) do
        [_, json] ->
          case Jason.decode(json) do
            {:ok, data} -> {:ok, data}
            _ -> {:error, :invalid_json}
          end

        _ ->
          {:error, :no_data}
      end
    end)
  end
end

# Run benchmarks if this file is executed directly
if Code.ensure_loaded?(Benchee) do
  Bench.StreamingBench.run()
else
  IO.puts("Benchee not available. Run: mix deps.get")
end
