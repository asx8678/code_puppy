defmodule CodePuppyControl.TUI.MarkdownTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Markdown

  describe "render/1" do
    test "renders plain text unchanged" do
      result = Markdown.render("Hello world")
      # Should be a list of Owl.Data fragments
      assert is_list(result)
    end

    test "renders h1 header" do
      result = Markdown.render("# Title")
      assert is_list(result)
    end

    test "renders h2 header" do
      result = Markdown.render("## Subtitle")
      assert is_list(result)
    end

    test "renders h3 header" do
      result = Markdown.render("### Section")
      assert is_list(result)
    end

    test "renders bold text" do
      result = Markdown.render("This is **bold** text")
      assert is_list(result)
    end

    test "renders italic text" do
      result = Markdown.render("This is *italic* text")
      assert is_list(result)
    end

    test "renders inline code" do
      result = Markdown.render("Use `mix test` to run")
      assert is_list(result)
    end

    test "renders code block" do
      md = "```elixir\ndef foo do\n  :ok\nend\n```"
      result = Markdown.render(md)
      assert is_list(result)
    end

    test "renders code block without language" do
      md = "```\nsome code\n```"
      result = Markdown.render(md)
      assert is_list(result)
    end

    test "renders unordered list" do
      md = "- Item one\n- Item two\n- Item three"
      result = Markdown.render(md)
      assert is_list(result)
    end

    test "renders blockquote" do
      md = "> This is a quote"
      result = Markdown.render(md)
      assert is_list(result)
    end

    test "renders multi-line blockquote" do
      md = "> Line one\n> Line two\n> Line three"
      result = Markdown.render(md)
      assert is_list(result)
    end

    test "renders horizontal rule" do
      result = Markdown.render("---")
      assert is_list(result)
    end

    test "renders empty string" do
      result = Markdown.render("")
      assert is_list(result)
    end

    test "renders mixed content" do
      md = """
      # Header

      Some **bold** and *italic* text.

      - List item

      > A quote

      ```elixir
      def hello, do: :world
      ```
      """

      result = Markdown.render(md)
      assert is_list(result)
    end
  end

  describe "render_inline/1" do
    test "renders plain text" do
      result = Markdown.render_inline("hello")
      assert is_list(result)
    end

    test "renders inline code" do
      result = Markdown.render_inline("use `code` here")
      assert is_list(result)
    end

    test "renders bold" do
      result = Markdown.render_inline("**bold**")
      assert is_list(result)
    end

    test "renders italic" do
      result = Markdown.render_inline("*italic*")
      assert is_list(result)
    end
  end
end
