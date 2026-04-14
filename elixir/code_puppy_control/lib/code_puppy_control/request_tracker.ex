defmodule CodePuppyControl.RequestTracker do
  @moduledoc """
  Tracks pending requests and correlates responses.

  This GenServer maintains a registry of pending JSON-RPC requests,
  allowing the system to match incoming responses with their original
  requesters via `handle_call` / `GenServer.reply`.
  """

  use GenServer

  require Logger

  @type request_id :: String.t() | integer()
  @type pending_request :: %{
          from: GenServer.from(),
          method: String.t(),
          timestamp: integer()
        }

  # Client API

  @doc """
  Starts the RequestTracker process.
  """
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Registers a pending request and awaits its response.

  Returns `{:ok, result}` on success or `{:error, reason}` on timeout
  or other failure.
  """
  @spec await_request(request_id(), String.t(), timeout()) :: {:ok, term()} | {:error, term()}
  def await_request(request_id, method, timeout \\ 30_000) do
    GenServer.call(__MODULE__, {:register, request_id, method, timeout}, timeout + 5000)
  end

  @doc """
  Completes a pending request with a result.
  """
  @spec complete_request(request_id(), term()) :: :ok | {:error, :not_found}
  def complete_request(request_id, result) do
    GenServer.call(__MODULE__, {:complete, request_id, result})
  end

  @doc """
  Fails a pending request with an error reason.
  """
  @spec fail_request(request_id(), term()) :: :ok | {:error, :not_found}
  def fail_request(request_id, reason) do
    GenServer.call(__MODULE__, {:fail, request_id, reason})
  end

  @doc """
  Returns statistics about pending requests.
  """
  @spec stats() :: %{pending: non_neg_integer(), oldest_ms: non_neg_integer() | nil}
  def stats do
    GenServer.call(__MODULE__, :stats)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    # Schedule periodic cleanup of stale requests
    schedule_cleanup()

    {:ok, %{pending: %{}, timers: %{}}}
  end

  @impl true
  def handle_call({:register, request_id, method, timeout}, from, state) do
    pending = %{
      from: from,
      method: method,
      timestamp: System.monotonic_time(:millisecond)
    }

    # Set a timer to auto-fail this request on timeout
    timer_ref = Process.send_after(self(), {:timeout, request_id}, timeout)

    new_state = %{
      state
      | pending: Map.put(state.pending, request_id, pending),
        timers: Map.put(state.timers, request_id, timer_ref)
    }

    # Return noreply - we'll reply later when the response arrives
    {:noreply, new_state}
  end

  @impl true
  def handle_call({:complete, request_id, result}, _from, state) do
    case Map.pop(state.pending, request_id) do
      {nil, _} ->
        {:reply, {:error, :not_found}, state}

      {pending, new_pending} ->
        # Cancel the timeout timer
        {timer, new_timers} = Map.pop(state.timers, request_id)
        if timer, do: Process.cancel_timer(timer)

        # Reply to the waiting process
        GenServer.reply(pending.from, {:ok, result})

        {:reply, :ok, %{state | pending: new_pending, timers: new_timers}}
    end
  end

  @impl true
  def handle_call({:fail, request_id, reason}, _from, state) do
    case Map.pop(state.pending, request_id) do
      {nil, _} ->
        {:reply, {:error, :not_found}, state}

      {pending, new_pending} ->
        # Cancel the timeout timer
        {timer, new_timers} = Map.pop(state.timers, request_id)
        if timer, do: Process.cancel_timer(timer)

        # Reply to the waiting process with error
        GenServer.reply(pending.from, {:error, reason})

        {:reply, :ok, %{state | pending: new_pending, timers: new_timers}}
    end
  end

  @impl true
  def handle_call(:stats, _from, state) do
    now = System.monotonic_time(:millisecond)

    oldest_ms =
      state.pending
      |> Map.values()
      |> Enum.map(fn %{timestamp: ts} -> now - ts end)
      |> Enum.min(&<=/2, fn -> nil end)

    {:reply, %{pending: map_size(state.pending), oldest_ms: oldest_ms}, state}
  end

  @impl true
  def handle_info({:timeout, request_id}, state) do
    case Map.pop(state.pending, request_id) do
      {nil, _} ->
        new_timers = Map.delete(state.timers, request_id)
        {:noreply, %{state | timers: new_timers}}

      {pending, new_pending} ->
        Logger.warning("Request #{request_id} (#{pending.method}) timed out")
        GenServer.reply(pending.from, {:error, :timeout})

        new_timers = Map.delete(state.timers, request_id)
        {:noreply, %{state | pending: new_pending, timers: new_timers}}
    end
  end

  @impl true
  def handle_info(:cleanup, state) do
    schedule_cleanup()

    now = System.monotonic_time(:millisecond)
    # 5 minutes
    stale_threshold = 5 * 60 * 1000

    stale_ids =
      for {id, %{timestamp: ts, from: from}} <- state.pending,
          now - ts > stale_threshold,
          do: {id, from}

    for {id, from} <- stale_ids do
      Logger.warning("Cleaning up stale request #{id}")
      GenServer.reply(from, {:error, :stale_request})
    end

    stale_id_set = MapSet.new(stale_ids, fn {id, _} -> id end)

    new_pending = Map.drop(state.pending, MapSet.to_list(stale_id_set))
    new_timers = Map.drop(state.timers, MapSet.to_list(stale_id_set))

    # Cancel timers for stale requests
    for {id, timer} <- state.timers, MapSet.member?(stale_id_set, id) do
      Process.cancel_timer(timer)
    end

    {:noreply, %{state | pending: new_pending, timers: new_timers}}
  end

  defp schedule_cleanup do
    Process.send_after(self(), :cleanup, 60_000)
  end
end
