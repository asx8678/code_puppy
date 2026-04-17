defmodule CodePuppyControl.Parsing.Parsers.PythonParser do
  @moduledoc """
  Python parser using Yecc-generated parser.

  Extracts symbols from Python source code including:
  - Functions (def statements)
  - Classes (class statements)
  - Imports (import and from...import statements)
  - Decorators (@decorator syntax)

  This parser uses the Python lexer (from bd-106) for tokenization
  and a Yecc-generated parser for building the AST.

  ## Examples

      iex> PythonParser.parse("def foo():\\n    pass")
      {:ok, %{language: "python", symbols: [%{name: "foo", kind: :function, ...}], ...}}

  """
  @behaviour CodePuppyControl.Parsing.ParserBehaviour

  alias CodePuppyControl.Parsing.ParserRegistry
  alias CodePuppyControl.Parsing.Lexers.PythonLexer

  # ---------------------------------------------------------------------------
  # ParserBehaviour Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def language, do: "python"

  @impl true
  def file_extensions, do: [".py", ".pyi"]

  @impl true
  def supported?, do: true

  @impl true
  def parse(source) when is_binary(source) do
    start = System.monotonic_time(:millisecond)

    with {:ok, tokens} <- PythonLexer.tokenize(source),
         {:ok, ast} <- :python_parser.parse(tokens) do
      symbols = ast_to_symbols(ast)

      {:ok,
       %{
         language: "python",
         symbols: symbols,
         diagnostics: [],
         success: true,
         parse_time_ms: System.monotonic_time(:millisecond) - start
       }}
    else
      {:error, reason} ->
        {:ok,
         %{
           language: "python",
           symbols: [],
           diagnostics: [format_error(reason)],
           success: false,
           parse_time_ms: System.monotonic_time(:millisecond) - start
         }}
    end
  end

  # ---------------------------------------------------------------------------
  # Symbol Extraction
  # ---------------------------------------------------------------------------

  @spec ast_to_symbols(list()) :: [map()]
  defp ast_to_symbols(nodes) when is_list(nodes) do
    Enum.flat_map(nodes, &node_to_symbol/1)
  end

  # Skip :skip atoms (newline placeholders)
  defp node_to_symbol(:skip), do: []

  # Function without decorators: {function, line, name, params}
  defp node_to_symbol({:function, line, name, _params}) do
    [
      %{
        name: to_string(name),
        kind: :function,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Function with decorators: {function, line, name, params, decorators}
  defp node_to_symbol({:function, line, name, _params, decorators}) do
    decorator_info = format_decorators(decorators)

    [
      %{
        name: to_string(name),
        kind: :function,
        line: line,
        end_line: nil,
        doc: decorator_info,
        children: []
      }
    ]
  end

  # Class without decorators: {class, line, name, params}
  defp node_to_symbol({:class, line, name, _params}) do
    [
      %{
        name: to_string(name),
        kind: :class,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Class with decorators: {class, line, name, params, decorators}
  defp node_to_symbol({:class, line, name, _params, decorators}) do
    decorator_info = format_decorators(decorators)

    [
      %{
        name: to_string(name),
        kind: :class,
        line: line,
        end_line: nil,
        doc: decorator_info,
        children: []
      }
    ]
  end

  # Import statement: {import, line, module}
  defp node_to_symbol({:import, line, module}) do
    [
      %{
        name: "import #{module}",
        kind: :import,
        line: line,
        end_line: line,
        doc: nil,
        children: []
      }
    ]
  end

  # From import statement: {from_import, line, module, name}
  defp node_to_symbol({:from_import, line, module, name}) do
    [
      %{
        name: "from #{module} import #{name}",
        kind: :import,
        line: line,
        end_line: line,
        doc: nil,
        children: []
      }
    ]
  end

  # Fallback for unrecognized nodes
  defp node_to_symbol(_node), do: []

  # ---------------------------------------------------------------------------
  # Helper Functions
  # ---------------------------------------------------------------------------

  defp format_decorators(decorators) when is_list(decorators) do
    decorators
    |> Enum.map(fn {:decorator, _line, name} -> "@#{to_string(name)}" end)
    |> Enum.join(" ")
  end

  defp format_decorators(_), do: nil

  defp format_error({line, _module, message}) when is_integer(line) do
    %{
      line: line,
      column: 1,
      message: to_string(message),
      severity: :error
    }
  end

  defp format_error(reason) do
    %{
      line: 1,
      column: 1,
      message: "Parse error: #{inspect(reason)}",
      severity: :error
    }
  end

  # ---------------------------------------------------------------------------
  # Registration
  # ---------------------------------------------------------------------------

  @doc """
  Registers this parser with the ParserRegistry.
  Call this during application startup.
  """
  @spec register() :: :ok | {:error, :unsupported | :invalid_module}
  def register do
    ParserRegistry.register(__MODULE__)
  end
end
