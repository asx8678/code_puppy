defmodule CodePuppyControl.CodeContext.SymbolInfo do
  @moduledoc """
  Information about a code symbol (function, class, method, etc.).

  This struct represents a single symbol found in source code, including
  its name, kind (function, class, etc.), position in the file, and any
  nested child symbols.

  ## Fields

    * `name` - The symbol name (e.g., "my_function", "MyClass")
    * `kind` - The symbol kind (e.g., "function", "class", "method", "module")
    * `start_line` - Starting line number (1-based)
    * `end_line` - Ending line number (1-based)
    * `start_col` - Starting column (0-based, default 0)
    * `end_col` - Ending column (0-based, default 0)
    * `parent` - Parent symbol name for nested symbols (default nil)
    * `docstring` - Documentation string if available (default nil)
    * `children` - List of nested SymbolInfo structs (default [])

  ## Examples

      iex> %SymbolInfo{name: "my_func", kind: "function", start_line: 10, end_line: 15}
      %SymbolInfo{name: "my_func", kind: "function", start_line: 10, end_line: 15, ...}
  """

  @enforce_keys [:name, :kind, :start_line, :end_line]
  defstruct [
    :name,
    :kind,
    :start_line,
    :end_line,
    :start_col,
    :end_col,
    :parent,
    :docstring,
    children: []
  ]

  @type t :: %__MODULE__{
          name: String.t(),
          kind: String.t(),
          start_line: pos_integer(),
          end_line: pos_integer(),
          start_col: non_neg_integer(),
          end_col: non_neg_integer(),
          parent: String.t() | nil,
          docstring: String.t() | nil,
          children: [t()]
        }

  @doc """
  Creates a new SymbolInfo struct with the given attributes.

  ## Examples

      iex> SymbolInfo.new("my_func", "function", 10, 20)
      %SymbolInfo{name: "my_func", kind: "function", start_line: 10, end_line: 20, ...}

      iex> SymbolInfo.new("MyClass", "class", 1, 50, children: [child_symbol])
      %SymbolInfo{name: "MyClass", kind: "class", children: [child_symbol], ...}
  """
  @spec new(String.t(), String.t(), pos_integer(), pos_integer(), keyword()) :: t()
  def new(name, kind, start_line, end_line, opts \\ []) do
    %__MODULE__{
      name: name,
      kind: kind,
      start_line: start_line,
      end_line: end_line,
      start_col: Keyword.get(opts, :start_col, 0),
      end_col: Keyword.get(opts, :end_col, 0),
      parent: Keyword.get(opts, :parent),
      docstring: Keyword.get(opts, :docstring),
      children: Keyword.get(opts, :children, [])
    }
  end

  @doc """
  Creates a SymbolInfo from a map (e.g., from JSON/NIF output).

  ## Examples

      iex> map = %{"name" => "foo", "kind" => "function", "start_line" => 1, "end_line" => 5}
      iex> SymbolInfo.from_map(map)
      %SymbolInfo{name: "foo", kind: "function", start_line: 1, end_line: 5, ...}
  """
  @spec from_map(map() | %{String.t() => term()}) :: t()
  def from_map(data) when is_map(data) do
    name = Map.get(data, "name") || Map.get(data, :name) || ""
    kind = Map.get(data, "kind") || Map.get(data, :kind) || "unknown"
    start_line = Map.get(data, "start_line") || Map.get(data, :start_line) || 0
    end_line = Map.get(data, "end_line") || Map.get(data, :end_line) || 0
    start_col = Map.get(data, "start_col") || Map.get(data, :start_col) || 0
    end_col = Map.get(data, "end_col") || Map.get(data, :end_col) || 0
    parent = Map.get(data, "parent") || Map.get(data, :parent)
    docstring = Map.get(data, "docstring") || Map.get(data, :docstring)

    raw_children = Map.get(data, "children") || Map.get(data, :children) || []

    children =
      Enum.map(raw_children, fn
        %__MODULE__{} = child -> child
        child_map when is_map(child_map) -> from_map(child_map)
        _other -> nil
      end)
      |> Enum.reject(&is_nil/1)

    %__MODULE__{
      name: name,
      kind: kind,
      start_line: start_line,
      end_line: end_line,
      start_col: start_col,
      end_col: end_col,
      parent: parent,
      docstring: docstring,
      children: children
    }
  end

  @doc """
  Converts a SymbolInfo to a map for serialization.

  ## Examples

      iex> symbol = %SymbolInfo{name: "foo", kind: "function", start_line: 1, end_line: 5}
      iex> SymbolInfo.to_map(symbol)
      %{"name" => "foo", "kind" => "function", "start_line" => 1, "end_line" => 5, ...}
  """
  @spec to_map(t()) :: %{String.t() => term()}
  def to_map(%__MODULE__{} = symbol) do
    %{
      "name" => symbol.name,
      "kind" => symbol.kind,
      "start_line" => symbol.start_line,
      "end_line" => symbol.end_line,
      "start_col" => symbol.start_col,
      "end_col" => symbol.end_col,
      "parent" => symbol.parent,
      "docstring" => symbol.docstring,
      "children" => Enum.map(symbol.children, &to_map/1)
    }
  end

  @doc """
  Returns the line range as a tuple {start_line, end_line}.

  ## Examples

      iex> symbol = %SymbolInfo{start_line: 10, end_line: 20}
      iex> SymbolInfo.line_range(symbol)
      {10, 20}
  """
  @spec line_range(t()) :: {pos_integer(), pos_integer()}
  def line_range(%__MODULE__{} = symbol) do
    {symbol.start_line, symbol.end_line}
  end

  @doc """
  Checks if this is a top-level symbol (no parent).

  ## Examples

      iex> SymbolInfo.top_level?(%SymbolInfo{parent: nil})
      true

      iex> SymbolInfo.top_level?(%SymbolInfo{parent: "SomeClass"})
      false
  """
  @spec top_level?(t()) :: boolean()
  def top_level?(%__MODULE__{} = symbol) do
    is_nil(symbol.parent)
  end

  @doc """
  Returns the size of the symbol in lines.

  ## Examples

      iex> symbol = %SymbolInfo{start_line: 10, end_line: 15}
      iex> SymbolInfo.size_lines(symbol)
      6
  """
  @spec size_lines(t()) :: pos_integer()
  def size_lines(%__MODULE__{} = symbol) do
    symbol.end_line - symbol.start_line + 1
  end

  @doc """
  Gets all descendant symbols (recursive children).

  ## Examples

      iex> parent = %SymbolInfo{name: "Parent", children: [
      ...>   %SymbolInfo{name: "Child1", children: [%SymbolInfo{name: "GrandChild"}]},
      ...>   %SymbolInfo{name: "Child2"}
      ...> ]}
      iex> SymbolInfo.all_descendants(parent)
      [%SymbolInfo{name: "Child1"}, %SymbolInfo{name: "GrandChild"}, %SymbolInfo{name: "Child2"}]
  """
  @spec all_descendants(t()) :: [t()]
  def all_descendants(%__MODULE__{} = symbol) do
    symbol.children
    |> Enum.flat_map(fn child ->
      [child | all_descendants(child)]
    end)
  end

  @doc """
  Finds a symbol by name (including nested symbols).

  ## Examples

      iex> parent = %SymbolInfo{name: "Parent", children: [
      ...>   %SymbolInfo{name: "Child"}
      ...> ]}
      iex> SymbolInfo.find_by_name(parent, "Child")
      %SymbolInfo{name: "Child"}
      iex> SymbolInfo.find_by_name(parent, "NonExistent")
      nil
  """
  @spec find_by_name(t(), String.t()) :: t() | nil
  def find_by_name(%__MODULE__{} = symbol, name) do
    if symbol.name == name do
      symbol
    else
      Enum.find_value(symbol.children, fn child ->
        find_by_name(child, name)
      end)
    end
  end

  @doc """
  Filters symbols by kind.

  ## Examples

      iex> symbols = [
      ...>   %SymbolInfo{name: "MyClass", kind: "class"},
      ...>   %SymbolInfo{name: "my_func", kind: "function"}
      ...> ]
      iex> SymbolInfo.filter_by_kind(symbols, "class")
      [%SymbolInfo{name: "MyClass", kind: "class"}]
  """
  @spec filter_by_kind([t()], String.t() | [String.t()]) :: [t()]
  def filter_by_kind(symbols, kind) when is_binary(kind) do
    Enum.filter(symbols, &(&1.kind == kind))
  end

  def filter_by_kind(symbols, kinds) when is_list(kinds) do
    Enum.filter(symbols, &(&1.kind in kinds))
  end
end
