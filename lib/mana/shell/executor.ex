defmodule Mana.Shell.Executor do
  @moduledoc """
  GenServer managing shell command execution via Erlang Ports.

  Uses Ports (NOT threads) for process management. Port sends {:data, data}
  messages to the GenServer mailbox, which are handled via handle_info callbacks.

  ## Security Features

  - Dangerous command blocklist with configurable patterns
  - Command validation before execution

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
  # Default Dangerous Command Patterns (can be overridden via Application config)
  # ============================================================================

  @default_dangerous_patterns [
    # rm -rf / or similar destructive deletions
    ~r/rm\s+-rf\s+\//i,
    # Disk operations with dd (direct to device)
    ~r/dd\s+if=/i,
    # Filesystem formatting
    ~r/mkfs/i,
    # Raw device writes
    ~r/>\s*\/dev\/sd[a-z]/i,
    ~r/>\s*\/dev\/hd[a-z]/i,
    ~r/>\s*\/dev\/disk/i,
    ~r/>\s*\/dev\/nvme/i,
    # Fork bomb pattern
    ~r/:\(\)\s*\{[^}]*:\|[^}]*\}/,
    # curl | sh pattern
    ~r/curl.*\|\s*(sh|bash)/i,
    # wget | bash pattern
    ~r/wget.*\|\s*(sh|bash)/i,
    # sudo rm, sudo dd
    ~r/sudo\s+rm/i,
    ~r/sudo\s+dd/i,
    # format commands
    ~r/format\s/i
  ]

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
  Before execution, checks if the command is in the dangerous command blocklist.
  """
  @spec execute(String.t(), String.t(), integer()) :: {:ok, Result.t()} | {:error, term()}
  def execute(command, cwd, timeout) do
    if dangerous_command?(command) do
      {:error, "Command blocked: dangerous command detected"}
    else
      GenServer.call(__MODULE__, {:execute, command, cwd, timeout}, timeout + 5_000)
    end
  end

  @doc """
  Executes a shell command in the background.

  Returns {:ok, reference()} immediately. The caller can monitor the
  process via the returned reference.
  Before execution, checks if the command is in the dangerous command blocklist.
  """
  @spec execute_background(String.t(), String.t()) :: {:ok, reference()} | {:error, term()}
  def execute_background(command, cwd) do
    if dangerous_command?(command) do
      {:error, "Command blocked: dangerous command detected"}
    else
      GenServer.call(__MODULE__, {:execute_background, command, cwd})
    end
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
  # Security Functions
  # ============================================================================

  @doc """
  Checks if a command matches dangerous patterns in the blocklist.

  Returns true if the command is considered dangerous and should be blocked.

  This function is designed to block actual execution of dangerous commands,
  not just commands that mention dangerous patterns in strings.

  ## Examples

      iex> dangerous_command?("rm -rf /")
      true

      iex> dangerous_command?("echo 'rm -rf /'")
      false

      iex> dangerous_command?("ls -la")
      false
  """
  @spec dangerous_command?(String.t()) :: boolean()
  def dangerous_command?(command) when is_binary(command) do
    patterns = get_dangerous_patterns()

    # Normalize the command: trim whitespace
    normalized = String.trim(command)

    # Check for dangerous patterns only in the actual command execution context
    # We check if the pattern appears at the start or after shell operators
    Enum.any?(patterns, fn pattern ->
      matches_dangerous_in_context?(normalized, pattern)
    end)
  end

  def dangerous_command?(_), do: false

  # Check if a pattern matches in a context where it would actually execute
  # Pattern must be at start, after shell control operators, or is itself a dangerous operation
  defp matches_dangerous_in_context?(command, pattern) do
    cond do
      # Match at the beginning of command
      Regex.match?(~r/^#{pattern.source}/i, command) ->
        true

      # Match after shell control operators
      Regex.match?(~r/[;&|]\s*#{pattern.source}/i, command) ->
        true

      # For raw device writes (> /dev/sd*), match anywhere as this is always dangerous
      pattern.source =~ "dev/sd" and Regex.match?(pattern, command) ->
        true

      # Match in subshell context $()
      Regex.match?(~r/\$\([^)]*#{pattern.source}/i, command) ->
        true

      # Match in backtick execution
      Regex.match?(~r/`[^`]*#{pattern.source}/i, command) ->
        true

      true ->
        false
    end
  end

  @doc """
  Returns the list of dangerous command patterns.

  Patterns are loaded from Application config :mana, :dangerous_command_patterns
  or use the default list if not configured.
  """
  @spec get_dangerous_patterns() :: list(Regex.t())
  def get_dangerous_patterns do
    Application.get_env(:mana, :dangerous_command_patterns, @default_dangerous_patterns)
  end

  @doc """
  Validates that the configured dangerous patterns are valid regexes.

  Returns {:ok, patterns} if all patterns are valid, or {:error, reason} if any
  pattern is invalid.
  """
  @spec validate_dangerous_patterns(list()) :: {:ok, list(Regex.t())} | {:error, String.t()}
  def validate_dangerous_patterns(patterns) do
    Enum.reduce_while(patterns, {:ok, []}, fn pattern, {:ok, acc} ->
      case pattern do
        %Regex{} -> {:cont, {:ok, [pattern | acc]}}
        _ -> {:halt, {:error, "Invalid pattern: #{inspect(pattern)} - must be a Regex"}}
      end
    end)
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
