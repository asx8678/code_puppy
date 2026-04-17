defmodule CodePuppyControl.TurboParseNif do
  @moduledoc """
  DEPRECATED: Rust NIF bindings have been replaced with pure Elixir parsers.
  See CodePuppyControl.Parsing.Parser for the new implementation.

  This module is kept as a stub for backwards compatibility.
  All functions return {:error, :nif_removed}.
  """

  @doc "Check if a language is supported by turbo_parse"
  @spec is_language_supported(String.t()) :: false
  def is_language_supported(_language), do: false

  @doc "Get list of all supported languages"
  @spec supported_languages() :: []
  def supported_languages(), do: []

  @doc "Extract symbols from source code"
  @spec extract_symbols(String.t(), String.t()) :: {:error, :nif_removed}
  def extract_symbols(_source, _language), do: {:error, :nif_removed}

  @doc "Extract symbols from a file"
  @spec extract_symbols_from_file(String.t(), String.t() | nil) :: {:error, :nif_removed}
  def extract_symbols_from_file(_path, _language \\ nil), do: {:error, :nif_removed}

  @doc "Parse source code"
  @spec parse_source(String.t(), String.t()) :: {:error, :nif_removed}
  def parse_source(_source, _language), do: {:error, :nif_removed}

  @doc "Parse a file"
  @spec parse_file(String.t(), String.t() | nil) :: {:error, :nif_removed}
  def parse_file(_path, _language \\ nil), do: {:error, :nif_removed}

  @doc "Extract syntax diagnostics (errors, warnings)"
  @spec extract_syntax_diagnostics(String.t(), String.t()) :: {:error, :nif_removed}
  def extract_syntax_diagnostics(_source, _language), do: {:error, :nif_removed}

  @doc "Get fold ranges for code folding"
  @spec get_folds(String.t(), String.t()) :: {:error, :nif_removed}
  def get_folds(_source, _language), do: {:error, :nif_removed}

  @doc "Get fold ranges from a file"
  @spec get_folds_from_file(String.t(), String.t() | nil) :: {:error, :nif_removed}
  def get_folds_from_file(_path, _language \\ nil), do: {:error, :nif_removed}

  @doc "Get syntax highlights"
  @spec get_highlights(String.t(), String.t()) :: {:error, :nif_removed}
  def get_highlights(_source, _language), do: {:error, :nif_removed}

  @doc "Get syntax highlights from a file"
  @spec get_highlights_from_file(String.t(), String.t() | nil) :: {:error, :nif_removed}
  def get_highlights_from_file(_path, _language \\ nil), do: {:error, :nif_removed}

  @doc "Get the turbo_parse crate version"
  @spec version() :: String.t()
  def version(), do: "0.0.0-removed"

  @doc "Normalize a language name (aliases to canonical name)"
  @spec normalize_language(String.t()) :: nil
  def normalize_language(_language), do: nil

  @doc "Get language metadata (name, available query types)"
  @spec get_language_info(String.t()) :: {:error, :nif_removed}
  def get_language_info(_language), do: {:error, :nif_removed}
end
