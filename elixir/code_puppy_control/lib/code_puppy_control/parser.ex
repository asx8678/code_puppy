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
    if nif_available?() and TurboParseNif.is_language_supported(language) do
      case TurboParseNif.extract_symbols(source, language) do
        json when is_binary(json) -> Jason.decode(json)
        other -> {:ok, other}
      end
    else
      # Fallback to regex-based extraction
      symbols = SymbolExtractor.extract(source, language, 1000)
      
      outline = %{
        "language" => language,
        "symbols" => Enum.map(symbols, fn sym ->
          # Parse symbol string like "def foo" or "class Bar"
          [kind, name] = String.split(sym, " ", parts: 2)
          %{
            "name" => name,
            "kind" => kind_to_symbol_kind(kind),
            "start_line" => 1,
            "end_line" => 1,
            "start_col" => 0,
            "end_col" => 0
          }
        end),
        "extraction_time_ms" => 0.0,
        "success" => true,
        "errors" => []
      }
      
      {:ok, outline}
    end
  end

  @doc """
  Extract symbols from file, with fallback.
  """
  def extract_symbols_from_file(path, language \\ nil) do
    lang = language || detect_language(path)

    if nif_available?() and is_binary(lang) and TurboParseNif.is_language_supported(lang) do
      case TurboParseNif.extract_symbols_from_file(path, lang) do
        json when is_binary(json) -> Jason.decode(json)
        other -> {:ok, other}
      end
    else
      case File.read(path) do
        {:ok, content} -> extract_symbols(content, lang || "unknown")
        {:error, reason} -> {:error, reason}
      end
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

  defp kind_to_symbol_kind("def"), do: "function"
  defp kind_to_symbol_kind("class"), do: "class"
  defp kind_to_symbol_kind("defmodule"), do: "module"
  defp kind_to_symbol_kind(other), do: other
end
