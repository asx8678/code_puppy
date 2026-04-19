defmodule CodePuppyControl.PtyManager.Stub do
  @moduledoc """
  Stub PTY manager for development and testing.

  A GenServer that mimics the real `CodePuppyControl.PtyManager` interface
  without spawning actual OS PTY processes. Registers under the same name
  (`CodePuppyControl.PtyManager`) so that calls to the PtyManager public API
  are intercepted by this stub in test environments.

  Records calls in state so tests can assert on what was sent.

  ## Usage in tests

      # Start the stub (registers under PtyManager name)
      CodePuppyControl.PtyManager.Stub.start_link([])

      # Inspect recorded calls
      calls = CodePuppyControl.PtyManager.Stub.get_calls("my-session")

      # Simulate PTY output for a session
      CodePuppyControl.PtyManager.Stub.simulate_output("my-session", "Hello")

  ## How it works

  The real `PtyManager` is a GenServer whose public functions call
  `GenServer.call(__MODULE__, ...)`. This stub registers under the same
  name and handles the same message tuples, so `PtyManager.create_session/2`
  etc. are routed here automatically.
  """

  use GenServer

  @pty_manager_name CodePuppyControl.PtyManager

  defstruct sessions: %{}, calls: %{}

  # ---------------------------------------------------------------------------
  # Client API — GenServer start
  # ---------------------------------------------------------------------------

  @doc """
  Starts the stub GenServer.

  By default registers under `CodePuppyControl.PtyManager` so that
  `PtyManager.create_session/2` etc. route here.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, @pty_manager_name)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  # ---------------------------------------------------------------------------
  # Test helpers
  # ---------------------------------------------------------------------------

  @doc "Get all recorded calls for a session (returns a list of `{action, payload}` tuples)."
  @spec get_calls(String.t()) :: [{atom(), term()}]
  def get_calls(session_id) do
    GenServer.call(@pty_manager_name, {:stub_get_calls, session_id})
  end

  @doc "Clear all recorded calls and sessions."
  @spec clear_all() :: :ok
  def clear_all do
    GenServer.call(@pty_manager_name, :stub_clear_all)
  end

  @doc """
  Simulate PTY output for a session (sends `{:pty_output, session_id, data}`
  to the session's subscriber).

  This replaces the erlexec output that the real PtyManager would forward.
  """
  @spec simulate_output(String.t(), binary()) :: :ok
  def simulate_output(session_id, data) do
    GenServer.call(@pty_manager_name, {:stub_simulate_output, session_id, data})
  end

  # ---------------------------------------------------------------------------
  # GenServer callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    {:ok, %__MODULE__{}}
  end

  # -- Handle the same messages as the real PtyManager GenServer --

  @impl true
  def handle_call({:create_session, session_id, opts}, _from, state) do
    cols = Keyword.get(opts, :cols, 80)
    rows = Keyword.get(opts, :rows, 24)
    shell = Keyword.get(opts, :shell, "/bin/sh")
    subscriber = Keyword.get(opts, :subscriber)

    session = %{
      session_id: session_id,
      cols: cols,
      rows: rows,
      shell: shell,
      subscriber: subscriber
    }

    state = %{
      state
      | sessions: Map.put(state.sessions, session_id, session),
        calls:
          Map.update(state.calls, session_id, [{:create, %{cols: cols, rows: rows}}], fn calls ->
            calls ++ [{:create, %{cols: cols, rows: rows}}]
          end)
    }

    {:reply, {:ok, session}, state}
  end

  @impl true
  def handle_call({:write, session_id, data}, _from, state) do
    state = %{
      state
      | calls:
          Map.update(state.calls, session_id, [{:write, data}], fn calls ->
            calls ++ [{:write, data}]
          end)
    }

    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:resize, session_id, cols, rows}, _from, state) do
    state = %{
      state
      | sessions:
          Map.update(state.sessions, session_id, %{cols: cols, rows: rows}, fn session ->
            Map.merge(session, %{cols: cols, rows: rows})
          end),
        calls:
          Map.update(
            state.calls,
            session_id,
            [{:resize, %{cols: cols, rows: rows}}],
            fn calls -> calls ++ [{:resize, %{cols: cols, rows: rows}}] end
          )
    }

    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:close_session, session_id}, _from, state) do
    session = Map.get(state.sessions, session_id)

    if session && session.subscriber do
      send(session.subscriber, {:pty_exit, session_id, :closed})
    end

    state = %{
      state
      | sessions: Map.delete(state.sessions, session_id),
        calls:
          Map.update(state.calls, session_id, [{:close, nil}], fn calls ->
            calls ++ [{:close, nil}]
          end)
    }

    {:reply, :ok, state}
  end

  @impl true
  def handle_call(:close_all, _from, state) do
    Enum.each(state.sessions, fn {_id, session} ->
      if session.subscriber do
        send(session.subscriber, {:pty_exit, session.session_id, :closed})
      end
    end)

    {:reply, :ok, %__MODULE__{}}
  end

  @impl true
  def handle_call(:list_sessions, _from, state) do
    {:reply, Map.keys(state.sessions), state}
  end

  @impl true
  def handle_call({:get_session, session_id}, _from, state) do
    {:reply, Map.get(state.sessions, session_id), state}
  end

  @impl true
  def handle_call({:subscribe, session_id, subscriber_pid}, _from, state) do
    case Map.get(state.sessions, session_id) do
      nil ->
        {:reply, {:error, :not_found}, state}

      session ->
        updated = Map.put(session, :subscriber, subscriber_pid)
        {:reply, :ok, %{state | sessions: Map.put(state.sessions, session_id, updated)}}
    end
  end

  @impl true
  def handle_call({:unsubscribe, session_id, _subscriber_pid}, _from, state) do
    case Map.get(state.sessions, session_id) do
      nil ->
        {:reply, :ok, state}

      session ->
        updated = Map.put(session, :subscriber, nil)
        {:reply, :ok, %{state | sessions: Map.put(state.sessions, session_id, updated)}}
    end
  end

  @impl true
  def handle_call(:count, _from, state) do
    {:reply, map_size(state.sessions), state}
  end

  # -- Stub-specific test helpers --

  @impl true
  def handle_call({:stub_get_calls, session_id}, _from, state) do
    {:reply, Map.get(state.calls, session_id, []), state}
  end

  @impl true
  def handle_call(:stub_clear_all, _from, _state) do
    {:reply, :ok, %__MODULE__{}}
  end

  @impl true
  def handle_call({:stub_simulate_output, session_id, data}, _from, state) do
    case Map.get(state.sessions, session_id) do
      nil ->
        {:reply, :ok, state}

      session ->
        if session.subscriber do
          send(session.subscriber, {:pty_output, session_id, data})
        end

        {:reply, :ok, state}
    end
  end

  # Catch-all for unrecognised calls
  @impl true
  def handle_call(msg, _from, state) do
    {:reply, {:error, {:unknown_call, msg}}, state}
  end
end
