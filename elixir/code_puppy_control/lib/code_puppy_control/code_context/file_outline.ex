defmodule CodePuppyControl.CodeContext.FileOutline do
  @moduledoc """
  Hierarchical outline of a source file with symbol information.

  This struct represents the structure of a source file, including its
  programming language and a list of top-level symbols with their
  hierarchical relationships (nested functions, methods, etc.).

  ## Fields

    * `language` - The detected programming language (e.g., "python", "elixir")
    * `symbols` - List of top-level SymbolInfo structs
    * `extraction_time_ms` - Time taken to extract symbols in milliseconds
    * `success` - Whether symbol extraction succeeded
    * `errors` - List of error messages if extraction failed

  ## Examples

      iex> %FileOutline{language: "python", symbols: [], success: true}
      %FileOutline{language: "python", symbols: [], success: true, errors: []}
  """

  alias CodePuppyControl.CodeContext.SymbolInfo

  @enforce_keys [:language]
  defstruct [
    :language,
    symbols: [],
    extraction_time_ms: 0.0,
    success: true,
    errors: []
  ]

  @type t :: %__MODULE__{
          language: String.t(),
          symbols: [SymbolInfo.t()],
          extraction_time_ms: float(),
          success: boolean(),
          errors: [String.t()]
        }

  @doc """
  Creates a new FileOutline struct.

  ## Examples

      iex> FileOutline.new("python")
      %FileOutline{language: "python", symbols: [], success: true, ...}

      iex> FileOutline.new("elixir", symbols: [symbol], success: true)
      %FileOutline{language: "elixir", symbols: [symbol], ...}
  """
  @spec new(String.t(), keyword()) :: t()
  def new(language, opts \\ []) do
    %__MODULE__{
      language: language,
      symbols: Keyword.get(opts, :symbols, []),
      extraction_time_ms: Keyword.get(opts, :extraction_time_ms, 0.0),
      success: Keyword.get(opts, :success, true),
      errors: Keyword.get(opts, :errors, [])
    }
  end

  @doc """
  Creates a FileOutline from a map (e.g., from JSON/NIF output).

  ## Examples

      iex> map = %{"language" => "python", "symbols" => [], "success" => true}
      iex> FileOutline.from_map(map)
      %FileOutline{language: "python", symbols: [], success: true, ...}
  """
  @spec from_map(map()) :: t()
  def from_map(data) when is_map(data) do
    language = Map.get(data, "language") || Map.get(data, :language) || "unknown"

    raw_symbols = Map.get(data, "symbols") || Map.get(data, :symbols) || []

    symbols =
      Enum.map(raw_symbols, fn
        %SymbolInfo{} = s -> s
        s when is_map(s) -> SymbolInfo.from_map(s)
        _ -> nil
      end)
      |> Enum.reject(&is_nil/1)

    extraction_time_ms =
      Map.get(data, "extraction_time_ms") || Map.get(data, :extraction_time_ms) || 0.0

    success = Map.get(data, "success") || Map.get(data, :success) || true

    errors =
      case Map.get(data, "errors") || Map.get(data, :errors) do
        nil -> []
        list when is_list(list) -> list
        other -> [to_string(other)]
      end

    %__MODULE__{
      language: language,
      symbols: symbols,
      extraction_time_ms: extraction_time_ms,
      success: success,
      errors: errors
    }
  end

  @doc """
  Converts a FileOutline to a map for serialization.

  ## Examples

      iex> outline = %FileOutline{language: "python", symbols: []}
      iex> FileOutline.to_map(outline)
      %{"language" => "python", "symbols" => [], ...}
  """
  @spec to_map(t()) :: %{String.t() => term()}
  def to_map(%__MODULE__{} = outline) do
    %{
      "language" => outline.language,
      "symbols" => Enum.map(outline.symbols, &SymbolInfo.to_map/1),
      "extraction_time_ms" => outline.extraction_time_ms,
      "success" => outline.success,
      "errors" => outline.errors
    }
  end

  @doc """
  Returns only top-level symbols (those without parents).

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "global_func", kind: "function", parent: nil},
      ...>   %SymbolInfo{name: "method", kind: "method", parent: "Class"}
      ...> ]}
      iex> FileOutline.top_level_symbols(outline)
      [%SymbolInfo{name: "global_func", kind: "function", parent: nil}]
  """
  @spec top_level_symbols(t()) :: [SymbolInfo.t()]
  def top_level_symbols(%__MODULE__{} = outline) do
    Enum.filter(outline.symbols, &SymbolInfo.top_level?/1)
  end

  @doc """
  Returns all class-like symbols (class, struct, interface, trait, enum).

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "MyClass", kind: "class"},
      ...>   %SymbolInfo{name: "my_func", kind: "function"}
      ...> ]}
      iex> FileOutline.classes(outline)
      [%SymbolInfo{name: "MyClass", kind: "class"}]
  """
  @spec classes(t()) :: [SymbolInfo.t()]
  def classes(%__MODULE__{} = outline) do
    class_kinds = ["class", "struct", "interface", "trait", "enum"]
    SymbolInfo.filter_by_kind(outline.symbols, class_kinds)
  end

  @doc """
  Returns all function-like symbols (function, method).

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "MyClass", kind: "class"},
      ...>   %SymbolInfo{name: "my_func", kind: "function"}
      ...> ]}
      iex> FileOutline.functions(outline)
      [%SymbolInfo{name: "my_func", kind: "function"}]
  """
  @spec functions(t()) :: [SymbolInfo.t()]
  def functions(%__MODULE__{} = outline) do
    function_kinds = ["function", "method"]
    SymbolInfo.filter_by_kind(outline.symbols, function_kinds)
  end

  @doc """
  Returns all import symbols.

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "os", kind: "import"},
      ...>   %SymbolInfo{name: "sys", kind: "import"}
      ...> ]}
      iex> FileOutline.imports(outline)
      [%SymbolInfo{name: "os", kind: "import"}, %SymbolInfo{name: "sys", kind: "import"}]
  """
  @spec imports(t()) :: [SymbolInfo.t()]
  def imports(%__MODULE__{} = outline) do
    SymbolInfo.filter_by_kind(outline.symbols, "import")
  end

  @doc """
  Finds a symbol by name (including nested symbols).

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "Parent", kind: "class", children: [
      ...>     %SymbolInfo{name: "Child", kind: "method"}
      ...>   ]}
      ...> ]}
      iex> FileOutline.get_symbol_by_name(outline, "Child")
      %SymbolInfo{name: "Child", kind: "method"}
      iex> FileOutline.get_symbol_by_name(outline, "NonExistent")
      nil
  """
  @spec get_symbol_by_name(t(), String.t()) :: SymbolInfo.t() | nil
  def get_symbol_by_name(%__MODULE__{} = outline, name) do
    Enum.find_value(outline.symbols, fn symbol ->
      SymbolInfo.find_by_name(symbol, name)
    end)
  end

  @doc """
  Returns all symbols within a line range (inclusive).

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "early", start_line: 1, end_line: 5},
      ...>   %SymbolInfo{name: "target", start_line: 10, end_line: 20},
      ...>   %SymbolInfo{name: "late", start_line: 30, end_line: 40}
      ...> ]}
      iex> FileOutline.get_symbols_in_range(outline, 8, 25)
      [%SymbolInfo{name: "target", start_line: 10, end_line: 20}]
  """
  @spec get_symbols_in_range(t(), pos_integer(), pos_integer()) :: [SymbolInfo.t()]
  def get_symbols_in_range(%__MODULE__{} = outline, start_line, end_line) do
    Enum.filter(outline.symbols, fn symbol ->
      symbol.start_line >= start_line and symbol.end_line <= end_line
    end)
  end

  @doc """
  Returns the total number of symbols including nested ones.

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "Parent", children: [
      ...>     %SymbolInfo{name: "Child"},
      ...>     %SymbolInfo{name: "AnotherChild"}
      ...>   ]}
      ...> ]}
      iex> FileOutline.total_symbol_count(outline)
      3
  """
  @spec total_symbol_count(t()) :: non_neg_integer()
  def total_symbol_count(%__MODULE__{} = outline) do
    outline.symbols
    |> Enum.map(fn s -> 1 + length(SymbolInfo.all_descendants(s)) end)
    |> Enum.sum()
  end

  @doc """
  Applies a depth limit to the symbol hierarchy.

  ## Examples

      iex> outline = %FileOutline{symbols: [
      ...>   %SymbolInfo{name: "A", children: [
      ...>     %SymbolInfo{name: "B", children: [
      ...>       %SymbolInfo{name: "C"}
      ...>     ]}
      ...>   ]}
      ...> ]}
      iex> limited = FileOutline.limit_depth(outline, 2)
      iex> length(hd(limited.symbols).children)
      1
      iex> hd(limited.symbols).children |> hd() |> Map.get(:children)
      []
  """
  @spec limit_depth(t(), pos_integer()) :: t()
  def limit_depth(%__MODULE__{} = outline, max_depth) do
    limited_symbols = do_limit_depth(outline.symbols, max_depth, 1)
    %{outline | symbols: limited_symbols}
  end

  defp do_limit_depth(symbols, max_depth, current_depth) when current_depth >= max_depth do
    Enum.map(symbols, fn symbol ->
      %{symbol | children: []}
    end)
  end

  defp do_limit_depth(symbols, max_depth, current_depth) do
    Enum.map(symbols, fn symbol ->
      if symbol.children == [] do
        symbol
      else
        %{symbol | children: do_limit_depth(symbol.children, max_depth, current_depth + 1)}
      end
    end)
  end
end
