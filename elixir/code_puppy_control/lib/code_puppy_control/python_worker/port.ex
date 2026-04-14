defmodule CodePuppyControl.PythonWorker.Port do
  @moduledoc """
  GenServer that owns a Python Port for JSON-RPC communication.

  This process:
  1. Spawns a Python worker via Port
  2. Sends JSON-RPC commands using Content-Length framing
  3. Receives notifications and responses
  4. Monitors the Python process for exit
  5. Handles restart via DynamicSupervisor

  ## Framing

  Messages are framed using Content-Length HTTP-style headers:

      Content-Length: 47\r\n
      \r\n
      {"jsonrpc":"2.0","id":1,"method":"initialize"}
  """

  use GenServer

  require Logger

  alias CodePuppyControl.Protocol

  defstruct [:port, :run_id, :buffer, :request_counter, :parent_pid]

  @type t :: %__MODULE__{
          port: port() | nil,
          run_id: String.t(),
          buffer: String.t(),
          request_counter: non_neg_integer(),
          parent_pid: pid()
        }

  # Client API

  @doc """
  Starts a linked PythonWorker.Port for a specific run.

  ## Options

    * `:run_id` - Required. The run identifier this worker handles.
    * `:script_path` - Optional. Path to Python worker script. Defaults to application config.
    * `:parent` - Optional. PID to monitor. When parent exits, worker exits.

  """
  def start_link(opts) do
    run_id = Keyword.fetch!(opts, :run_id)
    GenServer.start_link(__MODULE__, opts, name: via_tuple(run_id))
  end

  @doc """
  Returns a `via_tuple` for Registry lookup.
  """
  def via_tuple(run_id) do
    {:via, Registry, {CodePuppyControl.Run.Registry, {:python_worker, run_id}}}
  end

  @doc """
  Sends a JSON-RPC request to the Python worker and awaits response.

  Returns `{:ok, result}` or `{:error, reason}`.
  """
  @spec call(String.t(), String.t(), map(), timeout()) :: {:ok, term()} | {:error, term()}
  def call(run_id, method, params, timeout \\ 30_000) do
    GenServer.call(via_tuple(run_id), {:call, method, params, timeout}, timeout + 5000)
  end

  @doc """
  Sends a JSON-RPC notification to the Python worker (no response expected).
  """
  @spec notify(String.t(), String.t(), map()) :: :ok
  def notify(run_id, method, params) do
    GenServer.cast(via_tuple(run_id), {:notify, method, params})
  end

  @doc """
  Looks up the run_id for a given Port PID.
  """
  @spec pid_to_run_id(pid()) :: {:ok, String.t()} | :error
  def pid_to_run_id(pid) do
    case Registry.keys(CodePuppyControl.Run.Registry, pid) do
      [{:python_worker, run_id} | _] -> {:ok, run_id}
      _ -> :error
    end
  end

  @doc """
  Gracefully shuts down the Python worker.
  """
  @spec shutdown(String.t()) :: :ok
  def shutdown(run_id) do
    GenServer.cast(via_tuple(run_id), :shutdown)
  end

  # Server Callbacks

  @impl true
  def init(opts) do
    run_id = Keyword.fetch!(opts, :run_id)
    parent_pid = Keyword.get(opts, :parent, self())
    script_path = get_script_path(opts)

    # Monitor the parent so we exit when it does
    Process.monitor(parent_pid)

    Logger.info("Starting Python worker for run #{run_id}")

    port_opts = [
      :binary,
      :use_stdio,
      :exit_status,
      :stderr_to_stdout,
      args: [script_path, "--run-id", run_id]
    ]

    port = Port.open({:spawn, "python3"}, port_opts)

    state = %__MODULE__{
      port: port,
      run_id: run_id,
      buffer: "",
      request_counter: 0,
      parent_pid: parent_pid
    }

    # Send initialize request
    send(self(), :send_initialize)

    {:ok, state}
  end

  @impl true
  def handle_call({:call, method, params, timeout}, from, state) do
    request_id = generate_request_id(state)

    message = Protocol.encode_request(method, params, request_id)
    framed = Protocol.frame(message)

    Port.command(state.port, framed)

    # Register with RequestTracker for async response handling
    Task.start(fn ->
      case CodePuppyControl.RequestTracker.await_request(request_id, method, timeout) do
        {:ok, result} ->
          GenServer.reply(from, {:ok, result})

        {:error, reason} ->
          GenServer.reply(from, {:error, reason})
      end
    end)

    new_state = %{state | request_counter: state.request_counter + 1}
    {:noreply, new_state}
  end

  @impl true
  def handle_cast({:notify, method, params}, state) do
    message = Protocol.encode_notification(method, params)
    framed = Protocol.frame(message)

    Port.command(state.port, framed)
    {:noreply, state}
  end

  @impl true
  def handle_cast(:shutdown, state) do
    Logger.info("Shutting down Python worker for run #{state.run_id}")

    # Send exit notification
    message = Protocol.encode_notification("exit", %{"code" => 0})
    framed = Protocol.frame(message)
    Port.command(state.port, framed)

    # Close the port
    Port.close(state.port)

    {:stop, :normal, %{state | port: nil}}
  end

  @impl true
  def handle_info(:send_initialize, state) do
    # Send initialize notification to Python worker
    message = Protocol.encode_notification("initialize", %{
      "run_id" => state.run_id,
      "elixir_pid" => :erlang.pid_to_list(self())
    })

    framed = Protocol.frame(message)
    Port.command(state.port, framed)

    {:noreply, state}
  end

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = state) do
    new_buffer = state.buffer <> data
    {messages, rest} = Protocol.parse_framed(new_buffer)

    # Process each message
    for message <- messages do
      handle_message(message, state.run_id)
    end

    {:noreply, %{state | buffer: rest}}
  end

  @impl true
  def handle_info({port, {:exit_status, status}}, %{port: port} = state) do
    if status != 0 do
      Logger.error("Python worker exited with status #{status} for run #{state.run_id}")
    else
      Logger.info("Python worker exited normally for run #{state.run_id}")
    end

    {:stop, {:port_exit, status}, %{state | port: nil}}
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, pid, reason}, %{parent_pid: pid} = state) do
    Logger.info("Parent process #{inspect(pid)} exited (#{inspect(reason)}), stopping worker")
    {:stop, :normal, state}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  @impl true
  def terminate(_reason, state) do
    if state.port do
      Port.close(state.port)
    end

    :ok
  end

  # Private functions

  defp handle_message(%{"id" => id, "result" => result}, _run_id) do
    CodePuppyControl.RequestTracker.complete_request(id, result)
  end

  defp handle_message(%{"id" => id, "error" => error}, _run_id) do
    CodePuppyControl.RequestTracker.fail_request(id, {:python_error, error})
  end

  defp handle_message(message, run_id) when is_map(message) do
    # Notification - publish to PubSub
    Phoenix.PubSub.broadcast(
      CodePuppyControl.PubSub,
      "run:#{run_id}",
      {:python_notification, run_id, message}
    )
  end

  defp generate_request_id(state) do
    "#{state.run_id}-#{state.request_counter}-#{System.unique_integer([:positive])}"
  end

  defp get_script_path(opts) do
    Keyword.get(opts, :script_path) ||
      Application.get_env(:code_puppy_control, :python_worker_script) ||
      raise "Python worker script path not configured"
  end
end
