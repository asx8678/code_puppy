defmodule CodePuppyControl.CodeContextTest do
  @moduledoc """
  Tests for the main CodeContext API module.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.CodeContext
  alias CodePuppyControl.CodeContext.{Context, FileOutline, SymbolInfo}

  setup do
    # Create a temporary directory for testing
    tmp_dir =
      Path.join(System.tmp_dir!(), "code_context_api_#{System.unique_integer([:positive])}")

    File.mkdir_p!(tmp_dir)

    # Create test files
    File.write!(
      Path.join(tmp_dir, "sample.py"),
      """
      class DataProcessor:
          def process(self, data):
              return data.upper()

          def validate(self, data):
              return len(data) > 0

      def helper_function():
          return "helper"
      """
    )

    File.write!(
      Path.join(tmp_dir, "sample.ex"),
      """
      defmodule DataProcessor do
        def process(data) do
          String.upcase(data)
        end

        defp validate(data) do
          String.length(data) > 0
        end
      end
      """
    )

    on_exit(fn ->
      CodeContext.stop_global_explorer()
      File.rm_rf!(tmp_dir)
    end)

    {:ok, tmp_dir: tmp_dir}
  end

  describe "get_context/2" do
    test "gets context for a Python file", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      assert {:ok, context} = CodeContext.get_context(file_path)

      assert %Context{} = context
      assert context.file_path == Path.expand(file_path)
      assert context.language == "python"
      assert Context.has_content?(context)
    end

    test "respects include_content: false option", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      assert {:ok, context} = CodeContext.get_context(file_path, include_content: false)

      refute Context.has_content?(context)
      assert context.content == nil
    end

    test "respects with_symbols: false option", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      assert {:ok, context} = CodeContext.get_context(file_path, with_symbols: false)

      assert context.outline == nil
      assert context.content != nil
    end

    test "returns context with error for non-existent file" do
      assert {:ok, context} = CodeContext.get_context("/nonexistent/file.py")
      assert context.has_errors == true
      assert context.error_message != nil
    end
  end

  describe "get_context!/2" do
    test "returns context on success", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      context = CodeContext.get_context!(file_path)

      assert %Context{} = context
      assert context.language == "python"
    end

    test "get_context! returns context for non-existent file (with error flag)" do
      context = CodeContext.get_context!("/nonexistent/file.py")
      assert %Context{} = context
      assert context.has_errors == true
    end
  end

  describe "get_outline/2" do
    test "gets outline for a Python file", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      assert {:ok, outline} = CodeContext.get_outline(file_path)

      assert %FileOutline{} = outline
      assert outline.language == "python"
      assert is_list(outline.symbols)
    end

    test "respects max_depth option", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      assert {:ok, outline} = CodeContext.get_outline(file_path, max_depth: 1)

      # All nested symbols should have empty children
      for symbol <- outline.symbols do
        assert symbol.children == []
      end
    end
  end

  describe "get_outline!/2" do
    test "returns outline on success", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      outline = CodeContext.get_outline!(file_path)

      assert %FileOutline{} = outline
    end
  end

  describe "explore_directory/2" do
    test "explores directory and returns contexts", %{tmp_dir: tmp_dir} do
      assert {:ok, contexts} = CodeContext.explore_directory(tmp_dir)

      assert is_list(contexts)
      assert length(contexts) >= 2

      # Should find both Python and Elixir files
      languages = Enum.map(contexts, & &1.language) |> Enum.uniq()
      assert "python" in languages
      assert "elixir" in languages
    end

    test "respects pattern option", %{tmp_dir: tmp_dir} do
      assert {:ok, contexts} = CodeContext.explore_directory(tmp_dir, pattern: "*.py")

      assert Enum.all?(contexts, &(&1.language == "python"))
    end

    test "respects max_files option", %{tmp_dir: tmp_dir} do
      # Create additional files
      for i <- 1..10 do
        File.write!(Path.join(tmp_dir, "extra#{i}.py"), "def extra#{i}(): pass")
      end

      assert {:ok, contexts} = CodeContext.explore_directory(tmp_dir, max_files: 5)

      assert length(contexts) <= 5
    end
  end

  describe "explore_directory!/2" do
    test "returns contexts on success", %{tmp_dir: tmp_dir} do
      contexts = CodeContext.explore_directory!(tmp_dir)

      assert is_list(contexts)
      assert length(contexts) >= 2
    end
  end

  describe "find_symbol_definitions/3" do
    test "finds symbol definitions across directory", %{tmp_dir: tmp_dir} do
      assert {:ok, results} = CodeContext.find_symbol_definitions(tmp_dir, "DataProcessor")

      assert is_list(results)
      # Should find DataProcessor class in Python and module in Elixir
      assert Enum.any?(results, fn {_path, symbol} -> symbol.name == "DataProcessor" end)
    end

    test "returns empty list for non-existent symbol", %{tmp_dir: tmp_dir} do
      assert {:ok, results} = CodeContext.find_symbol_definitions(tmp_dir, "NonExistent")

      assert results == []
    end
  end

  describe "format_outline/2" do
    test "formats outline as string" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("MyClass", "class", 1, 50),
          SymbolInfo.new("my_func", "function", 60, 70)
        ]
      }

      formatted = CodeContext.format_outline(outline)

      assert formatted =~ "📋 Outline (python)"
      assert formatted =~ "MyClass"
      assert formatted =~ "my_func"
    end

    test "includes line numbers by default" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("MyClass", "class", 1, 50)
        ]
      }

      formatted = CodeContext.format_outline(outline)

      assert formatted =~ "(L1)"
    end

    test "omits line numbers when show_lines: false" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("MyClass", "class", 1, 50)
        ]
      }

      formatted = CodeContext.format_outline(outline, show_lines: false)

      refute formatted =~ "(L1)"
    end

    test "formats nested symbols" do
      child = SymbolInfo.new("child_method", "method", 10, 20)
      parent = SymbolInfo.new("MyClass", "class", 1, 50, children: [child])

      outline = %FileOutline{
        language: "python",
        symbols: [parent]
      }

      formatted = CodeContext.format_outline(outline)

      assert formatted =~ "MyClass"
      assert formatted =~ "child_method"
    end
  end

  describe "enhance_read_result/2" do
    test "enhances result with symbol information", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      result = %{content: "def test(): pass", num_tokens: 10, file_path: file_path}

      assert {:ok, enhanced} = CodeContext.enhance_read_result(result, with_symbols: true)

      assert enhanced[:outline] != nil
      assert enhanced[:symbols_available] == true
    end

    test "skips enhancement when with_symbols: false" do
      result = %{content: "def test(): pass", num_tokens: 10, file_path: "/some/path.py"}

      assert {:ok, enhanced} = CodeContext.enhance_read_result(result, with_symbols: false)

      # Should return original result unchanged
      assert enhanced[:outline] == nil
    end
  end

  describe "cache management" do
    test "invalidate_cache/1 clears specific file cache", %{tmp_dir: tmp_dir} do
      file_path = Path.join(tmp_dir, "sample.py")

      # Access to populate cache
      CodeContext.get_context(file_path)
      {:ok, stats1} = CodeContext.get_cache_stats()
      assert stats1.cache_size > 0

      # Invalidate specific file
      assert :ok = CodeContext.invalidate_cache(file_path)

      {:ok, stats2} = CodeContext.get_cache_stats()
      assert stats2.cache_size < stats1.cache_size
    end

    test "invalidate_cache/0 clears all cache", %{tmp_dir: tmp_dir} do
      # Populate cache
      CodeContext.get_context(Path.join(tmp_dir, "sample.py"))

      # Clear all
      assert :ok = CodeContext.invalidate_cache()

      {:ok, stats} = CodeContext.get_cache_stats()
      assert stats.cache_size == 0
    end

    test "get_cache_stats/0 returns statistics", %{tmp_dir: tmp_dir} do
      # Initial state
      {:ok, stats1} = CodeContext.get_cache_stats()
      assert is_map(stats1)

      # Populate cache
      CodeContext.get_context(Path.join(tmp_dir, "sample.py"))

      # Updated state
      {:ok, stats2} = CodeContext.get_cache_stats()
      assert stats2.parse_count > 0
    end
  end

  describe "global explorer management" do
    test "start_global_explorer/1 starts the global instance" do
      CodeContext.stop_global_explorer()

      assert {:ok, pid} = CodeContext.start_global_explorer()
      assert Process.alive?(pid)
    end

    test "stop_global_explorer/0 stops the global instance" do
      CodeContext.start_global_explorer()

      assert :ok = CodeContext.stop_global_explorer()
      refute Process.whereis(:code_context_global_explorer)
    end

    test "global explorer is lazily started on first use", %{tmp_dir: tmp_dir} do
      # Ensure stopped
      CodeContext.stop_global_explorer()
      refute Process.whereis(:code_context_global_explorer)

      # First call should start it
      CodeContext.get_context(Path.join(tmp_dir, "sample.py"))

      assert Process.whereis(:code_context_global_explorer)
    end
  end
end
