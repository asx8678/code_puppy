defmodule CodePuppyControl.Run.State do
  @moduledoc """
  GenServer for managing the state of a single run.

  Tracks:
  - Run lifecycle (pending, running, completed, failed)
  - Tool executions and their results
  - Correlation between requests and responses
  - Metadata about the run

  This process is started on demand and exits when the run completes
  or after a period of inactivity.
  """

  use GenServer

  require Logger

  alias CodePuppyControl.PythonWorker.Supervisor, as: WorkerSupervisor

  defstruct [
    :run_id,
    :status,
    :started_at,
    :completed_at,
    :error,
    :request_history,
    :last_activity,
    :metadata
  ]

  @type status :: :pending | :running | :completed | :failed

  @type t :: %__MODULE__{
          run_id: String.t(),
          status: status(),
          started_at: DateTime.t() | nil,
          completed_at: DateTime.t() | nil,
          error: term() | nil,
          request_history: list(map()),
          last_activity: integer(),
          metadata: map()
        }

  @inactivity_timeout :timer.minutes(30)

  # Client API

  @doc """
  Starts a Run.State process for the given run_id.
  """
  def start_link(opts) do
    run_id = Keyword.fetch!(opts, :run_id)
    GenServer.start_link(__MODULE__, opts, name: via_tuple(run_id))
  end

  @doc """
  Returns a via tuple for Registry lookup.
  """
  def via_tuple(run_id) do
    {:via, Registry, {CodePuppyControl.Run.Registry, {:run_state, run_id}}}
  end

  @doc """
  Creates a new run state process on demand.
  """
  @spec start_run(String.t(), map()) :: {:ok, pid()} | {:error, term()}
  def start_run(run_id, metadata \\ %{}) do
    child_spec = %{
      id: {__MODULE__, run_id},
      start: {__MODULE__, :start_link, [[run_id: run_id, metadata: metadata]]},
      restart: :temporary
    }

    case DynamicSupervisor.start_child(CodePuppyControl.Run.Supervisor, child_spec) do
      {:ok, pid} -> {:ok, pid}
      {:ok, pid, _info} -> {:ok, pid}
      {:error, {:already_started, pid}} -> {:ok, pid}
      {:error, reason} -> {:error, reason}
    end
  end

  @doc """
  Gets the current state of a run.
  """
  @spec get_state(String.t()) :: {:ok, t()} | {:error, :not_found}
  def get_state(run_id) do
    case Registry.lookup(CodePuppyControl.Run.Registry, {:run_state, run_id}) do
      [] -> {:error, :not_found}
      [{pid, _} | _] -> {:ok, GenServer.call(pid, :get_state)}
    end
  end

  @doc """
  Records a request sent to the Python worker.
  """
  @spec record_request(String.t(), map()) :: :ok
  def record_request(run_id, request) do
    GenServer.cast(via_tuple(run_id), {:record_request, request})
  end

  @doc """
  Records a response received from the Python worker.
  """
  @spec record_response(String.t(), map()) :: :ok
  def record_response(run_id, response) do
    GenServer.cast(via_tuple(run_id), {:record_response, response})
  end

  @doc """
  Updates the run status.
  """
  @spec set_status(String.t(), status(), term() | nil) :: :ok
  def set_status(run_id, status, error \\ nil) do
    GenServer.cast(via_tuple(run_id), {:set_status, status, error})
  end

  @doc """
  Gets the request history for a run.
  """
  @spec get_history(String.t()) :: list(map())
  def get_history(run_id) do
    case Registry.lookup(CodePuppyControl.Run.Registry, {:run_state, run_id}) do
      [] -> []
      [{pid, _} | _] -> GenServer.call(pid, :get_history)
    end
  end

  @doc """
  Gets the state from a State process PID.
  """
  @spec get_state_from_pid(pid()) :: {:ok, t()} | {:error, :not_found}
  def get_state_from_pid(pid) do
    try do
      {:ok, GenServer.call(pid, :get_state)}
    catch
      :exit, _ -> {:error, :not_found}
    end
  end

  # Server Callbacks

  @impl true
  def init(opts) do
    run_id = Keyword.fetch!(opts, :run_id)
    metadata = Keyword.get(opts, :metadata, %{})

    # Subscribe to PubSub for Python notifications
    Phoenix.PubSub.subscribe(CodePuppyControl.PubSub, "run:#{run_id}")

    state = %__MODULE__{
      run_id: run_id,
      status: :pending,
      started_at: DateTime.utc_now(),
      completed_at: nil,
      error: nil,
      request_history: [],
      last_activity: System.monotonic_time(:millisecond),
      metadata: metadata
    }

    # Schedule inactivity check
    schedule_inactivity_check()

    Logger.info("Started Run.State for #{run_id}")
    {:ok, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, touch(state)}
  end

  @impl true
  def handle_call(:get_history, _from, state) do
    {:reply, state.request_history, touch(state)}
  end

  @impl true
  def handle_cast({:record_request, request}, state) do
    entry = %{
      type: :request,
      timestamp: DateTime.utc_now(),
      data: request
    }

    new_state = %{state | request_history: [entry | state.request_history]}
    {:noreply, touch(new_state)}
  end

  @impl true
  def handle_cast({:record_response, response}, state) do
    entry = %{
      type: :response,
      timestamp: DateTime.utc_now(),
      data: response
    }

    new_state = %{state | request_history: [entry | state.request_history]}

    # Update status based on response
    new_state =
      case response do
        %{"error" => _} -> %{new_state | status: :failed}
        _ -> new_state
      end

    {:noreply, touch(new_state)}
  end

  @impl true
  def handle_cast({:set_status, status, error}, state) do
    new_state = %{
      state
      | status: status,
        error: error,
        completed_at: if(status in [:completed, :failed], do: DateTime.utc_now())
    }

    {:noreply, touch(new_state)}
  end

  @impl true
  def handle_info({:python_notification, run_id, message}, state) do
    # Handle notifications from Python worker
    Logger.debug("Received notification for run #{run_id}: #{inspect(message)}")

    # Record in history
    entry = %{
      type: :notification,
      timestamp: DateTime.utc_now(),
      data: message
    }

    new_state = %{state | request_history: [entry | state.request_history]}

    # Handle specific notification types
    new_state =
      case message do
        %{"method" => "tool_executed", "params" => params} ->
          # Handle tool execution notification
          handle_tool_executed(new_state, params)

        %{"method" => "run_completed", "params" => _params} ->
          %{new_state | status: :completed, completed_at: DateTime.utc_now()}

        %{"method" => "run_failed", "params" => params} ->
          %{
            new_state
            | status: :failed,
              error: params["error"],
              completed_at: DateTime.utc_now()
          }

        _ ->
          new_state
      end

    {:noreply, touch(new_state)}
  end

  @impl true
  def handle_info(:check_inactivity, state) do
    now = System.monotonic_time(:millisecond)
    elapsed = now - state.last_activity

    cond do
      state.status in [:completed, :failed] and elapsed > @inactivity_timeout ->
        Logger.info("Run #{state.run_id} inactive after completion, shutting down")
        {:stop, :normal, state}

      elapsed > @inactivity_timeout * 2 ->
        # Force shutdown even if still running (something is wrong)
        Logger.warning("Run #{state.run_id} stuck for too long, forcing shutdown")
        WorkerSupervisor.terminate_worker(state.run_id)
        {:stop, :normal, state}

      true ->
        schedule_inactivity_check()
        {:noreply, state}
    end
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("Run.State received unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # Private functions

  defp touch(state) do
    %{state | last_activity: System.monotonic_time(:millisecond)}
  end

  defp schedule_inactivity_check do
    Process.send_after(self(), :check_inactivity, @inactivity_timeout)
  end

  defp handle_tool_executed(state, params) do
    # Update metadata with tool execution info
    tool_name = params["tool_name"]
    _tool_result = params["result"]

    tools = Map.get(state.metadata, :tools_executed, [])
    new_metadata = Map.put(state.metadata, :tools_executed, [tool_name | tools])

    %{state | metadata: new_metadata}
  end
end
