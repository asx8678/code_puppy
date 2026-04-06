defmodule Mana.Tools.IgnorePatterns do
  @moduledoc "Compiled ignore patterns for file operations"

  @patterns [
    ~r/\.git/,
    ~r/__pycache__/,
    ~r/node_modules/,
    ~r/\.venv/,
    ~r/venv/,
    ~r/dist/,
    ~r/build/,
    ~r/\.tox/,
    ~r/\.mypy_cache/,
    ~r/\.pytest_cache/,
    ~r/\.eggs/,
    ~r/\.DS_Store/,
    ~r/\.idea/,
    ~r/\.vscode/,
    ~r/\.env$/,
    ~r/\.env\.local$/,
    ~r/\.beam$/,
    ~r/_build/,
    ~r/deps/,
    ~r/\.elixir_ls/
  ]

  @doc "Check if a path should be ignored"
  @spec ignore_path?(String.t()) :: boolean()
  def ignore_path?(path) do
    basename = Path.basename(path)
    parts = String.split(path, "/")

    Enum.any?(@patterns, fn pattern ->
      Regex.match?(pattern, basename) or Enum.any?(parts, &Regex.match?(pattern, &1))
    end)
  end

  @doc "Check if a directory should be ignored"
  @spec ignore_dir?(String.t()) :: boolean()
  def ignore_dir?(dir) do
    ignore_path?(dir)
  end

  @doc "Filter a list of paths, removing ignored ones"
  @spec filter_paths([String.t()]) :: [String.t()]
  def filter_paths(paths) do
    Enum.reject(paths, &ignore_path?/1)
  end
end
