defmodule CodePuppyControl.Parser do
  @moduledoc """
  High-level parsing interface using turbo_parse NIF.

  Falls back to regex-based extraction when NIF unavailable.

  Also provides hashline formatting for file display with line anchors.
  """

  alias CodePuppyControl.TurboParseNif
  alias CodePuppyControl.HashlineNif
  alias CodePuppyControl.Indexer.SymbolExtractor

  @doc """
  Check if NIF is available.
  """
  def nif_available? do
    try do
      TurboParseNif.supported_languages()
      true
    rescue
      _ -> false
    end
  end

  @doc """
  Extract symbols from source, with fallback to regex.
  """
  def extract_symbols(source, language) do
    cond do
      nif_available?() and TurboParseNif.is_language_supported(language) ->
        # NIF returns {:ok, result} directly — no Jason.decode needed
        TurboParseNif.extract_symbols(source, language)

      language in ["python", "elixir"] ->
        # Use SymbolExtractor for regex-based fallback on known languages
        symbols = SymbolExtractor.extract_regex_symbols(source, language)

        outline = %{
          "language" => language,
          "symbols" => symbols,
          "extraction_time_ms" => 0.0,
          "success" => true,
          "errors" => []
        }

        {:ok, outline}

      true ->
        # Unsupported language - return empty result
        {:ok,
         %{
           "language" => language,
           "symbols" => [],
           "extraction_time_ms" => 0.0,
           "success" => false,
           "errors" => ["Unsupported language: #{language}"]
         }}
    end
  end

  @doc """
  Extract symbols from file, with fallback.
  """
  def extract_symbols_from_file(path, language \\ nil) do
    lang = language || detect_language(path)

    cond do
      nif_available?() and is_binary(lang) and TurboParseNif.is_language_supported(lang) ->
        # NIF returns {:ok, result} directly
        TurboParseNif.extract_symbols_from_file(path, lang)

      is_binary(lang) and lang in ["python", "elixir"] ->
        # Fallback: read file and use regex extraction
        case File.read(path) do
          {:ok, content} ->
            symbols = SymbolExtractor.extract_regex_symbols(content, lang)
            {:ok, %{"language" => lang, "symbols" => symbols, "success" => true}}

          {:error, reason} ->
            {:error, reason}
        end

      true ->
        {:ok, %{"language" => lang || "unknown", "symbols" => [], "success" => false}}
    end
  end

  @doc """
  Parse source code.
  """
  def parse_source(source, language) do
    TurboParseNif.parse_source(source, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Parse a file.
  """
  def parse_file(path, language \\ nil) do
    TurboParseNif.parse_file(path, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Extract syntax diagnostics (errors, warnings) from source code.
  """
  def extract_syntax_diagnostics(source, language) do
    TurboParseNif.extract_syntax_diagnostics(source, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Get fold ranges for code folding.
  """
  def get_folds(source, language) do
    TurboParseNif.get_folds(source, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Get fold ranges from a file.
  """
  def get_folds_from_file(path, language \\ nil) do
    TurboParseNif.get_folds_from_file(path, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Get syntax highlights.
  """
  def get_highlights(source, language) do
    TurboParseNif.get_highlights(source, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Get syntax highlights from a file.
  """
  def get_highlights_from_file(path, language \\ nil) do
    TurboParseNif.get_highlights_from_file(path, language)
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc """
  Get supported languages.
  """
  def supported_languages do
    if nif_available?() do
      TurboParseNif.supported_languages()
    else
      ["python", "elixir"]
    end
  end

  @doc """
  Get the turbo_parse version string.
  """
  def version do
    if nif_available?() do
      TurboParseNif.version()
    else
      "unavailable"
    end
  rescue
    _ -> "unavailable"
  end

  @doc """
  Normalize a language name (aliases to canonical name).

  Examples:
    normalize_language("py")  => "python"
    normalize_language("js")  => "javascript"
    normalize_language("jsx") => "javascript"
  """
  def normalize_language(language) do
    if nif_available?() do
      TurboParseNif.normalize_language(language)
    else
      # Fallback normalization
      case String.downcase(language) do
        "py" -> "python"
        "js" -> "javascript"
        "jsx" -> "javascript"
        "ts" -> "typescript"
        "ex" -> "elixir"
        "exs" -> "elixir"
        other -> other
      end
    end
  end

  @doc """
  Get language metadata (name, available query types).

  Returns {:ok, info} or {:error, :unsupported_language}.
  """
  def get_language_info(language) do
    if nif_available?() do
      TurboParseNif.get_language_info(language)
    else
      if language in ["python", "elixir"] do
        {:ok,
         %{
           "name" => language,
           "highlights_available" => true,
           "folds_available" => true,
           "indents_available" => true
         }}
      else
        {:error, :unsupported_language}
      end
    end
  rescue
    _ -> {:error, :unsupported_language}
  end

  # ---------------------------------------------------------------------------
  # Hashline integration - file display with line anchors
  # ---------------------------------------------------------------------------

  @doc """
  Format text with hashline prefixes for display with line anchors.

  Each line gets a `LINE_NUM#HASH:` prefix for precise referencing.
  `start_line` is 1-based by convention.
  """
  @spec format_with_hashlines(String.t(), non_neg_integer()) :: String.t()
  def format_with_hashlines(text, start_line \\ 1) do
    HashlineNif.format_hashlines(text, start_line)
  end

  @doc """
  Strip hashline prefixes from text, returning plain content.
  """
  @spec strip_hashlines(String.t()) :: String.t()
  def strip_hashlines(text) do
    HashlineNif.strip_hashline_prefixes(text)
  end

  @doc """
  Validate that a hashline anchor still matches the current line content.
  """
  @spec validate_anchor(non_neg_integer(), String.t(), String.t()) :: boolean()
  def validate_anchor(idx, line, expected_hash) do
    HashlineNif.validate_hashline_anchor(idx, line, expected_hash)
  end

  @doc """
  Read a file and format with hashline prefixes for display.

  Returns `{:ok, formatted_text}` or `{:error, reason}`.
  `start_line` is 1-based by convention.
  """
  @spec read_file_with_hashlines(String.t(), non_neg_integer()) ::
          {:ok, String.t()} | {:error, term()}
  def read_file_with_hashlines(path, start_line \\ 1) do
    case File.read(path) do
      {:ok, content} ->
        {:ok, format_with_hashlines(content, start_line)}

      {:error, reason} ->
        {:error, reason}
    end
  end

  # Private helpers

  defp detect_language(path) do
    case Path.extname(path) do
      ".py" -> "python"
      ".rs" -> "rust"
      ".js" -> "javascript"
      ".ts" -> "typescript"
      ".tsx" -> "tsx"
      ".ex" -> "elixir"
      ".exs" -> "elixir"
      _ -> nil
    end
  end
end
