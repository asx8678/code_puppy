defmodule Mana.Callbacks.Registry do
  @moduledoc """
  GenServer that stores callback registrations and dispatches events.

  ## Features

  - Ordered callback registration (callbacks invoked in registration order)
  - Event backlog for phases without listeners (up to 100 events, 30s TTL)
  - Phase validation against `Mana.Plugin.Hook`
  - Callback dispatch happens in the caller's process (not GenServer)

  ## State Structure

  - `callbacks`: Map of phase to ordered list of callback functions
  - `backlog`: Map of phase to buffered events with timestamps
  - `stats`: Dispatch and error counters

  ## Usage

      # Register a callback
      Mana.Callbacks.Registry.register(:startup, &MyMod.on_startup/0)

      # Dispatch to all callbacks (runs in caller process)
      Mana.Callbacks.Registry.dispatch(:startup, [])

      # Get and clear backlog
      Mana.Callbacks.Registry.drain_backlog(:startup)
  """

  use GenServer

  require Logger

  alias Mana.Plugin.Hook

  # Default backlog configuration
  @max_backlog_size 100
  @backlog_ttl_ms 30_000
  @cleanup_interval_ms 60_000

  # Client API

  @doc """
  Starts the Callbacks Registry GenServer.
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
  Registers a callback for a phase.

  Returns `:ok` on success, `{:error, reason}` on failure.
  """
  @spec register(atom(), fun()) :: :ok | {:error, term()}
  def register(phase, callback) when is_atom(phase) and is_function(callback) do
    if Hook.valid?(phase) do
      GenServer.call(__MODULE__, {:register, phase, callback})
    else
      {:error, :invalid_phase}
    end
  end

  def register(_, _), do: {:error, :invalid_arguments}

  @doc """
  Unregisters a callback for a phase.

  Returns `:ok` on success.
  """
  @spec unregister(atom(), fun()) :: :ok | {:error, term()}
  def unregister(phase, callback) when is_atom(phase) and is_function(callback) do
    GenServer.call(__MODULE__, {:unregister, phase, callback})
  end

  def unregister(_, _), do: {:error, :invalid_arguments}

  @doc """
  Clears all callbacks for a phase.

  Returns `:ok` on success.
  """
  @spec clear(atom()) :: :ok | {:error, term()}
  def clear(phase) when is_atom(phase) do
    GenServer.call(__MODULE__, {:clear, phase})
  end

  def clear(_), do: {:error, :invalid_arguments}

  @doc """
  Dispatches args to all callbacks registered for a phase.

  The callbacks are executed in the CALLER's process, not in the GenServer.
  This function reads the callbacks from the GenServer, then calls them directly.

  Returns `{:ok, results}` where results is a list of callback return values.
  """
  @spec dispatch(atom()) :: {:ok, list()} | {:error, term()}
  @spec dispatch(atom(), list()) :: {:ok, list()} | {:error, term()}
  def dispatch(phase, args \\ [])

  def dispatch(phase, args) when is_atom(phase) and is_list(args) do
    if Hook.valid?(phase) do
      # Get callbacks from GenServer
      callbacks = GenServer.call(__MODULE__, {:get_callbacks, phase})

      if callbacks == [] do
        # Buffer to backlog
        GenServer.cast(__MODULE__, {:buffer_event, phase, args})
        {:ok, []}
      else
        # Execute in caller's process
        # Deduplicate callbacks to prevent double dispatch
        unique_callbacks = Enum.uniq(callbacks)

        results =
          Enum.map(unique_callbacks, fn callback ->
            try do
              apply(callback, args)
            catch
              kind, reason ->
                Logger.warning("Callback error for phase #{phase}: #{kind} - #{inspect(reason)}")
                {:error, {kind, reason}}
            end
          end)

        # Update stats with unique count
        GenServer.cast(__MODULE__, {:increment_stats, :dispatches, length(unique_callbacks)})

        {:ok, results}
      end
    else
      {:error, :invalid_phase}
    end
  end

  def dispatch(phase, args) when is_atom(phase), do: dispatch(phase, [args])

  @doc """
  Gets and clears the backlog for a phase.

  Returns `{:ok, events}` where events is a list of buffered events.
  """
  @spec drain_backlog(atom()) :: {:ok, list(map())} | {:error, term()}
  def drain_backlog(phase) when is_atom(phase) do
    GenServer.call(__MODULE__, {:drain_backlog, phase})
  end

  def drain_backlog(_), do: {:error, :invalid_arguments}

  @doc """
  Returns current registry statistics.
  """
  @spec get_stats() :: map()
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  @doc """
  Returns all registered callbacks for a phase.
  """
  @spec get_callbacks(atom()) :: list(fun())
  def get_callbacks(phase) when is_atom(phase) do
    GenServer.call(__MODULE__, {:get_callbacks, phase})
  end

  # Server Callbacks

  @impl true
  def init(opts) do
    max_backlog = Keyword.get(opts, :max_backlog_size, @max_backlog_size)
    backlog_ttl = Keyword.get(opts, :backlog_ttl, @backlog_ttl_ms)

    # Schedule periodic cleanup of expired backlog entries
    schedule_cleanup()

    {:ok,
     %{
       callbacks: %{},
       backlog: %{},
       stats: %{dispatches: 0, errors: 0},
       config: %{
         max_backlog_size: max_backlog,
         backlog_ttl_ms: backlog_ttl
       }
     }}
  end

  @impl true
  def handle_call({:register, phase, callback}, _from, state) do
    callbacks = Map.get(state.callbacks, phase, [])

    # Check for duplicate
    if callback in callbacks do
      {:reply, {:error, :already_registered}, state}
    else
      new_callbacks = callbacks ++ [callback]
      new_state = %{state | callbacks: Map.put(state.callbacks, phase, new_callbacks)}
      {:reply, :ok, new_state}
    end
  end

  @impl true
  def handle_call({:unregister, phase, callback}, _from, state) do
    callbacks = Map.get(state.callbacks, phase, [])
    new_callbacks = List.delete(callbacks, callback)

    new_callbacks_map =
      if new_callbacks == [] do
        Map.delete(state.callbacks, phase)
      else
        Map.put(state.callbacks, phase, new_callbacks)
      end

    {:reply, :ok, %{state | callbacks: new_callbacks_map}}
  end

  @impl true
  def handle_call({:clear, phase}, _from, state) do
    new_callbacks = Map.delete(state.callbacks, phase)
    {:reply, :ok, %{state | callbacks: new_callbacks}}
  end

  @impl true
  def handle_call({:get_callbacks, phase}, _from, state) do
    callbacks = Map.get(state.callbacks, phase, [])
    {:reply, callbacks, state}
  end

  @impl true
  def handle_call({:drain_backlog, phase}, _from, state) do
    backlog = Map.get(state.backlog, phase, [])
    new_backlog = Map.delete(state.backlog, phase)
    {:reply, {:ok, backlog}, %{state | backlog: new_backlog}}
  end

  @impl true
  def handle_call(:get_stats, _from, state) do
    backlog_size =
      state.backlog
      |> Map.values()
      |> Enum.map(&length/1)
      |> Enum.sum()

    stats = %{
      dispatches: state.stats.dispatches,
      errors: state.stats.errors,
      callbacks_registered: count_callbacks(state.callbacks),
      backlog_size: backlog_size
    }

    {:reply, stats, state}
  end

  @impl true
  def handle_cast({:buffer_event, phase, args}, state) do
    timestamp = System.monotonic_time(:millisecond)
    event = %{args: args, timestamp: timestamp}

    backlog = Map.get(state.backlog, phase, [])

    # Enforce max backlog size (FIFO eviction)
    backlog =
      if length(backlog) >= state.config.max_backlog_size do
        [_ | rest] = backlog
        rest ++ [event]
      else
        backlog ++ [event]
      end

    {:noreply, %{state | backlog: Map.put(state.backlog, phase, backlog)}}
  end

  @impl true
  def handle_cast({:increment_stats, :dispatches, count}, state) do
    new_dispatches = state.stats.dispatches + count
    new_stats = %{state.stats | dispatches: new_dispatches}
    {:noreply, %{state | stats: new_stats}}
  end

  @impl true
  def handle_info(:cleanup_expired, state) do
    now = System.monotonic_time(:millisecond)
    ttl = state.config.backlog_ttl_ms

    # Remove expired events from all backlogs
    new_backlog =
      Map.new(state.backlog, fn {phase, events} ->
        filtered =
          Enum.filter(events, fn event ->
            now - event.timestamp < ttl
          end)

        {phase, filtered}
      end)
      |> Enum.filter(fn {_phase, events} -> events != [] end)
      |> Map.new()

    schedule_cleanup()

    {:noreply, %{state | backlog: new_backlog}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # Private Functions

  defp count_callbacks(callbacks_map) do
    callbacks_map
    |> Map.values()
    |> Enum.map(&length/1)
    |> Enum.sum()
  end

  defp schedule_cleanup do
    Process.send_after(self(), :cleanup_expired, @cleanup_interval_ms)
  end
end
