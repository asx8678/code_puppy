defmodule CodePuppyControl.Tools.CpShell do
  @moduledoc """
  `:cp_`-prefixed Tool-behaviour wrapper for shell command execution.

  Exposes `CodePuppyControl.Tools.CommandRunner` through the Tool
  behaviour so the CodePuppy agent can call `cp_run_command` via
  the tool registry.

  Refs: code_puppy-4s8.7 (Phase C CI gate)
  """

  defmodule CpRunCommand do
    @moduledoc """
    Executes a shell command in the project directory.

    Delegates to `CodePuppyControl.Tools.CommandRunner.run/2`.
    """

    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_run_command

    @impl true
    def description do
      "Execute a shell command with comprehensive monitoring and " <>
        "safety features. Supports streaming output, timeout " <>
        "handling, and background execution."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "command" => %{
            "type" => "string",
            "description" => "Shell command to execute"
          },
          "timeout" => %{
            "type" => "integer",
            "description" => "Timeout in seconds (default: 60)"
          },
          "cwd" => %{
            "type" => "string",
            "description" => "Working directory for the command (optional)"
          }
        },
        "required" => ["command"]
      }
    end

    @impl true
    def invoke(args, _context) do
      command = Map.get(args, "command", "")
      timeout = Map.get(args, "timeout")
      cwd = Map.get(args, "cwd")

      opts =
        []
        |> maybe_put(:timeout, timeout)
        |> maybe_put(:cwd, cwd)

      case CodePuppyControl.Tools.CommandRunner.run(command, opts) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, reason}
      end
    end

    defp maybe_put(opts, _key, nil), do: opts
    defp maybe_put(opts, key, value), do: Keyword.put(opts, key, value)
  end
end
