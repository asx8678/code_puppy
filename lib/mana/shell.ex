defmodule Mana.Shell do
  @moduledoc """
  Shell command execution facade.

  Provides a simple, safe API for executing shell commands with:
  - Safety checks via ShellSafety plugin
  - YOLO mode support (bypass medium-risk checks)
  - Synchronous and background execution
  - Process management and cleanup

  ## Usage

      # Run command synchronously (30s default timeout)
      {:ok, result} = Mana.Shell.run("ls -la")

      # Run with custom timeout and working directory
      {:ok, result} = Mana.Shell.run("npm install", cwd: "/project", timeout: 60_000)

      # Run in background
      {:ok, ref} = Mana.Shell.run_background("long_task.sh")

      # Kill all running processes
      :ok = Mana.Shell.kill_all()

  ## Safety

  Commands are checked by the ShellSafety plugin before execution.
  High-risk and critical-risk commands are blocked by default.
  Medium-risk commands can be bypassed with yolo_mode.
  """

  alias Mana.Config
  alias Mana.Shell.Executor
  alias Mana.Shell.Result

  @type run_option :: {:cwd, String.t()} | {:timeout, integer()}

  # ============================================================================
  # Public API
  # ============================================================================

  @doc """
  Run a command synchronously.

  ## Options

  - `:cwd` - Working directory (default: current working directory)
  - `:timeout` - Timeout in milliseconds (default: 30,000)

  ## Returns

  - `{:ok, Result.t()}` - Command completed (success or failure captured in result)
  - `{:error, {:blocked, reason}}` - Command blocked by safety check

  ## Examples

      {:ok, result} = Mana.Shell.run("echo hello")
      assert result.success == true
      assert result.stdout == "hello"

      {:ok, result} = Mana.Shell.run("exit 1")
      assert result.success == false
      assert result.exit_code == 1
  """
  @spec run(String.t(), keyword()) :: {:ok, Result.t()} | {:error, term()}
  def run(command, opts \\ []) do
    cwd = Keyword.get(opts, :cwd, File.cwd!())
    timeout = Keyword.get(opts, :timeout, 30_000)

    # Safety check via ShellSafety plugin
    safety_result = check_safety(command, opts)

    case safety_result do
      %{safe: true} ->
        Executor.execute(command, cwd, timeout)

      %{safe: false, reason: reason} ->
        if Config.yolo_mode?() do
          IO.puts("[Shell] YOLO mode: #{reason}")
          Executor.execute(command, cwd, timeout)
        else
          {:error, {:blocked, reason}}
        end
    end
  end

  @doc """
  Run a command in background.

  The command runs without blocking. Use the returned reference
  to track the process via Executor.list_processes/0.

  ## Options

  - `:cwd` - Working directory (default: current working directory)

  ## Returns

  - `{:ok, reference()}` - Process started
  - `{:error, {:blocked, reason}}` - Command blocked by safety check

  ## Examples

      {:ok, ref} = Mana.Shell.run_background("sleep 10")
      # ... later
      :ok = Mana.Shell.kill_all()
  """
  @spec run_background(String.t(), keyword()) :: {:ok, reference()} | {:error, term()}
  def run_background(command, opts \\ []) do
    cwd = Keyword.get(opts, :cwd, File.cwd!())

    # Safety check via ShellSafety plugin
    safety_result = check_safety(command, opts)

    case safety_result do
      %{safe: true} ->
        Executor.execute_background(command, cwd)

      %{safe: false, reason: reason} ->
        if Config.yolo_mode?() do
          IO.puts("[Shell] YOLO mode: #{reason}")
          Executor.execute_background(command, cwd)
        else
          {:error, {:blocked, reason}}
        end
    end
  end

  @doc """
  Kill all running processes.

  Terminates all processes started via this module. They will be
  marked as user_interrupted in their results.

  ## Returns

  - `:ok`
  """
  @spec kill_all() :: :ok
  def kill_all do
    Executor.kill_all()
  end

  @doc """
  List all currently running processes.

  ## Returns

  List of `{reference(), command, started_at}` tuples.
  """
  @spec list_processes() :: list({reference(), String.t(), integer()})
  def list_processes do
    Executor.list_processes()
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp check_safety(command, opts) do
    # Dispatch :run_shell_command callback
    # Build a state for the ShellSafety plugin (matches plugin state structure)
    state = %{
      config: %{
        yolo_mode: Config.yolo_mode?(),
        allow_sudo: false,
        log_assessments: false
      }
    }

    context = %{cwd: Keyword.get(opts, :cwd)}

    case Mana.Callbacks.dispatch(:run_shell_command, [context, command, state]) do
      {:ok, [{:ok, %{safe: _} = result} | _]} ->
        result

      {:ok, [%{safe: _} = result | _]} ->
        result

      {:ok, []} ->
        # No callbacks registered, assume safe
        %{safe: true, risk: :none}

      {:error, _} ->
        # Error in callbacks, assume safe (fail open for callbacks)
        %{safe: true, risk: :none}
    end
  end
end
