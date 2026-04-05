defmodule Mana.TUI.MarkdownTest do
  @moduledoc """
  Tests for Mana.TUI.Markdown module.
  """

  use ExUnit.Case, async: true

  alias Mana.TUI.Markdown

  describe "render/1" do
    test "renders plain text" do
      result = Markdown.render("Hello world")
      assert result == "Hello world"
    end

    test "renders h1 heading" do
      result = Markdown.render("# Title")
      assert result =~ "Title"
      assert result =~ "==="
    end

    test "renders h2 heading" do
      result = Markdown.render("## Subtitle")
      assert result =~ "Subtitle"
      assert result =~ "---"
    end

    test "renders h3 heading" do
      result = Markdown.render("### Section")
      assert result =~ "Section"
    end

    test "renders code block with language" do
      markdown = "```elixir\ndef hello do\n  :world\nend\n```"
      result = Markdown.render(markdown)
      assert result =~ "elixir"
      assert result =~ "def hello do"
      assert result =~ "1"
      assert result =~ "2"
      assert result =~ "3"
    end

    test "renders code block without language" do
      markdown = "```\nsome code\nmore code\n```"
      result = Markdown.render(markdown)
      assert result =~ "some code"
      assert result =~ "more code"
      assert result =~ "1"
      assert result =~ "2"
    end

    test "renders inline code" do
      result = Markdown.render("Use `function()` to call")
      assert result =~ "function()"
    end

    test "renders bold text" do
      result = Markdown.render("**bold text**")
      assert result =~ "bold text"
    end

    test "renders italic text" do
      result = Markdown.render("*italic text*")
      assert result =~ "italic text"
    end

    test "renders unordered list" do
      markdown = "- Item 1\n- Item 2\n- Item 3"
      result = Markdown.render(markdown)
      assert result =~ "• Item 1"
      assert result =~ "• Item 2"
      assert result =~ "• Item 3"
    end

    test "renders ordered list" do
      markdown = "1. First\n2. Second\n3. Third"
      result = Markdown.render(markdown)
      assert result =~ "1. First"
      assert result =~ "2. Second"
      assert result =~ "3. Third"
    end

    test "renders link" do
      result = Markdown.render("[Link text](https://example.com)")
      assert result =~ "Link text"
      assert result =~ "https://example.com"
    end

    test "renders paragraph" do
      result = Markdown.render("This is a paragraph.")
      assert result =~ "This is a paragraph."
    end

    test "renders blockquote" do
      result = Markdown.render("> This is a quote")
      assert result =~ "This is a quote"
    end

    test "renders horizontal rule" do
      result = Markdown.render("---")
      assert result =~ "─"
    end

    test "renders mixed markdown" do
      markdown = """
      # Heading

      Some **bold** and *italic* text.

      - Item 1
      - Item 2

      `code`
      """

      result = Markdown.render(markdown)
      assert result =~ "Heading"
      assert result =~ "bold"
      assert result =~ "italic"
      assert result =~ "Item 1"
      assert result =~ "code"
    end

    test "handles empty string" do
      assert Markdown.render("") == ""
    end

    test "handles invalid markdown gracefully" do
      # Invalid markdown should return original
      result = Markdown.render("not valid markdown {{{")
      assert is_binary(result)
    end
  end

  describe "render_ast/1" do
    test "renders AST list" do
      ast = [{"p", [], ["Hello"], %{}}]
      result = Markdown.render_ast(ast)
      assert result =~ "Hello"
    end

    test "renders multiple AST nodes" do
      ast = [
        {"h1", [], ["Title"], %{}},
        {"p", [], ["Content"], %{}}
      ]

      result = Markdown.render_ast(ast)
      assert result =~ "Title"
      assert result =~ "Content"
    end
  end
end
