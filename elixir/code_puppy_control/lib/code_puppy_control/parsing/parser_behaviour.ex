defmodule CodePuppyControl.Parsing.ParserBehaviour do
  @moduledoc """
  Behaviour for language-specific parsers.

  Each implementation extracts declarations (functions, classes, modules, imports)
  from source code without building a full AST. Trade-off: simple & fast over complete.

  ## Example Implementation

      defmodule MyParser do
        @behaviour CodePuppyControl.Parsing.ParserBehaviour

        @impl true
        def parse(source) do
          # Parse and return structured result
        end

        @impl true
        def language, do: "my_lang"

        @impl true
        def file_extensions, do: [".my", ".myl"]

        @impl true
        def supported?, do: true
      end
  """

  @typedoc """
  Symbol representation for a declaration (function, class, module, etc.)
  """
  @type symbol :: %{
          name: String.t(),
          kind: :function | :class | :module | :method | :import | :constant | :type,
          line: pos_integer(),
          end_line: pos_integer() | nil,
          doc: String.t() | nil,
          children: [symbol()]
        }

  @typedoc """
  Diagnostic message for syntax errors or warnings.
  """
  @type diagnostic :: %{
          line: pos_integer(),
          column: pos_integer(),
          message: String.t(),
          severity: :error | :warning | :info
        }

  @typedoc """
  Complete parse result with symbols, diagnostics, and metadata.
  """
  @type parse_result :: %{
          language: String.t(),
          symbols: [symbol()],
          diagnostics: [diagnostic()],
          success: boolean(),
          parse_time_ms: float()
        }

  @doc """
  Parse source code and extract symbols and diagnostics.

  ## Parameters
    - source: The source code string to parse

  ## Returns
    - `{:ok, parse_result()}` on successful parsing (even with diagnostics)
    - `{:error, term()}` on parse failure
  """
  @callback parse(source :: String.t()) :: {:ok, parse_result()} | {:error, term()}

  @doc """
  Returns the canonical language name this parser handles.

  ## Examples
      iex> MyParser.language()
      "elixir"
  """
  @callback language() :: String.t()

  @doc """
  Returns the list of file extensions this parser supports.

  Extensions should include the leading dot (e.g., ".ex", ".exs").

  ## Examples
      iex> MyParser.file_extensions()
      [".ex", ".exs"]
  """
  @callback file_extensions() :: [String.t()]

  @doc """
  Returns true if this parser is available/supported.

  Some parsers may depend on external libraries or NIFs that
  might not be available at runtime.

  ## Examples
      iex> MyParser.supported?()
      true
  """
  @callback supported?() :: boolean()
end
