defmodule Mix.Tasks.Bench do
  @moduledoc """
  Run performance benchmarks using Benchee.

  ## Usage

      mix bench                    # Run default benchmark (agent_runner_bench.exs)
      mix bench streaming          # Run bench/streaming_bench.exs
      mix bench ttsr               # Run bench/ttsr_bench.exs
      mix bench repo_compass       # Run bench/repo_compass_bench.exs
      mix bench agent_runner       # Run bench/agent_runner_bench.exs
      mix bench path/to/custom.exs # Run custom benchmark file

  ## Available Benchmarks

  - `agent_runner` - Agent execution and message handling
  - `streaming` - SSE parsing and PartTracker operations
  - `ttsr` - Ring buffer and pattern matching
  - `repo_compass` - File indexing and symbol extraction

  All benchmarks are self-contained and don't require external services.
  """

  use Mix.Task

  @shortdoc "Run performance benchmarks"

  @available_benchmarks %{
    "agent_runner" => "bench/agent_runner_bench.exs",
    "streaming" => "bench/streaming_bench.exs",
    "ttsr" => "bench/ttsr_bench.exs",
    "repo_compass" => "bench/repo_compass_bench.exs"
  }

  @impl true
  def run(args) do
    # Start the application to load all modules
    Mix.Task.run("app.start")

    # Get the benchmark file to run
    bench_file = get_bench_file(args)

    unless File.exists?(bench_file) do
      Mix.raise("""
      Benchmark file not found: #{bench_file}

      Available benchmarks:
      #{format_available_benchmarks()}

      Or provide a path to a custom .exs file.
      """)
    end

    # Ensure benchee is available
    ensure_benchee()

    IO.puts("Running benchmark: #{bench_file}\n")

    # Load and run the benchmark
    Code.require_file(bench_file)
  end

  # Determine which benchmark file to run
  defp get_bench_file(args) do
    case List.first(args) do
      nil ->
        # Default benchmark
        "bench/agent_runner_bench.exs"

      name when is_binary(name) ->
        cond do
          # Check if it's a known benchmark name
          Map.has_key?(@available_benchmarks, name) ->
            @available_benchmarks[name]

          # Check if it's a path to a file
          File.exists?(name) ->
            name

          # Try adding .exs extension
          File.exists?(name <> ".exs") ->
            name <> ".exs"

          # Try bench/ prefix
          File.exists?("bench/#{name}.exs") ->
            "bench/#{name}.exs"

          # Try bench/ prefix without .exs
          File.exists?("bench/#{name}") ->
            "bench/#{name}"

          # Return as-is and let it fail with a nice error
          true ->
            name
        end
    end
  end

  # Ensure Benchee dependency is available
  defp ensure_benchee do
    unless Code.ensure_loaded?(Benchee) do
      Mix.raise("""
      Benchee is not available.

      Please add to your mix.exs:

          {:benchee, "~> 1.3", only: :dev, runtime: false}

      Then run: mix deps.get
      """)
    end
  end

  # Format available benchmarks for help text
  defp format_available_benchmarks do
    @available_benchmarks
    |> Enum.map(fn {name, file} -> "  - #{name} -> #{file}" end)
    |> Enum.join("\n")
  end
end
