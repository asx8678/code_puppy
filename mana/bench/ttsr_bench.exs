defmodule Bench.TTSRBench do
  @moduledoc """
  Benchmarks for TTSR (Test-Time Safety Rules) components.

  Hot-path code:
  - Ring buffer push operations
  - Regex pattern matching on buffer
  - Rule checking
  """

  alias Mana.TTSR.Rule

  @buffer_size 512

  # Sample rules for benchmarking
  @sample_rules [
    %Rule{
      name: "no_shell_exec",
      trigger: ~r/shell_exec|exec\s*\(/i,
      content: "Shell execution detected",
      source: "bench/rules.json",
      scope: :all,
      repeat: :once,
      pending: false,
      triggered_at_turn: nil
    },
    %Rule{
      name: "rm_rf_check",
      trigger: ~r/rm\s+-rf|\brm\s+-f/i,
      content: "Dangerous rm command detected",
      source: "bench/rules.json",
      scope: :text,
      repeat: :once,
      pending: false,
      triggered_at_turn: nil
    },
    %Rule{
      name: "no_delete_all",
      trigger: ~r/delete\s+all|drop\s+table/i,
      content: "Bulk deletion detected",
      source: "bench/rules.json",
      scope: :text,
      repeat: {:gap, 2},
      pending: false,
      triggered_at_turn: nil
    }
  ]

  @sample_content_stream Stream.cycle(["A"]) |> Enum.take(1000) |> Enum.join()

  @doc """
  Run all benchmarks.
  """
  def run do
    IO.puts("Running TTSR benchmarks...\n")

    Benchee.run(%{
      "ring buffer push (1000 chars)" => fn ->
        buffer = ""

        Enum.reduce(String.graphemes(@sample_content_stream), buffer, fn char, acc ->
          push_to_buffer(acc, char)
        end)
      end,
      "ring buffer push (10000 chars)" => fn ->
        large_content = Stream.cycle(["X"]) |> Enum.take(10000) |> Enum.join()
        buffer = ""

        Enum.reduce(String.graphemes(large_content), buffer, fn char, acc ->
          push_to_buffer(acc, char)
        end)
      end,
      "regex match on 512 char buffer" => fn ->
        buffer = String.duplicate("test content ", 40) <> "rm -rf /"

        Enum.each(@sample_rules, fn rule ->
          Regex.match?(rule.trigger, buffer)
        end)
      end,
      "rule eligibility check (1000 iterations)" => fn ->
        rule = hd(@sample_rules)

        Enum.each(1..1000, fn turn ->
          Rule.eligible?(rule, turn)
        end)
      end,
      "rule struct creation" => fn ->
        Enum.map(1..100, fn i ->
          %Rule{
            name: "rule_#{i}",
            trigger: ~r/test#{i}/i,
            content: "Rule content #{i}",
            source: "bench/rules.json",
            scope: :text,
            repeat: :once,
            pending: false,
            triggered_at_turn: nil
          }
        end)
      end,
      "pattern matching (complex regex)" => fn ->
        complex_regex = ~r/(rm\s+-rf|delete\s+all|drop\s+database|exec\s*\(|shell_exec)/i
        buffer = String.duplicate("some normal content ", 20) <> "shell_exec('rm -rf /')"

        Regex.match?(complex_regex, buffer)
      end
    })
  end

  # Helper functions (mirroring StreamWatcher implementation)

  defp push_to_buffer(buffer, char) do
    new = buffer <> char

    if String.length(new) > @buffer_size do
      String.slice(new, -@buffer_size, @buffer_size)
    else
      new
    end
  end
end

# Run benchmarks if this file is executed directly
if Code.ensure_loaded?(Benchee) do
  Bench.TTSRBench.run()
else
  IO.puts("Benchee not available. Run: mix deps.get")
end
