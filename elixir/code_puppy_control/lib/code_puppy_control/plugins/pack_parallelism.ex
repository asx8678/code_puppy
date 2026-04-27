defmodule CodePuppyControl.Plugins.PackParallelism do
  @moduledoc """
  Semaphore-based concurrency limiter for agent pack invocations.

  Replaces the Python `_async_active` counter (HACK(pack-parallelism) race)
  with an Elixir GenServer that serializes all state mutations, eliminating
  the race condition where concurrent acquire/release calls could read stale
  counter values from `threading.Lock`-protected Python attributes.

  ## Architecture

  - **GenServer**: Serializes all mutations (acquire, release, config update,
    force-reset). Eliminates the Python race between `_async_active` counter
    increments/decrements and the `asyncio.Semaphore` internal state.
  - **ETS table** (`:pack_parallelism_limits`): Public read access for fast
    `status/0` and `try_acquire/1` reads. Each row:
    `{limit_type, current_count, max_limit}`.
  - **FIFO waiter queue**: Blocking `acquire/2` with per-type timeout and
    fairness guarantees.

  ## Why This Fixes the Race

  The Python `RunLimiter` had two independent state machines sharing state
  through a `threading.Lock`:
    1. `asyncio.Semaphore` (internal `_value` counter)
    2. `_async_active` / `_async_waiters` (Python integers under `_state_lock`)

  The race occurred when:
  - Thread A reads `_async_active = 1`, context switches
  - Thread B reads `_async_active = 1`, increments to 2
  - Thread A increments to 2 (overwriting B's 2 with 2 again — lost update)

  The Elixir GenServer serializes all mutations through a single process
  mailbox. No lock, no race. `handle_call` for acquire and `handle_cast`
  for release are atomic by the BEAM scheduler.

  ## Configuration

      config :code_puppy_control, :pack_parallelism,
        max_concurrent_runs: 2,
        allow_parallel: true,
        wait_timeout: 600_000  # ms (10 minutes)

  ## Telemetry Events

  - `[:code_puppy, :pack_parallelism, :acquire]` — emitted on successful acquire
  - `[:code_puppy, :pack_parallelism, :release]` — emitted on release
  - `[:code_puppy, :pack_parallelism, :timeout]` — emitted on waiter timeout
  - `[:code_puppy, :pack_parallelism, :reset]` — emitted on force-reset

  ## JSON-RPC Methods

  The following methods are dispatched through `StdioService` when the
  Elixir control plane is active, replacing the Python-side handlers in
  `bridge_controller.py`:

  - `run_limiter.acquire`  — Acquire a pack slot (blocking with timeout)
  - `run_limiter.release`  — Release a pack slot
  - `run_limiter.status`  — Return current counts and config
  - `run_limiter.set_limit` — Update the concurrency limit at runtime
  - `run_limiter.reset`    — Emergency force-reset of all state
  """

  use GenServer

  require Logger

  @table :pack_parallelism_limits

  @default_max_concurrent_runs 2
  @default_allow_parallel true
  @default_wait_timeout 600_000

  @type limiter_type :: :pack_run

  # ── Public API ──────────────────────────────────────────────────────────

  @doc """
  Starts the pack parallelism GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Acquires a pack run slot. Blocks until a slot is available or timeout.

  Returns `:ok` on success or `{:error, :timeout}` if no slot was available
  within the timeout period.

  ## Examples

      :ok = PackParallelism.acquire()
      :ok = PackParallelism.acquire(timeout: 5_000)
      {:error, :timeout} = PackParallelism.acquire(timeout: 100)
  """
  @spec acquire(keyword()) :: :ok | {:error, :timeout}
  def acquire(opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_wait_timeout)

    GenServer.call(__MODULE__, {:acquire, timeout}, call_timeout(timeout))
  catch
    :exit, {:timeout, _} -> {:error, :timeout}
  end

  @doc """
  Non-blocking attempt to acquire a pack run slot.

  Returns `:ok` on success or `{:error, :unavailable}` if all slots are in use.
  """
  @spec try_acquire() :: :ok | {:error, :unavailable}
  def try_acquire do
    GenServer.call(__MODULE__, :try_acquire)
  end

  @doc """
  Releases a previously acquired pack run slot.

  Wakes the next waiting caller (if any) in FIFO order.
  """
  @spec release() :: :ok
  def release do
    GenServer.cast(__MODULE__, :release)
  end

  @doc """
  Executes `fun` after acquiring a pack slot, and always releases it.

  Returns `{:ok, result}` on success, or `{:error, :timeout}` if no slot
  became available within the timeout.
  """
  @spec with_slot((-> result), keyword()) :: {:ok, result} | {:error, :timeout}
        when result: any()
  def with_slot(fun, opts \\ []) when is_function(fun, 0) do
    case acquire(opts) do
      :ok ->
        try do
          {:ok, fun.()}
        after
          release()
        end

      {:error, :timeout} = err ->
        err
    end
  end

  @doc """
  Returns the current concurrency status.

  ## Examples

      PackParallelism.status()
      #=> %{limit: 2, active: 1, waiters: 0, available: 1}
  """
  @spec status() :: %{
          limit: non_neg_integer(),
          active: non_neg_integer(),
          waiters: non_neg_integer(),
          available: non_neg_integer()
        }
  def status do
    GenServer.call(__MODULE__, :status)
  end

  @doc """
  Updates the concurrency limit at runtime.

  When growing (`new > old`), releases net-new slots to the semaphore.
  When shrinking (`new < old`), absorbs releases into deficit tracking.
  """
  @spec set_limit(non_neg_integer()) :: :ok | {:error, :invalid}
  def set_limit(new_limit) when is_integer(new_limit) and new_limit >= 1 do
    GenServer.call(__MODULE__, {:set_limit, new_limit})
  end

  def set_limit(_), do: {:error, :invalid}

  @doc """
  Emergency force-reset of all counters and waiter queues.

  Used by `/pack-parallel reset` to recover from stuck states.
  Cancels all pending waiters (they receive `{:error, :timeout}`).
  Returns the previous state for logging.
  """
  @spec reset() :: map()
  def reset do
    GenServer.call(__MODULE__, :reset)
  end

  @doc """
  Synchronous ping to flush pending messages. Useful in tests.
  """
  @spec ping() :: :pong
  def ping do
    GenServer.call(__MODULE__, :ping)
  end

  @doc """
  Returns the effective limit (respects allow_parallel config).
  If `allow_parallel` is false, always returns 1.
  """
  @spec effective_limit() :: non_neg_integer()
  def effective_limit do
    case :ets.lookup(@table, :pack_run) do
      [{:pack_run, _current, limit}] -> limit
      [] -> @default_max_concurrent_runs
    end
  end

  # ── JSON-RPC Handler Functions ──────────────────────────────────────

  @doc """
  Handle `run_limiter.acquire` JSON-RPC method.
  """
  @spec handle_jsonrpc_acquire(map()) :: map()
  def handle_jsonrpc_acquire(params) do
    timeout_ms =
      case Map.get(params, "timeout") do
        nil -> @default_wait_timeout
        t when is_number(t) -> trunc(t * 1000)
        _ -> @default_wait_timeout
      end

    case acquire(timeout: timeout_ms) do
      :ok ->
        %{"status" => "ok"}

      {:error, :timeout} ->
        %{"status" => "timeout", "fallback" => true}
    end
  end

  @doc """
  Handle `run_limiter.release` JSON-RPC method.
  """
  @spec handle_jsonrpc_release(map()) :: map()
  def handle_jsonrpc_release(_params) do
    release()
    %{"status" => "ok"}
  end

  @doc """
  Handle `run_limiter.status` JSON-RPC method.
  """
  @spec handle_jsonrpc_status(map()) :: map()
  def handle_jsonrpc_status(_params) do
    s = status()
    %{
      "status" => "ok",
      "limit" => s.limit,
      "active" => s.active,
      "waiters" => s.waiters
    }
  end

  @doc """
  Handle `run_limiter.set_limit` JSON-RPC method.
  """
  @spec handle_jsonrpc_set_limit(map()) :: map()
  def handle_jsonrpc_set_limit(params) do
    limit = Map.get(params, "limit", 2)

    case set_limit(limit) do
      :ok -> %{"status" => "ok", "limit" => effective_limit()}
      {:error, :invalid} -> %{"status" => "error", "message" => "Invalid limit value"}
    end
  end

  @doc """
  Handle `run_limiter.reset` JSON-RPC method.
  """
  @spec handle_jsonrpc_reset(map()) :: map()
  def handle_jsonrpc_reset(_params) do
    previous = reset()
    %{"status" => "ok", "previous" => previous}
  end

  # ── GenServer Callbacks ─────────────────────────────────────────────────

  @impl true
  def init(opts) do
    table =
      :ets.new(@table, [
        :set,
        :public,
        :named_table,
        read_concurrency: true,
        write_concurrency: true
      ])

    config = load_config(opts)
    max_runs = Keyword.get(config, :max_concurrent_runs, @default_max_concurrent_runs)
    allow_parallel = Keyword.get(config, :allow_parallel, @default_allow_parallel)

    effective = if allow_parallel, do: max(1, max_runs), else: 1

    :ets.insert(table, {:pack_run, 0, effective})

    Logger.info(
      "PackParallelism initialized: limit=#{effective}, allow_parallel=#{allow_parallel}"
    )

    state = %{
      max_concurrent_runs: max_runs,
      allow_parallel: allow_parallel,
      wait_timeout: Keyword.get(config, :wait_timeout, @default_wait_timeout),
      waiters: :queue.new(),
      deficit: 0
    }

    {:ok, state}
  end

  @impl true
  def handle_call(:ping, _from, state) do
    {:reply, :pong, state}
  end

  @impl true
  def handle_call(:status, _from, state) do
    [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)
    waiter_count = :queue.len(state.waiters)

    reply = %{
      limit: limit,
      active: current,
      waiters: waiter_count,
      available: max(limit - current, 0)
    }

    {:reply, reply, state}
  end

  @impl true
  def handle_call(:try_acquire, _from, state) do
    [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)

    if current < limit do
      :ets.update_counter(@table, :pack_run, {2, 1})
      emit_telemetry(:acquire, current + 1, limit)
      {:reply, :ok, state}
    else
      {:reply, {:error, :unavailable}, state}
    end
  end

  @impl true
  def handle_call({:acquire, timeout}, from, state) do
    [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)

    if current < limit do
      # Slot available — increment and reply immediately
      :ets.update_counter(@table, :pack_run, {2, 1})
      emit_telemetry(:acquire, current + 1, limit)
      {:reply, :ok, state}
    else
      # No slot — queue the caller for later
      ref = make_ref()
      timer_ref = maybe_start_timeout_timer(ref, timeout)
      waiter = %{from: from, ref: ref, timer_ref: timer_ref}
      {:noreply, %{state | waiters: :queue.in(waiter, state.waiters)}}
    end
  end

  @impl true
  def handle_call({:set_limit, new_limit}, _from, state) do
    [{:pack_run, current, old_limit}] = :ets.lookup(@table, :pack_run)

    # Respect allow_parallel: if false, effective limit is always 1
    effective =
      if state.allow_parallel,
        do: max(1, new_limit),
        else: 1

    state =
      cond do
        effective > old_limit ->
          # Growing: release net-new slots
          growth = effective - old_limit
          deficit_absorbed = min(growth, state.deficit)
          new_deficit = state.deficit - deficit_absorbed
          net_new = growth - deficit_absorbed

          # Increment the ETS limit (and counter if we have net-new)
          :ets.insert(@table, {:pack_run, current, effective})

          # For net-new capacity, increment the counter to make slots available
          if net_new > 0 do
            :ets.update_counter(@table, :pack_run, {2, net_new})
          end

          Logger.info(
            "PackParallelism limit grown: #{old_limit} -> #{effective} " <>
              "(deficit absorbed: #{deficit_absorbed}, net-new: #{net_new})"
          )

          %{state | deficit: new_deficit}

        effective < old_limit ->
          # Shrinking: track deficit for absorbing future releases
          excess = old_limit - effective
          new_deficit = state.deficit + excess
          :ets.insert(@table, {:pack_run, current, effective})

          Logger.info(
            "PackParallelism limit shrunk: #{old_limit} -> #{effective} " <>
              "(deficit now: #{new_deficit})"
          )

          %{state | deficit: new_deficit}

        true ->
          # No change
          state
      end

    {:reply, :ok, state}
  end

  @impl true
  def handle_call(:reset, _from, state) do
    # Reply to all waiters with timeout
    reply_to_all_waiters(state, {:error, :timeout})

    # Capture previous state for return value
    [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)
    waiter_count = :queue.len(state.waiters)

    previous = %{
      "active" => current,
      "waiters" => waiter_count,
      "limit" => limit,
      "deficit" => state.deficit
    }

    # Reset ETS counters
    :ets.insert(@table, {:pack_run, 0, limit})

    emit_telemetry(:reset, 0, limit)

    {:reply, previous, %{state | waiters: :queue.new(), deficit: 0}}
  end

  @impl true
  def handle_cast(:release, state) do
    [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)

    state =
      if current > 0 do
        if state.deficit > 0 do
          # Absorb release into deficit (enforcing lower cap)
          :ets.update_counter(@table, :pack_run, {2, -1})
          Logger.debug("PackParallelism: release absorbed by deficit (now #{state.deficit - 1})")
          %{state | deficit: state.deficit - 1}
        else
          # Normal release — decrement counter, then wake next waiter
          :ets.update_counter(@table, :pack_run, {2, -1})
          emit_telemetry(:release, current - 1, limit)
          dequeue_and_reply(state)
        end
      else
        Logger.warning("PackParallelism: release called with no active runs")
        state
      end

    {:noreply, state}
  end

  @impl true
  def handle_info({:acquire_timeout, ref}, state) do
    {waiter, new_waiters} = pop_waiter(state.waiters, ref)

    if waiter do
      cancel_timeout_timer(waiter.timer_ref)
      GenServer.reply(waiter.from, {:error, :timeout})
      emit_telemetry(:timeout, 0, 0)
    end

    {:noreply, %{state | waiters: new_waiters}}
  end

  @impl true
  def handle_info(_msg, state) do
    {:noreply, state}
  end

  # ── Private Helpers ─────────────────────────────────────────────────────

  defp load_config(opts) do
    app_config = Application.get_env(:code_puppy_control, :pack_parallelism, [])

    # opts override app config override defaults
    Keyword.merge(app_config, opts)
  end

  defp call_timeout(:infinity), do: :infinity
  defp call_timeout(timeout), do: timeout + 5_000

  defp maybe_start_timeout_timer(_ref, :infinity), do: nil
  defp maybe_start_timeout_timer(ref, timeout) do
    Process.send_after(self(), {:acquire_timeout, ref}, timeout)
  end

  defp dequeue_and_reply(state) do
    case :queue.out(state.waiters) do
      {{:value, waiter}, rest_waiters} ->
        cancel_timeout_timer(waiter.timer_ref)

        # Increment counter for the woken waiter
        [{:pack_run, current, limit}] = :ets.lookup(@table, :pack_run)
        new_count = current + 1
        :ets.insert(@table, {:pack_run, new_count, limit})

        emit_telemetry(:acquire, new_count, limit)
        GenServer.reply(waiter.from, :ok)

        %{state | waiters: rest_waiters}

      {:empty, _} ->
        state
    end
  end

  defp pop_waiter(queue, ref) do
    queue_list = :queue.to_list(queue)

    {matching, remaining} =
      Enum.split_with(queue_list, fn waiter -> waiter.ref == ref end)

    new_queue = :queue.from_list(remaining)
    {List.first(matching), new_queue}
  end

  defp reply_to_all_waiters(state, reply) do
    state.waiters
    |> :queue.to_list()
    |> Enum.each(fn waiter ->
      cancel_timeout_timer(waiter.timer_ref)
      GenServer.reply(waiter.from, reply)
    end)
  end

  defp cancel_timeout_timer(nil), do: :ok
  defp cancel_timeout_timer(timer_ref) do
    Process.cancel_timer(timer_ref)
    :ok
  end

  defp emit_telemetry(:acquire, current, limit) do
    :telemetry.execute(
      [:code_puppy, :pack_parallelism, :acquire],
      %{count: current, limit: limit, timestamp: System.monotonic_time()},
      %{type: :pack_run}
    )
  end

  defp emit_telemetry(:release, current, limit) do
    :telemetry.execute(
      [:code_puppy, :pack_parallelism, :release],
      %{count: current, limit: limit, timestamp: System.monotonic_time()},
      %{type: :pack_run}
    )
  end

  defp emit_telemetry(:timeout, _current, _limit) do
    :telemetry.execute(
      [:code_puppy, :pack_parallelism, :timeout],
      %{timestamp: System.monotonic_time()},
      %{type: :pack_run}
    )
  end

  defp emit_telemetry(:reset, current, limit) do
    :telemetry.execute(
      [:code_puppy, :pack_parallelism, :reset],
      %{count: current, limit: limit, timestamp: System.monotonic_time()},
      %{type: :pack_run}
    )
  end
end
