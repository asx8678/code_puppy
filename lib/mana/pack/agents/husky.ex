defmodule Mana.Pack.Agents.Husky do
  @moduledoc """
  Husky 🐺 - Task execution specialist.

  The sled dog of the pack! Strong, reliable, and built for pulling heavy loads.
  Executes actual coding tasks within worktrees. Given a bd issue and a worktree,
  Husky makes it happen!

  ## Responsibilities

  - Execute shell commands in worktree isolation
  - Run tests (pytest, npm test, cargo test, etc.)
  - Run linters and formatters
  - Execute build commands
  - Run git commands in worktrees

  ## Example

      task = %{
        id: "task-1",
        issue_id: "bd-42",
        worktree: "../bd-42",
        description: "Run tests in worktree",
        metadata: %{
          command: "pytest",
          args: ["-v"],
          env: %{"PYTHONPATH" => "src"}
        }
      }

      {:ok, result} = Mana.Pack.Agents.Husky.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Husky-specific task metadata"
  @type metadata :: %{
          command: String.t(),
          args: [String.t()],
          env: map() | nil,
          command_type: String.t() | nil
        }

  # Predefined command types with common settings
  @command_types %{
    "pytest" => %{command: "pytest", args: ["-v"]},
    "pytest_silent" => %{command: "pytest", args: ["--tb=short"]},
    "npm_test" => %{command: "npm", args: ["test", "--", "--silent"]},
    "npm_test_verbose" => %{command: "npm", args: ["test"]},
    "cargo_test" => %{command: "cargo", args: ["test"]},
    "mix_test" => %{command: "mix", args: ["test"]},
    "go_test" => %{command: "go", args: ["test", "./..."]},
    "ruff_check" => %{command: "ruff", args: ["check", "."]},
    "ruff_format" => %{command: "ruff", args: ["format", "."]},
    "mypy" => %{command: "mypy", args: ["src/"]},
    "eslint" => %{command: "npx", args: ["eslint", "src/"]},
    "tsc" => %{command: "npx", args: ["tsc", "--noEmit"]},
    "git_status" => %{command: "git", args: ["status"]},
    "git_add" => %{command: "git", args: ["add", "-A"]},
    "git_commit" => %{command: "git", args: ["commit", "-m"]},
    "git_push" => %{command: "git", args: ["push", "-u", "origin"]},
    "mix_compile" => %{command: "mix", args: ["compile", "--warnings-as-errors"]},
    "mix_format" => %{command: "mix", args: ["format", "--check-formatted"]}
  }

  @doc """
  Executes a Husky task.

  ## Task Types

  The metadata can specify either:
  - `:command_type` - Use a predefined command type (e.g., "pytest", "npm_test")
  - `:command` + `:args` - Custom command with arguments

  Common command types:

  - `"pytest"` - Run Python tests with verbose output
  - `"pytest_silent"` - Run Python tests with short tracebacks
  - `"npm_test"` - Run npm tests silently
  - `"npm_test_verbose"` - Run npm tests with output
  - `"cargo_test"` - Run Rust tests
  - `"mix_test"` - Run Elixir tests
  - `"go_test"` - Run Go tests
  - `"ruff_check"` - Run Python linter
  - `"ruff_format"` - Format Python code
  - `"mypy"` - Run Python type checker
  - `"eslint"` - Run JavaScript/TypeScript linter
  - `"tsc"` - Run TypeScript type checker
  - `"git_status"`, `"git_add"`, `"git_commit"`, `"git_push"` - Git operations

  ## Options

    - `:cwd` - Working directory (required, usually the worktree path)
    - `:timeout` - Command timeout in milliseconds (default: 120000 for tests)
    - `:env` - Additional environment variables

  ## Returns

    - `{:ok, %{stdout: String.t(), stderr: String.t(), exit_code: integer()}}`
    - `{:error, reason}`
  """
  @impl true
  @spec execute(Mana.Pack.Agent.task(), Mana.Pack.Agent.opts()) ::
          {:ok, map()} | {:error, term()}
  def execute(task, opts \\ []) do
    metadata = task[:metadata] || %{}

    # Get worktree from task or opts, with validation
    cwd =
      case Mana.Pack.Agent.get_meta(task, :worktree) || Keyword.get(opts, :cwd) do
        nil ->
          Logger.warning("Husky task executed without a worktree - using current directory")
          File.cwd!()

        path ->
          path
      end

    timeout =
      Keyword.get(opts, :timeout, compute_timeout(Mana.Pack.Agent.get_meta(metadata, :command_type)))

    {command, args, _env} = build_command(metadata)

    Logger.debug("Husky executing in #{cwd}: #{command} #{Enum.join(args, " ")}")

    # Build environment
    base_env =
      case Mana.Pack.Agent.get_meta(metadata, :env) do
        nil -> []
        env_map -> Enum.map(env_map, fn {k, v} -> {to_string(k), to_string(v)} end)
      end

    cmd_opts =
      if Enum.empty?(base_env) do
        [cd: cwd, stderr_to_stdout: true, parallelism: true]
      else
        [cd: cwd, stderr_to_stdout: true, parallelism: true, env: base_env]
      end

    try do
      case Mana.Pack.CommandRunner.run(command, args, Keyword.put(cmd_opts, :timeout, timeout)) do
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
        Logger.error("Husky execution failed: #{inspect(e)}")
        {:error, %{reason: :execution_failed, details: inspect(e)}}
    end
  end

  @doc """
  Builds the command based on metadata.

  Returns `{command, args, env}` tuple.
  """
  @spec build_command(map()) :: {String.t(), [String.t()], keyword()}
  def build_command(metadata) do
    command_type = Mana.Pack.Agent.get_meta(metadata, :command_type)

    case command_type do
      nil ->
        # Custom command
        command = Mana.Pack.Agent.get_meta(metadata, :command) || "echo"
        args = Mana.Pack.Agent.get_meta(metadata, :args) || []
        {to_string(command), Enum.map(args, &to_string/1), []}

      type ->
        case Map.get(@command_types, to_string(type)) do
          nil ->
            # Unknown type, fall back to custom
            command = Mana.Pack.Agent.get_meta(metadata, :command) || "echo"
            args = Mana.Pack.Agent.get_meta(metadata, :args) || []
            {to_string(command), Enum.map(args, &to_string/1), []}

          predefined ->
            # Use predefined but allow override
            custom_args = Mana.Pack.Agent.get_meta(metadata, :args)
            args = if custom_args, do: custom_args, else: predefined.args
            {predefined.command, Enum.map(args, &to_string/1), []}
        end
    end
  end

  @doc """
  Computes appropriate timeout based on command type.
  """
  @spec compute_timeout(String.t() | nil) :: non_neg_integer()
  def compute_timeout(nil), do: 60_000

  def compute_timeout(type) do
    case type do
      "pytest" -> 120_000
      "pytest_silent" -> 120_000
      "npm_test" -> 180_000
      "npm_test_verbose" -> 180_000
      "cargo_test" -> 300_000
      "mix_test" -> 120_000
      "go_test" -> 120_000
      "mix_compile" -> 60_000
      _ -> 60_000
    end
  end

  @doc """
  Runs a test command in a worktree.

  Convenience function for common test execution.
  """
  @spec run_tests(String.t(), String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def run_tests(worktree, test_command \\ "pytest", opts \\ []) do
    task = %{
      id: "test-#{:erlang.unique_integer([:positive])}",
      issue_id: opts[:issue_id],
      worktree: worktree,
      description: "Run #{test_command} tests",
      metadata: %{
        command_type: test_command,
        args: opts[:args] || []
      }
    }

    execute(task, opts)
  end

  @doc """
  Runs git commands in a worktree.

  ## Examples

      Mana.Pack.Agents.Husky.git_command("../bd-42", "status", [])
      Mana.Pack.Agents.Husky.git_command("../bd-42", "commit", ["-m", "feat: add feature"])
  """
  @spec git_command(String.t(), String.t(), [String.t()], keyword()) ::
          {:ok, map()} | {:error, term()}
  def git_command(worktree, subcommand, args \\ [], opts \\ []) do
    task = %{
      id: "git-#{:erlang.unique_integer([:positive])}",
      issue_id: opts[:issue_id],
      worktree: worktree,
      description: "Git #{subcommand}",
      metadata: %{
        command: "git",
        args: [subcommand | args]
      }
    }

    execute(task, opts)
  end

  @doc """
  Commits changes in a worktree with a conventional commit message.
  """
  @spec commit(String.t(), String.t(), String.t(), keyword()) ::
          {:ok, map()} | {:error, term()}
  def commit(worktree, issue_id, message, opts \\ []) do
    type = opts[:type] || "feat"
    full_message = "#{type}: #{message}\n\nCloses #{issue_id}"

    git_command(worktree, "commit", ["-m", full_message], opts)
  end

  @doc """
  Pushes a branch from a worktree to origin.
  """
  @spec push(String.t(), String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def push(worktree, branch, opts \\ []) do
    git_command(worktree, "push", ["-u", "origin", branch], opts)
  end
end
