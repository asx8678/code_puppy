defmodule Mana.RateLimiter do
  @moduledoc """
  GenServer with per-model limits and circuit breaker.

  Implements a token bucket rate limiter with circuit breaker pattern
  for each model. When rate limits are exceeded, the circuit opens
  and requests are blocked until the recovery interval passes.
  """
  use GenServer

  require Logger

  @default_limit 60
  @recovery_interval 30_000

  defstruct models: %{}, last_recovery: nil

  @type model_state :: %{
          count: non_neg_integer(),
          state: :closed | :open | :half_open,
          limit: non_neg_integer()
        }

  @type t :: %__MODULE__{
          models: %{String.t() => model_state()},
          last_recovery: DateTime.t() | nil
        }

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the RateLimiter GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
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
  Check if a request is allowed for a model.

  Returns :ok if allowed, {:error, :rate_limited} if blocked.
  """
  @spec check(String.t()) :: :ok | {:error, :rate_limited}
  def check(model) do
    GenServer.call(__MODULE__, {:check, model})
  end

  @doc """
  Report a rate limit error (429) for a model.

  This reduces the limit and opens the circuit breaker.
  """
  @spec report_rate_limit(String.t()) :: :ok
  def report_rate_limit(model) do
    GenServer.cast(__MODULE__, {:rate_limit, model})
  end

  @doc """
  Get current state for a model (for testing/debugging).
  """
  @spec get_model_state(String.t()) :: model_state() | nil
  def get_model_state(model) do
    GenServer.call(__MODULE__, {:get_state, model})
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    schedule_recovery()
    {:ok, %__MODULE__{last_recovery: DateTime.utc_now()}}
  end

  @impl true
  def handle_call({:check, model}, _from, state) do
    model_state = Map.get(state.models, model, default_model_state())

    case model_state.state do
      :closed ->
        new_count = model_state.count + 1

        if new_count > model_state.limit do
          new_models =
            Map.put(state.models, model, %{model_state | state: :open, count: new_count})

          Logger.warning("Rate limit exceeded for model #{model}, opening circuit")
          {:reply, {:error, :rate_limited}, %{state | models: new_models}}
        else
          new_models = Map.put(state.models, model, %{model_state | count: new_count})
          {:reply, :ok, %{state | models: new_models}}
        end

      :open ->
        {:reply, {:error, :rate_limited}, state}

      :half_open ->
        new_models =
          Map.put(state.models, model, %{model_state | state: :closed, count: 1})

        Logger.info("Circuit half-open for model #{model}, allowing test request")
        {:reply, :ok, %{state | models: new_models}}
    end
  end

  @impl true
  def handle_call({:get_state, model}, _from, state) do
    {:reply, Map.get(state.models, model), state}
  end

  @impl true
  def handle_cast({:rate_limit, model}, state) do
    model_state = Map.get(state.models, model, default_model_state())
    new_limit = max(div(model_state.limit, 2), 1)

    new_models =
      Map.put(state.models, model, %{
        model_state
        | state: :open,
          limit: new_limit
      })

    Logger.warning("Rate limit reported for model #{model}, reducing limit to #{new_limit}")
    {:noreply, %{state | models: new_models}}
  end

  @impl true
  def handle_info(:recover, state) do
    new_models =
      Map.new(state.models, fn {model, model_state} ->
        case model_state.state do
          :open ->
            Logger.info("Circuit recovery for model #{model}, transitioning to half-open")
            {model, %{model_state | state: :half_open}}

          _ ->
            {model, %{model_state | count: 0}}
        end
      end)

    schedule_recovery()
    {:noreply, %{state | models: new_models, last_recovery: DateTime.utc_now()}}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp default_model_state do
    %{count: 0, state: :closed, limit: @default_limit}
  end

  defp schedule_recovery do
    Process.send_after(self(), :recover, @recovery_interval)
  end
end
