defmodule Bench.RepoCompassBench do
  @moduledoc """
  Benchmarks for RepoCompass indexing and formatting.

  Hot-path code:
  - File discovery and filtering
  - Symbol extraction from source files
  - Index formatting for prompts
  - AST walking for Elixir files
  """

  alias Mana.RepoCompass.Indexer
  alias Mana.RepoCompass.Formatter

  # Use fixtures directory for benchmarks
  @fixtures_dir Path.join(__DIR__, "fixtures")

  # Sample index data for formatting benchmarks
  @sample_index Enum.map(1..50, fn i ->
    %{
      path: "lib/mana/module_#{i}.ex",
      kind: :elixir_module,
      symbols: ["def start_link/1", "def init/1", "def handle_call/3", "defp private_fn/0"]
    }
  end) ++
    Enum.map(1..30, fn i ->
      %{
        path: "test/test_#{i}.exs",
        kind: :elixir_script,
        symbols: ["defmodule ManaTest.#{i}", "test \"test #{i}\""]
      }
    end) ++
    Enum.map(1..20, fn i ->
      %{
        path: "docs/readme_#{i}.md",
        kind: :documentation,
        symbols: []
      }
    end)

  @sample_elixir_content """
  defmodule Mana.SampleModule do
    @moduledoc "A sample module for benchmarking"

    use GenServer

    def start_link(opts) do
      GenServer.start_link(__MODULE__, opts, name: __MODULE__)
    end

    def init(opts) do
      {:ok, %{counter: 0, data: opts[:data]}}
    end

    def get_count(pid) do
      GenServer.call(pid, :get_count)
    end

    def increment(pid) do
      GenServer.cast(pid, :increment)
    end

    def handle_call(:get_count, _from, state) do
      {:reply, state.counter, state}
    end

    def handle_cast(:increment, state) do
      {:noreply, %{state | counter: state.counter + 1}}
    end

    def handle_info(:tick, state) do
      {:noreply, %{state | counter: state.counter + 1}}
    end

    defp private_helper(arg) do
      arg * 2
    end

    defp another_private(arg1, arg2) do
      arg1 + arg2
    end
  end
  """

  @doc """
  Run all benchmarks.
  """
  def run do
    IO.puts("Running RepoCompass benchmarks...\n")

    Benchee.run(%{
      "index 100 .ex files (fixtures)" => fn ->
        # Index the fixtures directory
        index_fixtures()
      end,
      "format output (50 entries)" => fn ->
        Formatter.format(@sample_index, "test_project")
      end,
      "format output (100 entries)" => fn ->
        large_index = @sample_index ++ @sample_index
        Formatter.format(large_index, "test_project")
      end,
      "extract symbols (Elixir AST walk)" => fn ->
        extract_elixir_symbols(@sample_elixir_content)
      end,
      "classify file (100 iterations)" => fn ->
        files = [
          "lib/test.ex",
          "test/test.exs",
          "README.md",
          "config/runtime.exs",
          "mix.exs",
          "priv/data.json",
          "pyproject.toml"
        ]

        Enum.each(1..100, fn _ ->
          Enum.each(files, &classify_file/1)
        end)
      end,
      "file discovery (fixtures dir)" => fn ->
        discover_files(@fixtures_dir, 100)
      end
    })
  end

  # Helper functions

  defp index_fixtures do
    if File.dir?(@fixtures_dir) do
      Indexer.index(@fixtures_dir, max_files: 100, max_symbols_per_file: 10)
    else
      # Fallback: create sample data
      create_sample_fixtures()
      Indexer.index(@fixtures_dir, max_files: 100, max_symbols_per_file: 10)
    end
  end

  defp create_sample_fixtures do
    File.mkdir_p!(@fixtures_dir)

    # Create sample .ex files
    Enum.each(1..50, fn i ->
      content = """
      defmodule Mana.Fixture#{i} do
        @moduledoc "Fixture module #{i}"

        def function_#{i}_a(arg), do: arg
        def function_#{i}_b(arg1, arg2), do: arg1 + arg2
        defp private_#{i}, do: :ok
      end
      """

      File.write!(Path.join(@fixtures_dir, "fixture_#{i}.ex"), content)
    end)

    # Create sample .exs files
    Enum.each(1..30, fn i ->
      content = """
      defmodule Mana.FixtureTest#{i} do
        use ExUnit.Case

        test "test #{i}" do
          assert true
        end
      end
      """

      File.write!(Path.join(@fixtures_dir, "fixture_test_#{i}.exs"), content)
    end)

    # Create sample .md files
    Enum.each(1..20, fn i ->
      content = "# Document #{i}\n\nThis is fixture documentation #{i}.\n"
      File.write!(Path.join(@fixtures_dir, "doc_#{i}.md"), content)
    end)
  end

  defp extract_elixir_symbols(content) do
    case Code.string_to_quoted(content) do
      {:ok, ast} ->
        {_, symbols} =
          Macro.prewalk(ast, [], fn
            {:defmodule, _, [{:__aliases__, _, parts} | _]} = node, acc ->
              name = parts |> Enum.map_join(".", &to_string/1)
              {node, [name | acc]}

            {:def, _, [{name, _, _} | _]} = node, acc when is_atom(name) ->
              {node, ["def #{name}" | acc]}

            {:defp, _, [{name, _, _} | _]} = node, acc when is_atom(name) ->
              {node, ["defp #{name}" | acc]}

            node, acc ->
              {node, acc}
          end)

        symbols

      _ ->
        []
    end
  end

  defp classify_file(path) do
    case Path.extname(path) do
      ".ex" -> :elixir_module
      ".exs" -> :elixir_script
      ".py" -> :python_module
      ".md" -> :documentation
      ".toml" -> :config
      ".json" -> :config
      _ -> :unknown
    end
  end

  defp discover_files(dir, max) do
    case File.ls(dir) do
      {:ok, entries} ->
        entries
        |> Enum.flat_map(fn entry ->
          path = Path.join(dir, entry)

          cond do
            File.dir?(path) and entry not in [".git", "deps", "_build"] ->
              discover_files(path, max)

            File.regular?(path) and Path.extname(entry) in [".ex", ".exs", ".py", ".md"] ->
              [path]

            true ->
              []
          end
        end)
        |> Enum.take(max)

      {:error, _} ->
        []
    end
  end
end

# Run benchmarks if this file is executed directly
if Code.ensure_loaded?(Benchee) do
  Bench.RepoCompassBench.run()
else
  IO.puts("Benchee not available. Run: mix deps.get")
end
