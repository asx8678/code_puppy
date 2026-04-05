defmodule Mana.Tools.IgnorePatternsTest do
  @moduledoc """
  Tests for Mana.Tools.IgnorePatterns module.
  """

  use ExUnit.Case, async: true

  alias Mana.Tools.IgnorePatterns

  describe "ignore_path?/1" do
    test "ignores .git directories" do
      assert IgnorePatterns.ignore_path?(".git")
      assert IgnorePatterns.ignore_path?("/path/to/.git")
      assert IgnorePatterns.ignore_path?(".git/objects")
    end

    test "ignores __pycache__" do
      assert IgnorePatterns.ignore_path?("__pycache__")
      assert IgnorePatterns.ignore_path?("/path/to/__pycache__")
    end

    test "ignores node_modules" do
      assert IgnorePatterns.ignore_path?("node_modules")
      assert IgnorePatterns.ignore_path?("/project/node_modules")
    end

    test "ignores virtualenv directories" do
      assert IgnorePatterns.ignore_path?(".venv")
      assert IgnorePatterns.ignore_path?("venv")
      assert IgnorePatterns.ignore_path?("/path/.venv")
    end

    test "ignores build directories" do
      assert IgnorePatterns.ignore_path?("dist")
      assert IgnorePatterns.ignore_path?("build")
      assert IgnorePatterns.ignore_path?("_build")
    end

    test "ignores cache directories" do
      assert IgnorePatterns.ignore_path?(".tox")
      assert IgnorePatterns.ignore_path?(".mypy_cache")
      assert IgnorePatterns.ignore_path?(".pytest_cache")
      assert IgnorePatterns.ignore_path?(".eggs")
    end

    test "ignores IDE files" do
      assert IgnorePatterns.ignore_path?(".DS_Store")
      assert IgnorePatterns.ignore_path?(".idea")
      assert IgnorePatterns.ignore_path?(".vscode")
      assert IgnorePatterns.ignore_path?(".elixir_ls")
    end

    test "ignores environment files" do
      assert IgnorePatterns.ignore_path?(".env")
      assert IgnorePatterns.ignore_path?(".env.local")
    end

    test "ignores Elixir build artifacts" do
      assert IgnorePatterns.ignore_path?(".beam")
      assert IgnorePatterns.ignore_path?("deps")
    end

    test "does not ignore regular files" do
      refute IgnorePatterns.ignore_path?("main.py")
      refute IgnorePatterns.ignore_path?("README.md")
      refute IgnorePatterns.ignore_path?("lib/mana.ex")
      refute IgnorePatterns.ignore_path?(".env.example")
    end
  end

  describe "ignore_dir?/1" do
    test "uses same logic as ignore_path?" do
      assert IgnorePatterns.ignore_dir?(".git")
      assert IgnorePatterns.ignore_dir?("node_modules")
      refute IgnorePatterns.ignore_dir?("src")
    end
  end

  describe "filter_paths/1" do
    test "filters out ignored paths" do
      paths = [
        "src/main.py",
        ".git/config",
        "README.md",
        "node_modules/lodash",
        "lib/mana.ex"
      ]

      filtered = IgnorePatterns.filter_paths(paths)

      assert "src/main.py" in filtered
      assert "README.md" in filtered
      assert "lib/mana.ex" in filtered
      refute ".git/config" in filtered
      refute "node_modules/lodash" in filtered
    end

    test "returns empty list when all paths are ignored" do
      paths = [".git", "__pycache__", ".venv"]
      assert IgnorePatterns.filter_paths(paths) == []
    end

    test "returns all paths when none are ignored" do
      paths = ["src", "test", "lib"]
      assert IgnorePatterns.filter_paths(paths) == paths
    end
  end
end
