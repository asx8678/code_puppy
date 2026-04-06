defmodule Mana.Tools.Terminal.PtyManager do
  @moduledoc """
  GenServer that manages PTY terminal sessions via DynamicSupervisor.

  Provides a central API for creating, interacting with, and destroying
  terminal sessions. Each session is a `Mana.Tools.Terminal.Session`
  GenServer running under `Mana.Terminal.SessionSupervisor`.

  ## Architecture

  ```
  ┌───────────────────────────────┐
  │       PtyManager              │
  │       (GenServer)             │
  └──────────┬────────────────────┘
             │
             │  DynamicSupervisor
             │
  ┌──────────▼────────────────────┐
  │  Mana.Terminal.SessionSupervisor │
  │  (DynamicSupervisor)           │
  │                                │
  │  ┌─ Session "sess_1" ──────┐  │
  │  │  GenServer + Port       │  │
  │  └─────────────────────────┘  │
  │  ┌─ Session "sess_2" ──────┐  │
  │  │  GenServer + Port       │  │
  │  └─────────────────────────┘  │
  └────────────────────────────────┘
  ```

  ## Registry

  Sessions are registered in `Mana.Terminal.SessionRegistry` for fast
  concurrent lookups by session_id without going through the PtyManager
  GenServer (avoiding bottleneck).

  ## Lifecycle

  The infrastructure (Registry + DynamicSupervisor) is lazily started
  on first use, following the same pattern as `Mana.BrowserSupervisor`.

  ## API

  - `open_session/1` — Create a new terminal session
  - `run_command/2` — Execute a command in a session
  - `send_keys/2` — Send raw keystrokes
  - `read_output/1` — Read and clear the output buffer
  - `close_session/1` — Close and clean up a session
  - `list_sessions/0` — List active session IDs
  """

  use GenServer

  require Logger

  alias Mana.Tools.Terminal.Session

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type session_opts :: [
          {:session_id, String.t()}
          | {:shell, String.t()}
          | {:timeout, pos_integer()}
          | {:max_buffer_size, pos_integer()}
        ]

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @doc """
  Starts the PtyManager GenServer.
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
      restart: :transient
    }
  end

  @doc """
  Opens a new terminal session.

  ## Options

    - `:session_id` — Unique ID (auto-generated UUID if not provided)
    - `:shell` — Shell executable (default: $SHELL or /bin/bash)
    - `:timeout` — Command timeout in ms (default: 30_000)
    - `:max_buffer_size` — Max output buffer in bytes (default: 100_000)

  ## Returns

    - `{:ok, session_id}` — Session created successfully
    - `{:error, reason}` — Session creation failed
  """
  @spec open_session(session_opts()) :: {:ok, String.t()} | {:error, term()}
  def open_session(opts \\ []) do
    ensure_infrastructure()
    GenServer.call(__MODULE__, {:open_session, opts})
  end

  @doc """
  Executes a command in a terminal session and waits for output.

  Uses sentinel-based completion detection. Returns when the command
  finishes or times out.

  ## Returns

    - `{:ok, output}` — Command output
    - `{:error, reason}` — Execution failed
  """
  @spec run_command(String.t(), String.t()) :: {:ok, String.t()} | {:error, term()}
  def run_command(session_id, command) do
    with {:ok, pid} <- lookup_session(session_id),
         do: Session.run_command(pid, command)
  end

  @doc """
  Sends raw keystrokes to a terminal session.

  Unlike `run_command/2`, this does NOT append a newline or wait for
  completion. Useful for sending individual keystrokes, control
  sequences, or partial input.

  ## Returns

    - `:ok` — Keys sent successfully
    - `{:error, reason}` — Send failed
  """
  @spec send_keys(String.t(), String.t()) :: :ok | {:error, term()}
  def send_keys(session_id, keys) do
    with {:ok, pid} <- lookup_session(session_id),
         do: Session.send_keys(pid, keys)
  end

  @doc """
  Reads and clears the current output buffer for a session.

  Returns all accumulated output since the last read and clears the buffer.

  ## Returns

    - `{:ok, output}` — Current buffer contents
    - `{:error, reason}` — Read failed
  """
  @spec read_output(String.t()) :: {:ok, String.t()} | {:error, term()}
  def read_output(session_id) do
    with {:ok, pid} <- lookup_session(session_id),
         do: Session.read_output(pid)
  end

  @doc """
  Closes a terminal session and cleans up resources.

  Terminates the shell process and removes the session from the registry.

  ## Returns

    - `:ok` — Session closed successfully
    - `{:error, reason}` — Close failed
  """
  @spec close_session(String.t()) :: :ok | {:error, term()}
  def close_session(session_id) do
    GenServer.call(__MODULE__, {:close_session, session_id})
  end

  @doc """
  Lists all active terminal session IDs.
  """
  @spec list_sessions() :: [String.t()]
  def list_sessions do
    ensure_infrastructure()

    Mana.Terminal.SessionRegistry
    |> Registry.select([{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Enum.sort()
  end

  @doc """
  Returns metadata about a session.
  """
  @spec get_session_info(String.t()) :: {:ok, map()} | {:error, term()}
  def get_session_info(session_id) do
    with {:ok, pid} <- lookup_session(session_id),
         do: Session.get_info(pid)
  end

  # ---------------------------------------------------------------------------
  # Infrastructure (Lazy Start)
  # ---------------------------------------------------------------------------

  @doc """
  Ensures the terminal infrastructure (Registry + DynamicSupervisor)
  is started. Idempotent — safe to call multiple times.
  """
  @spec ensure_infrastructure() :: :ok | {:error, term()}
  def ensure_infrastructure do
    ensure_registry()
    ensure_session_supervisor()
    ensure_manager()
    :ok
  end

  defp ensure_registry do
    case Process.whereis(Mana.Terminal.SessionRegistry) do
      nil ->
        spec = %{
          id: Mana.Terminal.SessionRegistry,
          start: {Registry, :start_link, [[keys: :unique, name: Mana.Terminal.SessionRegistry]]},
          type: :worker
        }

        case Supervisor.start_child(Mana.Supervisor, spec) do
          {:ok, _pid} -> :ok
          {:error, {:already_started, _pid}} -> :ok
          {:error, reason} -> Logger.warning("[#{__MODULE__}] Could not start SessionRegistry: #{inspect(reason)}")
        end

      _pid ->
        :ok
    end
  end

  defp ensure_session_supervisor do
    case Process.whereis(Mana.Terminal.SessionSupervisor) do
      nil ->
        spec = %{
          id: Mana.Terminal.SessionSupervisor,
          start: {DynamicSupervisor, :start_link, [[strategy: :one_for_one, name: Mana.Terminal.SessionSupervisor]]},
          type: :supervisor
        }

        case Supervisor.start_child(Mana.Supervisor, spec) do
          {:ok, _pid} -> :ok
          {:error, {:already_started, _pid}} -> :ok
          {:error, reason} -> Logger.warning("[#{__MODULE__}] Could not start SessionSupervisor: #{inspect(reason)}")
        end

      _pid ->
        :ok
    end
  end

  defp ensure_manager do
    case Process.whereis(__MODULE__) do
      nil ->
        case DynamicSupervisor.start_child(
               Mana.Terminal.SessionSupervisor,
               child_spec([])
             ) do
          {:ok, _pid} ->
            :ok

          {:error, {:already_started, _pid}} ->
            :ok

          {:error, reason} ->
            Logger.error("[#{__MODULE__}] Failed to start: #{inspect(reason)}")
            {:error, reason}
        end

      _pid ->
        :ok
    end
  end

  # ---------------------------------------------------------------------------
  # Session Lookup
  # ---------------------------------------------------------------------------

  @spec lookup_session(String.t()) :: {:ok, pid()} | {:error, term()}
  defp lookup_session(session_id) do
    case Session.lookup(session_id) do
      {:ok, pid} -> {:ok, pid}
      {:error, :not_found} -> {:error, {:session_not_found, session_id}}
    end
  end

  # ---------------------------------------------------------------------------
  # GenServer Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    {:ok, %{sessions: MapSet.new()}}
  end

  @impl true
  def handle_call({:open_session, opts}, _from, state) do
    session_id = Keyword.get_lazy(opts, :session_id, &generate_session_id/0)

    if MapSet.member?(state.sessions, session_id) or session_exists?(session_id) do
      {:reply, {:error, {:session_already_exists, session_id}}, state}
    else
      session_opts = Keyword.put(opts, :session_id, session_id)

      case DynamicSupervisor.start_child(
             Mana.Terminal.SessionSupervisor,
             Session.child_spec(session_opts)
           ) do
        {:ok, _pid} ->
          new_state = %{state | sessions: MapSet.put(state.sessions, session_id)}
          Logger.info("[#{__MODULE__}] Opened session: #{session_id}")
          {:reply, {:ok, session_id}, new_state}

        {:error, {:already_started, _pid}} ->
          {:reply, {:error, {:session_already_exists, session_id}}, state}

        {:error, reason} ->
          Logger.error("[#{__MODULE__}] Failed to open session #{session_id}: #{inspect(reason)}")
          {:reply, {:error, reason}, state}
      end
    end
  end

  @impl true
  def handle_call({:close_session, session_id}, _from, state) do
    case Session.lookup(session_id) do
      {:ok, pid} ->
        DynamicSupervisor.terminate_child(Mana.Terminal.SessionSupervisor, pid)
        new_state = %{state | sessions: MapSet.delete(state.sessions, session_id)}
        Logger.info("[#{__MODULE__}] Closed session: #{session_id}")
        {:reply, :ok, new_state}

      {:error, :not_found} ->
        # Session not in Registry — may have crashed. Clean up our tracking.
        new_state = %{state | sessions: MapSet.delete(state.sessions, session_id)}
        {:reply, {:error, {:session_not_found, session_id}}, new_state}
    end
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ---------------------------------------------------------------------------
  # Internal Helpers
  # ---------------------------------------------------------------------------

  @spec generate_session_id() :: String.t()
  defp generate_session_id do
    :crypto.strong_rand_bytes(8) |> Base.encode16(case: :lower)
  end

  @spec session_exists?(String.t()) :: boolean()
  defp session_exists?(session_id) do
    case Process.whereis(Mana.Terminal.SessionRegistry) do
      nil -> false
      _registry -> Registry.lookup(Mana.Terminal.SessionRegistry, session_id) != []
    end
  end
end
