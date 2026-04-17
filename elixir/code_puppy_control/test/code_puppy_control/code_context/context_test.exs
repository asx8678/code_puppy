defmodule CodePuppyControl.CodeContext.ContextTest do
  @moduledoc """
  Tests for the Context module.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.CodeContext.{Context, FileOutline, SymbolInfo}

  describe "new/2" do
    test "creates a Context with required file_path" do
      context = Context.new("/path/to/file.py")

      assert context.file_path == "/path/to/file.py"
      assert context.content == nil
      assert context.language == nil
      assert context.outline == nil
      assert context.file_size == 0
      assert context.num_lines == 0
      assert context.num_tokens == 0
      assert context.parse_time_ms == 0.0
      assert context.has_errors == false
      assert context.error_message == nil
    end

    test "creates a Context with optional fields" do
      outline = FileOutline.new("python", symbols: [SymbolInfo.new("test", "function", 1, 10)])

      context =
        Context.new("/path/to/file.py",
          content: "def test(): pass",
          language: "python",
          outline: outline,
          file_size: 100,
          num_lines: 10,
          num_tokens: 25,
          parse_time_ms: 50.0
        )

      assert context.content == "def test(): pass"
      assert context.language == "python"
      assert context.outline == outline
      assert context.file_size == 100
      assert context.num_lines == 10
      assert context.num_tokens == 25
      assert context.parse_time_ms == 50.0
    end
  end

  describe "from_map/1" do
    test "creates Context from string-keyed map" do
      map = %{
        "file_path" => "/path/to/file.py",
        "language" => "python",
        "num_lines" => 100,
        "num_tokens" => 500
      }

      context = Context.from_map(map)

      assert context.file_path == "/path/to/file.py"
      assert context.language == "python"
      assert context.num_lines == 100
      assert context.num_tokens == 500
    end

    test "creates Context from atom-keyed map" do
      map = %{
        file_path: "/path/to/file.ex",
        language: :elixir
      }

      context = Context.from_map(map)

      assert context.file_path == "/path/to/file.ex"
      assert context.language == :elixir
    end

    test "handles outline map conversion" do
      map = %{
        "file_path" => "/path/to/file.py",
        "outline" => %{
          "language" => "python",
          "symbols" => [],
          "success" => true
        }
      }

      context = Context.from_map(map)

      assert context.outline != nil
      assert context.outline.language == "python"
    end

    test "handles nil outline" do
      map = %{
        "file_path" => "/path/to/file.py",
        "outline" => nil
      }

      context = Context.from_map(map)

      assert context.outline == nil
    end
  end

  describe "to_map/1" do
    test "converts Context to map" do
      context = Context.new("/path/to/file.py", language: "python", num_lines: 100)

      map = Context.to_map(context)

      assert map["file_path"] == "/path/to/file.py"
      assert map["language"] == "python"
      assert map["num_lines"] == 100
    end

    test "converts outline to map" do
      outline = FileOutline.new("python", symbols: [SymbolInfo.new("test", "function", 1, 10)])
      context = Context.new("/path/to/file.py", outline: outline)

      map = Context.to_map(context)

      assert is_map(map["outline"])
      assert map["outline"]["language"] == "python"
    end
  end

  describe "parsed?/1" do
    test "returns true when outline exists and success is true" do
      outline = FileOutline.new("python", success: true)
      context = Context.new("/path/to/file.py", outline: outline)

      assert Context.parsed?(context)
    end

    test "returns false when outline is nil" do
      context = Context.new("/path/to/file.py")

      refute Context.parsed?(context)
    end

    test "returns false when outline success is false" do
      outline = FileOutline.new("python", success: false, errors: ["Parse error"])
      context = Context.new("/path/to/file.py", outline: outline)

      refute Context.parsed?(context)
    end
  end

  describe "symbol_count/1" do
    test "returns number of symbols from outline" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("func1", "function", 1, 10),
          SymbolInfo.new("func2", "function", 15, 20)
        ]
      }

      context = Context.new("/path/to/file.py", outline: outline)

      assert Context.symbol_count(context) == 2
    end

    test "returns 0 when outline is nil" do
      context = Context.new("/path/to/file.py")

      assert Context.symbol_count(context) == 0
    end
  end

  describe "summary/1" do
    test "generates basic summary" do
      context =
        Context.new("/path/to/file.py",
          language: "python",
          num_lines: 100,
          num_tokens: 500
        )

      summary = Context.summary(context)

      assert summary =~ "📄 /path/to/file.py"
      assert summary =~ "Language: python"
      assert summary =~ "Lines: 100, Tokens: 500"
    end

    test "includes symbol count when outline present" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("Class1", "class", 1, 50),
          SymbolInfo.new("func1", "function", 60, 70)
        ]
      }

      context =
        Context.new("/path/to/file.py",
          language: "python",
          outline: outline
        )

      summary = Context.summary(context)

      assert summary =~ "Symbols: 2"
      assert summary =~ "Classes: 1"
      assert summary =~ "Functions: 1"
    end

    test "includes error message when has_errors" do
      context =
        Context.new("/path/to/file.py",
          has_errors: true,
          error_message: "File not found"
        )

      summary = Context.summary(context)

      assert summary =~ "⚠️ Error: File not found"
    end
  end

  describe "file_name/1" do
    test "returns file name from path" do
      context = Context.new("/path/to/file.py")

      assert Context.file_name(context) == "file.py"
    end
  end

  describe "directory/1" do
    test "returns directory from path" do
      context = Context.new("/path/to/file.py")

      assert Context.directory(context) == "/path/to"
    end
  end

  describe "has_content?/1" do
    test "returns true when content is present" do
      context = Context.new("/path/to/file.py", content: "some code")

      assert Context.has_content?(context)
    end

    test "returns false when content is nil" do
      context = Context.new("/path/to/file.py")

      refute Context.has_content?(context)
    end

    test "returns false when content is empty" do
      context = Context.new("/path/to/file.py", content: "")

      refute Context.has_content?(context)
    end
  end
end
