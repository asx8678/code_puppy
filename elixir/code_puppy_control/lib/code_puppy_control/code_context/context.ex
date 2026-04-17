defmodule CodePuppyControl.CodeContext.Context do
  @moduledoc """
  Complete context for a code file including symbols, content, and metadata.

  This struct represents the full context for exploring a source file, including
  its path, content (optionally), extracted symbols, language detection, and
  various metadata like file size, token count, and parsing status.

  ## Fields

    * `file_path` - Absolute path to the file (required)
    * `content` - File content as string (optional, may be nil)
    * `language` - Detected programming language (e.g., "python", "elixir")
    * `outline` - FileOutline with extracted symbols
    * `file_size` - File size in bytes
    * `num_lines` - Number of lines in the file
    * `num_tokens` - Estimated token count
    * `parse_time_ms` - Time taken to parse the file in milliseconds
    * `has_errors` - Whether there were errors reading/parsing
    * `error_message` - Error message if has_errors is true

  ## Examples

      iex> %Context{file_path: "/path/to/file.ex", language: "elixir"}
      %Context{file_path: "/path/to/file.ex", language: "elixir", ...}
  """

  alias CodePuppyControl.CodeContext.FileOutline

  @enforce_keys [:file_path]
  defstruct [
    :file_path,
    content: nil,
    language: nil,
    outline: nil,
    file_size: 0,
    num_lines: 0,
    num_tokens: 0,
    parse_time_ms: 0.0,
    has_errors: false,
    error_message: nil
  ]

  @type t :: %__MODULE__{
          file_path: String.t(),
          content: String.t() | nil,
          language: String.t() | nil,
          outline: FileOutline.t() | nil,
          file_size: non_neg_integer(),
          num_lines: non_neg_integer(),
          num_tokens: non_neg_integer(),
          parse_time_ms: float(),
          has_errors: boolean(),
          error_message: String.t() | nil
        }

  @doc """
  Creates a new Context struct.

  ## Examples

      iex> Context.new("/path/to/file.ex")
      %Context{file_path: "/path/to/file.ex", ...}

      iex> Context.new("/path/to/file.py", language: "python", num_lines: 100)
      %Context{file_path: "/path/to/file.py", language: "python", num_lines: 100, ...}
  """
  @spec new(String.t(), keyword()) :: t()
  def new(file_path, opts \\ []) do
    %__MODULE__{
      file_path: file_path,
      content: Keyword.get(opts, :content),
      language: Keyword.get(opts, :language),
      outline: Keyword.get(opts, :outline),
      file_size: Keyword.get(opts, :file_size, 0),
      num_lines: Keyword.get(opts, :num_lines, 0),
      num_tokens: Keyword.get(opts, :num_tokens, 0),
      parse_time_ms: Keyword.get(opts, :parse_time_ms, 0.0),
      has_errors: Keyword.get(opts, :has_errors, false),
      error_message: Keyword.get(opts, :error_message)
    }
  end

  @doc """
  Creates a Context from a map (e.g., from JSON serialization).

  ## Examples

      iex> map = %{"file_path" => "/path/to/file.ex", "language" => "elixir", "success" => true}
      iex> Context.from_map(map)
      %Context{file_path: "/path/to/file.ex", language: "elixir", ...}
  """
  @spec from_map(map()) :: t()
  def from_map(data) when is_map(data) do
    file_path = Map.get(data, "file_path") || Map.get(data, :file_path) || ""
    content = Map.get(data, "content") || Map.get(data, :content)
    language = Map.get(data, "language") || Map.get(data, :language)

    outline =
      case Map.get(data, "outline") || Map.get(data, :outline) do
        %FileOutline{} = o -> o
        map when is_map(map) -> FileOutline.from_map(map)
        _ -> nil
      end

    file_size = Map.get(data, "file_size") || Map.get(data, :file_size) || 0
    num_lines = Map.get(data, "num_lines") || Map.get(data, :num_lines) || 0
    num_tokens = Map.get(data, "num_tokens") || Map.get(data, :num_tokens) || 0
    parse_time_ms = Map.get(data, "parse_time_ms") || Map.get(data, :parse_time_ms) || 0.0
    has_errors = Map.get(data, "has_errors") || Map.get(data, :has_errors) || false
    error_message = Map.get(data, "error_message") || Map.get(data, :error_message)

    %__MODULE__{
      file_path: file_path,
      content: content,
      language: language,
      outline: outline,
      file_size: file_size,
      num_lines: num_lines,
      num_tokens: num_tokens,
      parse_time_ms: parse_time_ms,
      has_errors: has_errors,
      error_message: error_message
    }
  end

  @doc """
  Converts a Context to a map for serialization.

  ## Examples

      iex> context = %Context{file_path: "/path/to/file.ex", language: "elixir"}
      iex> Context.to_map(context)
      %{"file_path" => "/path/to/file.ex", "language" => "elixir", ...}
  """
  @spec to_map(t()) :: %{String.t() => term()}
  def to_map(%__MODULE__{} = context) do
    %{
      "file_path" => context.file_path,
      "content" => context.content,
      "language" => context.language,
      "outline" => if(context.outline, do: FileOutline.to_map(context.outline), else: nil),
      "file_size" => context.file_size,
      "num_lines" => context.num_lines,
      "num_tokens" => context.num_tokens,
      "parse_time_ms" => context.parse_time_ms,
      "has_errors" => context.has_errors,
      "error_message" => context.error_message
    }
  end

  @doc """
  Checks if the file was successfully parsed (has outline and success flag).

  ## Examples

      iex> context = %Context{outline: %FileOutline{success: true}}
      iex> Context.parsed?(context)
      true

      iex> context = %Context{outline: nil}
      iex> Context.parsed?(context)
      false

      iex> context = %Context{outline: %FileOutline{success: false}}
      iex> Context.parsed?(context)
      false
  """
  @spec parsed?(t()) :: boolean()
  def parsed?(%__MODULE__{} = context) do
    context.outline != nil and context.outline.success
  end

  @doc """
  Returns the total number of symbols (from outline if available).

  ## Examples

      iex> context = %Context{outline: %FileOutline{symbols: [%SymbolInfo{}, %SymbolInfo{}]}}
      iex> Context.symbol_count(context)
      2

      iex> context = %Context{outline: nil}
      iex> Context.symbol_count(context)
      0
  """
  @spec symbol_count(t()) :: non_neg_integer()
  def symbol_count(%__MODULE__{} = context) do
    if context.outline do
      length(context.outline.symbols)
    else
      0
    end
  end

  @doc """
  Generates a human-readable summary of the code context.

  ## Examples

      iex> context = %Context{
      ...>   file_path: "/path/to/file.py",
      ...>   language: "python",
      ...>   num_lines: 100,
      ...>   num_tokens: 500,
      ...>   outline: %FileOutline{symbols: [%SymbolInfo{kind: "class"}, %SymbolInfo{kind: "function"}]}
      ...> }
      iex> Context.summary(context)
      "📄 /path/to/file.py\\n   Language: python\\n   Lines: 100, Tokens: 500\\n   Symbols: 2"
  """
  @spec summary(t()) :: String.t()
  def summary(%__MODULE__{} = context) do
    lines = [
      "📄 #{context.file_path}",
      "   Language: #{context.language || "unknown"}",
      "   Lines: #{context.num_lines}, Tokens: #{context.num_tokens}"
    ]

    lines =
      if context.outline do
        count = length(context.outline.symbols)
        lines ++ ["   Symbols: #{count}"]
      else
        lines
      end

    lines =
      if context.outline do
        classes = FileOutline.classes(context.outline)

        if classes != [] do
          lines ++ ["   Classes: #{length(classes)}"]
        else
          lines
        end
      else
        lines
      end

    lines =
      if context.outline do
        functions = FileOutline.functions(context.outline)

        if functions != [] do
          lines ++ ["   Functions: #{length(functions)}"]
        else
          lines
        end
      else
        lines
      end

    lines =
      if context.has_errors && context.error_message do
        lines ++ ["   ⚠️ Error: #{context.error_message}"]
      else
        lines
      end

    Enum.join(lines, "\n")
  end

  @doc """
  Returns the file name without the path.

  ## Examples

      iex> context = %Context{file_path: "/path/to/file.ex"}
      iex> Context.file_name(context)
      "file.ex"
  """
  @spec file_name(t()) :: String.t()
  def file_name(%__MODULE__{} = context) do
    Path.basename(context.file_path)
  end

  @doc """
  Returns the directory path of the file.

  ## Examples

      iex> context = %Context{file_path: "/path/to/file.ex"}
      iex> Context.directory(context)
      "/path/to"
  """
  @spec directory(t()) :: String.t()
  def directory(%__MODULE__{} = context) do
    Path.dirname(context.file_path)
  end

  @doc """
  Checks if the file has content included.

  ## Examples

      iex> context = %Context{content: "some code"}
      iex> Context.has_content?(context)
      true

      iex> context = %Context{content: nil}
      iex> Context.has_content?(context)
      false
  """
  @spec has_content?(t()) :: boolean()
  def has_content?(%__MODULE__{} = context) do
    context.content != nil and context.content != ""
  end
end
