defmodule CodePuppyControl.TurboParseNif do
  @moduledoc """
  NIF bindings to turbo_parse Rust crate.

  Provides tree-sitter based parsing for 6 languages:
  Python, Rust, JavaScript, TypeScript, TSX, Elixir
  """

  use Rustler,
    otp_app: :code_puppy_control,
    crate: "turbo_parse_nif"

  # NIF stubs - these are replaced by the Rust implementations at load time

  @doc "Check if a language is supported by turbo_parse"
  @spec is_language_supported(String.t()) :: boolean()
  def is_language_supported(_language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get list of all supported languages"
  @spec supported_languages() :: [String.t()]
  def supported_languages(), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Extract symbols from source code"
  @spec extract_symbols(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def extract_symbols(_source, _language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Extract symbols from a file"
  @spec extract_symbols_from_file(String.t(), String.t() | nil) :: {:ok, map()} | {:error, term()}
  def extract_symbols_from_file(_path, _language \\ nil), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Parse source code"
  @spec parse_source(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def parse_source(_source, _language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Parse a file"
  @spec parse_file(String.t(), String.t() | nil) :: {:ok, map()} | {:error, term()}
  def parse_file(_path, _language \\ nil), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Extract syntax diagnostics (errors, warnings)"
  @spec extract_syntax_diagnostics(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def extract_syntax_diagnostics(_source, _language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get fold ranges for code folding"
  @spec get_folds(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def get_folds(_source, _language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get fold ranges from a file"
  @spec get_folds_from_file(String.t(), String.t() | nil) :: {:ok, map()} | {:error, term()}
  def get_folds_from_file(_path, _language \\ nil), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get syntax highlights"
  @spec get_highlights(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def get_highlights(_source, _language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get syntax highlights from a file"
  @spec get_highlights_from_file(String.t(), String.t() | nil) :: {:ok, map()} | {:error, term()}
  def get_highlights_from_file(_path, _language \\ nil), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get the turbo_parse crate version"
  @spec version() :: String.t()
  def version(), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Normalize a language name (aliases to canonical name)"
  @spec normalize_language(String.t()) :: String.t()
  def normalize_language(_language), do: :erlang.nif_error(:nif_not_loaded)

  @doc "Get language metadata (name, available query types)"
  @spec get_language_info(String.t()) :: {:ok, map()} | {:error, :unsupported_language}
  def get_language_info(_language), do: :erlang.nif_error(:nif_not_loaded)
end
