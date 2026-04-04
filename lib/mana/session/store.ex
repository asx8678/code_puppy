defmodule Mana.Session.Store do
  @moduledoc """
  GenServer + ETS for session history management.

  ## Features

  - Fast concurrent reads via ETS
  - Session history storage
  - JSON persistence to disk
  - Session creation, deletion, and listing

  ## State Structure

  - `sessions`: Map of session_id => [messages]
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
  Creates a new session and returns its ID.
  """
  @spec create_session() :: String.t()
  def create_session do
    GenServer.call(__MODULE__, :create_session)
  end

  @doc """
  Gets message history for a session.
  """
  @spec get_history(String.t()) :: [map()]
  def get_history(session_id) do
    case :ets.lookup(@table, session_id) do
      [{^session_id, messages}] -> messages
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
  @spec load(String.t()) :: :ok | {:error, term()}
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

    # Load existing sessions from disk
    sessions = load_all_sessions()

    # Populate ETS
    Enum.each(sessions, fn {id, messages} ->
      :ets.insert(@table, {id, messages})
    end)

    {:ok, %{sessions: sessions, active_session: nil}}
  end

  @impl true
  def handle_call(:create_session, _from, state) do
    session_id = generate_session_id()
    :ets.insert(@table, {session_id, []})

    new_sessions = Map.put(state.sessions, session_id, [])
    new_state = %{state | sessions: new_sessions, active_session: session_id}

    {:reply, session_id, new_state}
  end

  @impl true
  def handle_call({:append, session_id, message}, _from, state) do
    # Get current messages from ETS
    messages =
      case :ets.lookup(@table, session_id) do
        [{^session_id, existing}] -> existing
        [] -> []
      end

    # Normalize message keys and add timestamp
    normalized =
      %{
        role: message[:role] || message["role"],
        content: message[:content] || message["content"]
      }

    message_with_timestamp =
      Map.put(normalized, :timestamp, System.system_time(:millisecond))

    new_messages = messages ++ [message_with_timestamp]

    # Update ETS
    :ets.insert(@table, {session_id, new_messages})

    # Update state
    new_sessions = Map.put(state.sessions, session_id, new_messages)

    {:reply, :ok, %{state | sessions: new_sessions}}
  end

  @impl true
  def handle_call({:clear, session_id}, _from, state) do
    :ets.insert(@table, {session_id, []})
    new_sessions = Map.put(state.sessions, session_id, [])
    {:reply, :ok, %{state | sessions: new_sessions}}
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
          :ets.insert(@table, {session_id, messages})
          %{state | sessions: Map.put(state.sessions, session_id, messages)}

        _ ->
          state
      end

    {:reply, result, new_state}
  end

  @impl true
  def handle_call(:list_sessions, _from, state) do
    # Get from disk as well to show all available sessions
    disk_sessions = list_sessions_from_disk()
    memory_sessions = Map.keys(state.sessions)
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

    # Update state
    new_sessions = Map.delete(state.sessions, session_id)

    new_active =
      if state.active_session == session_id do
        nil
      else
        state.active_session
      end

    {:reply, :ok, %{state | sessions: new_sessions, active_session: new_active}}
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
    messages = load_session_messages(file_path)
    {id, messages}
  end

  defp load_session_messages(file_path) do
    case File.read(file_path) do
      {:ok, contents} -> decode_messages(contents)
      _ -> []
    end
  end

  defp decode_messages(contents) do
    case Jason.decode(contents) do
      {:ok, data} when is_list(data) -> Enum.map(data, &normalize_message_keys/1)
      _ -> []
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
    messages =
      case :ets.lookup(@table, session_id) do
        [{^session_id, msgs}] -> msgs
        [] -> []
      end

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
            # Normalize keys to atoms
            normalized = Enum.map(messages, &normalize_message_keys/1)
            {:ok, normalized}

          _ ->
            {:error, :invalid_format}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp normalize_message_keys(message) when is_map(message) do
    %{
      role: message["role"],
      content: message["content"],
      timestamp: message["timestamp"]
    }
  end

  defp normalize_message_keys(_), do: %{role: nil, content: nil, timestamp: nil}
end
