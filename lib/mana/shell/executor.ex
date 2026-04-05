defmodule Mana.Shell.Executor do
  @moduledoc """
  GenServer managing shell command execution via Erlang Ports.

  Uses Ports (NOT threads) for process management. Port sends {:data, data}
  messages to the GenServer mailbox, which are handled via handle_info callbacks.

  ## Features

  - Synchronous command execution with timeout
  - Background command execution
  - Process monitoring and cleanup
  - Timeout handling via Process.send_after
  - User interruption support via kill_all/0

  ## Usage

      # Synchronous execution
      {:ok, result} = Executor.execute("ls -la", "/home/user", 30_000)

      # Background execution
      {:ok, ref} = Executor.execute_background("long_running.sh", "/tmp")

      # Kill all processes
      :ok = Executor.kill_all()
  """

  use GenServer

  require Logger

  alias Mana.Shell.Result

  defstruct processes: %{}, killed_refs: MapSet.new()

  # ============================================================================
  # API
  # ============================================================================

  @doc """
  Starts the Executor GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Executes a shell command synchronously with timeout.

  Returns {:ok, Result.t()} on success or timeout, {:error, term()} on failure.
  """
  @spec execute(String.t(), String.t(), integer()) :: {:ok, Result.t()} | {:error, term()}
  def execute(command, cwd, timeout) do
    GenServer.call(__MODULE__, {:execute, command, cwd, timeout}, timeout + 5_000)
  end

  @doc """
  Executes a shell command in the background.

  Returns {:ok, reference()} immediately. The caller can monitor the
  process via the returned reference.
  """
  @spec execute_background(String.t(), String.t()) :: {:ok, reference()} | {:error, term()}
  def execute_background(command, cwd) do
    GenServer.call(__MODULE__, {:execute_background, command, cwd})
  end

  @doc """
  Kills all running processes and marks them as user interrupted.

  Returns :ok after closing all ports.
  """
  @spec kill_all() :: :ok
  def kill_all do
    GenServer.call(__MODULE__, :kill_all)
  end

  @doc """
  Lists all currently running processes.

  Returns a list of tuples with {ref, command, started_at}.
  """
  @spec list_processes() :: list({reference(), String.t(), integer()})
  def list_processes do
    GenServer.call(__MODULE__, :list_processes)
  end

  # ============================================================================
  # GenServer Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    {:ok, %__MODULE__{}}
  end

  @impl true
  def handle_call({:execute, command, cwd, timeout}, from, state) do
    port = open_port(command, cwd)
    ref = Port.monitor(port)

    process_info = %{
      port: port,
      command: command,
      started_at: System.monotonic_time(:millisecond),
      caller: from,
      stdout: [],
      stderr: [],
      timeout: timeout
    }

    # Schedule timeout check
    Process.send_after(self(), {:check_timeout, ref}, timeout)

    new_state = %{state | processes: Map.put(state.processes, ref, process_info)}
    {:noreply, new_state}
  end

  @impl true
  def handle_call({:execute_background, command, cwd}, _from, state) do
    port = open_port(command, cwd)
    ref = Port.monitor(port)

    process_info = %{
      port: port,
      command: command,
      started_at: System.monotonic_time(:millisecond),
      caller: nil,
      stdout: [],
      stderr: [],
      timeout: nil
    }

    new_state = %{state | processes: Map.put(state.processes, ref, process_info)}
    {:reply, {:ok, ref}, new_state}
  end

  @impl true
  def handle_call(:kill_all, _from, state) do
    # Close all ports and mark as killed
    killed_refs =
      Enum.reduce(state.processes, state.killed_refs, fn {ref, process}, acc ->
        Port.close(process.port)
        MapSet.put(acc, ref)
      end)

    new_state = %{state | processes: %{}, killed_refs: killed_refs}
    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call(:list_processes, _from, state) do
    processes =
      Enum.map(state.processes, fn {ref, process} ->
        {ref, process.command, process.started_at}
      end)

    {:reply, processes, state}
  end

  @impl true
  def handle_info({port, {:data, {:eol, line}}}, state) when is_port(port) do
    case find_by_port(state.processes, port) do
      {ref, process} ->
        updated = %{process | stdout: [line | process.stdout]}
        new_processes = Map.put(state.processes, ref, updated)
        {:noreply, %{state | processes: new_processes}}

      nil ->
        # Port not found, may have been cleaned up already
        {:noreply, state}
    end
  end

  @impl true
  def handle_info({port, {:data, data}}, state) when is_port(port) do
    # Handle non-line data (raw binary chunks)
    case find_by_port(state.processes, port) do
      {ref, process} ->
        updated = %{process | stdout: [data | process.stdout]}
        new_processes = Map.put(state.processes, ref, updated)
        {:noreply, %{state | processes: new_processes}}

      nil ->
        {:noreply, state}
    end
  end

  @impl true
  def handle_info({:DOWN, ref, :port, _port, _reason}, state) do
    # Port has terminated, clean up if not already handled
    case Map.pop(state.processes, ref) do
      {nil, _processes} ->
        {:noreply, state}

      {process, new_processes} ->
        # Process terminated without exit_status message
        # Create a result for this case
        elapsed = System.monotonic_time(:millisecond) - process.started_at

        result = %Result{
          success: false,
          command: process.command,
          stdout: process.stdout |> Enum.reverse() |> Enum.join("\n"),
          stderr: "Process terminated unexpectedly",
          exit_code: -1,
          execution_time: elapsed,
          timeout?: false,
          user_interrupted?: MapSet.member?(state.killed_refs, ref)
        }

        # Reply to caller if synchronous
        if process.caller do
          GenServer.reply(process.caller, {:ok, result})
        end

        new_state = %{
          state
          | processes: new_processes,
            killed_refs: MapSet.delete(state.killed_refs, ref)
        }

        {:noreply, new_state}
    end
  end

  @impl true
  def handle_info({port, {:exit_status, exit_code}}, state) when is_port(port) do
    case find_by_port(state.processes, port) do
      {ref, process} ->
        elapsed = System.monotonic_time(:millisecond) - process.started_at

        result = %Result{
          success: exit_code == 0,
          command: process.command,
          stdout: process.stdout |> Enum.reverse() |> Enum.join("\n"),
          stderr: "",
          exit_code: exit_code,
          execution_time: elapsed,
          timeout?: false,
          user_interrupted?: MapSet.member?(state.killed_refs, ref)
        }

        # Reply to caller if synchronous
        if process.caller do
          GenServer.reply(process.caller, {:ok, result})
        end

        Port.demonitor(ref, [:flush])

        new_state = %{
          state
          | processes: Map.delete(state.processes, ref),
            killed_refs: MapSet.delete(state.killed_refs, ref)
        }

        {:noreply, new_state}

      nil ->
        # Process not found, may have timed out or been killed
        {:noreply, state}
    end
  end

  @impl true
  def handle_info({:check_timeout, ref}, state) do
    case Map.get(state.processes, ref) do
      nil ->
        {:noreply, state}

      process ->
        handle_timeout_check(ref, process, state)
    end
  end

  @impl true
  def handle_info(_msg, state) do
    # Ignore unknown messages
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp handle_timeout_check(ref, process, state) do
    elapsed = System.monotonic_time(:millisecond) - process.started_at

    timeout = process.timeout

    if timeout && elapsed >= timeout do
      process_timed_out(ref, process, elapsed, state)
    else
      schedule_timeout_check(ref, timeout, elapsed, state)
    end
  end

  defp process_timed_out(ref, process, elapsed, state) do
    Port.close(process.port)

    result = %Result{
      success: false,
      command: process.command,
      stdout: process.stdout |> Enum.reverse() |> Enum.join("\n"),
      stderr: "Command timed out after #{process.timeout}ms",
      exit_code: -1,
      execution_time: elapsed,
      timeout?: true,
      user_interrupted?: false
    }

    reply_to_caller(process.caller, result)
    Port.demonitor(ref, [:flush])

    new_state = %{
      state
      | processes: Map.delete(state.processes, ref),
        killed_refs: MapSet.delete(state.killed_refs, ref)
    }

    {:noreply, new_state}
  end

  defp schedule_timeout_check(ref, timeout, elapsed, state) do
    remaining = timeout - elapsed
    Process.send_after(self(), {:check_timeout, ref}, max(remaining, 100))
    {:noreply, state}
  end

  defp reply_to_caller(nil, _result), do: :ok
  defp reply_to_caller(caller, result), do: GenServer.reply(caller, {:ok, result})

  defp open_port(command, cwd) do
    Port.open({:spawn, "sh -c '#{escape(command)}'"}, [
      :binary,
      :exit_status,
      :stderr_to_stdout,
      {:cd, cwd},
      {:line, 1024}
    ])
  end

  defp escape(command) do
    String.replace(command, "'", "'\\''")
  end

  defp find_by_port(processes, port) do
    Enum.find(processes, fn {_, p} -> p.port == port end)
  end
end
