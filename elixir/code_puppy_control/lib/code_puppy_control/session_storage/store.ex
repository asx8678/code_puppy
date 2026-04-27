defmodule CodePuppyControl.SessionStorage.Store do
  @moduledoc """
  ETS-backed session cache with PubSub events and disk crash-survivability.

  Write path (crash-safe): SQLite → ETS → PubSub.
  Read path: ETS (O(1)) → SQLite (cache miss).
  Recovery: rebuilds ETS from SQLite on init; terminal sessions handed
  to `TerminalRecovery` for PTY recreation.

  ETS tables: `:session_store_ets` (sessions), `:session_terminal_ets` (terminals).
  PubSub topics: `"sessions:events"`, `"terminal:recovery"`.

  Replaces Python `session_storage_bridge.py` pattern with ETS + PubSub
  on top of the existing SQLite backend. (code_puppy-ctj.1)
  """

  use GenServer

  require Logger

  alias CodePuppyControl.Sessions
  alias CodePuppyControl.SessionStorage.TerminalRecovery

  @pubsub CodePuppyControl.PubSub
  @sessions_topic "sessions:events"
  @terminal_topic "terminal:recovery"

  # ETS table names
  @session_table :session_store_ets
  @terminal_table :session_terminal_ets

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type session_name :: String.t()
  @type history :: [map()]
  @type compacted_hashes :: [String.t()]

  @type session_entry :: %{
          name: session_name(),
          history: history(),
          compacted_hashes: compacted_hashes(),
          total_tokens: non_neg_integer(),
          message_count: non_neg_integer(),
          auto_saved: boolean(),
          timestamp: String.t(),
          has_terminal: boolean(),
          terminal_meta: terminal_meta() | nil,
          updated_at: integer()
        }

  @type terminal_meta :: %{
          session_id: String.t(),
          cols: pos_integer(),
          rows: pos_integer(),
          shell: String.t() | nil,
          attached_at: integer()
        }

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @doc """
  Starts the SessionStorage Store GenServer.

  ## Options

    * `:name` — registration name (default: `__MODULE__`)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Saves a session with write-through: SQLite → ETS → PubSub.

  Crash-survivability: SQLite write must succeed before ETS/PubSub.

  Options: `:compacted_hashes`, `:total_tokens`, `:auto_saved`, `:timestamp`,
  `:has_terminal`, `:terminal_meta`.
  """
  @spec save_session(session_name(), history(), keyword()) ::
          {:ok, map()} | {:error, term()}
  def save_session(name, history, opts \\ []) do
    GenServer.call(__MODULE__, {:save_session, name, history, opts})
  end

  @doc """
  Loads a session (cache-first: ETS → SQLite fallback).

  Returns `{:ok, %{history: list(), compacted_hashes: list()}}` or
  `{:error, reason}`.
  """
  @spec load_session(session_name()) ::
          {:ok, %{history: history(), compacted_hashes: compacted_hashes()}}
          | {:error, term()}
  def load_session(name) do
    # Fast path: ETS lookup (no GenServer call needed for reads)
    case :ets.lookup(@session_table, name) do
      [{^name, entry}] ->
        {:ok, %{history: entry.history, compacted_hashes: entry.compacted_hashes}}

      [] ->
        # Cache miss: read from SQLite, populate ETS
        case Sessions.load_session(name) do
          {:ok, data} ->
            entry = session_data_to_entry(name, data)
            :ets.insert(@session_table, {name, entry})
            {:ok, data}

          {:error, reason} ->
            {:error, reason}
        end
    end
  end

  @doc """
  Loads a session with full metadata (cache-first).

  Returns the full session entry map including terminal metadata.
  """
  @spec load_session_full(session_name()) ::
          {:ok, session_entry()} | {:error, term()}
  def load_session_full(name) do
    case :ets.lookup(@session_table, name) do
      [{^name, entry}] ->
        {:ok, entry}

      [] ->
        case Sessions.load_session_full(name) do
          {:ok, session} ->
            entry = chat_session_to_entry(session)
            :ets.insert(@session_table, {name, entry})
            {:ok, entry}

          {:error, reason} ->
            {:error, reason}
        end
    end
  end

  @doc """
  Deletes a session with write-through.

  1. Delete from SQLite (durable)
  2. Remove from ETS
  3. Remove terminal tracking if present
  4. Broadcast deletion via PubSub
  """
  @spec delete_session(session_name()) :: :ok | {:error, term()}
  def delete_session(name) do
    GenServer.call(__MODULE__, {:delete_session, name})
  end

  @doc """
  Lists all session names from ETS (no disk access needed after init).
  """
  @spec list_sessions() :: {:ok, [session_name()]}
  def list_sessions do
    names =
      @session_table
      |> :ets.match({:"$1", :_})
      |> List.flatten()
      |> Enum.sort()

    {:ok, names}
  end

  @doc """
  Lists sessions with metadata from ETS.
  """
  @spec list_sessions_with_metadata() :: {:ok, [session_entry()]}
  def list_sessions_with_metadata do
    entries =
      @session_table
      |> :ets.tab2list()
      |> Enum.map(fn {_name, entry} -> entry end)
      |> Enum.sort_by(& &1.timestamp, :desc)

    {:ok, entries}
  end

  @doc """
  Cleans up old sessions, keeping only the most recent N.

  Uses timestamp-based ordering from ETS metadata.
  """
  @spec cleanup_sessions(non_neg_integer()) :: {:ok, [session_name()]}
  def cleanup_sessions(max_sessions) do
    GenServer.call(__MODULE__, {:cleanup_sessions, max_sessions})
  end

  @doc """
  Checks if a session exists in ETS (fast, no disk access).
  """
  @spec session_exists?(session_name()) :: boolean()
  def session_exists?(name) do
    :ets.member(@session_table, name)
  end

  @doc """
  Returns the count of sessions from ETS.
  """
  @spec count_sessions() :: non_neg_integer()
  def count_sessions do
    :ets.info(@session_table, :size)
  end

  # ---------------------------------------------------------------------------
  # Terminal Session Tracking
  # ---------------------------------------------------------------------------

  @doc """
  Registers a terminal session for crash recovery.

  Records metadata (cols, rows, shell, attached_at) so TerminalRecovery
  can recreate the PTY on crash/restart.
  """
  @spec register_terminal(session_name(), terminal_meta()) :: :ok
  def register_terminal(session_name, meta) do
    GenServer.call(__MODULE__, {:register_terminal, session_name, meta})
  end

  @doc """
  Unregisters a terminal session. Called on graceful close.
  """
  @spec unregister_terminal(session_name()) :: :ok
  def unregister_terminal(session_name) do
    GenServer.call(__MODULE__, {:unregister_terminal, session_name})
  end

  @doc """
  Lists all tracked terminal sessions (for crash recovery).
  """
  @spec list_terminal_sessions() :: [terminal_meta()]
  def list_terminal_sessions do
    @terminal_table
    |> :ets.tab2list()
    |> Enum.map(fn {_name, meta} -> meta end)
  end

  @doc """
  Returns the PubSub topic for session events.
  """
  @spec sessions_topic() :: String.t()
  def sessions_topic, do: @sessions_topic

  @doc """
  Returns the PubSub topic for terminal recovery events.
  """
  @spec terminal_topic() :: String.t()
  def terminal_topic, do: @terminal_topic

  @doc """
  Subscribes to session lifecycle events via PubSub.

  Events: `{:session_saved, name, meta}`, `{:session_deleted, name}`,
  `{:sessions_cleaned, deleted_names}`.
  """
  @spec subscribe_sessions() :: :ok | {:error, term()}
  def subscribe_sessions do
    Phoenix.PubSub.subscribe(@pubsub, @sessions_topic)
  end

  @doc """
  Subscribes to terminal recovery events via PubSub.

  Events: `{:terminal_recovered, id, meta}`, `{:terminal_recovery_failed, id, reason}`,
  `{:terminal_registered, id}`, `{:terminal_unregistered, id}`.
  """
  @spec subscribe_terminal() :: :ok | {:error, term()}
  def subscribe_terminal do
    Phoenix.PubSub.subscribe(@pubsub, @terminal_topic)
  end

  # ---------------------------------------------------------------------------
  # Server Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(opts) do
    # Create ETS tables (owner is this GenServer; tables survive as long as
    # the process lives and are automatically destroyed on termination)
    session_table =
      :ets.new(@session_table, [
        :named_table,
        :set,
        :public,
        read_concurrency: true,
        write_concurrency: true
      ])

    terminal_table =
      :ets.new(@terminal_table, [
        :named_table,
        :set,
        :public,
        read_concurrency: true,
        write_concurrency: true
      ])

    # Recovery: rebuild ETS from SQLite
    recovered = recover_from_disk()

    # Terminal session recovery: identify sessions that had active terminals
    # at crash time and trigger recovery
    terminal_sessions = recover_terminal_sessions()

    Logger.info(
      "SessionStorage.Store initialized: #{recovered} sessions recovered, " <>
        "#{length(terminal_sessions)} terminal sessions pending recovery"
    )

    {:ok,
     %{
       session_table: session_table,
       terminal_table: terminal_table,
       opts: opts
     }}
  end

  @impl true
  def handle_call({:save_session, name, history, opts}, _from, state) do
    compacted_hashes = Keyword.get(opts, :compacted_hashes, [])
    total_tokens = Keyword.get(opts, :total_tokens, 0)
    auto_saved = Keyword.get(opts, :auto_saved, false)
    timestamp = Keyword.get(opts, :timestamp, now_iso())
    has_terminal = Keyword.get(opts, :has_terminal, false)
    terminal_meta = Keyword.get(opts, :terminal_meta)

    # 1. Persist to SQLite (durable — crash-survivability)
    case Sessions.save_session(name, history,
           compacted_hashes: compacted_hashes,
           total_tokens: total_tokens,
           auto_saved: auto_saved,
           timestamp: timestamp
         ) do
      {:ok, session} ->
        # 2. Update ETS cache (only after durable write succeeds)
        entry =
          build_entry(
            name,
            history,
            compacted_hashes,
            total_tokens,
            auto_saved,
            timestamp,
            has_terminal,
            terminal_meta
          )

        :ets.insert(@session_table, {name, entry})

        # 3. Broadcast via PubSub
        Phoenix.PubSub.broadcast(
          @pubsub,
          @sessions_topic,
          {:session_saved, name, Map.drop(entry, [:history])}
        )

        # Step 4: Track terminal metadata if present
        if has_terminal && terminal_meta do
          :ets.insert(@terminal_table, {name, terminal_meta})
        end

        {:reply, {:ok, session_to_result(session)}, state}

      {:error, reason} ->
        # Durable write failed — no ETS update, no broadcast
        Logger.error("Session save failed for #{name}: #{inspect(reason)}")
        {:reply, {:error, reason}, state}
    end
  end

  @impl true
  def handle_call({:delete_session, name}, _from, state) do
    # Step 1: Delete from SQLite (durable)
    :ok = Sessions.delete_session(name)

    # Step 2: Remove from ETS
    :ets.delete(@session_table, name)
    # Remove terminal tracking
    had_terminal = match?([{^name, _}], :ets.lookup(@terminal_table, name))
    :ets.delete(@terminal_table, name)
    # Broadcast deletion
    Phoenix.PubSub.broadcast(@pubsub, @sessions_topic, {:session_deleted, name})

    if had_terminal do
      Phoenix.PubSub.broadcast(@pubsub, @terminal_topic, {:terminal_unregistered, name})
    end

    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:cleanup_sessions, max_sessions}, _from, state) do
    all_entries =
      @session_table
      |> :ets.tab2list()
      |> Enum.map(fn {_, e} -> e end)
      |> Enum.sort_by(& &1.timestamp, :asc)

    if length(all_entries) <= max_sessions do
      {:reply, {:ok, []}, state}
    else
      to_delete = Enum.drop(all_entries, max_sessions)
      deleted = Enum.map(to_delete, & &1.name)
      Enum.each(deleted, &Sessions.delete_session/1)

      Enum.each(deleted, fn n ->
        :ets.delete(@session_table, n)
        :ets.delete(@terminal_table, n)
      end)

      Phoenix.PubSub.broadcast(@pubsub, @sessions_topic, {:sessions_cleaned, deleted})
      {:reply, {:ok, deleted}, state}
    end
  end

  @impl true
  def handle_call({:register_terminal, session_name, meta}, _from, state) do
    # Update ETS tracking
    :ets.insert(@terminal_table, {session_name, meta})

    # Mark the session entry as having a terminal
    case :ets.lookup(@session_table, session_name) do
      [{^session_name, entry}] ->
        updated = %{entry | has_terminal: true, terminal_meta: meta}
        :ets.insert(@session_table, {session_name, updated})

      [] ->
        :ok
    end

    # Broadcast terminal registration
    Phoenix.PubSub.broadcast(
      @pubsub,
      @terminal_topic,
      {:terminal_registered, session_name}
    )

    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:unregister_terminal, session_name}, _from, state) do
    # Remove from terminal tracking
    :ets.delete(@terminal_table, session_name)

    # Update session entry
    case :ets.lookup(@session_table, session_name) do
      [{^session_name, entry}] ->
        updated = %{entry | has_terminal: false, terminal_meta: nil}
        :ets.insert(@session_table, {session_name, updated})

      [] ->
        :ok
    end

    # Broadcast terminal unregistration
    Phoenix.PubSub.broadcast(
      @pubsub,
      @terminal_topic,
      {:terminal_unregistered, session_name}
    )

    {:reply, :ok, state}
  end

  # ---------------------------------------------------------------------------
  # Recovery
  # ---------------------------------------------------------------------------

  # Rebuild ETS cache from SQLite on startup (crash recovery).
  # Returns the number of sessions recovered.
  defp recover_from_disk do
    case Sessions.list_sessions_with_metadata() do
      {:ok, sessions} ->
        count =
          Enum.reduce(sessions, 0, fn session, acc ->
            entry = chat_session_to_entry(session)
            :ets.insert(@session_table, {session.name, entry})
            acc + 1
          end)

        Logger.info("SessionStorage.Store: recovered #{count} sessions from SQLite")
        count

      {:error, reason} ->
        Logger.warning(
          "SessionStorage.Store: failed to recover sessions from SQLite: #{inspect(reason)}"
        )

        0
    end
  end

  # Identify terminal sessions that need recovery and hand off to
  # TerminalRecovery module.
  defp recover_terminal_sessions do
    terminal_entries =
      @session_table
      |> :ets.tab2list()
      |> Enum.filter(fn {_name, entry} -> entry.has_terminal end)
      |> Enum.map(fn {_name, entry} -> entry end)

    if length(terminal_entries) > 0 do
      Logger.info(
        "SessionStorage.Store: #{length(terminal_entries)} terminal sessions pending recovery"
      )

      # Delegate recovery to TerminalRecovery module (async)
      TerminalRecovery.recover_sessions(terminal_entries)
    end

    terminal_entries
  end

  # ---------------------------------------------------------------------------
  # Child Spec
  # ---------------------------------------------------------------------------

  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker
    }
  end

  # ---------------------------------------------------------------------------
  # Private Helpers
  # ---------------------------------------------------------------------------

  defp now_iso, do: DateTime.utc_now() |> DateTime.to_iso8601()

  defp build_entry(
         name,
         history,
         compacted_hashes,
         total_tokens,
         auto_saved,
         timestamp,
         has_terminal,
         terminal_meta
       ) do
    %{
      name: name,
      history: history,
      compacted_hashes: compacted_hashes,
      total_tokens: total_tokens,
      message_count: length(history),
      auto_saved: auto_saved,
      timestamp: timestamp,
      has_terminal: has_terminal,
      terminal_meta: terminal_meta,
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  # Convert a Sessions.ChatSession map to a session entry for ETS.
  defp chat_session_to_entry(session) when is_map(session) do
    %{
      name: Map.get(session, :name, Map.get(session, "name", "")),
      history: Map.get(session, :history, Map.get(session, "history", [])),
      compacted_hashes:
        Map.get(session, :compacted_hashes, Map.get(session, "compacted_hashes", [])),
      total_tokens: Map.get(session, :total_tokens, Map.get(session, "total_tokens", 0)),
      message_count: Map.get(session, :message_count, Map.get(session, "message_count", 0)),
      auto_saved: Map.get(session, :auto_saved, Map.get(session, "auto_saved", false)),
      timestamp: Map.get(session, :timestamp, Map.get(session, "timestamp", "")),
      has_terminal: Map.get(session, :has_terminal, false),
      terminal_meta: Map.get(session, :terminal_meta),
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  # Convert session data from Sessions.load_session to an ETS entry.
  defp session_data_to_entry(name, data) do
    %{
      name: name,
      history: Map.get(data, :history, []),
      compacted_hashes: Map.get(data, :compacted_hashes, []),
      total_tokens: 0,
      message_count: length(Map.get(data, :history, [])),
      auto_saved: false,
      timestamp: "",
      has_terminal: false,
      terminal_meta: nil,
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  # Convert a ChatSession struct to a result map matching Sessions API.
  defp session_to_result(session) do
    %{
      name: session.name,
      message_count: session.message_count,
      total_tokens: session.total_tokens,
      auto_saved: session.auto_saved,
      timestamp: session.timestamp
    }
  end
end
