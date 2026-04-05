defmodule Mana.Pack.Agents.Terrier do
  @moduledoc """
  Terrier 🐕 - Worktree management specialist.

  The worktree digging specialist! Creates, manages, and cleans up git worktrees
  for parallel development. Each worktree is a separate working directory with
  its own branch.

  ## Responsibilities

  - Create worktrees for new branches
  - List existing worktrees
  - Remove/clean up worktrees
  - Prune stale worktree entries

  ## Naming Conventions

  - Worktree paths: `../bd-<issue-number>` or `../feature-<slug>`
  - Branch names: `feature/<issue-id>-<slug>`

  ## Example

      task = %{
        id: "task-1",
        issue_id: "bd-42",
        worktree: "../bd-42",
        description: "Create worktree for bd-42",
        metadata: %{
          action: "create",
          branch: "feature/bd-42-auth",
          base: "main"
        }
      }

      {:ok, result} = Mana.Pack.Agents.Terrier.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Terrier-specific task metadata"
  @type metadata :: %{
          action: String.t(),
          branch: String.t() | nil,
          base: String.t() | nil,
          force: boolean()
        }

  @doc """
  Executes a Terrier task.

  ## Task Types

  The metadata `:action` field determines the operation:

  - `"create"` - Create a new worktree (requires `:worktree`, `:branch`)
  - `"list"` - List existing worktrees
  - `"remove"` - Remove a worktree (requires `:worktree`)
  - `"prune"` - Prune stale worktree entries
  - `"move"` - Move a worktree (requires `:source`, `:destination`)

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
    cwd = Keyword.get(opts, :cwd, File.cwd!())
    timeout = Keyword.get(opts, :timeout, 30_000)

    command = build_git_command(task)

    Logger.debug("Terrier executing: git #{Enum.join(command, " ")}")

    try do
      case Mana.Pack.CommandRunner.run("git", command,
             cd: cwd,
             stderr_to_stdout: true,
             parallelism: true,
             timeout: timeout
           ) do
        {:ok, output} ->
          {:ok, %{stdout: output, stderr: "", exit_code: 0}}

        {:error, {:exit_code, _code, output}} ->
          # Check if this is a "already exists" error which we can handle gracefully
          if String.contains?(output, "already exists") or String.contains?(output, "already checked out") do
            {:ok, %{stdout: output, stderr: output, exit_code: 0, warning: :already_exists}}
          else
            {:error, %{reason: :git_error, stdout: output, exit_code: 1}}
          end

        {:error, :timeout} ->
          {:error, %{reason: :timeout, timeout_ms: timeout}}

        {:error, reason} ->
          {:error, reason}
      end
    rescue
      e ->
        Logger.error("Terrier execution failed: #{inspect(e)}")
        {:error, %{reason: :execution_failed, details: inspect(e)}}
    end
  end

  @doc """
  Builds the git worktree command based on task metadata.

  ## Examples

      iex> task = %{metadata: %{action: "list"}}
      iex> Mana.Pack.Agents.Terrier.build_git_command(task)
      ["worktree", "list"]

      iex> task = %{worktree: "../bd-42", metadata: %{action: "create", branch: "feature/bd-42-auth", base: "main"}}
      iex> Mana.Pack.Agents.Terrier.build_git_command(task)
      ["worktree", "add", "../bd-42", "-b", "feature/bd-42-auth", "main"]
  """
  @spec build_git_command(Mana.Pack.Agent.task()) :: [String.t()]
  def build_git_command(task) do
    metadata = task[:metadata] || %{}
    action = Mana.Pack.Agent.get_meta(metadata, :action) || "list"

    case action do
      "create" ->
        build_create_command(task, metadata)

      "list" ->
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        ["worktree", "list" | args]

      "remove" ->
        worktree = task[:worktree] || task["worktree"] || Mana.Pack.Agent.get_meta(metadata, :worktree)
        force = Mana.Pack.Agent.get_meta(metadata, :force) || false

        if worktree do
          if force, do: ["worktree", "remove", "--force", worktree], else: ["worktree", "remove", worktree]
        else
          ["worktree", "remove"]
        end

      "prune" ->
        ["worktree", "prune"]

      "move" ->
        source = Mana.Pack.Agent.get_meta(metadata, :source)
        destination = Mana.Pack.Agent.get_meta(metadata, :destination)

        if source && destination do
          ["worktree", "move", source, destination]
        else
          ["worktree", "move"]
        end

      "verify" ->
        worktree = task[:worktree] || task["worktree"] || Mana.Pack.Agent.get_meta(metadata, :worktree)
        if worktree, do: ["worktree", "list", worktree], else: ["worktree", "list"]

      _ ->
        ["worktree", "list"]
    end
  end

  @doc """
  Builds a git worktree add command.
  """
  @spec build_create_command(Mana.Pack.Agent.task(), map()) :: [String.t()]
  def build_create_command(task, metadata) do
    worktree = task[:worktree] || task["worktree"] || Mana.Pack.Agent.get_meta(metadata, :worktree)
    branch = Mana.Pack.Agent.get_meta(metadata, :branch)
    base = Mana.Pack.Agent.get_meta(metadata, :base) || "main"

    cond do
      worktree && branch ->
        ["worktree", "add", worktree, "-b", branch, base]

      worktree ->
        ["worktree", "add", worktree, base]

      true ->
        ["worktree", "add"]
    end
  end

  @doc """
  Generates a standard worktree path for an issue.

  ## Examples

      iex> Mana.Pack.Agents.Terrier.worktree_path_for_issue("bd-42")
      "../bd-42"

      iex> Mana.Pack.Agents.Terrier.worktree_path_for_issue("bd-42", "/home/user/project")
      "/home/user/bd-42"
  """
  @spec worktree_path_for_issue(String.t(), String.t() | nil) :: String.t()
  def worktree_path_for_issue(issue_id, base_path \\ nil) do
    if base_path do
      Path.join([Path.dirname(base_path), issue_id])
    else
      "../#{issue_id}"
    end
  end

  @doc """
  Generates a standard branch name for an issue.

  ## Examples

      iex> Mana.Pack.Agents.Terrier.branch_name_for_issue("bd-42", "implement-auth")
      "feature/bd-42-implement-auth"
  """
  @spec branch_name_for_issue(String.t(), String.t()) :: String.t()
  def branch_name_for_issue(issue_id, slug) do
    "feature/#{issue_id}-#{slug}"
  end

  @doc """
  Checks if a worktree exists.

  Returns `{:ok, boolean()}` where the boolean indicates if the worktree exists.
  """
  @spec worktree_exists?(String.t(), keyword()) :: {:ok, boolean()} | {:error, term()}
  def worktree_exists?(worktree_path, opts \\ []) do
    cwd = Keyword.get(opts, :cwd, File.cwd!())

    case Mana.Pack.CommandRunner.run("git", ["worktree", "list", "--porcelain"],
           cd: cwd,
           stderr_to_stdout: true,
           parallelism: true
         ) do
      {:ok, output} ->
        exists = String.contains?(output, worktree_path)
        {:ok, exists}

      {:error, reason} ->
        {:error, %{reason: :git_error, details: reason}}
    end
  end
end
