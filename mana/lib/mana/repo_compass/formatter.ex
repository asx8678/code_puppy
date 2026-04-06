defmodule Mana.RepoCompass.Formatter do
  @moduledoc "Formats indexed project symbols for prompt injection"

  @max_chars 2400

  @doc "Format project index as a prompt section"
  @spec format([map()], String.t()) :: String.t()
  def format(index, project_name) do
    header = "## Repo Compass\nProject: #{project_name}\nStructural context map:\n"

    lines =
      Enum.map(index, fn %{path: path, kind: kind, symbols: symbols} ->
        symbol_str = Enum.join(symbols, "; ")
        "- #{path} [#{format_kind(kind)}]: #{symbol_str}"
      end)

    full = header <> Enum.join(lines, "\n")

    if String.length(full) > @max_chars do
      truncate(full, @max_chars)
    else
      full
    end
  end

  defp format_kind(:elixir_module), do: "elixir"
  defp format_kind(:elixir_script), do: "script"
  defp format_kind(:python_module), do: "python"
  defp format_kind(:documentation), do: "docs"
  defp format_kind(:config), do: "config"
  defp format_kind(_), do: "file"

  defp truncate(text, max) do
    String.slice(text, 0, max - 3) <> "..."
  end
end
