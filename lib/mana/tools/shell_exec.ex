defmodule Mana.Tools.ShellExec do
  @moduledoc """
  Tool for executing shell commands with safety controls.

  Uses Mana.Shell.Executor for command execution which provides:
  - Dangerous command blocklist
  - Timeout handling
  - Process isolation via Erlang Ports
  - Background execution support

  ## Safety

  Commands are validated against a dangerous command blocklist before execution.
  See Mana.Shell.Executor for the list of blocked patterns.

  ## Usage

      # Synchronous execution (default)
      ShellExec.execute(%{
        "command" => "ls -la",
        "cwd" => "/tmp",
        "timeout" => 60
      })
      # => {:ok, %{"stdout" => "...", "stderr" => "", "exit_code" => 0}}

      # Background execution
      ShellExec.execute(%{
        "command" => "long_running.sh",
        "cwd" => "/tmp",
        "background" => true
      })
      # => {:ok, %{"ref" => "...", "status" => "running"}}
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Shell.Executor

  @default_timeout 60

  @impl true
  def name, do: "run_shell_command"

  @impl true
  def description, do: "Execute a shell command with timeout and safety controls"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        command: %{
          type: "string",
          description: "Command to execute"
        },
        cwd: %{
          type: "string",
          description: "Working directory for command execution",
          default: "."
        },
        timeout: %{
          type: "integer",
          description: "Timeout in seconds",
          default: @default_timeout
        },
        background: %{
          type: "boolean",
          description: "Run command in background (returns immediately)",
          default: false
        }
      },
      required: ["command"]
    }
  end

  @impl true
  def execute(args) do
    command = Map.get(args, "command")
    cwd = Map.get(args, "cwd", ".")
    timeout_sec = Map.get(args, "timeout", @default_timeout)
    background = Map.get(args, "background", false)

    # Validate required parameter
    if is_nil(command) or command == "" do
      return_error("Missing required parameter: command")
    end

    # Convert timeout to milliseconds
    timeout_ms = timeout_sec * 1000

    # Resolve working directory
    cwd =
      if Path.type(cwd) == :relative do
        Path.expand(cwd, File.cwd!())
      else
        Path.expand(cwd)
      end

    # Ensure directory exists
    unless File.dir?(cwd) do
      return_error("Working directory does not exist: #{cwd}")
    end

    if background do
      execute_background(command, cwd)
    else
      execute_sync(command, cwd, timeout_ms)
    end
  end

  defp execute_sync(command, cwd, timeout_ms) do
    case Executor.execute(command, cwd, timeout_ms) do
      {:ok, result} ->
        {:ok,
         %{
           "stdout" => result.stdout,
           "stderr" => result.stderr,
           "exit_code" => result.exit_code,
           "success" => result.success,
           "execution_time_ms" => result.execution_time,
           "timeout" => result.timeout?,
           "user_interrupted" => result.user_interrupted?
         }}

      {:error, reason} ->
        {:error, "Command execution failed: #{reason}"}
    end
  end

  defp execute_background(command, cwd) do
    case Executor.execute_background(command, cwd) do
      {:ok, ref} ->
        ref_str = :erlang.ref_to_list(ref) |> List.to_string()

        {:ok,
         %{
           "ref" => ref_str,
           "status" => "running",
           "command" => command,
           "cwd" => cwd
         }}

      {:error, reason} ->
        {:error, "Background execution failed: #{reason}"}
    end
  end

  defp return_error(message) do
    {:error, message}
  end
end
