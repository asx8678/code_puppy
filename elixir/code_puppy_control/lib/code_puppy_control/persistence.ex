defmodule CodePuppyControl.Persistence do
  @moduledoc """
  Safe atomic persistence helpers for file operations.

  Provides atomic file write operations to prevent partial/corrupt files
  on crash or interruption. All writes use temp-file + atomic rename.

  Port of the Python `code_puppy.persistence` module.
  """

  require Logger

  @doc """
  Resolves a path to its absolute form, optionally verifying it's within an
  allowed parent directory.

  Uses `Path.expand/1` to normalize `..` components without following symlinks,
  preventing path traversal attacks while avoiding TOCTOU race conditions.

  ## Parameters

    * `path` - The path to resolve
    * `allowed_parent` - Optional parent directory that path must be within

  ## Returns

    Resolved absolute path.

  ## Raises

    * `ArgumentError` if path resolves outside `allowed_parent`
  """
  @spec safe_resolve_path(Path.t(), Path.t() | nil) :: Path.t()
  def safe_resolve_path(path, allowed_parent \\ nil)

  def safe_resolve_path(path, nil) do
    path |> Path.expand() |> normalize_path()
  end

  def safe_resolve_path(path, allowed_parent) do
    resolved = path |> Path.expand() |> normalize_path()
    allowed = allowed_parent |> Path.expand() |> normalize_path()

    resolved_str = to_string(resolved)
    allowed_str = to_string(allowed)

    unless String.starts_with?(resolved_str, allowed_str) do
      raise ArgumentError,
            "Path #{resolved_str} is outside allowed parent #{allowed_str}"
    end

    resolved
  end

  @doc """
  Writes text content to a file atomically using temp file + rename.

  The file is first written to a temporary file in the same directory,
  then atomically renamed to the target path. This prevents partial writes
  if the process crashes during the write.

  ## Parameters

    * `path` - Target file path
    * `content` - Text content to write
    * `opts` - Keyword options:
      - `:encoding` - Text encoding (default: `"utf-8"`)

  ## Raises

    * `File.Error` if the write fails
  """
  @spec atomic_write_text(Path.t(), String.t(), keyword()) :: :ok
  def atomic_write_text(path, content, opts \\ []) do
    encoding = Keyword.get(opts, :encoding, "utf-8")
    resolved = safe_resolve_path(path)
    ensure_parent_dir!(resolved)

    tmp_path = Path.join(Path.dirname(resolved), ".#{Path.basename(resolved)}.tmp")

    try do
      File.write!(tmp_path, content, encoding: String.to_atom(encoding))
      File.rename!(tmp_path, resolved)
      :ok
    rescue
      e ->
        _ = File.rm(tmp_path)
        reraise e, __STACKTRACE__
    end
  end

  @doc """
  Writes binary data to a file atomically using temp file + rename.

  ## Parameters

    * `path` - Target file path
    * `data` - Binary data to write

  ## Raises

    * `File.Error` if the write fails
  """
  @spec atomic_write_bytes(Path.t(), binary()) :: :ok
  def atomic_write_bytes(path, data) do
    resolved = safe_resolve_path(path)
    ensure_parent_dir!(resolved)

    tmp_path = Path.join(Path.dirname(resolved), ".#{Path.basename(resolved)}.tmp")

    try do
      File.write!(tmp_path, data)
      File.rename!(tmp_path, resolved)
      :ok
    rescue
      e ->
        _ = File.rm(tmp_path)
        reraise e, __STACKTRACE__
    end
  end

  @doc """
  Writes a JSON-encodable term to a file atomically.

  ## Parameters

    * `path` - Target file path
    * `data` - Data to encode as JSON (must be JSON-serializable)
    * `opts` - Keyword options:
      - `:pretty` - Whether to pretty-print (default: `true`)

  ## Raises

    * `Jason.EncodeError` if data is not JSON-serializable
    * `File.Error` if the write fails
  """
  @spec atomic_write_json(Path.t(), term(), keyword()) :: :ok
  def atomic_write_json(path, data, opts \\ []) do
    pretty = Keyword.get(opts, :pretty, true)

    content =
      if pretty do
        Jason.encode!(data, pretty: true)
      else
        Jason.encode!(data)
      end

    atomic_write_text(path, content)
  end

  @doc """
  Reads a JSON file safely, returning `default` if the file doesn't exist
  or is invalid.

  ## Parameters

    * `path` - File path to read
    * `default` - Value to return if file doesn't exist or is invalid (default: `nil`)

  ## Returns

    Parsed JSON data or `default`
  """
  @spec read_json(Path.t(), term()) :: term()
  def read_json(path, default \\ nil) do
    resolved = safe_resolve_path(path)

    with true <- File.exists?(resolved),
         {:ok, content} <- File.read(resolved),
         {:ok, decoded} <- Jason.decode(content) do
      decoded
    else
      _ -> default
    end
  end

  @doc """
  Reads a file as binary safely, returning `default` if the file doesn't exist.

  ## Parameters

    * `path` - File path to read
    * `default` - Value to return if file doesn't exist (default: `nil`)

  ## Returns

    Binary content or `default`
  """
  @spec read_bytes(Path.t(), term()) :: term()
  def read_bytes(path, default \\ nil) do
    resolved = safe_resolve_path(path)

    case File.read(resolved) do
      {:ok, content} -> content
      _ -> default
    end
  end

  @doc """
  Creates a backup of a file by copying it to a timestamped backup path.

  ## Parameters

    * `path` - Path to the file to back up
    * `backup_dir` - Directory to store backups (default: `<parent_dir>/backups`)

  ## Returns

    `{:ok, backup_path}` on success, `{:error, reason}` on failure
  """
  @spec backup(Path.t(), Path.t() | nil) :: {:ok, Path.t()} | {:error, term()}
  def backup(path, backup_dir \\ nil) do
    resolved = safe_resolve_path(path)

    unless File.exists?(resolved) do
      {:error, :not_found}
    else
      dir = backup_dir || Path.join(Path.dirname(resolved), "backups")
      ensure_parent_dir!(dir)

      timestamp = DateTime.utc_now() |> DateTime.to_iso8601() |> String.replace(":", "-")
      basename = Path.basename(resolved)
      backup_path = Path.join(dir, "#{basename}.#{timestamp}.bak")

      case File.cp(resolved, backup_path) do
        :ok -> {:ok, backup_path}
        {:error, reason} -> {:error, reason}
      end
    end
  end

  @doc """
  Restores a file from a backup.

  ## Parameters

    * `backup_path` - Path to the backup file
    * `target_path` - Path to restore to (defaults to original path derived from backup name)

  ## Returns

    `:ok` on success, `{:error, reason}` on failure
  """
  @spec restore(Path.t(), Path.t() | nil) :: :ok | {:error, term()}
  def restore(backup_path, target_path \\ nil) do
    resolved_backup = safe_resolve_path(backup_path)

    unless File.exists?(resolved_backup) do
      {:error, :not_found}
    else
      target = target_path || derive_original_path(resolved_backup)
      resolved_target = safe_resolve_path(target)
      ensure_parent_dir!(resolved_target)

      File.cp(resolved_backup, resolved_target)
    end
  end

  @doc """
  Lists available backups for a given file.

  ## Parameters

    * `path` - Original file path
    * `backup_dir` - Backup directory (default: `<parent_dir>/backups`)

  ## Returns

    List of backup file paths, sorted newest-first
  """
  @spec list_backups(Path.t(), Path.t() | nil) :: [Path.t()]
  def list_backups(path, backup_dir \\ nil) do
    resolved = safe_resolve_path(path)
    dir = backup_dir || Path.join(Path.dirname(resolved), "backups")

    unless File.dir?(dir) do
      []
    else
      basename = Path.basename(resolved)
      _pattern = "#{basename}.*.bak"

      dir
      |> File.ls!()
      |> Enum.filter(&String.match?(&1, ~r/^#{Regex.escape(basename)}\.\d{4}-.*\.bak$/))
      |> Enum.map(&Path.join(dir, &1))
      |> Enum.sort_by(&File.stat!(&1, time: :mtime).mtime, :desc)
    end
  end

  # ── Private Helpers ──────────────────────────────────────────────────────

  defp normalize_path(path) do
    path |> to_string() |> String.trim_trailing("/")
  end

  defp ensure_parent_dir!(path) do
    parent = Path.dirname(path)

    unless File.dir?(parent) do
      File.mkdir_p!(parent)
    end

    :ok
  end

  defp derive_original_path(backup_path) do
    basename = Path.basename(backup_path)
    # Strip the .YYYY-MM-DDTHH-MM-SS.bak suffix
    original_name =
      basename
      |> String.replace(~r/\.[\dT\-]+\.bak$/, "")

    Path.join(Path.dirname(backup_path), original_name)
  end
end
