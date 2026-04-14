defmodule CodePuppyControl.Indexer.SymbolExtractor do
  @moduledoc """
  Extracts symbols (functions, classes, modules) from source code.

  Currently supports:
  - Python: class definitions and function definitions (including async)
  - Elixir: defmodule, def, defp, defmacro, defmacrop

  The implementation uses regex matching to mirror the Rust port behavior.
  For production use, a proper parser (like tree-sitter) would be more robust.
  """

  # Python regex patterns
  @python_class_regex ~r/^class\s+(\w+)/m
  @python_def_regex ~r/^(?:async\s+)?def\s+(\w+)\s*\(/m

  # Elixir regex patterns
  @elixir_def_regex ~r/^\s*(?:def|defp|defmacro|defmacrop)\s+(\w+)/m
  @elixir_module_regex ~r/^\s*defmodule\s+([\w.]+)/m

  @doc """
  Extracts symbols from source code content.

  ## Parameters

    - content: The source code as a string
    - kind: The file kind (determines which parser to use)
    - max_symbols: Maximum number of symbols to return

  ## Returns

  A list of symbol strings like ["class MyClass", "def my_function"]

  ## Examples

      iex> content = "class Foo:\\n    def bar():\\n        pass"
      iex> SymbolExtractor.extract(content, "python", 10)
      ["class Foo", "def bar"]
  """
  @spec extract(String.t(), String.t(), pos_integer()) :: [String.t()]
  def extract(content, kind, max_symbols) do
    case kind do
      "python" -> extract_python(content, max_symbols)
      "elixir" -> extract_elixir(content, max_symbols)
      # TODO(indexer): Implement symbol extraction for rust, javascript, typescript, tsx
      # These are marked as extract_symbols=true in Constants but currently return []
      _ -> []
    end
  end

  # Private functions for Python symbol extraction

  defp extract_python(content, max_symbols) do
    classes =
      @python_class_regex
      |> Regex.scan(content)
      |> Enum.map(fn [_, name] -> "class #{name}" end)

    functions =
      @python_def_regex
      |> Regex.scan(content)
      |> Enum.map(fn [_, name] -> "def #{name}" end)

    (classes ++ functions)
    |> Enum.take(max_symbols)
  end

  # Private functions for Elixir symbol extraction

  defp extract_elixir(content, max_symbols) do
    modules =
      @elixir_module_regex
      |> Regex.scan(content)
      |> Enum.map(fn [_, name] -> "defmodule #{name}" end)

    functions =
      @elixir_def_regex
      |> Regex.scan(content)
      |> Enum.map(fn [_, name] -> "def #{name}" end)

    (modules ++ functions)
    |> Enum.uniq()
    |> Enum.take(max_symbols)
  end
end
