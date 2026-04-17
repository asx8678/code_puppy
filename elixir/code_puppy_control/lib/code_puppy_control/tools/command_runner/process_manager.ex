defmodule CodePuppyControl.Tools.CommandRunner.ProcessManager do
  @moduledoc """
  Process tracking for shell commands (bd-64).

  This GenServer tracks running shell commands and provides:

  - Command registration/unregistration
  - Bulk process killing via shell pkill
  - Command tracking for safety

  ## Usage

      # Register a command being started
      {:ok, pid} = ProcessManager.register_command("echo hello")

      # Unregister when complete
      :ok = ProcessManager.unregister_command("echo hello")

      # Kill all running commands
      count = ProcessManager.kill_all()
  """

  use GenServer

  require Logger

  defstruct [:commands, :counter]

  @typedoc """
  Command tracking information.
  """
  @type command_info :: %{
          command: String.t(),
          started_at: integer(),
          id: non_neg_integer()
        }

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the ProcessManager GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Registers a command that is about to be executed.

  Returns a tracking ID for the command.
  """
  @spec register_command(String.t()) :: {:ok, non_neg_integer()}
  def register_command(command) do
    GenServer.call(__MODULE__, {:register, command})
  end

  @doc """
  Unregisters a command that has completed.
  """
  @spec unregister_command(String.t()) :: :ok
  def unregister_command(command) do
    GenServer.call(__MODULE__, {:unregister, command})
  end

  @doc """
  Kills all running shell processes (best effort).

  Uses shell pkill/killall to signal processes. This is a best-effort
  operation as we don't have direct PID tracking for System.cmd processes.

  Returns the count of processes signaled (always 0 in current implementation).
  """
  @spec kill_all() :: non_neg_integer()
  def kill_all do
    GenServer.call(__MODULE__, :kill_all)
  end

  @doc """
  Returns the count of currently running commands.
  """
  @spec count() :: non_neg_integer()
  def count do
    GenServer.call(__MODULE__, :count)
  end

  @doc """
  Kills a specific process by its OS PID (not implemented for System.cmd).
  """
  @spec kill_process(integer()) :: :ok | {:error, String.t()}
  def kill_process(pid) do
    GenServer.call(__MODULE__, {:kill_process, pid})
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    state = %__MODULE__{
      commands: %{},
      counter: 0
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:register, command}, _from, state) do
    id = state.counter + 1

    info = %{
      command: command,
      started_at: System.monotonic_time(:second),
      id: id
    }

    new_commands = Map.put(state.commands, command, info)

    {:reply, {:ok, id}, %{state | commands: new_commands, counter: id}}
  end

  @impl true
  def handle_call({:unregister, command}, _from, state) do
    new_commands = Map.delete(state.commands, command)
    {:reply, :ok, %{state | commands: new_commands}}
  end

  @impl true
  def handle_call(:kill_all, _from, state) do
    # Try to find and kill any sh processes that might be our commands
    # This is best-effort only
    count = length(Map.keys(state.commands))

    # On Unix, try to kill shell processes that match our commands
    if count > 0 do
      case :os.type() do
        {:unix, _} ->
          # Try pkill with pattern matching for commands (very broad)
          System.cmd("pkill", ["-f", "sh -c"], stderr_to_stdout: true, timeout: 5000)

        {:win32, _} ->
          # Windows - not easily doable without WMI
          :ok

        _ ->
          :ok
      end
    end

    # Clear all tracked commands
    {:reply, count, %{state | commands: %{}}}
  end

  @impl true
  def handle_call(:count, _from, state) do
    {:reply, map_size(state.commands), state}
  end

  @impl true
  def handle_call({:kill_process, _pid}, _from, state) do
    # Not implemented for System.cmd-based approach
    {:reply, {:error, "Process killing not implemented for System.cmd"}, state}
  end
end
