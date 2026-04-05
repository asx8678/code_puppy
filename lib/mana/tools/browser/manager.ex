defmodule Mana.Tools.Browser.Manager do
  @moduledoc """
  GenServer that manages a Playwright browser process via an Erlang Port.

  Spawns a Node.js child process running a Playwright bridge script and
  communicates with it using JSON-RPC style messages over stdin/stdout.

  ## Architecture

  ```
  ┌──────────────────────┐      stdin (JSON)     ┌─────────────────────────┐
  │  Mana.Tools.Browser  │ ──────────────────▶   │  Node.js Bridge Script  │
  │       .Manager       │                       │  (Playwright)           │
  │      (GenServer)     │ ◀──────────────────   │                         │
  └──────────────────────┘      stdout (JSON)     └─────────────────────────┘
          │
          │  Port.open({:spawn_executable, node}, ...)
          │
    Erlang Port
  ```

  ## Lifecycle

  The Manager is **not** started in the application supervision tree by
  default. It is started lazily on first use:

      # First call starts the GenServer (and the Node.js process)
      {:ok, result} = Mana.Tools.Browser.Manager.execute("navigate", %{"url" => "https://example.com"})

  Alternatively, you can start it explicitly:

      {:ok, pid} = Mana.Tools.Browser.Manager.start_browser()

  ## Supervision

  When started via `ensure_started/0`, the Manager is placed under
  `Mana.BrowserSupervisor` (a DynamicSupervisor) with a `:transient`
  restart strategy — it only restarts on abnormal exits.

  ## Error Handling

  - Port crashes are detected via `{:EXIT, port, reason}` and the state
    is set to `:disconnected`
  - Callers receive `{:error, :port_disconnected}` when the port is down
  - The Manager can be restarted with `start_browser/0` after a crash

  ## Wire Protocol

  See `Mana.Tools.Browser.Protocol` for the JSON-RPC message format.
  """

  use GenServer

  require Logger

  alias Mana.Tools.Browser.Protocol

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type state_status :: :disconnected | :connecting | :ready | :busy

  @type state :: %__MODULE__{
          port: port() | nil,
          status: state_status(),
          script_path: String.t(),
          node_path: String.t(),
          request_id: non_neg_integer(),
          pending: %{optional(Protocol.command_id()) => GenServer.from()},
          buffer: binary()
        }

  @type execute_result :: {:ok, map()} | {:error, term()}

  defstruct [
    :port,
    status: :disconnected,
    script_path: "",
    node_path: "node",
    request_id: 0,
    pending: %{},
    buffer: ""
  ]

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @doc """
  Starts the Browser Manager and the underlying Node.js Playwright process.

  If the Manager is already running and connected, returns `{:ok, pid}`.

  ## Returns

    - `{:ok, pid}` — Manager started successfully
    - `{:error, reason}` — Startup failed

  ## Examples

      {:ok, pid} = Mana.Tools.Browser.Manager.start_browser()
  """
  @spec start_browser() :: GenServer.on_start() | {:error, term()}
  def start_browser do
    ensure_started()
  end

  @doc """
  Stops the Browser Manager gracefully.

  Closes the port (which terminates the Node.js process) and stops the GenServer.

  ## Returns

    - `:ok` — Manager stopped successfully
    - `{:error, reason}` — Stop failed
  """
  @spec stop_browser() :: :ok | {:error, term()}
  def stop_browser do
    if pid = Process.whereis(__MODULE__) do
      GenServer.call(pid, :stop_browser)
    else
      {:error, :not_running}
    end
  end

  @doc """
  Sends a command to the Playwright bridge and waits for the response.

  This is the primary API for executing browser operations. The Manager
  must be started first (it will be lazily started if not already running).

  ## Parameters

    - `command_name` — The Playwright command (e.g. "navigate", "click", "screenshot")
    - `args` — A map of command arguments

  ## Returns

    - `{:ok, result_map}` — Command succeeded
    - `{:error, reason}` — Command failed or Manager is disconnected

  ## Examples

      {:ok, %{"url" => "https://example.com"}} =
        Mana.Tools.Browser.Manager.execute("navigate", %{"url" => "https://example.com"})

      {:ok, %{"success" => true}} =
        Mana.Tools.Browser.Manager.execute("click", %{"selector" => "#submit"})
  """
  @spec execute(Protocol.command_name(), Protocol.params()) :: execute_result()
  def execute(command_name, args) do
    ensure_started()
    GenServer.call(__MODULE__, {:execute, command_name, args}, 30_000)
  end

  @doc """
  Returns the current status of the Browser Manager.

  ## Returns

    - `%{status: atom(), connected: boolean(), pending_count: non_neg_integer()}`
  """
  @spec get_status() :: map()
  def get_status do
    if pid = Process.whereis(__MODULE__) do
      GenServer.call(pid, :get_status)
    else
      %{status: :not_started, connected: false, pending_count: 0}
    end
  end

  # ---------------------------------------------------------------------------
  # Lazy Start
  # ---------------------------------------------------------------------------

  @doc """
  Ensures the Browser Manager GenServer is running.

  If not already running, starts it under `Mana.BrowserSupervisor`
  with a `:transient` restart strategy. The Node.js process is not
  spawned until `start_browser/0` or `execute/2` is called.

  ## Returns

    - `{:ok, pid}` — Manager is running
    - `{:error, reason}` — Could not start
  """
  @spec ensure_started() :: GenServer.on_start() | {:error, term()}
  def ensure_started do
    case Process.whereis(__MODULE__) do
      nil ->
        # Ensure the DynamicSupervisor exists for lazy starts
        ensure_browser_supervisor()

        case DynamicSupervisor.start_child(
               Mana.BrowserSupervisor,
               child_spec([])
             ) do
          {:ok, pid} ->
            {:ok, pid}

          {:error, {:already_started, pid}} ->
            {:ok, pid}

          {:error, reason} ->
            Logger.error("[#{__MODULE__}] Failed to start: #{inspect(reason)}")
            {:error, reason}
        end

      pid ->
        if Process.alive?(pid) do
          {:ok, pid}
        else
          # Process registered but dead — wait for cleanup and retry
          Process.unregister(__MODULE__)
          ensure_started()
        end
    end
  end

  defp ensure_browser_supervisor do
    case Process.whereis(Mana.BrowserSupervisor) do
      nil ->
        spec = %{
          id: Mana.BrowserSupervisor,
          start: {DynamicSupervisor, :start_link, [[strategy: :one_for_one, name: Mana.BrowserSupervisor]]},
          type: :supervisor
        }

        case Supervisor.start_child(Mana.Supervisor, spec) do
          {:ok, _pid} -> :ok
          {:error, {:already_started, _pid}} -> :ok
          {:error, reason} -> Logger.warning("[#{__MODULE__}] Could not start BrowserSupervisor: #{inspect(reason)}")
        end

      _pid ->
        :ok
    end
  end

  # ---------------------------------------------------------------------------
  # Child Spec (transient restart)
  # ---------------------------------------------------------------------------

  @doc """
  Returns the child specification for supervision trees.

  Uses `:transient` restart strategy — the process is restarted only
  if it terminates abnormally.
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

  @doc false
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  # ---------------------------------------------------------------------------
  # GenServer Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(opts) do
    state = %__MODULE__{
      script_path: Keyword.get(opts, :script_path, default_script_path()),
      node_path: Keyword.get(opts, :node_path, System.find_executable("node") || "node"),
      status: :disconnected
    }

    # We do NOT start the port here — it is started lazily on first command
    # or when start_browser/0 is called explicitly.
    {:ok, state}
  end

  @impl true
  def handle_call(:stop_browser, _from, state) do
    if state.port do
      Port.close(state.port)
    end

    {:stop, :normal, :ok, %{state | port: nil, status: :disconnected, pending: %{}, buffer: ""}}
  end

  @impl true
  def handle_call(:get_status, _from, state) do
    status = %{
      status: state.status,
      connected: state.port != nil and state.status in [:ready, :busy],
      pending_count: map_size(state.pending)
    }

    {:reply, status, state}
  end

  @impl true
  def handle_call({:execute, command_name, args}, from, %{status: :disconnected} = state) do
    # Lazily start the port on first command
    case open_port(state) do
      {:ok, new_state} ->
        handle_call({:execute, command_name, args}, from, %{new_state | status: :ready})

      {:error, reason} ->
        {:reply, {:error, {:port_start_failed, reason}}, state}
    end
  end

  @impl true
  def handle_call({:execute, command_name, args}, from, %{status: status} = state)
      when status in [:ready, :busy] do
    request_id = state.request_id + 1

    case Protocol.encode_command(command_name, args, id: request_id) do
      {:ok, json} ->
        send_command(state.port, json)

        new_pending = Map.put(state.pending, request_id, from)
        # Monitor the caller so we can clean up if they crash
        {pid, _tag} = from
        Process.monitor(pid, tag: {:caller_down, request_id})

        {:noreply, %{state | request_id: request_id, pending: new_pending, status: :busy}}

      {:error, reason} ->
        {:reply, {:error, reason}, state}
    end
  end

  @impl true
  def handle_call({:execute, _command_name, _args}, _from, %{status: :connecting} = state) do
    {:reply, {:error, :connecting}, state}
  end

  @impl true
  def handle_info({:caller_down, request_id, _mon}, state) do
    # Caller crashed before we replied — clean up pending request
    new_pending = Map.delete(state.pending, request_id)
    new_status = if map_size(new_pending) == 0, do: :ready, else: state.status
    {:noreply, %{state | pending: new_pending, status: new_status}}
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, _pid, {:caller_down, _request_id}}, state) do
    {:noreply, state}
  end

  @impl true
  def handle_info({port, {:data, {:eol, line}}}, %{port: port} = state) do
    new_state = handle_response_line(state, line)
    {:noreply, new_state}
  end

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = state) when is_binary(data) do
    # Accumulate partial lines (fallback for non-line-delimited data)
    new_buffer = state.buffer <> data

    case String.split(new_buffer, "\n", parts: 2) do
      [line, rest] ->
        new_state =
          state
          |> Map.put(:buffer, rest)
          |> handle_response_line(line)

        {:noreply, new_state}

      _ ->
        {:noreply, %{state | buffer: new_buffer}}
    end
  end

  @impl true
  def handle_info({:EXIT, port, reason}, %{port: port} = state) do
    Logger.error("[#{__MODULE__}] Port exited: #{inspect(reason)}")

    # Reply to all pending callers with an error
    Enum.each(state.pending, fn {_id, from} ->
      GenServer.reply(from, {:error, :port_disconnected})
    end)

    {:noreply, %{state | port: nil, status: :disconnected, pending: %{}, buffer: ""}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ---------------------------------------------------------------------------
  # Internal: Port Management
  # ---------------------------------------------------------------------------

  @spec open_port(state()) :: {:ok, state()} | {:error, term()}
  defp open_port(%{script_path: script_path, node_path: node_path} = state) do
    if not File.exists?(script_path) do
      Logger.warning("[#{__MODULE__}] Bridge script not found at #{script_path}, using stub mode")
      # Return ok without opening a port — execute calls will fail gracefully
      {:ok, %{state | status: :ready}}
    else
      try do
        port =
          Port.open(
            {:spawn_executable, String.to_charlist(node_path)},
            [
              {:args, [String.to_charlist(script_path)]},
              :binary,
              :exit_status,
              :use_stdio,
              :stderr_to_std_err,
              {:line, 4096}
            ]
          )

        # Link to receive EXIT messages
        Process.flag(:trap_exit, true)
        Port.connect(port, self())

        Logger.info("[#{__MODULE__}] Started Playwright bridge: #{node_path} #{script_path}")
        {:ok, %{state | port: port, status: :ready}}
      rescue
        e ->
          Logger.error("[#{__MODULE__}] Failed to open port: #{inspect(e)}")
          {:error, e}
      end
    end
  end

  @spec send_command(port(), binary()) :: boolean()
  defp send_command(port, json) do
    Port.command(port, String.to_charlist(json))
  end

  # ---------------------------------------------------------------------------
  # Internal: Response Handling
  # ---------------------------------------------------------------------------

  @spec handle_response_line(state(), binary()) :: state()
  defp handle_response_line(state, line) do
    line = String.trim(line)

    if line == "" do
      state
    else
      case Protocol.decode_response(line) do
        {:ok, response} ->
          resolve_response(state, response)

        {:error, reason} ->
          Logger.warning("[#{__MODULE__}] Failed to decode response: #{inspect(reason)} line: #{truncate(line, 200)}")
          state
      end
    end
  end

  @spec resolve_response(state(), map()) :: state()
  defp resolve_response(state, %{"id" => id} = response) do
    case Map.pop(state.pending, id) do
      {nil, _pending} ->
        # No pending request for this ID — ignore (could be a duplicate)
        state

      {from, new_pending} ->
        result = Protocol.classify(response)
        GenServer.reply(from, result)

        new_status = if map_size(new_pending) == 0, do: :ready, else: :busy
        %{state | pending: new_pending, status: new_status}
    end
  end

  defp resolve_response(state, _response) do
    # Response without an ID — ignore
    state
  end

  # ---------------------------------------------------------------------------
  # Internal: Helpers
  # ---------------------------------------------------------------------------

  @spec default_script_path() :: String.t()
  defp default_script_path do
    :code.priv_dir(:mana)
    |> to_string()
    |> Path.join("browser_bridge.js")
  end

  @spec truncate(String.t(), non_neg_integer()) :: String.t()
  defp truncate(string, max_length) when byte_size(string) > max_length do
    String.slice(string, 0, max_length) <> "..."
  end

  defp truncate(string, _max_length), do: string
end
