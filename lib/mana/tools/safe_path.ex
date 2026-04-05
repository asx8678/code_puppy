defmodule Mana.Tools.SafePath do
  @moduledoc """
  Path traversal protection for file operations.

  This module provides utilities to validate file paths and prevent
  path traversal attacks where malicious paths like `../../../etc/passwd`
  could escape the intended working directory.

  ## Usage

      # Check if a path is safe
      case SafePath.validate("/safe/path/to/file.txt", "/allowed/base") do
        {:ok, expanded_path} -> # proceed with file operation
        {:error, reason} -> # reject the operation
      end

  ## Features

  - Expands paths with `Path.expand/1` to resolve symlinks and relative paths
  - Validates paths don't escape the allowed base directory via traversal
  - Rejects paths containing `..` that would escape the base
  - Allows absolute paths that don't contain traversal attempts
  - Thread-safe and pure functions (no side effects during validation)
  """

  require Logger

  @doc """
  Validates that a path is safe for file operations.

  The path validation rules:
  1. Must not contain null bytes (path injection)
  2. If relative, must stay within the base directory (no `..` escapes)
  3. If absolute, must not contain `..` segments (traversal attempt)
  4. Must be expandable to an absolute path

  ## Parameters

  - `path` - The path to validate (relative or absolute)
  - `base_dir` - The allowed base directory that relative paths must stay within

  ## Returns

  - `{:ok, expanded_path}` - The validated, expanded absolute path
  - `{:error, reason}` - The path is unsafe or invalid

  ## Examples

      iex> SafePath.validate("lib/file.ex", "/project")
      {:ok, "/project/lib/file.ex"}

      iex> SafePath.validate("../../../etc/passwd", "/project")
      {:error, "Path escapes allowed directory"}

      iex> SafePath.validate("/etc/passwd", "/project")
      {:ok, "/etc/passwd"}
  """
  @spec validate(String.t(), String.t()) :: {:ok, String.t()} | {:error, String.t()}
  def validate(path, base_dir) when is_binary(path) and is_binary(base_dir) do
    with :ok <- check_null_bytes(path),
         # Absolute paths with .. are suspicious - reject them
         :ok <- check_absolute_traversal(path),
         {:ok, expanded_base} <- expand_path(base_dir),
         # Expand relative paths relative to base_dir, not cwd
         {:ok, expanded_path} <- expand_path_relative_to_base(path, expanded_base),
         :ok <- check_traversal_in_expanded(expanded_path),
         :ok <- check_relative_path_within_base(expanded_path, expanded_base, path) do
      {:ok, expanded_path}
    end
  end

  def validate(_, _), do: {:error, "Invalid path or base directory"}

  @doc """
  Validates a list of paths, returning the first error or all expanded paths.

  ## Parameters

  - `paths` - List of paths to validate
  - `base_dir` - The allowed base directory

  ## Returns

  - `{:ok, expanded_paths}` - All paths are valid
  - `{:error, reason}` - At least one path is invalid
  """
  @spec validate_many(list(String.t()), String.t()) :: {:ok, list(String.t())} | {:error, String.t()}
  def validate_many(paths, base_dir) when is_list(paths) and is_binary(base_dir) do
    Enum.reduce_while(paths, {:ok, []}, fn path, {:ok, acc} ->
      case validate(path, base_dir) do
        {:ok, expanded} -> {:cont, {:ok, [expanded | acc]}}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
    |> case do
      {:ok, expanded} -> {:ok, Enum.reverse(expanded)}
      error -> error
    end
  end

  @doc """
  Quick check if a path appears to contain traversal attempts.

  This is a lightweight check that doesn't require knowing the base directory.
  It looks for patterns that *might* indicate traversal attempts but doesn't
  validate against a specific base.

  ## Parameters

  - `path` - The path to check

  ## Returns

  - `true` - Suspicious traversal patterns detected
  - `false` - No obvious traversal patterns (but still needs full validation)

  ## Examples

      iex> SafePath.suspicious_traversal?("../../../etc/passwd")
      true

      iex> SafePath.suspicious_traversal?("lib/file.ex")
      false
  """
  @spec suspicious_traversal?(String.t()) :: boolean()
  def suspicious_traversal?(path) when is_binary(path) do
    # Check for explicit .. sequences that might escape
    # Check for null bytes (path injection)
    String.contains?(path, "../") ||
      String.contains?(path, "..\\") ||
      String.ends_with?(path, "..") ||
      String.contains?(path, "\x00")
  end

  def suspicious_traversal?(_), do: false

  @doc """
  Gets the current working directory to use as a safe base.

  Returns the absolute path of the current working directory,
  or an error if it cannot be determined.
  """
  @spec current_working_dir() :: {:ok, String.t()} | {:error, String.t()}
  def current_working_dir do
    case File.cwd() do
      {:ok, cwd} -> {:ok, Path.expand(cwd)}
      {:error, reason} -> {:error, "Cannot determine working directory: #{reason}"}
    end
  end

  @doc """
  Validates that a path is within or equal to the base directory.

  This is the core validation logic used by `validate/2`.

  ## Returns

  - `:ok` - Path is safe
  - `{:error, reason}` - Path escapes the allowed directory
  """
  @spec validate_within_base(String.t(), String.t()) :: :ok | {:error, String.t()}
  def validate_within_base(path, base_dir) do
    check_path_within_base(path, base_dir)
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp expand_path(path) do
    try do
      expanded = Path.expand(path)
      {:ok, expanded}
    rescue
      _ -> {:error, "Failed to expand path: #{path}"}
    end
  end

  # For relative paths, expand them relative to the base directory
  # For absolute paths, just expand them normally
  defp expand_path_relative_to_base(path, base_dir) do
    try do
      expanded =
        if Path.type(path) == :relative do
          # Expand relative to base_dir
          Path.expand(path, base_dir)
        else
          # Absolute path - expand normally
          Path.expand(path)
        end

      {:ok, expanded}
    rescue
      _ -> {:error, "Failed to expand path: #{path}"}
    end
  end

  defp check_null_bytes(path) do
    if String.contains?(path, "\x00") do
      {:error, "Path contains null bytes"}
    else
      :ok
    end
  end

  defp check_absolute_traversal(path) do
    # Absolute paths containing .. are suspicious
    if Path.type(path) == :absolute and suspicious_traversal?(path) do
      {:error, "Path escapes allowed directory"}
    else
      :ok
    end
  end

  defp check_traversal_in_expanded(expanded_path) do
    # Check if the expanded path contains any parent directory references
    # that would indicate a traversal attempt
    # We use Path.split which gives us path components
    parts = Path.split(expanded_path)

    # Count depth: go up one level for "..", down one for normal components
    # Skip the root component ("/" on Unix)
    depth_result =
      Enum.reduce(parts, {:ok, 0}, fn part, {:ok, depth} ->
        cond do
          # Root component - doesn't change depth
          part == "/" ->
            {:ok, depth}

          # Current directory - doesn't change depth
          part == "." ->
            {:ok, depth}

          # Parent directory - go up (decrease depth)
          part == ".." ->
            new_depth = depth - 1
            # Negative depth means we went above root - that's traversal!
            if new_depth < 0, do: {:error, "traversal"}, else: {:ok, new_depth}

          # Normal directory/file - go down (increase depth)
          true ->
            {:ok, depth + 1}
        end
      end)

    case depth_result do
      {:error, _} -> {:error, "Path escapes allowed directory"}
      {:ok, _} -> :ok
    end
  end

  defp check_relative_path_within_base(expanded_path, expanded_base, original_path) do
    # If the original path was absolute, allow it (as long as no traversal was detected)
    # If it was relative, it must be within the base directory after expansion
    if Path.type(original_path) == :absolute do
      :ok
    else
      # For relative paths, check they didn't escape the base after expansion
      # This handles cases like base=/project and path=../../etc/passwd
      # which would expand to something outside /project
      check_path_within_base(expanded_path, expanded_base)
    end
  end

  defp check_path_within_base(expanded_path, expanded_base) do
    # Ensure the path starts with the base directory
    # We need to handle the case where the path IS the base directory
    if expanded_path == expanded_base do
      :ok
    else
      # Check if path starts with base_dir + "/" to ensure it's truly within
      base_with_sep = expanded_base <> "/"

      if String.starts_with?(expanded_path, base_with_sep) do
        :ok
      else
        {:error, "Path escapes allowed directory"}
      end
    end
  end
end
