defmodule Mana.Pack.Agents.Bloodhound do
  @moduledoc """
  Bloodhound 🐕‍🦺 - Issue tracking specialist.

  The issue tracking specialist who follows the scent of dependencies.
  Expert in `bd` (the local issue tracker with powerful dependency support).
  Never loses the trail!

  ## Responsibilities

  - Create and manage issues using `bd create`, `bd update`, `bd close`
  - Query issue status with `bd ready`, `bd blocked`, `bd list`
  - Manage dependencies with `bd dep add`, `bd dep remove`, `bd dep tree`
  - Add labels and comments to issues

  ## Example

      task = %{
        id: "task-1",
        issue_id: nil,
        worktree: nil,
        description: "List ready issues",
        metadata: %{command: "ready"}
      }

      {:ok, result} = Mana.Pack.Agents.Bloodhound.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Bloodhound-specific task metadata"
  @type metadata :: %{
          command: String.t(),
          args: [String.t()],
          issue_id: String.t() | nil,
          description: String.t() | nil,
          priority: integer() | nil,
          issue_type: String.t() | nil,
          deps: String.t() | nil
        }

  @doc """
  Executes a Bloodhound task.

  ## Task Types

  The metadata `:command` field determines the action:

  - `"create"` - Create a new issue (requires `:description`)
  - `"list"` - List all issues
  - `"ready"` - List issues with no blockers
  - `"blocked"` - List blocked issues
  - `"show"` - Show issue details (requires `:issue_id`)
  - `"close"` - Close an issue (requires `:issue_id`)
  - `"reopen"` - Reopen an issue (requires `:issue_id`)
  - `"dep_add"` - Add dependency (requires `:issue_id`, `:deps`)
  - `"dep_remove"` - Remove dependency (requires `:issue_id`, `:deps`)
  - `"dep_tree"` - Show dependency tree (requires `:issue_id`)
  - `"comment"` - Add comment (requires `:issue_id`, `:description`)
  - `"update"` - Update issue (requires `:issue_id`)

  ## Options

    - `:cwd` - Working directory (default: current directory)
    - `:timeout` - Command timeout in milliseconds (default: 30000)

  ## Returns

    - `{:ok, %{stdout: String.t(), stderr: String.t(), exit_code: integer()}}`
    - `{:error, reason}`
  """
  @impl true
  @spec execute(Mana.Pack.Agent.task(), Mana.Pack.Agent.opts()) ::
          {:ok, map()} | {:error, term()}
  def execute(task, opts \\ []) do
    command = build_bd_command(task)
    cwd = Keyword.get(opts, :cwd, File.cwd!())
    timeout = Keyword.get(opts, :timeout, 30_000)

    Logger.debug("Bloodhound executing: bd #{Enum.join(command, " ")}")

    try do
      case Mana.Pack.CommandRunner.run("bd", command,
             cd: cwd,
             stderr_to_stdout: true,
             parallelism: true,
             timeout: timeout
           ) do
        {:ok, output} ->
          {:ok, %{stdout: output, stderr: "", exit_code: 0}}

        {:error, {:exit_code, _code, output}} ->
          {:ok, %{stdout: output, stderr: output, exit_code: 1}}

        {:error, :timeout} ->
          {:error, %{reason: :timeout, timeout_ms: timeout}}

        {:error, reason} ->
          {:error, reason}
      end
    rescue
      e ->
        Logger.error("Bloodhound execution failed: #{inspect(e)}")
        {:error, %{reason: :execution_failed, details: inspect(e)}}
    end
  end

  @doc """
  Builds the bd command based on task metadata.

  ## Examples

      iex> task = %{metadata: %{command: "ready", args: ["--json"]}}
      iex> Mana.Pack.Agents.Bloodhound.build_bd_command(task)
      ["ready", "--json"]
  """
  @spec build_bd_command(Mana.Pack.Agent.task()) :: [String.t()]
  def build_bd_command(%{metadata: metadata}) do
    case Mana.Pack.Agent.get_meta(metadata, :command) do
      "create" ->
        build_create_command(metadata)

      "list" ->
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        ["list" | args]

      "ready" ->
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        ["ready" | args]

      "blocked" ->
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        ["blocked" | args]

      "show" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        if issue_id, do: ["show", issue_id | args], else: ["show"]

      "close" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        if issue_id, do: ["close", issue_id], else: ["close"]

      "reopen" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        if issue_id, do: ["reopen", issue_id], else: ["reopen"]

      "dep_add" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        deps = Mana.Pack.Agent.get_meta(metadata, :deps)
        if issue_id && deps, do: ["dep", "add", issue_id, deps], else: ["dep", "add"]

      "dep_remove" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        deps = Mana.Pack.Agent.get_meta(metadata, :deps)
        if issue_id && deps, do: ["dep", "remove", issue_id, deps], else: ["dep", "remove"]

      "dep_tree" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        if issue_id, do: ["dep", "tree", issue_id], else: ["dep", "tree"]

      "dep_cycles" ->
        ["dep", "cycles"]

      "comment" ->
        issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
        desc = Mana.Pack.Agent.get_meta(metadata, :description) || Mana.Pack.Agent.get_meta(metadata, :comment)
        if issue_id && desc, do: ["comment", issue_id, desc], else: ["comment"]

      "update" ->
        build_update_command(metadata)

      _ ->
        ["list"]
    end
  end

  def build_bd_command(_), do: ["list"]

  @doc """
  Builds a bd create command from metadata.
  """
  @spec build_create_command(map()) :: [String.t()]
  def build_create_command(metadata) do
    description = Mana.Pack.Agent.get_meta(metadata, :description) || ""
    priority = Mana.Pack.Agent.get_meta(metadata, :priority)
    issue_type = Mana.Pack.Agent.get_meta(metadata, :issue_type) || Mana.Pack.Agent.get_meta(metadata, :type)
    deps = Mana.Pack.Agent.get_meta(metadata, :deps)

    args = ["create", description]

    args =
      if priority do
        args ++ ["-p", to_string(priority)]
      else
        args
      end

    args =
      if issue_type do
        args ++ ["-t", to_string(issue_type)]
      else
        args
      end

    args =
      if deps do
        args ++ ["--deps", to_string(deps)]
      else
        args
      end

    args
  end

  @doc """
  Builds a bd update command from metadata.
  """
  @spec build_update_command(map()) :: [String.t()]
  def build_update_command(metadata) do
    issue_id = Mana.Pack.Agent.get_meta(metadata, :issue_id)
    description = Mana.Pack.Agent.get_meta(metadata, :description)
    priority = Mana.Pack.Agent.get_meta(metadata, :priority)
    issue_type = Mana.Pack.Agent.get_meta(metadata, :issue_type) || Mana.Pack.Agent.get_meta(metadata, :type)

    if issue_id do
      args = ["update", issue_id]

      args =
        if description do
          args ++ ["-d", description]
        else
          args
        end

      args =
        if priority do
          args ++ ["-p", to_string(priority)]
        else
          args
        end

      args =
        if issue_type do
          args ++ ["-t", to_string(issue_type)]
        else
          args
        end

      args
    else
      ["update"]
    end
  end
end
