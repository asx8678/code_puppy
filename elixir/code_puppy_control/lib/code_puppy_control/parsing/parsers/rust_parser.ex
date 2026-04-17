defmodule CodePuppyControl.Parsing.Parsers.RustParser do
  @moduledoc """
  Rust parser using Yecc-generated parser.

  Extracts symbols from Rust source code including:
  - Functions (fn declarations)
  - Structs (struct declarations)
  - Enums (enum declarations)
  - Impl blocks (impl declarations)
  - Traits (trait declarations)
  - Modules (mod declarations)
  - Use statements (imports)
  - Type aliases (type declarations)
  - Constants (const declarations)
  - Static items (static declarations)

  This parser uses the Rust lexer (from bd-98) for tokenization
  and a Yecc-generated parser for building the AST.

  ## Examples

      iex> RustParser.parse("fn main() {}")
      {:ok, %{language: "rust", symbols: [%{name: "main", kind: :function, ...}], ...}}

  """
  @behaviour CodePuppyControl.Parsing.ParserBehaviour

  alias CodePuppyControl.Parsing.ParserRegistry
  alias CodePuppyControl.Parsing.Lexers.RustLexer

  # ---------------------------------------------------------------------------
  # ParserBehaviour Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def language, do: "rust"

  @impl true
  def file_extensions, do: [".rs"]

  @impl true
  def supported?, do: true

  @impl true
  def parse(source) when is_binary(source) do
    start = System.monotonic_time(:millisecond)

    with {:ok, tokens} <- RustLexer.tokenize(source),
         {:ok, ast} <- :rust_parser.parse(tokens) do
      symbols = ast_to_symbols(ast)

      {:ok,
       %{
         language: "rust",
         symbols: symbols,
         diagnostics: [],
         success: true,
         parse_time_ms: System.monotonic_time(:millisecond) - start
       }}
    else
      {:error, reason} ->
        {:ok,
         %{
           language: "rust",
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

  # Skip :newline placeholders
  defp node_to_symbol(:newline), do: []
  defp node_to_symbol(nil), do: []

  # Function: {function, line, name, params, visibility}
  defp node_to_symbol({:function, line, name, _params, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :function,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Function without visibility (old format): {function, line, name, params}
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

  # Struct: {struct, line, name, visibility}
  defp node_to_symbol({:struct, line, name, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :class,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Struct without visibility (old format)
  defp node_to_symbol({:struct, line, name}) do
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

  # Enum: {enum, line, name, visibility}
  defp node_to_symbol({:enum, line, name, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :class,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Enum without visibility (old format)
  defp node_to_symbol({:enum, line, name}) do
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

  # Impl block: {impl, line, target_type, trait_type, _}
  defp node_to_symbol({:impl, line, target_type, trait_type, _}) when trait_type != nil do
    name = if trait_type, do: "impl #{trait_type} for #{target_type}", else: "impl #{target_type}"

    [
      %{
        name: name,
        kind: :module,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Impl block without trait: {impl, line, type, _}
  defp node_to_symbol({:impl, line, type, _}) do
    [
      %{
        name: "impl #{type}",
        kind: :module,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Trait: {trait, line, name, visibility}
  defp node_to_symbol({:trait, line, name, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :type,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Trait without visibility (old format)
  defp node_to_symbol({:trait, line, name}) do
    [
      %{
        name: to_string(name),
        kind: :type,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Module block: {mod, line, name, block, visibility}
  defp node_to_symbol({:mod, line, name, _block, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :module,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Module without visibility (old format)
  defp node_to_symbol({:mod, line, name}) do
    [
      %{
        name: to_string(name),
        kind: :module,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Module file: {mod_file, line, name, visibility}
  defp node_to_symbol({:mod_file, line, name, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: "#{name} (file)",
        kind: :module,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Module file without visibility (old format)
  defp node_to_symbol({:mod_file, line, name}) do
    [
      %{
        name: "#{name} (file)",
        kind: :module,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Use statement: {use, line, module, type}
  defp node_to_symbol({:use, line, module, _type}) do
    name =
      case module do
        {a, b} -> "#{a}::#{b}"
        _ -> to_string(module)
      end

    [
      %{
        name: name,
        kind: :import,
        line: line,
        end_line: nil,
        doc: nil,
        children: []
      }
    ]
  end

  # Type alias: {type_alias, line, name, target, visibility}
  defp node_to_symbol({:type_alias, line, name, target, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: "#{name} = #{target}",
        kind: :type,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Constant: {const, line, name, value, visibility}
  defp node_to_symbol({:const, line, name, _value, visibility}) do
    doc = format_visibility(visibility)

    [
      %{
        name: to_string(name),
        kind: :constant,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Static: {static, line, name, value, modifiers}
  defp node_to_symbol({:static, line, name, _value, modifiers}) do
    doc = if :mut in modifiers, do: "mut", else: nil
    doc = if :pub in modifiers, do: if(doc, do: "pub #{doc}", else: "pub"), else: doc

    [
      %{
        name: to_string(name),
        kind: :constant,
        line: line,
        end_line: nil,
        doc: doc,
        children: []
      }
    ]
  end

  # Fallback for unrecognized nodes
  defp node_to_symbol(_node) do
    []
  end

  # ---------------------------------------------------------------------------
  # Helper Functions
  # ---------------------------------------------------------------------------

  defp format_visibility(visibility) when is_list(visibility) do
    visibility
    |> Enum.map(&to_string/1)
    |> Enum.join(" ")
    |> case do
      "" -> nil
      str -> str
    end
  end

  defp format_visibility(_), do: nil

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
