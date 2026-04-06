defmodule Mana.RepoCompass.FormatterTest do
  use ExUnit.Case, async: true

  alias Mana.RepoCompass.Formatter

  describe "format/2" do
    test "formats index with header and project name" do
      index = [
        %{path: "lib/module.ex", kind: :elixir_module, symbols: ["MyModule", "def run"]}
      ]

      result = Formatter.format(index, "my_project")

      assert result =~ "## Repo Compass"
      assert result =~ "Project: my_project"
      assert result =~ "Structural context map:"
    end

    test "formats file entries with symbols" do
      index = [
        %{path: "lib/module.ex", kind: :elixir_module, symbols: ["MyModule", "def run"]},
        %{path: "script.py", kind: :python_module, symbols: ["def hello():"]},
        %{path: "README.md", kind: :documentation, symbols: []}
      ]

      result = Formatter.format(index, "test_project")

      assert result =~ "- lib/module.ex [elixir]: MyModule; def run"
      assert result =~ "- script.py [python]: def hello():"
    end

    test "formats different kinds correctly" do
      index = [
        %{path: "lib/a.ex", kind: :elixir_module, symbols: ["A"]},
        %{path: "script.exs", kind: :elixir_script, symbols: []},
        %{path: "code.py", kind: :python_module, symbols: []},
        %{path: "docs.md", kind: :documentation, symbols: []},
        %{path: "cfg.toml", kind: :config, symbols: []},
        %{path: "unknown.xyz", kind: :unknown, symbols: []}
      ]

      result = Formatter.format(index, "test")

      assert result =~ "[elixir]"
      assert result =~ "[script]"
      assert result =~ "[python]"
      assert result =~ "[docs]"
      assert result =~ "[config]"
      assert result =~ "[file]"
    end

    test "joins multiple symbols with semicolons" do
      index = [
        %{path: "lib/big.ex", kind: :elixir_module, symbols: ["Mod1", "Mod2", "def a", "def b"]}
      ]

      result = Formatter.format(index, "test")

      assert result =~ "Mod1; Mod2; def a; def b"
    end

    test "truncates output when exceeding max chars" do
      # Create a large index that will exceed 2400 chars
      many_symbols = for i <- 1..200, do: "VeryLongModuleName#{i}"

      index = [
        %{path: "lib/huge.ex", kind: :elixir_module, symbols: many_symbols}
      ]

      result = Formatter.format(index, "huge_project_with_very_long_name")

      assert String.length(result) <= 2400
      assert String.ends_with?(result, "...")
    end

    test "does not truncate when under max chars" do
      index = [
        %{path: "lib/small.ex", kind: :elixir_module, symbols: ["Small"]}
      ]

      result = Formatter.format(index, "tiny")

      refute result =~ "..."
      assert String.length(result) < 2400
    end

    test "handles empty index" do
      result = Formatter.format([], "empty_project")

      assert result =~ "## Repo Compass"
      assert result =~ "Project: empty_project"
    end

    test "handles files with no symbols" do
      index = [
        %{path: "lib/empty.ex", kind: :elixir_module, symbols: []}
      ]

      result = Formatter.format(index, "test")

      assert result =~ "- lib/empty.ex [elixir]:"
    end
  end
end
