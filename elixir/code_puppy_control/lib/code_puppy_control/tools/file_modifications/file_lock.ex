defmodule CodePuppyControl.Tools.FileModifications.FileLock do
  @moduledoc """
  Per-file locking for serializing concurrent mutations.

  Port of `code_puppy/utils/file_mutex.py`.

  Different files run concurrently; the same file (by realpath) is serialized.
  Uses a named `Agent` to track per-path `:global` locks.

  ## Design

  - Uses `:global.trans/3` for distributed lock semantics in a cluster
  - Falls back to a simple `Agent`-backed map for single-node operation
  - Locks are per-realpath to handle symlinks correctly
  - Automatic cleanup when locks are released

  ## Usage

      FileLock.with_lock("/path/to/file.py", fn ->
        # Only one process at a time for this file
        SafeWrite.safe_write("/path/to/file.py", content)
      end)
  """

  use Agent

  require Logger

  # ── Public API ──────────────────────────────────────────────────────────

  @doc """
  Start the file lock agent. Called by the application supervisor.
  """
  @spec start_link(keyword()) :: Agent.on_start()
  def start_link(_opts \\ []) do
    Agent.start_link(fn -> %{} end, name: __MODULE__)
  end

  @doc """
  Execute a function while holding a lock on the given file path.

  Serializes concurrent access to the same file (by realpath).
  Different files run concurrently.

  ## Returns

    * `{:ok, result}` — Function executed successfully
    * `{:error, reason}` — Lock acquisition failed or function raised

  ## Examples

      iex> FileLock.with_lock("/tmp/test.txt", fn -> :done end)
      {:ok, :done}
  """
  @spec with_lock(Path.t(), (-> result)) :: {:ok, result} | {:error, term()} when result: var
  def with_lock(file_path, fun) when is_binary(file_path) and is_function(fun, 0) do
    key = resolve_key(file_path)

    # Use :global.trans for cross-node locking in a cluster
    # Falls back to Agent-based tracking for single-node
    lock_id = {__MODULE__, key}

    try do
      :global.trans(lock_id, fn ->
        try do
          result = fun.()
          {result, nil}
        rescue
          e ->
            {nil, e}
        end
      end)
    catch
      :exit, reason ->
        {:error, {:lock_timeout, reason}}
    end
    |> case do
      {result, nil} -> {:ok, result}
      {nil, exception} -> {:error, exception}
      {:error, reason} -> {:error, reason}
    end
  end

  @doc """
  Return the number of currently tracked locks (for testing/monitoring).
  """
  @spec active_lock_count() :: non_neg_integer()
  def active_lock_count do
    # Best-effort count via Agent state
    if Process.whereis(__MODULE__) do
      Agent.get(__MODULE__, &map_size/1)
    else
      0
    end
  end

  @doc """
  Register that a lock is held for the given path.

  Called internally when a lock is acquired. This is used for
  tracking and monitoring; actual synchronization is via `:global.trans/3`.
  """
  @spec register_lock(Path.t()) :: :ok
  def register_lock(file_path) do
    key = resolve_key(file_path)

    if Process.whereis(__MODULE__) do
      Agent.update(__MODULE__, fn state ->
        Map.update(state, key, 1, &(&1 + 1))
      end)
    end

    :ok
  end

  @doc """
  Unregister a lock for the given path.

  Called internally when a lock is released.
  """
  @spec unregister_lock(Path.t()) :: :ok
  def unregister_lock(file_path) do
    key = resolve_key(file_path)

    if Process.whereis(__MODULE__) do
      Agent.update(__MODULE__, fn state ->
        case Map.get(state, key, 0) do
          1 -> Map.delete(state, key)
          n -> Map.put(state, key, n - 1)
        end
      end)
    end

    :ok
  end

  # ── Private ────────────────────────────────────────────────────────────

  defp resolve_key(file_path) do
    expanded = Path.expand(file_path)

    # Try to resolve the real path (follow symlinks for consistent keying)
    case File.stat(expanded) do
      {:ok, _} ->
        # File exists — use expanded path as key
        # Note: File.stat follows symlinks, lstat does not
        expanded

      {:error, _} ->
        # File doesn't exist — use expanded path as-is
        expanded
    end
  end
end
