defmodule CodePuppyControl.Tools.CommandRunner do
  @moduledoc """
  Shell command execution for agent tool calls.

  SECURITY NOTE: This module uses Elixir's `System.cmd/3` for subprocess execution.
  Commands arrive as complete strings from the LLM (e.g. "cd /foo && make test"
  or "cat file | grep pattern") and REQUIRE shell interpretation for pipes,
  redirects, chains, and variable expansion.

  Security is enforced by the `CommandRunner.Validator` module, which validates
  commands before execution and blocks dangerous operations.

  ## Usage

      # Simple command with default timeout
      {:ok, result} = CommandRunner.run("echo hello", timeout: 30)

  ## Result Structure

      %{
        success: boolean(),
        command: String.t(),
        stdout: String.t(),
        stderr: String.t(),
        exit_code: integer(),
        execution_time_ms: integer(),
        timeout: boolean(),
        error: String.t() | nil
      }

  ## Architecture

  - `CommandRunner` - Main API module (this module)
  - `CommandRunner.Validator` - Security validation (command length, forbidden chars, patterns)
  - `CommandRunner.ProcessManager` - Process tracking and lifecycle management
  """

  require Logger

  alias CodePuppyControl.Tools.CommandRunner.{ProcessManager, Validator}

  # Default timeout for commands (seconds)
  @default_timeout 60
  # Absolute maximum timeout for any command (seconds)
  @absolute_timeout 270
  # Maximum line length for output truncation
  @max_line_length 256

  @typedoc """
  Result structure for command execution.
  """
  @type result :: %{
          success: boolean(),
          command: String.t(),
          stdout: String.t(),
          stderr: String.t(),
          exit_code: integer() | nil,
          execution_time_ms: integer(),
          timeout: boolean(),
          error: String.t() | nil,
          user_interrupted: boolean()
        }

  @typedoc """
  Options for command execution.
  """
  @type opts :: [
          timeout: non_neg_integer(),
          cwd: String.t() | nil,
          env: [{String.t(), String.t()}]
        ]

  @doc """
  Runs a shell command with the given options.

  ## Options

  - `:timeout` - Timeout in seconds (default: 60, max: 270)
  - `:cwd` - Working directory for the command (default: current directory)
  - `:env` - Additional environment variables as key-value list

  ## Returns

  - `{:ok, result}` - Command executed successfully
  - `{:error, reason}` - Command failed validation or execution error

  ## Examples

      iex> CommandRunner.run("echo hello")
      {:ok, %{success: true, stdout: "hello", stderr: "", exit_code: 0, ...}}

      iex> CommandRunner.run("invalid_command_12345")
      {:ok, %{success: false, stdout: "", stderr: "...", exit_code: 127, ...}}
  """
  @spec run(String.t(), opts()) :: {:ok, result()} | {:error, String.t()}
  def run(command, opts \\ []) do
    timeout = min(Keyword.get(opts, :timeout, @default_timeout), @absolute_timeout)
    cwd = Keyword.get(opts, :cwd)
    env = Keyword.get(opts, :env, [])

    # Validate command before execution
    case Validator.validate(command) do
      {:ok, validated} ->
        do_run(validated, timeout, cwd, env)

      {:error, reason} ->
        {:error, "Command validation failed: #{reason}"}
    end
  end

  @doc """
  Kills all running shell processes tracked by the ProcessManager.

  Returns the number of processes killed.
  """
  @spec kill_all() :: non_neg_integer()
  def kill_all do
    ProcessManager.kill_all()
  end

  @doc """
  Returns the count of currently running shell processes.
  """
  @spec running_count() :: non_neg_integer()
  def running_count do
    ProcessManager.count()
  end

  @doc """
  Kills a specific process by its OS PID.

  Returns `:ok` if the process was signaled, `{:error, reason}` otherwise.
  """
  @spec kill_process(integer()) :: :ok | {:error, String.t()}
  def kill_process(pid) do
    ProcessManager.kill_process(pid)
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp do_run(command, timeout, cwd, env) do
    start_time = System.monotonic_time(:millisecond)

    # Build cmd options (no timeout here - we'll handle it manually)
    cmd_opts = build_cmd_opts(cwd, env, timeout * 1000)

    # Use system shell for command interpretation (pipes, redirects, etc.)
    {shell, shell_flag} = shell_command()

    # Register with ProcessManager for tracking
    {:ok, tracking_id} = ProcessManager.register_command(command)

    try do
      # Execute command through shell with timeout via Task
      task =
        Task.async(fn ->
          System.cmd(shell, [shell_flag, command], cmd_opts)
        end)

      case Task.yield(task, timeout * 1000) || Task.shutdown(task) do
        nil ->
          # Task was shut down due to timeout
          execution_time = System.monotonic_time(:millisecond) - start_time

          result =
            build_result(
              command,
              "",
              "",
              -9,
              execution_time,
              true
            )

          {:ok, result}

        {:ok, {output, exit_code}} ->
          execution_time = System.monotonic_time(:millisecond) - start_time

          result =
            build_result(
              command,
              output,
              "",
              exit_code,
              execution_time,
              false
            )

          {:ok, result}

        {:exit, reason} ->
          execution_time = System.monotonic_time(:millisecond) - start_time

          result =
            build_result(
              command,
              "",
              "Task exited: #{inspect(reason)}",
              -1,
              execution_time,
              false
            )

          {:ok, result}
      end
    rescue
      e -> {:error, "Command execution failed: #{Exception.message(e)}"}
    catch
      :exit, reason -> {:error, "Command execution failed: #{inspect(reason)}"}
    after
      ProcessManager.unregister_command(tracking_id)
    end
  end

  defp build_cmd_opts(nil, [], timeout_ms) do
    [stderr_to_stdout: true, parallelism: true] ++ timeout_opt(timeout_ms)
  end

  defp build_cmd_opts(cwd, env, timeout_ms) do
    opts = [stderr_to_stdout: true, parallelism: true]

    opts = if cwd, do: [{:cd, cwd} | opts], else: opts

    # Convert env list to proper format for System.cmd
    opts = if env != [], do: [{:env, env} | opts], else: opts

    opts ++ timeout_opt(timeout_ms)
  end

  # System.cmd timeout is specified in milliseconds via a different mechanism in newer Elixir
  # For compatibility, we'll handle timeout manually with Task async/await
  defp timeout_opt(_timeout_ms) do
    # We'll handle timeout via Task.await instead of System.cmd timeout option
    []
  end

  defp shell_command do
    case :os.type() do
      {:win32, _} -> {"cmd", "/c"}
      _ -> {"sh", "-c"}
    end
  end

  defp build_result(command, stdout, stderr, exit_code, execution_time_ms, timed_out) do
    success = exit_code == 0 && !timed_out

    error =
      cond do
        timed_out -> "Command timed out"
        exit_code != 0 -> "Command failed with exit code #{exit_code}"
        true -> nil
      end

    %{
      success: success,
      command: command,
      stdout: stdout,
      stderr: stderr,
      exit_code: exit_code,
      execution_time_ms: execution_time_ms,
      timeout: timed_out,
      error: error,
      # Not tracked in this implementation
      user_interrupted: false
    }
  end

  @doc """
  Truncates a line to the maximum allowed length.
  """
  @spec truncate_line(String.t(), non_neg_integer()) :: String.t()
  def truncate_line(line, max_length \\ @max_line_length) do
    if String.length(line) > max_length do
      truncated = String.slice(line, 0, max_length)
      truncated <> "... [line truncated, command output too long, try filtering with grep]"
    else
      line
    end
  end
end
