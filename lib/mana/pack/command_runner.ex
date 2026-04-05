defmodule Mana.Pack.CommandRunner do
  @moduledoc """
  Shared command execution helper with proper timeout support.

  System.cmd/3 does not support timeouts natively. This module wraps
  command execution in Task.async/Task.yield to provide reliable timeout
  handling that actually works.
  """

  require Logger

  @doc """
  Runs a command with the given arguments and options.

  ## Options

    - `:timeout` - Maximum execution time in milliseconds (default: 30_000)
    - Other options are passed through to System.cmd/3 (except :timeout)

  ## Returns

    - `{:ok, output}` - Command succeeded with exit code 0
    - `{:error, {:exit_code, code, output}}` - Command failed with non-zero exit
    - `{:error, :timeout}` - Command exceeded timeout
    - `{:error, reason}` - Other execution errors

  ## Examples

      Mana.Pack.CommandRunner.run("git", ["status"], cd: "/some/path")
      Mana.Pack.CommandRunner.run("pytest", ["-v"], timeout: 120_000, cd: worktree)
  """
  @spec run(String.t(), [String.t()], keyword()) ::
          {:ok, String.t()} | {:error, term()}
  def run(command, args, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 30_000)
    cmd_opts = Keyword.delete(opts, :timeout)

    # Use try/rescue inside the Task to handle nonexistent commands
    task =
      Task.async(fn ->
        try do
          # System.cmd returns {output, exit_code} on success
          # We wrap in {:ok, ...} to distinguish from caught errors
          result = System.cmd(command, args, cmd_opts)
          {:exec_ok, result}
        rescue
          e -> {:exec_error, e}
        catch
          :exit, reason -> {:exec_error, reason}
        end
      end)

    case Task.yield(task, timeout) || Task.shutdown(task) do
      {:ok, {:exec_ok, {output, 0}}} ->
        {:ok, output}

      {:ok, {:exec_ok, {output, code}}} ->
        {:error, {:exit_code, code, output}}

      {:ok, {:exec_error, reason}} ->
        Logger.error("CommandRunner execution failed: #{inspect(reason)}")
        {:error, %{reason: :execution_failed, details: inspect(reason)}}

      {:exit, reason} ->
        Logger.error("CommandRunner task crashed: #{inspect(reason)}")
        {:error, %{reason: :execution_failed, details: inspect(reason)}}

      nil ->
        {:error, :timeout}
    end
  end
end
