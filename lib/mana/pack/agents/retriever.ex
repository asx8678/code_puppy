defmodule Mana.Pack.Agents.Retriever do
  @moduledoc """
  Retriever 🦮 - Branch merge specialist.

  The branch merge specialist who fetches completed branches and brings
  them home to the base branch! Expert in local git merge operations
  and keeping the codebase cleanly integrated.

  ## Responsibilities

  - Fetch latest changes from remote
  - Switch to base branch and pull updates
  - Merge feature branches into base
  - Handle merge conflicts or escalate them
  - Clean up merged branches
  - Coordinate with other pack agents

  ## Merge Strategies

  - `:no_ff` - Create merge commit, preserve branch history (default)
  - `:squash` - Combine all commits into one
  - `:fast_forward` - Linear history when possible

  ## Example

      task = %{
        id: "merge-1",
        issue_id: "bd-42",
        worktree: "../bd-42",
        description: "Merge feature/bd-42-auth into main",
        metadata: %{
          action: "merge",
          branch: "feature/bd-42-auth",
          base: "main",
          strategy: "no_ff",
          cleanup: true
        }
      }

      {:ok, result} = Mana.Pack.Agents.Retriever.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Retriever-specific task metadata"
  @type metadata :: %{
          action: String.t(),
          branch: String.t() | nil,
          base: String.t() | nil,
          strategy: String.t() | nil,
          cleanup: boolean(),
          message: String.t() | nil
        }

  @default_base "main"
  @default_strategy "no_ff"

  @doc """
  Executes a Retriever merge task.

  ## Task Types

  The metadata `:action` field determines the operation:

  - `"merge"` - Merge a feature branch into base (requires `:branch`, `:base`)
  - `"fetch"` - Fetch latest changes from origin
  - `"checkout"` - Switch to a branch (requires `:branch` or `:base`)
  - `"pull"` - Pull latest changes for current branch
  - `"cleanup"` - Delete merged branches (requires `:branch`)
  - `"verify"` - Verify merge status
  - `"full_merge"` - Complete workflow: fetch, checkout base, pull, merge, cleanup

  ## Merge Strategies

  - `"no_ff"` - `--no-ff` flag, creates merge commit (recommended, default)
  - `"squash"` - `--squash` flag, combines commits
  - `"fast_forward"` - Default git merge, fast-forward when possible

  ## Options

    - `:cwd` - Working directory (default: current directory)
    - `:timeout` - Command timeout in milliseconds (default: 60000)
    - `:env` - Environment variables for git commands

  ## Returns

    - `{:ok, %{status: :merged, branch: String.t(), base: String.t(), commits: [map()]}}`
    - `{:ok, %{status: :conflict, conflicts: [String.t()], message: String.t()}}`
    - `{:error, reason}`
  """
  @impl true
  @spec execute(Mana.Pack.Agent.task(), Mana.Pack.Agent.opts()) ::
          {:ok, map()} | {:error, term()}
  def execute(task, opts \\ []) do
    metadata = task[:metadata] || %{}
    action = Mana.Pack.Agent.get_meta(metadata, :action) || "merge"

    cwd = Keyword.get(opts, :cwd, File.cwd!())
    timeout = Keyword.get(opts, :timeout, 60_000)

    Logger.debug("Retriever executing #{action} in #{cwd}")

    case action do
      "merge" ->
        do_merge(task, metadata, cwd, timeout)

      "fetch" ->
        do_fetch(cwd, timeout)

      "checkout" ->
        branch =
          Mana.Pack.Agent.get_meta(metadata, :branch) || Mana.Pack.Agent.get_meta(metadata, :base) || @default_base

        do_checkout(branch, cwd, timeout)

      "pull" ->
        remote = Mana.Pack.Agent.get_meta(metadata, :remote) || "origin"

        branch =
          Mana.Pack.Agent.get_meta(metadata, :branch) || Mana.Pack.Agent.get_meta(metadata, :base) || @default_base

        do_pull(remote, branch, cwd, timeout)

      "cleanup" ->
        branch = Mana.Pack.Agent.get_meta(metadata, :branch)
        do_cleanup(branch, cwd, timeout)

      "verify" ->
        branch = Mana.Pack.Agent.get_meta(metadata, :branch)
        do_verify(branch, cwd, timeout)

      "full_merge" ->
        do_full_merge(task, metadata, cwd, timeout)

      _ ->
        {:error, %{reason: :unknown_action, action: action}}
    end
  end

  # Individual git operations

  defp do_fetch(cwd, timeout) do
    case Mana.Pack.CommandRunner.run("git", ["fetch", "origin"],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        {:ok, %{status: :fetched, output: output}}

      {:error, reason} ->
        {:error, %{reason: :fetch_failed, details: reason}}
    end
  end

  defp do_checkout(branch, cwd, timeout) do
    case Mana.Pack.CommandRunner.run("git", ["checkout", branch],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        {:ok, %{status: :checked_out, branch: branch, output: output}}

      {:error, reason} ->
        {:error, %{reason: :checkout_failed, branch: branch, details: reason}}
    end
  end

  defp do_pull(remote, branch, cwd, timeout) do
    case Mana.Pack.CommandRunner.run("git", ["pull", remote, branch],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        {:ok, %{status: :pulled, remote: remote, branch: branch, output: output}}

      {:error, reason} ->
        {:error, %{reason: :pull_failed, details: reason}}
    end
  end

  defp do_merge(task, metadata, cwd, timeout) do
    branch = Mana.Pack.Agent.get_meta(metadata, :branch) || worktree_to_branch(task[:worktree])
    base = Mana.Pack.Agent.get_meta(metadata, :base) || @default_base
    strategy = Mana.Pack.Agent.get_meta(metadata, :strategy) || @default_strategy
    message = Mana.Pack.Agent.get_meta(metadata, :message)
    cleanup = Mana.Pack.Agent.get_meta(metadata, :cleanup) || false

    if branch do
      # Build merge command
      merge_args = build_merge_args(branch, strategy, message)

      case Mana.Pack.CommandRunner.run("git", ["merge" | merge_args],
             cd: cwd,
             timeout: timeout,
             stderr_to_stdout: true,
             parallelism: true
           ) do
        {:ok, output} ->
          result = %{
            status: :merged,
            branch: branch,
            base: base,
            strategy: strategy,
            output: output
          }

          # Cleanup if requested
          if cleanup do
            case do_cleanup(branch, cwd, timeout) do
              {:ok, _} -> {:ok, Map.put(result, :cleanup, :success)}
              {:error, _} -> {:ok, Map.put(result, :cleanup, :failed)}
            end
          else
            {:ok, result}
          end

        {:error, {:exit_code, _code, output}} ->
          if String.contains?(output, "conflict") or String.contains?(output, "CONFLICT") do
            conflicts = parse_conflicts(output)

            {:ok,
             %{
               status: :conflict,
               branch: branch,
               base: base,
               conflicts: conflicts,
               message: "Merge conflicts detected. Run 'git merge --abort' to cancel.",
               output: output
             }}
          else
            {:error, %{reason: :merge_failed, branch: branch, output: output}}
          end

        {:error, reason} ->
          {:error, %{reason: :merge_failed, branch: branch, details: reason}}
      end
    else
      return_error(:missing_branch, "Feature branch not specified")
    end
  end

  defp do_cleanup(nil, _cwd, _timeout) do
    {:error, %{reason: :missing_branch}}
  end

  defp do_cleanup(branch, cwd, timeout) do
    # Delete local branch
    case Mana.Pack.CommandRunner.run("git", ["branch", "-d", branch],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        {:ok, %{status: :cleaned, branch_deleted: branch, output: output}}

      {:error, _reason} ->
        # Try force delete if normal delete failed
        case Mana.Pack.CommandRunner.run("git", ["branch", "-D", branch],
               cd: cwd,
               timeout: timeout,
               stderr_to_stdout: true,
               parallelism: true
             ) do
          {:ok, output} ->
            {:ok, %{status: :cleaned, branch_deleted: branch, force: true, output: output}}

          {:error, reason} ->
            {:error, %{reason: :cleanup_failed, branch: branch, details: reason}}
        end
    end
  end

  defp do_verify(nil, _cwd, _timeout) do
    {:error, %{reason: :missing_branch}}
  end

  defp do_verify(branch, cwd, timeout) do
    # Check if branch is fully merged
    case Mana.Pack.CommandRunner.run("git", ["branch", "--merged"],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        is_merged = String.contains?(output, branch)

        # Also check unmerged branches - use case instead of bare match
        case Mana.Pack.CommandRunner.run("git", ["branch", "--no-merged"],
               cd: cwd,
               timeout: timeout,
               stderr_to_stdout: true,
               parallelism: true
             ) do
          {:ok, unmerged_output} ->
            has_unmerged = String.contains?(unmerged_output, branch)

            {:ok,
             %{
               status: :verified,
               branch: branch,
               merged: is_merged,
               unmerged: has_unmerged,
               can_delete: is_merged && not has_unmerged
             }}

          {:error, reason} ->
            {:error, %{reason: :verify_failed, details: reason}}
        end

      {:error, reason} ->
        {:error, %{reason: :verify_failed, details: reason}}
    end
  end

  # Full merge workflow

  defp do_full_merge(task, metadata, cwd, timeout) do
    branch = Mana.Pack.Agent.get_meta(metadata, :branch) || worktree_to_branch(task[:worktree])
    base = Mana.Pack.Agent.get_meta(metadata, :base) || @default_base
    strategy = Mana.Pack.Agent.get_meta(metadata, :strategy) || @default_strategy

    # Fix: Use if/else instead of unless for proper control flow
    if is_nil(branch) do
      return_error(:missing_branch, "Feature branch not specified")
    else
      # Execute full merge workflow
      with {:ok, _} <- do_fetch(cwd, timeout),
           {:ok, _} <- do_checkout(base, cwd, timeout),
           {:ok, _} <- do_pull("origin", base, cwd, timeout),
           {:ok, merge_result} <- do_merge(task, metadata, cwd, timeout) do
        # Check if merge resulted in conflicts
        if merge_result[:status] == :conflict do
          {:ok,
           %{
             status: :conflict,
             branch: branch,
             base: base,
             steps: [
               {:fetch, :ok},
               {:checkout, :ok},
               {:pull, :ok},
               {:merge, :conflict}
             ],
             conflicts: merge_result[:conflicts],
             message: "Merge conflicts require manual resolution"
           }}
        else
          {:ok,
           %{
             status: :completed,
             branch: branch,
             base: base,
             strategy: strategy,
             merge_status: merge_result.status,
             steps: [
               {:fetch, :ok},
               {:checkout, :ok},
               {:pull, :ok},
               {:merge, merge_result.status}
             ],
             message: "Full merge workflow completed"
           }}
        end
      else
        {:error, reason} ->
          # Determine which step failed by checking the reason
          failed_step =
            cond do
              reason[:reason] == :fetch_failed -> :fetch
              reason[:reason] == :checkout_failed -> :checkout
              reason[:reason] == :pull_failed -> :pull
              reason[:reason] == :merge_failed -> :merge
              true -> :unknown
            end

          {:error,
           %{
             reason: reason[:reason] || :workflow_failed,
             step: failed_step,
             details: reason
           }}
      end
    end
  end

  # Helper functions

  defp build_merge_args(branch, strategy, message) do
    args =
      case strategy do
        "no_ff" -> ["--no-ff"]
        "squash" -> ["--squash"]
        "fast_forward" -> []
        _ -> ["--no-ff"]
      end

    args =
      if message do
        args ++ ["-m", message]
      else
        args
      end

    args ++ [branch]
  end

  defp parse_conflicts(output) do
    # Extract conflicted file paths from git output
    output
    |> String.split("\n")
    |> Enum.filter(&String.contains?(&1, ["CONFLICT", "both modified", "added by us", "added by them"]))
    |> Enum.map(fn line ->
      # Try to extract filename
      case Regex.run(~r/in (.+?)(?:\s*\(|$)/, line) do
        [_, filename] -> filename
        _ -> line
      end
    end)
    |> Enum.uniq()
  end

  defp worktree_to_branch(nil), do: nil

  defp worktree_to_branch(worktree) do
    # Try to infer branch name from worktree path
    # e.g., "../bd-42" -> "feature/bd-42-*"
    basename = Path.basename(worktree)

    if String.starts_with?(basename, "bd-") do
      # Return pattern that might match
      "feature/#{basename}"
    else
      nil
    end
  end

  defp return_error(reason, message) do
    {:error, %{reason: reason, message: message}}
  end

  @doc """
  Aborts a merge in progress.

  Useful when conflicts cannot be resolved automatically.
  """
  @spec abort_merge(String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def abort_merge(cwd, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 30_000)

    case Mana.Pack.CommandRunner.run("git", ["merge", "--abort"],
           cd: cwd,
           timeout: timeout,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        {:ok, %{status: :aborted, output: output}}

      {:error, reason} ->
        {:error, %{reason: :abort_failed, details: reason}}
    end
  end

  @doc """
  Resolves merge conflicts by taking one side.

  - `"ours"` - Keep base branch version
  - `"theirs"` - Keep feature branch version
  """
  @spec resolve_conflict(String.t(), String.t(), String.t(), keyword()) ::
          {:ok, map()} | {:error, term()}
  def resolve_conflict(cwd, file, side, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 30_000)
    side_flag = if side == "ours", do: "--ours", else: "--theirs"

    with {:ok, _} <-
           Mana.Pack.CommandRunner.run("git", ["checkout", side_flag, file],
             cd: cwd,
             timeout: timeout,
             stderr_to_stdout: true,
             parallelism: true
           ),
         {:ok, _} <-
           Mana.Pack.CommandRunner.run("git", ["add", file],
             cd: cwd,
             timeout: timeout,
             stderr_to_stdout: true,
             parallelism: true
           ) do
      {:ok, %{status: :resolved, file: file, side: side}}
    else
      {:error, reason} ->
        {:error, %{reason: :resolve_failed, file: file, details: reason}}
    end
  end

  @doc """
  Completes a merge after resolving conflicts.
  """
  @spec complete_merge(String.t(), String.t() | nil, keyword()) :: {:ok, map()} | {:error, term()}
  def complete_merge(cwd, message \\ nil, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 30_000)

    args =
      if message do
        ["commit", "-m", message]
      else
        ["commit"]
      end

    case Mana.Pack.CommandRunner.run("git", args, cd: cwd, timeout: timeout, stderr_to_stdout: true, parallelism: true) do
      {:ok, output} ->
        {:ok, %{status: :completed, output: output}}

      {:error, reason} ->
        {:error, %{reason: :commit_failed, details: reason}}
    end
  end
end
