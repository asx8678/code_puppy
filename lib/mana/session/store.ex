defmodule Mana.Session.Store do
  @moduledoc """
  GenServer + ETS for session history management.

  ## Features

  - Fast concurrent reads via ETS
  - Session history storage with bounded size
  - O(1) message append using queue data structure
  - JSON persistence to disk
  - Session creation, deletion, and listing

  ## Configuration

  - `:max_history_size` - Maximum number of messages to keep per session.
    Default: 100. Set via `config :mana, Mana.Session.Store, max_history_size: 100`

  ## State Structure

  - `sessions`: Map of session_id => {queue, count}
  - `active_session`: Currently active session id or nil

  ## Usage

      # Start the store
      Mana.Session.Store.start_link([])

      # Create a new session
      session_id = Mana.Session.Store.create_session()

      # Append a message
      Mana.Session.Store.append(session_id, %{role: "user", content: "Hello"})

      # Get history
      history = Mana.Session.Store.get_history(session_id)

      # Save to disk
      Mana.Session.Store.save(session_id)

      # Load from disk
      Mana.Session.Store.load(session_id)
  """

  use GenServer

  require Logger

  alias Mana.Config.Paths

  @table :mana_sessions
  @default_max_history_size 100
  @compaction_threshold 200

  # Client API

  @doc """
  Starts the Session Store GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child specification for supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Creates a new session and returns its ID (alias for create_session/0).
  """
  @spec create_session() :: String.t()
  def create_session do
    GenServer.call(__MODULE__, :create_session)
  end

  @doc """
  Gets a session by ID, returning its message history (alias for get_history/1).
  """
  @spec get_session(String.t()) :: [map()]
  def get_session(session_id) do
    get_history(session_id)
  end

  @doc """
  Gets message history for a session.
  Returns messages in chronological order (oldest first).
  """
  @spec get_history(String.t()) :: [map()]
  def get_history(session_id) do
    case :ets.lookup(@table, session_id) do
      # Queue stores newest first, so reverse to get chronological order
      [{^session_id, {queue, _count}}] -> :queue.to_list(queue) |> Enum.reverse()
      [] -> []
    end
  end

  @doc """
  Appends a message to a session's history.
  """
  @spec append(String.t(), map()) :: :ok
  def append(session_id, message) do
    GenServer.call(__MODULE__, {:append, session_id, message})
  end

  @doc """
  Clears all messages from a session.
  """
  @spec clear(String.t()) :: :ok
  def clear(session_id) do
    GenServer.call(__MODULE__, {:clear, session_id})
  end

  @doc """
  Saves a session to disk.
  """
  @spec save(String.t()) :: :ok | {:error, term()}
  def save(session_id) do
    GenServer.call(__MODULE__, {:save, session_id})
  end

  @doc """
  Loads a session from disk.
  """
  @spec load(String.t()) :: {:ok, [map()]} | {:error, term()}
  def load(session_id) do
    GenServer.call(__MODULE__, {:load, session_id})
  end

  @doc """
  Lists all available session IDs.
  """
  @spec list_sessions() :: [String.t()]
  def list_sessions do
    GenServer.call(__MODULE__, :list_sessions)
  end

  @doc """
  Deletes a session from memory and disk.
  """
  @spec delete_session(String.t()) :: :ok | {:error, term()}
  def delete_session(session_id) do
    GenServer.call(__MODULE__, {:delete, session_id})
  end

  @doc """
  Gets the currently active session ID.
  """
  @spec active_session() :: String.t() | nil
  def active_session do
    GenServer.call(__MODULE__, :active_session)
  end

  @doc """
  Sets the active session ID.
  """
  @spec set_active_session(String.t() | nil) :: :ok
  def set_active_session(session_id) do
    GenServer.call(__MODULE__, {:set_active, session_id})
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    # Create ETS table with public access for fast reads
    :ets.new(@table, [
      :set,
      :named_table,
      :public,
      read_concurrency: true
    ])

    # Ensure directories exist
    Paths.ensure_dirs()

    # Defer disk I/O to handle_continue so init doesn't block
    {:ok, %{sessions: %{}, active_session: nil}, {:continue, :load_sessions}}
  end

  @impl true
  def handle_continue(:load_sessions, state) do
    sessions = load_all_sessions()

    Enum.each(sessions, fn {id, {queue, count}} ->
      :ets.insert(@table, {id, {queue, count}})
    end)

    {:noreply, %{state | sessions: sessions}}
  end

  @impl true
  def handle_call(:create_session, _from, state) do
    session_id = generate_session_id()
    # Store as {queue, count} tuple
    :ets.insert(@table, {session_id, {:queue.new(), 0}})
    {:reply, session_id, %{state | active_session: session_id}}
  end

  @impl true
  def handle_call({:append, session_id, message}, _from, state) do
    # Get current queue and count from ETS
    {queue, count} =
      case :ets.lookup(@table, session_id) do
        [{^session_id, {existing_queue, existing_count}}] -> {existing_queue, existing_count}
        [] -> {:queue.new(), 0}
      end

    # Normalize message keys via Mana.Message, preserving all fields
    normalized = Mana.Message.normalize_keys(message)

    message_with_timestamp =
      Map.put(normalized, :timestamp, System.system_time(:millisecond))

    max_size = max_history_size()

    # Add message to front of queue (O(1) operation)
    # We store in reverse order (newest first) for efficient append
    new_queue = :queue.in_r(message_with_timestamp, queue)
    new_count = count + 1

    # Trim old messages if over limit (remove from back of queue)
    {trimmed_queue, trimmed_count} =
      if new_count > max_size do
        {{:value, _}, q} = :queue.out(new_queue)
        {q, new_count - 1}
      else
        {new_queue, new_count}
      end

    # Check if compaction is needed (history grew too large)
    final_queue =
      if count > @compaction_threshold do
        compact_queue(trimmed_queue, max_size)
      else
        trimmed_queue
      end

    # Update ETS
    :ets.insert(@table, {session_id, {final_queue, trimmed_count}})

    # Update state (keep the queue in state too for consistency)
    new_sessions = Map.put(state.sessions, session_id, {final_queue, trimmed_count})

    {:reply, :ok, %{state | sessions: new_sessions}}
  end

  @impl true
  def handle_call({:clear, session_id}, _from, state) do
    # Check if session exists first (safe for non-existent sessions)
    case :ets.lookup(@table, session_id) do
      [{^session_id, _data}] ->
        # Session exists - reset to empty queue with count 0
        :ets.insert(@table, {session_id, {:queue.new(), 0}})
        # Update internal state to maintain consistency
        new_sessions = Map.put(state.sessions, session_id, {:queue.new(), 0})
        {:reply, :ok, %{state | sessions: new_sessions}}

      [] ->
        # Session doesn't exist - safe no-op
        {:reply, :ok, state}
    end
  end

  @impl true
  def handle_call({:save, session_id}, _from, state) do
    result = save_session_to_disk(session_id)
    {:reply, result, state}
  end

  @impl true
  def handle_call({:load, session_id}, _from, state) do
    result = load_session_from_disk(session_id)

    new_state =
      case result do
        {:ok, messages} ->
          # Convert list to queue (reverse to store newest first)
          queue = :queue.from_list(Enum.reverse(messages))
          count = length(messages)
          :ets.insert(@table, {session_id, {queue, count}})
          %{state | sessions: Map.put(state.sessions, session_id, {queue, count})}

        _ ->
          state
      end

    {:reply, result, new_state}
  end

  @impl true
  def handle_call(:list_sessions, _from, state) do
    disk_sessions = list_sessions_from_disk()
    memory_sessions = :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}])
    all_sessions = Enum.uniq(disk_sessions ++ memory_sessions) |> Enum.sort()
    {:reply, all_sessions, state}
  end

  @impl true
  def handle_call({:delete, session_id}, _from, state) do
    # Remove from ETS
    :ets.delete(@table, session_id)

    # Remove from disk
    file_path = session_file_path(session_id)
    File.rm(file_path)

    new_active =
      if state.active_session == session_id, do: nil, else: state.active_session

    {:reply, :ok, %{state | active_session: new_active}}
  end

  @impl true
  def handle_call(:active_session, _from, state) do
    {:reply, state.active_session, state}
  end

  @impl true
  def handle_call({:set_active, session_id}, _from, state) do
    # Validate session exists
    valid_session =
      if session_id == nil do
        nil
      else
        case :ets.lookup(@table, session_id) do
          [{^session_id, _}] -> session_id
          [] -> state.active_session
        end
      end

    {:reply, :ok, %{state | active_session: valid_session}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[Mana.Session.Store] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # Private Functions

  defp generate_session_id do
    timestamp = DateTime.utc_now() |> DateTime.to_unix(:millisecond)
    random = :rand.uniform(999_999)
    "session_#{timestamp}_#{random}"
  end

  defp session_file_path(session_id) do
    Path.join(Paths.sessions_dir(), "#{session_id}.json")
  end

  defp load_all_sessions do
    sessions_dir = Paths.sessions_dir()

    case File.ls(sessions_dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".json"))
        |> Enum.map(&load_session_entry(&1, sessions_dir))
        |> Map.new()

      _ ->
        %{}
    end
  end

  defp load_session_entry(file, sessions_dir) do
    id = String.replace_suffix(file, ".json", "")
    file_path = Path.join(sessions_dir, file)
    {queue, count} = load_session_messages(file_path)
    {id, {queue, count}}
  end

  defp load_session_messages(file_path) do
    case File.read(file_path) do
      {:ok, contents} -> decode_messages(contents)
      _ -> {:queue.new(), 0}
    end
  end

  defp decode_messages(contents) do
    case Jason.decode(contents) do
      {:ok, data} when is_list(data) ->
        messages = Mana.Message.normalize_list(data)
        # Store in reverse order (newest first) for efficient append
        queue = :queue.from_list(Enum.reverse(messages))
        count = length(messages)
        {queue, count}

      _ ->
        {:queue.new(), 0}
    end
  end

  defp list_sessions_from_disk do
    sessions_dir = Paths.sessions_dir()

    case File.ls(sessions_dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".json"))
        |> Enum.map(&String.replace_suffix(&1, ".json", ""))

      _ ->
        []
    end
  end

  defp save_session_to_disk(session_id) do
    {queue, _count} =
      case :ets.lookup(@table, session_id) do
        [{^session_id, data}] -> data
        [] -> {:queue.new(), 0}
      end

    # Convert queue to list (messages are stored newest-first, so reverse for disk)
    messages = :queue.to_list(queue) |> Enum.reverse()

    file_path = session_file_path(session_id)

    case Jason.encode(messages, pretty: true) do
      {:ok, json} ->
        File.write(file_path, json)

      error ->
        error
    end
  end

  defp load_session_from_disk(session_id) do
    file_path = session_file_path(session_id)

    case File.read(file_path) do
      {:ok, contents} ->
        case Jason.decode(contents) do
          {:ok, messages} when is_list(messages) ->
            # Normalize keys to atoms via Mana.Message
            {:ok, Mana.Message.normalize_list(messages)}

          _ ->
            {:error, :invalid_format}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Returns the maximum history size from config or default.
  """
  @spec max_history_size() :: non_neg_integer()
  def max_history_size do
    Application.get_env(:mana, __MODULE__, [])
    |> Keyword.get(:max_history_size, @default_max_history_size)
  end

  @doc """
  Compacts a queue to the specified maximum size by dropping oldest items.
  Used for memory optimization when history grows too large.
  """
  @spec compact_queue(:queue.queue(), non_neg_integer()) :: :queue.queue()
  def compact_queue(queue, max_size) do
    queue_length = :queue.len(queue)

    if queue_length <= max_size do
      queue
    else
      # Need to drop oldest items from the back of the queue
      to_drop = queue_length - max_size
      drop_from_back(queue, to_drop)
    end
  end

  # Helper to drop N items from the back (oldest) of the queue
  defp drop_from_back(queue, 0), do: queue

  defp drop_from_back(queue, n) when n > 0 do
    case :queue.out(queue) do
      {{:value, _}, rest} -> drop_from_back(rest, n - 1)
      {:empty, _} -> queue
    end
  end
end
