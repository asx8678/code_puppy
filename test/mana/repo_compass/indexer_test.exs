defmodule Mana.RepoCompass.IndexerTest do
  use ExUnit.Case, async: true

  alias Mana.RepoCompass.Indexer

  setup do
    # Create a temporary directory with test files
    temp_dir = System.tmp_dir!()
    test_project = Path.join(temp_dir, "test_project_#{:erlang.unique_integer([:positive])}")

    File.mkdir_p!(test_project)
    File.mkdir_p!(Path.join(test_project, "lib"))
    File.mkdir_p!(Path.join(test_project, "deps"))

    # Create an Elixir file with modules and functions
    elixir_content = """
    defmodule TestModule do
      def public_function do
        :ok
      end

      defp private_function do
        :secret
      end
    end

    defmodule AnotherModule do
      def greet(name) do
        "Hello, \#{name}"
      end
    end
    """

    File.write!(Path.join([test_project, "lib", "test_module.ex"]), elixir_content)

    # Create a Python file with functions and classes
    python_content = """
    def hello():
        return "Hello"

    class MyClass:
        def method(self):
            pass

    def another_function():
        pass
    """

    File.write!(Path.join(test_project, "script.py"), python_content)

    # Create a Markdown file
    File.write!(Path.join(test_project, "README.md"), "# Test Project\n")

    # Create a config file
    File.write!(Path.join(test_project, "config.toml"), "[section]\nkey = \"value\"\n")

    # Create a file in deps (should be skipped)
    File.write!(Path.join([test_project, "deps", "dependency.ex"]), "# Dep\n")

    on_exit(fn ->
      File.rm_rf!(test_project)
    end)

    {:ok, project_dir: test_project}
  end

  describe "index/2" do
    test "discovers and indexes source files", %{project_dir: project_dir} do
      results = Indexer.index(project_dir)

      assert results != []

      paths = Enum.map(results, & &1.path)
      assert "lib/test_module.ex" in paths
      assert "script.py" in paths
      assert "README.md" in paths
      assert "config.toml" in paths
    end

    test "skips directories in skip list", %{project_dir: project_dir} do
      results = Indexer.index(project_dir)

      paths = Enum.map(results, & &1.path)
      refute "deps/dependency.ex" in paths
    end

    test "respects max_files option", %{project_dir: project_dir} do
      results = Indexer.index(project_dir, max_files: 2)
      assert length(results) <= 2
    end

    test "classifies file kinds correctly", %{project_dir: project_dir} do
      results = Indexer.index(project_dir)

      elixir_file = Enum.find(results, &(&1.path == "lib/test_module.ex"))
      assert elixir_file.kind == :elixir_module

      python_file = Enum.find(results, &(&1.path == "script.py"))
      assert python_file.kind == :python_module

      md_file = Enum.find(results, &(&1.path == "README.md"))
      assert md_file.kind == :documentation

      toml_file = Enum.find(results, &(&1.path == "config.toml"))
      assert toml_file.kind == :config
    end

    test "extracts Elixir module and function names", %{project_dir: project_dir} do
      results = Indexer.index(project_dir, max_symbols_per_file: 10)

      elixir_file = Enum.find(results, &(&1.path == "lib/test_module.ex"))
      assert elixir_file != nil

      symbols = elixir_file.symbols
      assert "TestModule" in symbols
      assert "AnotherModule" in symbols
      assert "def public_function" in symbols
      assert "defp private_function" in symbols
      assert "def greet" in symbols
    end

    test "extracts Python function and class names", %{project_dir: project_dir} do
      results = Indexer.index(project_dir, max_symbols_per_file: 10)

      python_file = Enum.find(results, &(&1.path == "script.py"))
      assert python_file != nil

      symbols = python_file.symbols
      assert "def hello():" in symbols
      assert "class MyClass:" in symbols
      assert "def method(self):" in symbols
      assert "def another_function():" in symbols
    end

    test "respects max_symbols_per_file option", %{project_dir: project_dir} do
      results = Indexer.index(project_dir, max_symbols_per_file: 2)

      elixir_file = Enum.find(results, &(&1.path == "lib/test_module.ex"))
      assert length(elixir_file.symbols) <= 2
    end

    test "handles empty directories gracefully" do
      temp_dir = System.tmp_dir!()
      empty_dir = Path.join(temp_dir, "empty_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(empty_dir)

      try do
        results = Indexer.index(empty_dir)
        assert results == []
      after
        File.rm_rf!(empty_dir)
      end
    end

    test "handles non-existent directories gracefully" do
      results = Indexer.index("/non/existent/path")
      assert results == []
    end

    test "handles files with syntax errors gracefully", %{project_dir: project_dir} do
      # Create a file with invalid Elixir syntax
      bad_content = "defmodule Bad do def broken"
      File.write!(Path.join([project_dir, "lib", "bad.ex"]), bad_content)

      results = Indexer.index(project_dir)

      # Should still index other files
      assert results != []
    end
  end
end
