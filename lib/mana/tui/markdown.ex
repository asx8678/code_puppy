defmodule Mana.TUI.Markdown do
  @moduledoc "Earmark AST → IO.ANSI formatted terminal rendering"

  @doc "Render markdown string to ANSI-formatted terminal output"
  @spec render(String.t()) :: String.t()
  def render(markdown) do
    case Earmark.Parser.as_ast(markdown) do
      {:ok, ast, _warnings} -> render_ast(ast)
      _ -> markdown
    end
  end

  @doc "Render Earmark AST to ANSI"
  @spec render_ast(list()) :: String.t()
  def render_ast(ast) do
    Enum.map_join(ast, "\n", &render_node/1)
  end

  # Headings
  defp render_node({"h1", _attrs, children, _}) do
    content = render_children(children)

    IO.ANSI.format([
      :bright,
      :cyan,
      "\n#{content}\n",
      String.duplicate("=", String.length(content)),
      :reset
    ])
    |> to_string()
  end

  defp render_node({"h2", _attrs, children, _}) do
    content = render_children(children)

    IO.ANSI.format([
      :bright,
      :blue,
      "\n#{content}\n",
      String.duplicate("-", String.length(content)),
      :reset
    ])
    |> to_string()
  end

  defp render_node({"h3", _attrs, children, _}) do
    content = render_children(children)

    IO.ANSI.format([
      :bright,
      :green,
      "\n#{content}\n",
      :reset
    ])
    |> to_string()
  end

  # Code blocks with language (language-class pattern)
  defp render_node({"pre", _attrs, [{"code", [{"class", "language-" <> lang}], [code], _}], _}) do
    lines = String.split(code, "\n")
    header = IO.ANSI.format([:bright, :yellow, "  #{lang}", :reset]) |> to_string()

    numbered =
      Enum.map_join(lines, "\n", fn {line, n} ->
        num = String.pad_leading(to_string(n), 3)

        IO.ANSI.format([:faint, :white, "  #{num} │ ", :reset, line])
        |> to_string()
      end)

    "#{header}\n#{numbered}"
  end

  # Code blocks with or without language (general attrs pattern)
  defp render_node({"pre", _, [{"code", attrs, [code], _}], _}) when is_list(attrs) do
    lang = extract_language(attrs)
    lines = String.split(code, "\n")

    if lang do
      header = IO.ANSI.format([:bright, :yellow, "  #{lang}", :reset]) |> to_string()

      numbered =
        Enum.map_join(Enum.with_index(lines, 1), "\n", fn {line, n} ->
          num = String.pad_leading(to_string(n), 3)

          IO.ANSI.format([:faint, :white, "  #{num} │ ", :reset, line])
          |> to_string()
        end)

      "#{header}\n#{numbered}"
    else
      numbered =
        Enum.map_join(Enum.with_index(lines, 1), "\n", fn {line, n} ->
          num = String.pad_leading(to_string(n), 3)

          IO.ANSI.format([:faint, :white, "  #{num} │ ", :reset, line])
          |> to_string()
        end)

      numbered
    end
  end

  # Inline code
  defp render_node({"code", _attrs, [text], _}) when is_binary(text) do
    IO.ANSI.format([:yellow, " `#{text}` ", :reset]) |> to_string()
  end

  defp render_node({"code", _attrs, children, _}) do
    text = render_children(children)
    IO.ANSI.format([:yellow, " `#{text}` ", :reset]) |> to_string()
  end

  # Bold
  defp render_node({"strong", _attrs, children, _}) do
    content = render_children(children)
    IO.ANSI.format([:bright, content, :reset]) |> to_string()
  end

  # Italic
  defp render_node({"em", _attrs, children, _}) do
    content = render_children(children)
    IO.ANSI.format([:italic, content, :reset]) |> to_string()
  end

  # Unordered lists
  defp render_node({"ul", _attrs, children, _}) do
    Enum.map_join(children, "\n", fn child ->
      case child do
        {"li", _attrs, li_children, _} ->
          content = render_children(li_children)
          "  • #{content}"

        _ ->
          ""
      end
    end)
  end

  # Ordered lists
  defp render_node({"ol", _attrs, children, _}) do
    children
    |> Enum.with_index(1)
    |> Enum.map_join("\n", fn child ->
      case child do
        {{"li", _attrs, li_children, _}, n} ->
          content = render_children(li_children)
          "  #{n}. #{content}"

        _ ->
          ""
      end
    end)
  end

  # Links
  defp render_node({"a", [{"href", url}], [text], _}) do
    IO.ANSI.format([:underline, :blue, "#{text} (#{url})", :reset]) |> to_string()
  end

  defp render_node({"a", [{"href", url}], children, _}) do
    text = render_children(children)
    IO.ANSI.format([:underline, :blue, "#{text} (#{url})", :reset]) |> to_string()
  end

  # Paragraphs
  defp render_node({"p", _attrs, children, _}) do
    render_children(children)
  end

  # Blockquote
  defp render_node({"blockquote", _attrs, children, _}) do
    content = render_children(children)

    content
    |> String.split("\n")
    |> Enum.map_join("\n", fn line ->
      IO.ANSI.format([:faint, "  > #{line}", :reset]) |> to_string()
    end)
  end

  # Horizontal rule
  defp render_node({"hr", _, [], _}) do
    IO.ANSI.format([:faint, String.duplicate("─", 60), :reset]) |> to_string()
  end

  # Tables (simplified rendering)
  defp render_node({"table", _attrs, children, _}) do
    Enum.map_join(children, "\n", &render_node/1)
  end

  defp render_node({"thead", _attrs, children, _}) do
    headers =
      Enum.map_join(children, " | ", fn child ->
        case child do
          {"tr", _, cells, _} ->
            Enum.map_join(cells, " | ", fn cell ->
              case cell do
                {"th", _, cell_children, _} -> render_children(cell_children)
                _ -> ""
              end
            end)

          _ ->
            ""
        end
      end)

    header_line = IO.ANSI.format([:bright, :cyan, headers, :reset]) |> to_string()
    separator = String.duplicate("-", String.length(headers))
    "#{header_line}\n#{separator}"
  end

  defp render_node({"tbody", _attrs, children, _}) do
    Enum.map_join(children, "\n", &render_node/1)
  end

  defp render_node({"tr", _attrs, children, _}) do
    Enum.map_join(children, " | ", fn child ->
      case child do
        {"td", _, cell_children, _} -> render_children(cell_children)
        _ -> ""
      end
    end)
  end

  # Line break
  defp render_node({"br", _, [], _}), do: ""

  # Plain text
  defp render_node(text) when is_binary(text), do: text

  # Catch-all for unknown nodes
  defp render_node({tag, _attrs, children, _}) when is_binary(tag) do
    render_children(children)
  end

  defp render_node(_), do: ""

  # Helper functions
  defp extract_language(attrs) do
    case attrs do
      [{"class", "language-" <> lang}] -> lang
      [{"class", lang}] -> lang
      _ -> nil
    end
  end

  defp render_children(children) when is_list(children) do
    Enum.map_join(children, "", &render_node/1)
  end

  defp render_children(nil), do: ""
  defp render_children(text) when is_binary(text), do: text
end
