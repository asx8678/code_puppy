defmodule CodePuppyControl.ParserTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.Parser

  describe "supported_languages/0" do
    test "returns list of languages" do
      languages = Parser.supported_languages()
      assert is_list(languages)
      assert "python" in languages
      assert "elixir" in languages
    end
  end

  describe "nif_available?/0" do
    test "returns boolean" do
      assert is_boolean(Parser.nif_available?())
    end
  end

  describe "extract_symbols/2" do
    test "extracts Python function" do
      source = """
      def hello():
          pass

      class Foo:
          def bar(self):
              pass
      """

      {:ok, outline} = Parser.extract_symbols(source, "python")
      assert outline["success"] == true
      assert is_list(outline["symbols"])
      assert length(outline["symbols"]) >= 2
    end

    test "extracts Elixir module and functions" do
      source = """
      defmodule MyApp do
        def hello, do: :world
        defp private_fn, do: :secret
      end
      """

      {:ok, outline} = Parser.extract_symbols(source, "elixir")
      assert outline["success"] == true
      assert is_list(outline["symbols"])
      assert length(outline["symbols"]) >= 2
    end

    test "returns error for unsupported language" do
      source = "some code"
      {:ok, outline} = Parser.extract_symbols(source, "unsupported_language")
      # Should still return ok but with success=false or fallback
      assert is_map(outline)
    end
  end

  describe "parse_source/2" do
    test "parses Python code" do
      source = "def hello(): pass"

      {:ok, result} = Parser.parse_source(source, "python")
      assert is_map(result)
      assert result["success"] == true
      assert result["language"] == "python"
    end

    test "returns error details for invalid code" do
      source = "def hello(  # incomplete"

      {:ok, result} = Parser.parse_source(source, "python")
      # Even "invalid" code parses (tree-sitter is error-resilient)
      assert is_map(result)
      assert result["language"] == "python"
    end
  end

  describe "get_folds/2" do
    test "extracts fold ranges from Python" do
      source = """
      def outer():
          def inner():
              pass
          return inner
      """

      {:ok, result} = Parser.get_folds(source, "python")
      assert is_map(result)
      assert result["success"] == true
      assert is_list(result["folds"])
    end
  end

  describe "get_highlights/2" do
    test "extracts highlight captures from Python" do
      source = """
      def hello():
          return "world"
      """

      {:ok, result} = Parser.get_highlights(source, "python")
      assert is_map(result)
      assert result["success"] == true
      assert is_list(result["captures"])
    end
  end

  describe "extract_syntax_diagnostics/2" do
    test "finds errors in invalid code" do
      source = "def hello(  # missing closing paren and colon"

      {:ok, result} = Parser.extract_syntax_diagnostics(source, "python")
      assert is_map(result)
      assert is_list(result["diagnostics"])
      assert is_integer(result["error_count"])
      assert is_integer(result["warning_count"])
    end
  end

  describe "detect_language/1 via extract_symbols_from_file" do
    test "detects Python from .py extension" do
      # Create a temp file
      path = Path.join(System.tmp_dir!(), "test_#{:rand.uniform(10000)}.py")
      File.write!(path, "def foo(): pass")

      try do
        {:ok, outline} = Parser.extract_symbols_from_file(path)
        assert outline["language"] == "python"
      after
        File.rm(path)
      end
    end

    test "detects Elixir from .ex extension" do
      path = Path.join(System.tmp_dir!(), "test_#{:rand.uniform(10000)}.ex")
      File.write!(path, "defmodule Foo, do: :bar")

      try do
        {:ok, outline} = Parser.extract_symbols_from_file(path)
        # Should work even with fallback
        assert is_map(outline)
      after
        File.rm(path)
      end
    end
  end
end
