defmodule CodePuppyControl.CodeContext.ExplorerTest do
  @moduledoc """
  Tests for the Explorer GenServer.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.CodeContext.{Context, Explorer, FileOutline}

  setup do
    # Create a temporary directory for testing
    tmp_dir =
      Path.join(System.tmp_dir!(), "code_context_explorer_#{System.unique_integer([:positive])}")

    File.mkdir_p!(tmp_dir)

    # Create test files
    File.write!(
      Path.join(tmp_dir, "test.py"),
      """
      class MyClass:
          def method1(self):
              pass

          def method2(self):
              pass

      def global_function():
          pass
      """
    )

    File.write!(
      Path.join(tmp_dir, "test.ex"),
      """
      defmodule MyModule do
        def public_function do
          :ok
        end

        defp private_function do
          :error
        end
      end
      """
    )

    File.write!(
      Path.join(tmp_dir, "readme.md"),
      "# Test Project\n\nThis is a test.\n"
    )

    # Start a fresh explorer instance for each test
    {:ok, explorer} = Explorer.start_link(enable_cache: true, max_cache_size: 10)

    on_exit(fn ->
      File.rm_rf!(tmp_dir)
      if Process.alive?(explorer), do: GenServer.stop(explorer)
    end)

    {:ok, tmp_dir: tmp_dir, explorer: explorer}
  end

  describe "start_link/1" do
    test "starts successfully with default options" do
      # Use a unique name to avoid conflicts
      unique_name = :"explorer_test_#{System.unique_integer([:positive])}"
      assert {:ok, pid} = Explorer.start_link(name: unique_name)
      assert Process.alive?(pid)
      GenServer.stop(pid)
    end

    test "starts successfully with custom options" do
      unique_name = :"explorer_test_#{System.unique_integer([:positive])}"
      assert {:ok, pid} = Explorer.start_link(name: unique_name, enable_cache: false, max_cache_size: 50)
      assert Process.alive?(pid)
      GenServer.stop(pid)
    end
  end

  describe "child_spec/1" do
    test "returns a valid child_spec" do
      spec = Explorer.child_spec([])

      assert spec.id == Explorer
      assert spec.type == :worker
      assert spec.restart == :permanent
    end
  end

  describe "explore_file/3" do
    test "explores a Python file successfully", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: true)

      assert context.file_path == Path.expand(file_path)
      assert context.language == "python"
      assert context.num_lines > 0
      assert Context.has_content?(context)
      assert Context.parsed?(context)
    end

    test "explores file without content", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)

      assert context.content == nil
      assert not Context.has_content?(context)
    end

    test "explores an Elixir file successfully", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.ex")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: true)

      assert context.language == "elixir"
    end

    test "handles unsupported file types", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "readme.md")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)

      # Markdown files don't have symbol extraction
      assert context.outline == nil
    end

    test "returns context with error for non-existent file", %{explorer: explorer} do
      assert {:ok, context} = Explorer.explore_file(explorer, "/nonexistent/file.py")
      assert context.has_errors == true
      assert context.error_message != nil
    end

    test "caches results for repeated access", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      # First access
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)

      # Second access should be cached
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)

      # Check cache stats
      assert {:ok, stats} = Explorer.get_cache_stats(explorer)
      assert stats.cache_hits >= 1
    end

    test "force_refresh bypasses cache", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      # First access
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)
      {:ok, stats1} = Explorer.get_cache_stats(explorer)

      # Force refresh
      assert {:ok, _} =
               Explorer.explore_file(explorer, file_path,
                 include_content: true,
                 force_refresh: true
               )

      {:ok, stats2} = Explorer.get_cache_stats(explorer)
      # Parse count should increase
      assert stats2.parse_count > stats1.parse_count
    end
  end

  describe "explore_file!/3" do
    test "returns context on success", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      context = Explorer.explore_file!(explorer, file_path)

      assert %Context{} = context
      assert context.language == "python"
    end

    test "explore_file! returns context for non-existent file (with error flag)", %{explorer: explorer} do
      # explore_file! doesn't raise for non-existent files, it returns context with error flag
      context = Explorer.explore_file!(explorer, "/nonexistent/file.py")
      assert %Context{} = context
      assert context.has_errors == true
    end
  end

  describe "get_outline/3" do
    test "returns file outline", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      assert {:ok, outline} = Explorer.get_outline(explorer, file_path)

      assert %FileOutline{} = outline
      assert outline.language == "python"
      assert is_list(outline.symbols)
    end

    test "applies max_depth limit", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      assert {:ok, outline} = Explorer.get_outline(explorer, file_path, max_depth: 1)

      # Nested symbols should have empty children
      for symbol <- outline.symbols do
        assert symbol.children == []
      end
    end

    test "returns error outline for non-existent file", %{explorer: explorer} do
      assert {:ok, outline} = Explorer.get_outline(explorer, "/nonexistent/file.py")

      assert outline.success == false
      assert outline.errors != []
    end
  end

  describe "explore_directory/3" do
    test "explores directory recursively", %{tmp_dir: tmp_dir, explorer: explorer} do
      assert {:ok, contexts} = Explorer.explore_directory(explorer, tmp_dir)

      assert is_list(contexts)
      # Should find Python and Elixir files
      paths = Enum.map(contexts, & &1.file_path)
      assert Enum.any?(paths, &String.ends_with?(&1, "test.py"))
      assert Enum.any?(paths, &String.ends_with?(&1, "test.ex"))
    end

    test "respects max_files limit", %{tmp_dir: tmp_dir, explorer: explorer} do
      # Create additional files
      for i <- 1..10 do
        File.write!(Path.join(tmp_dir, "file#{i}.py"), "def test#{i}(): pass")
      end

      assert {:ok, contexts} = Explorer.explore_directory(explorer, tmp_dir, max_files: 5)

      assert length(contexts) <= 5
    end

    test "respects pattern filter", %{tmp_dir: tmp_dir, explorer: explorer} do
      assert {:ok, contexts} = Explorer.explore_directory(explorer, tmp_dir, pattern: "*.py")

      assert Enum.all?(contexts, &(&1.language == "python"))
    end

    test "handles non-recursive exploration", %{tmp_dir: tmp_dir, explorer: explorer} do
      # Create a subdirectory with a file
      sub_dir = Path.join(tmp_dir, "subdir")
      File.mkdir_p!(sub_dir)
      File.write!(Path.join(sub_dir, "nested.py"), "def nested(): pass")

      assert {:ok, contexts} = Explorer.explore_directory(explorer, tmp_dir, recursive: false)

      # Should not include nested file
      refute Enum.any?(contexts, &String.contains?(&1.file_path, "subdir"))
    end

    test "returns empty list for non-existent directory", %{explorer: explorer} do
      assert {:ok, []} = Explorer.explore_directory(explorer, "/nonexistent/directory")
    end
  end

  describe "find_symbol_definitions/4" do
    test "finds symbol definitions across directory", %{tmp_dir: tmp_dir, explorer: explorer} do
      assert {:ok, results} = Explorer.find_symbol_definitions(explorer, tmp_dir, "MyClass")

      assert is_list(results)
      # Should find MyClass in test.py
      assert Enum.any?(results, fn {_path, symbol} -> symbol.name == "MyClass" end)
    end

    test "finds nested symbol definitions", %{tmp_dir: tmp_dir, explorer: explorer} do
      assert {:ok, results} =
               Explorer.find_symbol_definitions(explorer, tmp_dir, "method1", max_files: 50)

      # method1 is a nested method inside MyClass
      assert Enum.any?(results, fn {_path, symbol} -> symbol.name == "method1" end)
    end

    test "returns empty list when symbol not found", %{tmp_dir: tmp_dir, explorer: explorer} do
      assert {:ok, results} = Explorer.find_symbol_definitions(explorer, tmp_dir, "NonExistent")

      assert results == []
    end
  end

  describe "invalidate_cache/2" do
    test "invalidates cache for specific file", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      # Access file to cache it
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)
      {:ok, stats1} = Explorer.get_cache_stats(explorer)
      assert stats1.cache_size > 0

      # Invalidate specific file
      assert :ok = Explorer.invalidate_cache(explorer, file_path)

      {:ok, stats2} = Explorer.get_cache_stats(explorer)
      assert stats2.cache_size < stats1.cache_size
    end

    test "invalidates all cache when no file specified", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      # Access file to cache it
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)

      # Clear all cache
      assert :ok = Explorer.invalidate_cache(explorer)

      {:ok, stats} = Explorer.get_cache_stats(explorer)
      assert stats.cache_size == 0
    end
  end

  describe "get_cache_stats/1" do
    test "returns cache statistics", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")

      # Initial stats
      {:ok, stats1} = Explorer.get_cache_stats(explorer)
      assert stats1.cache_size == 0

      # Access file
      assert {:ok, _} = Explorer.explore_file(explorer, file_path, include_content: true)

      # Updated stats
      {:ok, stats2} = Explorer.get_cache_stats(explorer)
      assert stats2.cache_size > 0
      assert stats2.parse_count > 0
      assert stats2.cache_misses > 0
    end
  end

  describe "language detection" do
    test "detects Python from extension", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.py")
      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)
      assert context.language == "python"
    end

    test "detects Elixir from .ex extension", %{tmp_dir: tmp_dir, explorer: explorer} do
      file_path = Path.join(tmp_dir, "test.ex")
      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)
      assert context.language == "elixir"
    end

    test "detects Elixir from .exs extension", %{tmp_dir: tmp_dir, explorer: explorer} do
      File.write!(Path.join(tmp_dir, "test.exs"), "defmodule Test do end")
      file_path = Path.join(tmp_dir, "test.exs")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)
      assert context.language == "elixir"
    end

    test "returns nil for unknown extensions", %{tmp_dir: tmp_dir, explorer: explorer} do
      File.write!(Path.join(tmp_dir, "test.xyz"), "unknown content")
      file_path = Path.join(tmp_dir, "test.xyz")

      assert {:ok, context} = Explorer.explore_file(explorer, file_path, include_content: false)
      assert context.language == nil
    end
  end
end
