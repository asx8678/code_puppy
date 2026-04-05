defmodule Mana.RepoCompass.Indexer do
  @moduledoc "Walks project tree and extracts symbols from source files"

  @doc "Index a project directory"
  @spec index(String.t(), keyword()) :: [map()]
  def index(project_dir, opts \\ []) do
    max_files = Keyword.get(opts, :max_files, 100)
    max_symbols = Keyword.get(opts, :max_symbols_per_file, 10)

    project_dir
    |> discover_files(max_files)
    |> Enum.map(fn path ->
      relative = Path.relative_to(path, project_dir)
      kind = classify_file(relative)
      symbols = extract_symbols(path, kind, max_symbols)
      %{path: relative, kind: kind, symbols: symbols}
    end)
    # Keep files that have symbols OR are documentation/config files
    |> Enum.reject(fn %{kind: kind, symbols: syms} ->
      syms == [] and kind not in [:documentation, :config]
    end)
  end

  defp discover_files(dir, max) do
    case File.ls(dir) do
      {:ok, entries} -> process_entries(entries, dir, max)
      {:error, _} -> []
    end
  end

  defp process_entries(entries, dir, max) do
    entries
    |> Enum.flat_map(&entry_to_paths(&1, dir, max))
    |> Enum.take(max)
  end

  defp entry_to_paths(entry, dir, max) do
    path = Path.join(dir, entry)

    cond do
      File.dir?(path) and not skip_dir?(entry) -> discover_files(path, max)
      File.regular?(path) and source_file?(entry) -> [path]
      true -> []
    end
  end

  defp skip_dir?(name), do: name in [".git", "deps", "_build", "node_modules", ".mix"]

  defp source_file?(name),
    do: Path.extname(name) in [".ex", ".exs", ".py", ".md", ".toml", ".json"]

  defp classify_file(path) do
    case Path.extname(path) do
      ".ex" -> :elixir_module
      ".exs" -> :elixir_script
      ".py" -> :python_module
      ".md" -> :documentation
      ".toml" -> :config
      ".json" -> :config
      _ -> :unknown
    end
  end

  defp extract_symbols(path, :elixir_module, max) do
    case File.read(path) do
      {:ok, content} ->
        case Code.string_to_quoted(content) do
          {:ok, ast} -> walk_ast(ast, max)
          _ -> []
        end

      {:error, _} ->
        []
    end
  end

  defp extract_symbols(path, :python_module, max) do
    case File.read(path) do
      {:ok, content} ->
        content
        |> String.split("\n")
        |> Enum.flat_map(fn line ->
          trimmed = String.trim(line)

          cond do
            String.match?(trimmed, ~r/^def\s+/) -> [trimmed]
            String.match?(trimmed, ~r/^class\s+/) -> [trimmed]
            true -> []
          end
        end)
        |> Enum.take(max)

      {:error, _} ->
        []
    end
  end

  defp extract_symbols(_path, _kind, _max) do
    []
  end

  defp walk_ast(ast, max) do
    {_, symbols} =
      Macro.prewalk(ast, [], fn
        {:defmodule, _, [{:__aliases__, _, parts} | _]} = node, acc ->
          name = parts |> Enum.map_join(".", &to_string/1)
          {node, [name | acc]}

        {:def, _, [{name, _, _} | _]} = node, acc when is_atom(name) ->
          {node, ["def #{name}" | acc]}

        {:defp, _, [{name, _, _} | _]} = node, acc when is_atom(name) ->
          {node, ["defp #{name}" | acc]}

        node, acc ->
          {node, acc}
      end)

    symbols |> Enum.reverse() |> Enum.take(max)
  end
end
