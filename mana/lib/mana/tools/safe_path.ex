defmodule Mana.Tools.SafePath do
  @moduledoc """
  Path traversal protection for file operations.

  This module provides utilities to validate file paths and prevent
  path traversal attacks where malicious paths like `../../../etc/passwd`
  could escape the intended working directory.

  ## Usage

      # Check if a path is safe
      case SafePath.validate("lib/file.ex", "/allowed/base") do
        {:ok, expanded_path} -> # proceed with file operation
        {:error, reason} -> # reject the operation
      end

  ## Features

  - Expands paths with `Path.expand/1` to normalize relative components
  - ALL paths (relative and absolute) must resolve within the base directory
  - Rejects paths containing `..` that would escape the base
  - Detects symlinks via `File.lstat/1` and validates their targets
  - Thread-safe with no side effects beyond stat calls during validation
  """

  require Logger

  @doc """
  Validates that a path is safe for file operations.

  The path validation rules:
  1. Must not contain null bytes (path injection)
  2. Must not contain `..` traversal in absolute paths
  3. Must expand to a path within the base directory (both relative AND absolute)
  4. Symlinks must resolve to paths within the base directory

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
      {:error, "Path escapes allowed directory"}

      iex> SafePath.validate("/project/lib/code.ex", "/project")
      {:ok, "/project/lib/code.ex"}
  """
  @spec validate(String.t(), String.t()) :: {:ok, String.t()} | {:error, String.t()}
  def validate(path, base_dir) when is_binary(path) and is_binary(base_dir) do
    with :ok <- check_null_bytes(path),
         {:ok, expanded_base} <- expand_path(base_dir),
         {:ok, expanded_path} <- expand_path_relative_to_base(path, expanded_base),
         :ok <- check_traversal_in_expanded(expanded_path),
         :ok <- check_relative_path_within_base(expanded_path, expanded_base, path) do
      resolve_and_check_symlinks(expanded_path, expanded_base)
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

  @doc """
  Atomically writes content to a validated path, minimizing TOCTOU window.

  The race condition: `validate/2` checks a path is safe, then a SEPARATE
  `File.write` call writes to it. Between those two calls, an attacker could
  swap the validated path for a symlink. This function mitigates that by:

  1. Validating the path
  2. Writing to a temp file in the same directory
  3. Re-validating the target path hasn't changed (symlink swap detection)
  4. Renaming temp to target (atomic on same filesystem)

  ## Parameters

  - `path` - The path to write to (relative or absolute)
  - `content` - The binary content to write
  - `cwd` - The allowed base directory

  ## Returns

  - `:ok` - File written successfully
  - `{:error, reason}` - Validation failed or write failed
  """
  @spec safe_write(String.t(), binary(), String.t()) :: :ok | {:error, String.t()}
  def safe_write(path, content, cwd) do
    with {:ok, safe_path} <- validate(path, cwd) do
      dir = Path.dirname(safe_path)
      tmp_name = ".mana_tmp_#{System.unique_integer([:positive, :monotonic])}"
      tmp_path = Path.join(dir, tmp_name)

      try do
        case File.write(tmp_path, content) do
          :ok ->
            # Re-validate: detect symlink swap between first validate and now
            case validate(path, cwd) do
              {:ok, ^safe_path} ->
                case File.rename(tmp_path, safe_path) do
                  :ok -> :ok
                  {:error, reason} -> {:error, "Failed to rename temp file: #{reason}"}
                end

              {:ok, _different} ->
                {:error, "Path resolution changed during write - possible symlink attack: #{path}"}

              {:error, reason} ->
                {:error, reason}
            end

          {:error, reason} ->
            {:error, "Failed to write temp file: #{reason}"}
        end
      after
        # Always clean up temp file on any error path.
        # On success, the rename already moved the file away so rm returns
        # {:error, :enoent} which is harmless. On error, it cleans up the temp file.
        File.rm(tmp_path)
      end
    end
  end

  @doc """
  Reads, transforms, and atomically writes back a file.

  Combines read + transform + safe_write for replace-in-file operations,
  minimizing the TOCTOU window by using atomic rename.

  ## Parameters

  - `path` - The path to the file (relative or absolute)
  - `transform_fn` - A function that takes the current content and returns new content
  - `cwd` - The allowed base directory

  ## Returns

  - `{:ok, new_content}` - File transformed and written successfully
  - `{:error, reason}` - Validation, read, or write failed
  """
  @spec safe_transform(String.t(), (String.t() -> String.t()), String.t()) ::
          {:ok, String.t()} | {:error, String.t()}
  def safe_transform(path, transform_fn, cwd) do
    with {:ok, safe_path} <- validate(path, cwd),
         {:ok, content} <- File.read(safe_path) do
      new_content = transform_fn.(content)

      case safe_write(path, new_content, cwd) do
        :ok -> {:ok, new_content}
        {:error, _} = err -> err
      end
    end
  end

  @doc """
  Atomically reads from a validated path, minimizing TOCTOU window.

  Similar to safe_write but for reading: validates, then re-validates
  right before reading to detect symlink swap attacks.

  ## Parameters

  - `path` - The path to read from (relative or absolute)
  - `cwd` - The allowed base directory

  ## Returns

  - `{:ok, content}` - File read successfully
  - `{:error, reason}` - Validation failed or read failed
  """
  @spec safe_read(String.t(), String.t()) :: {:ok, String.t()} | {:error, String.t()}
  def safe_read(path, cwd) do
    with {:ok, safe_path} <- validate(path, cwd),
         # Re-validate: detect symlink swap between first validate and now
         {:ok, ^safe_path} <- validate(path, cwd),
         # Additional check: ensure the path is not a symlink (catches race conditions)
         # Use the original expanded path, not the resolved symlink target
         :ok <- check_not_symlink(expanded_path_for_check(path, cwd)),
         {:ok, content} <- File.read(safe_path) do
      {:ok, content}
    else
      {:ok, _different} ->
        {:error, "Path resolution changed during read - possible symlink attack: #{path}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Atomically deletes a file at a validated path, minimizing TOCTOU window.

  Validates the path, re-validates right before deletion, and ensures
  the target is a regular file (not a symlink) at the moment of deletion.

  ## Parameters

  - `path` - The path to delete (relative or absolute)
  - `cwd` - The allowed base directory

  ## Returns

  - `:ok` - File deleted successfully
  - `{:error, reason}` - Validation failed or delete failed
  """
  @spec safe_delete(String.t(), String.t()) :: :ok | {:error, String.t()}
  def safe_delete(path, cwd) do
    with {:ok, safe_path} <- validate(path, cwd),
         # Re-validate: detect symlink swap between first validate and now
         {:ok, ^safe_path} <- validate(path, cwd),
         # Additional check: ensure the path is not a symlink (catches race conditions)
         # Use the original expanded path, not the resolved symlink target
         :ok <- check_not_symlink(expanded_path_for_check(path, cwd)),
         :ok <- File.rm(safe_path) do
      :ok
    else
      {:ok, _different} ->
        {:error, "Path resolution changed during delete - possible symlink attack: #{path}"}

      {:error, reason} when is_atom(reason) ->
        {:error, "Failed to delete #{path}: #{reason}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  # Returns the expanded path without symlink resolution, for TOCTOU checks.
  # This gives us the path as it would appear in the filesystem before symlink resolution.
  defp expanded_path_for_check(path, cwd) do
    if Path.type(path) == :relative do
      Path.expand(path, cwd)
    else
      Path.expand(path)
    end
  end

  # Returns :ok if it's a regular file or doesn't exist (for idempotent deletes).
  # Returns error if it's a symlink (possible attack).
  defp check_not_symlink(path) do
    case File.lstat(path) do
      {:ok, %File.Stat{type: :symlink}} ->
        {:error, "Path is a symlink - possible race condition attack: #{path}"}

      {:ok, _} ->
        # Regular file or other non-symlink type
        :ok

      {:error, :enoent} ->
        # File doesn't exist - ok for idempotent operations
        :ok

      {:error, reason} ->
        {:error, "Cannot stat #{path}: #{inspect(reason)}"}
    end
  end

  defp expand_path(path) do
    expanded = Path.expand(path)
    {:ok, expanded}
  rescue
    _ -> {:error, "Failed to expand path: #{path}"}
  end

  # For relative paths, expand them relative to the base directory
  # For absolute paths, just expand them normally
  defp expand_path_relative_to_base(path, base_dir) do
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

  defp check_null_bytes(path) do
    if String.contains?(path, "\x00") do
      {:error, "Path contains null bytes"}
    else
      :ok
    end
  end

  # NOTE: Redundant safety net. Path.expand/1 already resolves ".." segments,
  # so expanded paths should never contain them. We keep this as defense-in-depth
  # in case Path.expand behavior changes or has edge cases we haven't considered.
  defp check_traversal_in_expanded(expanded_path) do
    # Check if the expanded path contains any parent directory references
    # that would indicate a traversal attempt
    # We use Path.split which gives us path components
    parts = Path.split(expanded_path)

    # Count depth: go up one level for "..", down one for normal components
    # Skip the root component ("/" on Unix)
    depth_result = Enum.reduce(parts, {:ok, 0}, &update_depth/2)

    case depth_result do
      {:error, _} -> {:error, "Path escapes allowed directory"}
      {:ok, _} -> :ok
    end
  end

  defp update_depth("/", {:ok, depth}), do: {:ok, depth}
  defp update_depth(".", {:ok, depth}), do: {:ok, depth}
  defp update_depth("..", {:ok, depth}) when depth <= 0, do: {:error, "traversal"}
  defp update_depth("..", {:ok, depth}), do: {:ok, depth - 1}
  defp update_depth(_, {:ok, depth}), do: {:ok, depth + 1}

  defp check_relative_path_within_base(expanded_path, expanded_base, _original_path) do
    # ALL paths (relative or absolute) must resolve within the base directory.
    # Previously absolute paths bypassed this check, allowing reads of any file
    # on the system (e.g. /etc/shadow). That was a critical containment bypass.
    check_path_within_base(expanded_path, expanded_base)
  end

  # Detects symlinks via File.lstat/1 and validates their resolved targets
  # stay within the base directory. Non-existent paths (create operations)
  # pass through — the stat simply returns :enoent.
  defp resolve_and_check_symlinks(path, expanded_base) do
    case File.lstat(path) do
      {:ok, %File.Stat{type: :symlink}} ->
        resolve_symlink_target(path, expanded_base)

      {:ok, _} ->
        # Not a symlink — pass through
        {:ok, path}

      {:error, :enoent} ->
        # File doesn't exist yet (create operation) — pass through
        {:ok, path}

      {:error, reason} ->
        {:error, "Cannot stat #{path}: #{inspect(reason)}"}
    end
  end

  defp resolve_symlink_target(path, expanded_base) do
    case File.read_link(path) do
      {:ok, target} ->
        real_path = Path.expand(target, Path.dirname(path))

        case check_path_within_base(real_path, expanded_base) do
          :ok -> {:ok, real_path}
          {:error, _} -> {:error, "Symlink #{path} points outside base directory: #{real_path}"}
        end

      {:error, reason} ->
        {:error, "Cannot resolve symlink #{path}: #{inspect(reason)}"}
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
