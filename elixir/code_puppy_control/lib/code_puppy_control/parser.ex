defmodule CodePuppyControl.Parser do
  @moduledoc """
  High-level parsing interface using turbo_parse NIF.

  Falls back to regex-based extraction when NIF unavailable.
  """

  alias CodePuppyControl.TurboParseNif
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
        # Use NIF for supported languages
        case TurboParseNif.extract_symbols(source, language) do
          json when is_binary(json) -> Jason.decode(json)
          other -> {:ok, other}
        end

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
        case TurboParseNif.extract_symbols_from_file(path, lang) do
          json when is_binary(json) -> Jason.decode(json)
          other -> {:ok, other}
        end

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
    case TurboParseNif.parse_source(source, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Parse a file.
  """
  def parse_file(path, language \\ nil) do
    case TurboParseNif.parse_file(path, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Extract syntax diagnostics (errors, warnings) from source code.
  """
  def extract_syntax_diagnostics(source, language) do
    case TurboParseNif.extract_syntax_diagnostics(source, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Get fold ranges for code folding.
  """
  def get_folds(source, language) do
    case TurboParseNif.get_folds(source, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Get fold ranges from a file.
  """
  def get_folds_from_file(path, language \\ nil) do
    case TurboParseNif.get_folds_from_file(path, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Get syntax highlights.
  """
  def get_highlights(source, language) do
    case TurboParseNif.get_highlights(source, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
  end

  @doc """
  Get syntax highlights from a file.
  """
  def get_highlights_from_file(path, language \\ nil) do
    case TurboParseNif.get_highlights_from_file(path, language) do
      json when is_binary(json) -> Jason.decode(json)
      other -> {:ok, other}
    end
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
