defmodule CodePuppyControl.SessionStorage do
  @moduledoc """
  Session CRUD, search, and export for Code Puppy with ETS caching,
  Phoenix PubSub notifications, and disk crash-survivability.

  ## Storage backends

  When running inside the OTP supervision tree, this module delegates to
  `SessionStorage.Store` which provides:

    - **ETS hot cache** for O(1) reads
    - **SQLite durable store** via `CodePuppyControl.Sessions`
    - **PubSub events** on session mutations (saved, deleted, cleaned)
    - **Terminal session recovery** after crashes

  Outside the OTP app (e.g. standalone scripts), falls back to file-based
  JSON storage via `SessionStorage.FileBackend`.

  Never writes to `~/.code_puppy/` — migration is via `SessionStorage.Migrator`.

  ## Crash-survivability

  The write-through ordering (SQLite → ETS → PubSub) guarantees that a
  crash mid-operation never leaves the cache ahead of disk. On restart,
  the ETS cache is rebuilt from SQLite (see `SessionStorage.Store`).

  ## Terminal session recovery

  Sessions with active terminals are tracked in ETS with metadata
  (cols, rows, shell). On crash recovery, `SessionStorage.TerminalRecovery`
  attempts to recreate PTY sessions for tracked terminals.

  (code_puppy-ctj.1): Port session_storage.py + session_storage_bridge.py
  to Elixir with PubSub + ETS + disk crash-survivability.
  """

  require Logger

  alias CodePuppyControl.SessionStorage.Format
  alias CodePuppyControl.SessionStorage.Store
  alias CodePuppyControl.SessionStorage.FileBackend

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type session_name :: String.t()
  @type message :: map()
  @type history :: [message()]
  @type compacted_hashes :: [String.t()]
  @type total_tokens :: non_neg_integer()

  @type session_metadata :: %{
          session_name: session_name(),
          timestamp: String.t(),
          message_count: non_neg_integer(),
          total_tokens: total_tokens(),
          auto_saved: boolean()
        }

  @type session_data :: %{
          format: String.t(),
          payload: %{
            messages: history(),
            compacted_hashes: compacted_hashes()
          },
          metadata: session_metadata()
        }

  # ---------------------------------------------------------------------------
  # Directory Management
  # ---------------------------------------------------------------------------

  @doc """
  Returns the base directory for Elixir session storage.

  Delegates to `FileBackend.base_dir/0`.
  """
  @spec base_dir :: Path.t()
  defdelegate base_dir, to: FileBackend

  @doc """
  Ensures the session storage directory exists.
  """
  @spec ensure_dir :: {:ok, Path.t()} | {:error, term()}
  def ensure_dir do
    dir = base_dir()

    case File.mkdir_p(dir) do
      :ok -> {:ok, dir}
      {:error, reason} -> {:error, reason}
    end
  end

  # ---------------------------------------------------------------------------
  # CRUD Operations
  # ---------------------------------------------------------------------------

  @doc """
  Saves a session (creates or updates).

  When the OTP Store is running, delegates to Store for ETS caching +
  PubSub notifications + SQLite persistence.
  Falls back to file-based JSON storage otherwise.

  Options: `:compacted_hashes`, `:total_tokens`, `:auto_saved`, `:timestamp`,
  `:base_dir`, `:has_terminal`, `:terminal_meta`.
  """
  @spec save_session(session_name(), history(), keyword()) ::
          {:ok, session_metadata()} | {:error, term()}
  def save_session(name, history, opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      save_via_store(name, history, opts)
    else
      FileBackend.save_session(name, history, opts)
    end
  end

  defp save_via_store(name, history, opts) do
    case Store.save_session(name, history, opts) do
      {:ok, result} ->
        {:ok,
         %{
           session_name: result.name,
           timestamp: result[:timestamp] || now_iso(),
           message_count: result.message_count,
           total_tokens: result.total_tokens,
           auto_saved: result[:auto_saved] || false
         }}

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Loads session messages and compacted hashes.

  Uses ETS cache (via Store) when available, falls back to file-based.
  Options: `:base_dir`.
  """
  @spec load_session(session_name(), keyword()) ::
          {:ok, %{messages: history(), compacted_hashes: compacted_hashes()}}
          | {:error, :not_found | term()}
  def load_session(name, opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      case Store.load_session(name) do
        {:ok, %{history: history, compacted_hashes: hashes}} ->
          {:ok, %{messages: history, compacted_hashes: hashes}}

        {:error, reason} ->
          {:error, reason}
      end
    else
      FileBackend.load_session(name, opts)
    end
  end

  @doc """
  Loads full session data including format and metadata.

  Uses ETS cache (via Store) when available, falls back to file-based.
  Options: `:base_dir`.
  """
  @spec load_session_full(session_name(), keyword()) ::
          {:ok, session_data()} | {:error, :not_found | term()}
  def load_session_full(name, opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      case Store.load_session_full(name) do
        {:ok, entry} ->
          {:ok,
           %{
             "format" => Format.current_format(),
             "payload" => %{
               "messages" => entry.history,
               "compacted_hashes" => entry.compacted_hashes
             },
             "metadata" => %{
               "session_name" => entry.name,
               "timestamp" => entry.timestamp,
               "message_count" => entry.message_count,
               "total_tokens" => entry.total_tokens,
               "auto_saved" => entry.auto_saved
             }
           }}

        {:error, reason} ->
          {:error, reason}
      end
    else
      FileBackend.load_session_full(name, opts)
    end
  end

  @doc """
  Updates session metadata fields.

  Options: `:auto_saved`, `:total_tokens`, `:timestamp`, `:base_dir`.
  """
  @spec update_session(session_name(), keyword()) ::
          {:ok, session_metadata()} | {:error, term()}
  def update_session(name, opts \\ []) do
    FileBackend.update_session(name, opts)
  end

  @doc """
  Deletes a session by name (idempotent).

  When the Store is available, deletes from SQLite + ETS + PubSub.
  Otherwise falls back to file-based deletion.
  Options: `:base_dir`.
  """
  @spec delete_session(session_name(), keyword()) :: :ok | {:error, term()}
  def delete_session(name, opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      Store.delete_session(name)
    else
      FileBackend.delete_session(name, opts)
    end
  end

  # ---------------------------------------------------------------------------
  # Listing & Search
  # ---------------------------------------------------------------------------

  @doc """
  Lists all session names sorted alphabetically.

  When the Store is available, reads from ETS (no disk I/O).
  Otherwise falls back to file-based listing.
  Options: `:base_dir`.
  """
  @spec list_sessions(keyword()) :: {:ok, [session_name()]} | {:error, term()}
  def list_sessions(opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      Store.list_sessions()
    else
      FileBackend.list_sessions(opts)
    end
  end

  @doc """
  Lists sessions with metadata, sorted newest-first.

  When the Store is available, reads from ETS.
  Otherwise falls back to file-based listing.
  Options: `:base_dir`.
  """
  @spec list_sessions_with_metadata(keyword()) :: {:ok, [session_metadata()]} | {:error, term()}
  def list_sessions_with_metadata(opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      case Store.list_sessions_with_metadata() do
        {:ok, entries} -> {:ok, Enum.map(entries, &store_entry_to_metadata/1)}
      end
    else
      FileBackend.list_sessions_with_metadata(opts)
    end
  end

  @doc """
  Searches sessions by filters.

  Options: `:name_pattern`, `:auto_saved`, `:min_tokens`, `:max_tokens`,
  `:since`, `:until`, `:base_dir`, `:limit`.
  """
  @spec search_sessions(keyword()) :: {:ok, [session_metadata()]} | {:error, term()}
  def search_sessions(opts \\ []) do
    FileBackend.search_sessions(opts)
  end

  # ---------------------------------------------------------------------------
  # Cleanup
  # ---------------------------------------------------------------------------

  @doc """
  Cleans up old sessions, keeping only the most recent N.

  When the Store is available, delegates for ETS + SQLite + PubSub.
  Options: `:base_dir`.
  """
  @spec cleanup_sessions(non_neg_integer(), keyword()) ::
          {:ok, [session_name()]} | {:error, term()}
  def cleanup_sessions(max_sessions, _opts \\ [])

  def cleanup_sessions(max_sessions, _opts) when max_sessions <= 0, do: {:ok, []}

  def cleanup_sessions(max_sessions, opts) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      Store.cleanup_sessions(max_sessions)
    else
      FileBackend.cleanup_sessions(max_sessions, opts)
    end
  end

  # ---------------------------------------------------------------------------
  # Export
  # ---------------------------------------------------------------------------

  @doc """
  Exports a session to JSON. Options: `:base_dir`, `:output_path`.
  """
  @spec export_session(session_name(), keyword()) ::
          {:ok, String.t() | Path.t()} | {:error, term()}
  def export_session(name, opts \\ []) do
    FileBackend.export_session(name, opts)
  end

  @doc """
  Exports all sessions as a JSON array. Options: `:base_dir`, `:output_path`.
  """
  @spec export_all_sessions(keyword()) ::
          {:ok, String.t() | Path.t()} | {:error, term()}
  def export_all_sessions(opts \\ []) do
    FileBackend.export_all_sessions(opts)
  end

  # ---------------------------------------------------------------------------
  # Async Autosave
  # ---------------------------------------------------------------------------

  @doc """
  Non-blocking version of `save_session/3`. Snapshots history immediately,
  submits the save to a background Task, and returns `:ok`.

  Same options as `save_session/3`.
  """
  @spec save_session_async(session_name(), history(), keyword()) :: :ok
  def save_session_async(name, history, opts \\ []) do
    history_snapshot = history

    case FileBackend.safe_resolve_base_dir(opts) do
      {:ok, dir} ->
        opts_with_dir = Keyword.put(opts, :base_dir, dir)

        _ =
          Task.start(fn ->
            case save_session(name, history_snapshot, opts_with_dir) do
              {:ok, _meta} ->
                mark_autosave_complete(history_snapshot)

              {:error, reason} ->
                Logger.warning("Async session save failed: #{inspect(reason)}")
            end
          end)

        :ok

      {:error, reason} ->
        Logger.warning(
          "Async session save skipped — failed to resolve base_dir: #{inspect(reason)}"
        )

        :ok
    end
  end

  @doc """
  Returns `true` if the autosave should be skipped.

  Delegates to `CodePuppyControl.SessionStorage.AutosaveTracker`.
  """
  @spec should_skip_autosave?(history()) :: boolean()
  def should_skip_autosave?(history) do
    CodePuppyControl.SessionStorage.AutosaveTracker.should_skip_autosave?(history)
  end

  @doc """
  Records that an autosave has completed.

  Delegates to `CodePuppyControl.SessionStorage.AutosaveTracker`.
  """
  @spec mark_autosave_complete(history()) :: :ok
  def mark_autosave_complete(history) do
    CodePuppyControl.SessionStorage.AutosaveTracker.mark_autosave_complete(history)
  end

  # ---------------------------------------------------------------------------
  # Terminal Session Tracking (code_puppy-ctj.1)
  # ---------------------------------------------------------------------------

  @doc """
  Registers a terminal session for crash recovery tracking.

  When a PTY terminal is attached to a session, this records the terminal
  metadata so that on crash/restart, `SessionStorage.TerminalRecovery`
  can attempt to recreate the PTY session.

  Durably persists to SQLite — terminal metadata survives node crashes.
  Returns `{:error, :session_not_found}` if the session does not exist.
  """
  @spec register_terminal(session_name(), map()) :: :ok | {:error, term()}
  def register_terminal(session_name, meta) do
    if store_available?() do
      Store.register_terminal(session_name, meta)
    else
      {:error, :store_not_available}
    end
  end

  @doc """
  Unregisters a terminal session from crash recovery tracking.

  Called when a terminal session is closed gracefully.
  Durably clears terminal metadata from SQLite.
  Returns `{:error, :session_not_found}` if the session does not exist.
  """
  @spec unregister_terminal(session_name()) :: :ok | {:error, term()}
  def unregister_terminal(session_name) do
    if store_available?() do
      Store.unregister_terminal(session_name)
    else
      {:error, :store_not_available}
    end
  end

  @doc """
  Lists all tracked terminal sessions (for crash recovery diagnostics).

  Returns an empty list if the Store is not running.
  """
  @spec list_terminal_sessions() :: [map()]
  def list_terminal_sessions do
    if store_available?() do
      Store.list_terminal_sessions()
    else
      []
    end
  end

  @doc """
  Subscribes the calling process to session lifecycle events via PubSub.

  Events: `{:session_saved, name, metadata}`, `{:session_deleted, name}`,
  `{:sessions_cleaned, deleted_names}`.

  No-op if the Store is not running.
  """
  @spec subscribe_sessions() :: :ok | {:error, term()}
  def subscribe_sessions do
    if store_available?() do
      Store.subscribe_sessions()
    else
      :ok
    end
  end

  @doc """
  Subscribes the calling process to terminal recovery events via PubSub.

  Events: `{:terminal_recovered, session_id, meta}`,
  `{:terminal_recovery_failed, session_id, reason}`,
  `{:terminal_registered, session_id}`,
  `{:terminal_unregistered, session_id}`.

  No-op if the Store is not running.
  """
  @spec subscribe_terminal() :: :ok | {:error, term()}
  def subscribe_terminal do
    if store_available?() do
      Store.subscribe_terminal()
    else
      :ok
    end
  end

  # ---------------------------------------------------------------------------
  # Utility
  # ---------------------------------------------------------------------------

  @doc """
  Checks if a session exists.

  When the Store is available, checks ETS (O(1), no disk I/O).
  Options: `:base_dir`.
  """
  @spec session_exists?(session_name(), keyword()) :: boolean()
  def session_exists?(name, opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      Store.session_exists?(name)
    else
      FileBackend.session_exists?(name, opts)
    end
  end

  @doc """
  Returns the count of stored sessions.

  When the Store is available, reads from ETS.
  Options: `:base_dir`.
  """
  @spec count_sessions(keyword()) :: non_neg_integer()
  def count_sessions(opts \\ []) do
    if store_available?() and not Keyword.has_key?(opts, :base_dir) do
      Store.count_sessions()
    else
      FileBackend.count_sessions(opts)
    end
  end

  # ---------------------------------------------------------------------------
  # Private Helpers
  # ---------------------------------------------------------------------------

  @spec store_available?() :: boolean()
  defp store_available? do
    Process.whereis(Store) != nil
  end

  @spec store_entry_to_metadata(map()) :: session_metadata()
  defp store_entry_to_metadata(entry) do
    %{
      session_name: entry.name,
      timestamp: entry.timestamp,
      message_count: entry.message_count,
      total_tokens: entry.total_tokens,
      auto_saved: entry.auto_saved
    }
  end

  defp now_iso do
    DateTime.utc_now() |> DateTime.to_iso8601()
  end
end
