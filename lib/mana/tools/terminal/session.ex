defmodule Mana.Tools.Terminal.Session do
  @moduledoc """
  GenServer managing a single PTY session via an Erlang Port.

  Each session wraps an interactive shell process (zsh/bash) and provides
  bidirectional communication for sending commands and reading output.

  ## Architecture

  ```
  ┌───────────────────────────┐     stdin (bytes)     ┌─────────────────┐
  │  Mana.Tools.Terminal      │ ──────────────────▶   │  Shell Process  │
  │       .Session            │                       │  (zsh / bash)   │
  │      (GenServer)          │ ◀──────────────────   │                 │
  └───────────────────────────┘     stdout (bytes)     └─────────────────┘
          │
          │  Port.open({:spawn_executable, shell}, ...)
          │
    Erlang Port
  ```

  ## Command Completion Detection

  When `run_command/2` is called, we inject a sentinel echo after the
  user's command:

      <user_command>\\necho __MANA_DONE_<unique_id>__

  We watch the output buffer for the sentinel to appear. When it does,
  we extract the output before the sentinel and reply to the caller.
  A timeout fallback ensures we don't block forever.

  ## Session Lifecycle

  Sessions are started under `Mana.Terminal.SessionSupervisor`
  (a DynamicSupervisor) and registered in `Mana.Terminal.SessionRegistry`
  (a Registry) for fast lookup by session_id.

  ## Error Handling

  - Port crashes are detected via `{:EXIT, port, reason}` and the state
    is marked as disconnected
  - Callers receive `{:error, :port_disconnected}` when the port is down
  - The session GenServer itself stays alive so the caller can query
    the last known state
  """

  use GenServer

  require Logger

  @default_timeout 30_000
  @default_max_buffer_size 100_000

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @type state_status :: :disconnected | :ready | :waiting

  @type state :: %__MODULE__{
          session_id: String.t(),
          port: port() | nil,
          shell: String.t(),
          status: state_status(),
          buffer: binary(),
          max_buffer_size: pos_integer(),
          timeout: pos_integer(),
          waiting_caller: {pid(), reference()} | nil,
          sentinel: String.t() | nil,
          command_start_pos: non_neg_integer(),
          command_timer: reference() | nil
        }

  defstruct [
    :session_id,
    :port,
    :shell,
    status: :disconnected,
    buffer: "",
    max_buffer_size: @default_max_buffer_size,
    timeout: @default_timeout,
    waiting_caller: nil,
    sentinel: nil,
    command_start_pos: 0,
    command_timer: nil
  ]

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @doc """
  Starts a terminal session GenServer.

  ## Options

    - `:session_id` (required) — Unique identifier for the session
    - `:shell` — Path to the shell executable (default: $SHELL or /bin/bash)
    - `:timeout` — Command execution timeout in ms (default: 30_000)
    - `:max_buffer_size` — Maximum output buffer size in bytes (default: 100_000)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    session_id = Keyword.fetch!(opts, :session_id)
    GenServer.start_link(__MODULE__, opts, name: via_tuple(session_id))
  end

  @doc """
  Returns the child specification for DynamicSupervisor.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: {__MODULE__, Keyword.get(opts, :session_id)},
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :transient
    }
  end

  @doc """
  Sends a command to the shell and waits for completion.

  Uses sentinel-based detection: injects `echo __MANA_DONE_<id>__`
  after the command and watches for it in the output.
  """
  @spec run_command(pid(), String.t()) :: {:ok, String.t()} | {:error, term()}
  def run_command(pid, command) do
    GenServer.call(pid, {:run_command, command}, :infinity)
  end

  @doc """
  Sends raw keystrokes to the shell (no newline appended).
  """
  @spec send_keys(pid(), String.t()) :: :ok | {:error, term()}
  def send_keys(pid, keys) do
    GenServer.call(pid, {:send_keys, keys})
  end

  @doc """
  Reads and clears the current output buffer.
  """
  @spec read_output(pid()) :: {:ok, String.t()} | {:error, term()}
  def read_output(pid) do
    GenServer.call(pid, :read_output)
  end

  @doc """
  Returns session metadata without clearing the buffer.
  """
  @spec get_info(pid()) :: {:ok, map()} | {:error, term()}
  def get_info(pid) do
    GenServer.call(pid, :get_info)
  end

  @doc """
  Returns the VIA tuple for Registry-based process lookup.
  """
  @spec via_tuple(String.t()) :: {:via, Registry, {Registry.registry(), String.t()}}
  def via_tuple(session_id) do
    {:via, Registry, {Mana.Terminal.SessionRegistry, session_id}}
  end

  @doc """
  Looks up the PID for a session by ID.
  """
  @spec lookup(String.t()) :: {:ok, pid()} | {:error, :not_found}
  def lookup(session_id) do
    case Registry.lookup(Mana.Terminal.SessionRegistry, session_id) do
      [{pid, _}] -> {:ok, pid}
      [] -> {:error, :not_found}
    end
  end

  # ---------------------------------------------------------------------------
  # GenServer Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(opts) do
    session_id = Keyword.fetch!(opts, :session_id)
    shell = Keyword.get(opts, :shell, default_shell())
    timeout = Keyword.get(opts, :timeout, @default_timeout)
    max_buffer_size = Keyword.get(opts, :max_buffer_size, @default_max_buffer_size)

    case open_port(shell) do
      {:ok, port} ->
        Process.flag(:trap_exit, true)

        state = %__MODULE__{
          session_id: session_id,
          port: port,
          shell: shell,
          status: :ready,
          timeout: timeout,
          max_buffer_size: max_buffer_size
        }

        Logger.info("[#{__MODULE__}] Session #{session_id} started (#{shell})")
        {:ok, state}

      {:error, reason} ->
        Logger.error("[#{__MODULE__}] Failed to start session #{session_id}: #{inspect(reason)}")
        {:stop, reason}
    end
  end

  @impl true
  def handle_call({:run_command, _command}, _from, %{status: :disconnected} = state) do
    {:reply, {:error, :port_disconnected}, state}
  end

  @impl true
  def handle_call({:run_command, _command}, _from, %{status: :waiting} = state) do
    {:reply, {:error, :command_in_progress}, state}
  end

  @impl true
  def handle_call({:run_command, command}, from, %{status: :ready, port: port} = state) do
    sentinel = generate_sentinel()

    # Send the command followed by a sentinel echo
    full_input = "#{command}\necho '#{sentinel}'\n"
    Port.command(port, String.to_charlist(full_input))

    timer = Process.send_after(self(), :command_timeout, state.timeout)

    new_state = %{
      state
      | waiting_caller: from,
        sentinel: sentinel,
        command_start_pos: byte_size(state.buffer),
        command_timer: timer,
        status: :waiting
    }

    {:noreply, new_state}
  end

  @impl true
  def handle_call({:send_keys, _keys}, _from, %{status: :disconnected} = state) do
    {:reply, {:error, :port_disconnected}, state}
  end

  @impl true
  def handle_call({:send_keys, keys}, _from, %{port: port} = state) do
    Port.command(port, String.to_charlist(keys))
    {:reply, :ok, state}
  end

  @impl true
  def handle_call(:read_output, _from, state) do
    output = state.buffer
    {:reply, {:ok, output}, %{state | buffer: ""}}
  end

  @impl true
  def handle_call(:get_info, _from, state) do
    info = %{
      session_id: state.session_id,
      shell: state.shell,
      status: state.status,
      buffer_size: byte_size(state.buffer),
      waiting: state.waiting_caller != nil
    }

    {:reply, {:ok, info}, state}
  end

  @impl true
  def handle_call(:stop, _from, state) do
    {:stop, :normal, :ok, state}
  end

  # --- Port data handling ---

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = state) when is_binary(data) do
    new_buffer = append_to_buffer(state.buffer, data, state.max_buffer_size)

    case state.waiting_caller do
      nil ->
        {:noreply, %{state | buffer: new_buffer}}

      _from ->
        if state.sentinel && String.contains?(new_buffer, state.sentinel) do
          resolve_command(state, new_buffer)
        else
          # Reset timeout timer on each new data chunk
          if state.command_timer, do: Process.cancel_timer(state.command_timer)
          timer = Process.send_after(self(), :command_timeout, state.timeout)
          {:noreply, %{state | buffer: new_buffer, command_timer: timer}}
        end
    end
  end

  # Line-delimited data (when using {:line, N} option)
  @impl true
  def handle_info({port, {:data, {:eol, line}}}, %{port: port} = state) do
    handle_info({port, {:data, line <> "\n"}}, state)
  end

  @impl true
  def handle_info({port, {:data, {:noeol, fragment}}}, %{port: port} = state) do
    handle_info({port, {:data, fragment}}, state)
  end

  # Command timeout — reply with what we have so far
  @impl true
  def handle_info(:command_timeout, %{waiting_caller: nil} = state) do
    {:noreply, state}
  end

  @impl true
  def handle_info(:command_timeout, state) do
    Logger.warning("[#{__MODULE__}] Command timeout for session #{state.session_id}")

    output = extract_output(state.buffer, state.command_start_pos)
    GenServer.reply(state.waiting_caller, {:ok, output})

    {:noreply, %{state | waiting_caller: nil, sentinel: nil, command_timer: nil, status: :ready}}
  end

  # Port exit detection
  @impl true
  def handle_info({:EXIT, port, reason}, %{port: port} = state) do
    Logger.error("[#{__MODULE__}] Port exited for session #{state.session_id}: #{inspect(reason)}")

    # Reply to any waiting caller
    if state.waiting_caller do
      GenServer.reply(state.waiting_caller, {:error, :port_disconnected})
    end

    {:noreply, %{state | port: nil, status: :disconnected, waiting_caller: nil, sentinel: nil, command_timer: nil}}
  end

  # Ignore DOWN messages from monitors we don't track
  @impl true
  def handle_info({:DOWN, _ref, :process, _pid, _reason}, state) do
    {:noreply, state}
  end

  # Catch-all for unexpected messages
  @impl true
  def handle_info(msg, state) do
    Logger.debug("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  @impl true
  def terminate(reason, state) do
    Logger.info("[#{__MODULE__}] Session #{state.session_id} terminating: #{inspect(reason)}")

    if state.port do
      try do
        Port.close(state.port)
      rescue
        _ -> :ok
      end
    end

    :ok
  end

  # ---------------------------------------------------------------------------
  # Internal: Port Management
  # ---------------------------------------------------------------------------

  @spec open_port(String.t()) :: {:ok, port()} | {:error, term()}
  defp open_port(shell) do
    shell_path = String.to_charlist(shell)

    if System.find_executable(shell) do
      try do
        port =
          Port.open(
            {:spawn_executable, shell_path},
            [
              :binary,
              :exit_status,
              :use_stdio,
              :stderr_to_std_err
            ]
          )

        {:ok, port}
      rescue
        e ->
          {:error, e}
      end
    else
      {:error, {:shell_not_found, shell}}
    end
  end

  # ---------------------------------------------------------------------------
  # Internal: Command Resolution
  # ---------------------------------------------------------------------------

  @spec resolve_command(state(), binary()) :: {:noreply, state()}
  defp resolve_command(state, buffer) do
    # Cancel the timeout timer
    if state.command_timer, do: Process.cancel_timer(state.command_timer)

    # Extract output between command start and sentinel
    output = extract_output_before_sentinel(buffer, state.sentinel, state.command_start_pos)

    # Clean sentinel from the buffer
    cleaned_buffer =
      buffer
      |> String.split(state.sentinel, parts: 2)
      |> List.last()
      |> String.trim_leading("\n")

    GenServer.reply(state.waiting_caller, {:ok, output})

    {:noreply,
     %{state | buffer: cleaned_buffer, waiting_caller: nil, sentinel: nil, command_timer: nil, status: :ready}}
  end

  @spec extract_output_before_sentinel(binary(), String.t(), non_neg_integer()) :: String.t()
  defp extract_output_before_sentinel(buffer, sentinel, start_pos) do
    # Get everything after start_pos
    output_after_start = binary_part(buffer, start_pos, byte_size(buffer) - start_pos)

    # Remove the sentinel and the echo command that produced it
    output_after_start
    |> String.split(sentinel)
    |> List.first()
    |> String.trim_trailing("\n")
    |> strip_echo_line(sentinel)
  end

  @spec extract_output(binary(), non_neg_integer()) :: String.t()
  defp extract_output(buffer, start_pos) when start_pos >= byte_size(buffer) do
    ""
  end

  defp extract_output(buffer, start_pos) do
    binary_part(buffer, start_pos, byte_size(buffer) - start_pos)
  end

  # Strip the line that echoes the sentinel (it might contain the original echo command)
  @spec strip_echo_line(String.t(), String.t()) :: String.t()
  defp strip_echo_line(output, sentinel) do
    # Remove any line containing the sentinel text
    output
    |> String.split("\n")
    |> Enum.reject(fn line -> String.contains?(line, sentinel) end)
    |> Enum.join("\n")
  end

  # ---------------------------------------------------------------------------
  # Internal: Buffer Management
  # ---------------------------------------------------------------------------

  @spec append_to_buffer(binary(), binary(), pos_integer()) :: binary()
  defp append_to_buffer(buffer, data, max_size) do
    new_buffer = buffer <> data

    if byte_size(new_buffer) > max_size do
      # Keep only the last max_size bytes
      binary_part(new_buffer, byte_size(new_buffer) - max_size, max_size)
    else
      new_buffer
    end
  end

  # ---------------------------------------------------------------------------
  # Internal: Helpers
  # ---------------------------------------------------------------------------

  @spec generate_sentinel() :: String.t()
  defp generate_sentinel do
    id = :erlang.unique_integer([:positive])
    "__MANA_CMD_DONE_#{id}__"
  end

  @spec default_shell() :: String.t()
  defp default_shell do
    System.get_env("SHELL") || "/bin/bash"
  end
end
