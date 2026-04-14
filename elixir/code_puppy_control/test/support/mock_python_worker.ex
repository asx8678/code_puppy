defmodule CodePuppyControl.MockPythonWorker do
  @moduledoc """
  Mock Python worker for testing without real Python process.

  This GenServer mimics the behavior of a Python worker process
  for isolated testing of the Elixir-side protocol handling.

  ## Usage

      {:ok, mock} = MockPythonWorker.start_link([])
      MockPythonWorker.handle_request(mock, "initialize", %{})

  """

  use GenServer

  alias CodePuppyControl.Protocol

  defstruct [:parent_pid, :request_handlers, :buffer]

  # Client API

  @doc """
  Starts a mock Python worker linked to the current process.
  """
  def start_link(opts \\ []) do
    parent_pid = Keyword.get(opts, :parent, self())
    GenServer.start_link(__MODULE__, parent_pid, opts)
  end

  @doc """
  Simulates receiving a framed request from Elixir.

  Returns the response that would be sent back.
  """
  @spec handle_request(pid(), String.t(), map()) :: {:ok, map()} | {:error, term()}
  def handle_request(pid, method, params) do
    GenServer.call(pid, {:handle_request, method, params})
  end

  @doc """
  Sends a mock notification to the parent process.
  """
  @spec send_notification(pid(), String.t(), map()) :: :ok
  def send_notification(pid, method, params) do
    GenServer.cast(pid, {:send_notification, method, params})
  end

  @doc """
  Sets a custom handler for a specific method.

  The handler function receives `(method, params)` and should return
  `{:ok, result}` or `{:error, reason}`.
  """
  @spec set_handler(pid(), String.t(), function()) :: :ok
  def set_handler(pid, method, handler) do
    GenServer.call(pid, {:set_handler, method, handler})
  end

  @doc """
  Simulates the Python worker crashing.
  """
  @spec crash(pid()) :: :ok
  def crash(pid) do
    GenServer.stop(pid, :simulated_crash)
  end

  # Server Callbacks

  @impl true
  def init(parent_pid) do
    # Monitor parent to simulate Python worker exit behavior
    Process.monitor(parent_pid)

    state = %__MODULE__{
      parent_pid: parent_pid,
      request_handlers: default_handlers(),
      buffer: ""
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:handle_request, method, params}, _from, state) do
    response = dispatch_request(state.request_handlers, method, params)
    {:reply, response, state}
  end

  @impl true
  def handle_call({:set_handler, method, handler}, _from, state) do
    new_handlers = Map.put(state.request_handlers, method, handler)
    {:reply, :ok, %{state | request_handlers: new_handlers}}
  end

  @impl true
  def handle_cast({:send_notification, method, params}, state) do
    notification = Protocol.encode_notification(method, params)
    send(state.parent_pid, {:mock_notification, notification})
    {:noreply, state}
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, pid, _reason}, %{parent_pid: pid} = state) do
    {:stop, :normal, state}
  end

  @impl true
  def handle_info(_msg, state) do
    {:noreply, state}
  end

  # Private Functions

  defp default_handlers do
    %{
      "initialize" => fn _method, _params ->
        {:ok, %{"status" => "initialized", "capabilities" => %{"mock" => true}}}
      end,
      "ping" => fn _method, _params ->
        {:ok, %{"pong" => true, "timestamp" => System.system_time(:millisecond)}}
      end,
      "echo" => fn _method, params ->
        {:ok, %{"echo" => params}}
      end,
      "run.agent" => fn _method, params ->
        # Simulate a successful agent run
        {:ok,
         %{
           "run_id" => params["run_id"] || "mock-run-id",
           "status" => "started",
           "agent" => params["agent"] || "unknown"
         }}
      end,
      "run.cancel" => fn _method, params ->
        {:ok, %{"run_id" => params["run_id"], "status" => "cancelled"}}
      end
    }
  end

  defp dispatch_request(handlers, method, params) do
    case Map.get(handlers, method) do
      nil ->
        {:error, {:method_not_found, "Method '#{method}' not found in mock worker"}}

      handler ->
        try do
          handler.(method, params)
        rescue
          e -> {:error, {:handler_exception, Exception.message(e)}}
        end
    end
  end
end
