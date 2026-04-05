defmodule Mana.Pack.Agents.Shepherd do
  @moduledoc """
  Shepherd 🐕 - Code review critic.

  The code review guardian of the pack! A good shepherd guides the flock,
  and this shepherd guides code toward quality. Reviews code after Husky
  completes work and before Retriever can merge.

  ## Responsibilities

  - Run linters and type checkers
  - Execute tests and verify they pass
  - Check code quality and patterns
  - Provide structured review feedback
  - Verify file size limits (600 line max)

  ## Review Verdicts

  - `:approve` - Code is ready to merge
  - `:changes_requested` - Issues need to be fixed

  ## Example

      task = %{
        id: "review-1",
        issue_id: "bd-42",
        worktree: "../bd-42",
        description: "Review code changes",
        metadata: %{
          checks: ["ruff", "mypy", "pytest"],
          auto_fix: true
        }
      }

      {:ok, result} = Mana.Pack.Agents.Shepherd.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Review check type"
  @type check_type :: String.t()

  @typedoc "Shepherd-specific task metadata"
  @type metadata :: %{
          checks: [check_type()],
          auto_fix: boolean(),
          file_limit: integer()
        }

  # Maximum file size in lines
  @default_file_limit 600

  # Default checks to run
  @default_checks ["compile", "format", "test"]

  # Check configurations by language/project type
  @check_configs %{
    "ruff" => %{command: "ruff", args: ["check", "."]},
    "ruff_fix" => %{command: "ruff", args: ["check", "--fix", "."]},
    "ruff_format" => %{command: "ruff", args: ["format", "."]},
    "mypy" => %{command: "mypy", args: ["src/"]},
    "eslint" => %{command: "npx", args: ["eslint", "src/"]},
    "tsc" => %{command: "npx", args: ["tsc", "--noEmit"]},
    "pytest" => %{command: "pytest", args: ["-v"]},
    "pytest_silent" => %{command: "pytest", args: ["--tb=short"]},
    "npm_test" => %{command: "npm", args: ["test", "--", "--silent"]},
    "cargo_test" => %{command: "cargo", args: ["test"]},
    "cargo_check" => %{command: "cargo", args: ["check"]},
    "cargo_clippy" => %{command: "cargo", args: ["clippy", "--", "-D", "warnings"]},
    "mix_test" => %{command: "mix", args: ["test"]},
    "mix_format" => %{command: "mix", args: ["format", "--check-formatted"]},
    "mix_compile" => %{command: "mix", args: ["compile", "--warnings-as-errors"]},
    "go_test" => %{command: "go", args: ["test", "./..."]},
    "go_vet" => %{command: "go", args: ["vet", "./..."]},
    "compile" => %{command: nil, args: [], type: :compile},
    "format" => %{command: nil, args: [], type: :format},
    "test" => %{command: nil, args: [], type: :test}
  }

  @doc """
  Executes a Shepherd review task.

  ## Task Types

  The metadata `:checks` field specifies which checks to run:

  - `"ruff"` - Python linting
  - `"ruff_fix"` - Python linting with auto-fix
  - `"mypy"` - Python type checking
  - `"eslint"` - JavaScript/TypeScript linting
  - `"tsc"` - TypeScript type checking
  - `"pytest"` / `"npm_test"` / `"cargo_test"` / `"mix_test"` / `"go_test"` - Test suites
  - `"cargo_check"` / `"cargo_clippy"` - Rust checks
  - `"mix_format"` / `"mix_compile"` - Elixir checks
  - `"compile"` / `"format"` / `"test"` - Generic checks (auto-detected)

  ## Options

    - `:cwd` - Working directory (required, usually the worktree path)
    - `:timeout` - Per-check timeout in milliseconds (default: 120000)
    - `:auto_fix` - Attempt to auto-fix issues where possible

  ## Returns

    - `{:ok, %{verdict: :approve | :changes_requested, checks: [map()], summary: String.t()}}`
    - `{:error, reason}`
  """
  @impl true
  @spec execute(Mana.Pack.Agent.task(), Mana.Pack.Agent.opts()) ::
          {:ok, map()} | {:error, term()}
  def execute(task, opts \\ []) do
    metadata = task[:metadata] || %{}

    cwd =
      case Mana.Pack.Agent.get_meta(task, :worktree) || Keyword.get(opts, :cwd) do
        nil ->
          Logger.warning("Shepherd review without worktree - using current directory")
          File.cwd!()

        path ->
          path
      end

    checks = Mana.Pack.Agent.get_meta(metadata, :checks) || @default_checks
    auto_fix = Mana.Pack.Agent.get_meta(metadata, :auto_fix) || Keyword.get(opts, :auto_fix, false)
    file_limit = Mana.Pack.Agent.get_meta(metadata, :file_limit) || @default_file_limit

    Logger.debug("Shepherd reviewing #{cwd} with checks: #{inspect(checks)}")

    # Run each check
    check_results =
      Enum.map(checks, fn check ->
        run_check(check, cwd, auto_fix, opts)
      end)

    # Check file sizes if there are new/modified files
    size_results = check_file_sizes(cwd, file_limit)

    # Aggregate results
    all_results = check_results ++ size_results
    failed_count = Enum.count(all_results, fn r -> r[:exit_code] != 0 end)

    verdict = if failed_count == 0, do: :approve, else: :changes_requested

    summary = build_summary(all_results, verdict)

    {:ok,
     %{
       verdict: verdict,
       checks: all_results,
       summary: summary,
       worktree: cwd,
       failed_count: failed_count,
       total_count: length(all_results)
     }}
  end

  @doc """
  Runs a single check.
  """
  @spec run_check(String.t(), String.t(), boolean(), keyword()) :: map()
  def run_check(check_name, cwd, auto_fix, opts) do
    timeout = Keyword.get(opts, :timeout, 120_000)

    config = Map.get(@check_configs, check_name, %{command: check_name, args: []})

    # Handle generic checks
    {command, args} =
      case config[:type] do
        :compile -> detect_compile_command(cwd)
        :format -> detect_format_command(cwd, auto_fix)
        :test -> detect_test_command(cwd)
        _ -> {config.command, config.args}
      end

    start_time = System.monotonic_time(:millisecond)

    result =
      if command do
        try do
          case Mana.Pack.CommandRunner.run(command, args,
                 cd: cwd,
                 stderr_to_stdout: true,
                 parallelism: true,
                 timeout: timeout
               ) do
            {:ok, output} ->
              %{
                name: check_name,
                status: :passed,
                exit_code: 0,
                output: output,
                duration_ms: System.monotonic_time(:millisecond) - start_time
              }

            {:error, {:exit_code, _code, output}} ->
              %{
                name: check_name,
                status: :failed,
                exit_code: 1,
                output: output,
                duration_ms: System.monotonic_time(:millisecond) - start_time
              }

            {:error, :timeout} ->
              %{
                name: check_name,
                status: :timeout,
                exit_code: -1,
                output: "Check timed out after #{timeout}ms",
                duration_ms: timeout
              }

            {:error, reason} ->
              %{
                name: check_name,
                status: :error,
                exit_code: -1,
                output: "Execution failed: #{inspect(reason)}",
                duration_ms: System.monotonic_time(:millisecond) - start_time
              }
          end
        rescue
          e ->
            %{
              name: check_name,
              status: :error,
              exit_code: -1,
              output: "Execution failed: #{inspect(e)}",
              duration_ms: System.monotonic_time(:millisecond) - start_time
            }
        end
      else
        %{
          name: check_name,
          status: :skipped,
          exit_code: 0,
          output: "No command detected for this project type",
          duration_ms: 0
        }
      end

    # Try to auto-fix if requested and check failed
    if auto_fix && result.status == :failed && check_name == "ruff" do
      fix_result = run_check("ruff_fix", cwd, false, opts)

      if fix_result.status == :passed do
        %{result | status: :fixed, output: "Auto-fixed by ruff"}
      else
        result
      end
    else
      result
    end
  end

  @doc """
  Detects the appropriate compile command for a project.
  """
  @spec detect_compile_command(String.t()) :: {String.t(), [String.t()]} | {nil, []}
  def detect_compile_command(cwd) do
    cond do
      File.exists?(Path.join(cwd, "mix.exs")) -> {"mix", ["compile", "--warnings-as-errors"]}
      File.exists?(Path.join(cwd, "Cargo.toml")) -> {"cargo", ["check"]}
      File.exists?(Path.join(cwd, "pyproject.toml")) -> {"python", ["-m", "py_compile", "setup.py"]}
      File.exists?(Path.join(cwd, "package.json")) -> {"npm", ["run", "build"]}
      File.exists?(Path.join(cwd, "go.mod")) -> {"go", ["build", "./..."]}
      true -> {nil, []}
    end
  end

  @doc """
  Detects the appropriate format command for a project.
  """
  @spec detect_format_command(String.t(), boolean()) :: {String.t(), [String.t()]} | {nil, []}
  def detect_format_command(cwd, check_only \\ true) do
    cond do
      File.exists?(Path.join(cwd, "mix.exs")) ->
        if check_only, do: {"mix", ["format", "--check-formatted"]}, else: {"mix", ["format"]}

      File.exists?(Path.join(cwd, "Cargo.toml")) ->
        {"cargo", ["fmt", "--", "--check"]}
        |> then(fn {cmd, args} -> if check_only, do: {cmd, args}, else: {"cargo", ["fmt"]} end)

      File.exists?(Path.join(cwd, "pyproject.toml")) ->
        if check_only, do: {"ruff", ["format", "--check", "."]}, else: {"ruff", ["format", "."]}

      File.exists?(Path.join(cwd, "package.json")) ->
        if check_only, do: {"npx", ["prettier", "--check", "."]}, else: {"npx", ["prettier", "--write", "."]}

      true ->
        {nil, []}
    end
  end

  @doc """
  Detects the appropriate test command for a project.
  """
  @spec detect_test_command(String.t()) :: {String.t(), [String.t()]} | {nil, []}
  def detect_test_command(cwd) do
    cond do
      File.exists?(Path.join(cwd, "mix.exs")) -> {"mix", ["test"]}
      File.exists?(Path.join(cwd, "Cargo.toml")) -> {"cargo", ["test"]}
      File.exists?(Path.join(cwd, "pyproject.toml")) -> {"pytest", ["-v"]}
      File.exists?(Path.join(cwd, "package.json")) -> {"npm", ["test", "--", "--silent"]}
      File.exists?(Path.join(cwd, "go.mod")) -> {"go", ["test", "./..."]}
      true -> {nil, []}
    end
  end

  @doc """
  Checks file sizes in the worktree.
  """
  @spec check_file_sizes(String.t(), integer()) :: [map()]
  def check_file_sizes(cwd, limit) do
    # Find source files and check their line counts
    patterns = [
      "lib/**/*.ex",
      "src/**/*.{py,js,ts,rs,go}",
      "app/**/*.{py,js,ts,rb}",
      "*.py",
      "*.js",
      "*.ts",
      "*.ex"
    ]

    results =
      Enum.flat_map(patterns, fn pattern ->
        Path.wildcard(Path.join(cwd, pattern))
      end)
      |> Enum.reject(&String.contains?(&1, ["test", "_test", ".git", "node_modules", "_build", "target"]))
      |> Enum.map(&check_file_size(&1, limit))
      |> Enum.reject(&is_nil/1)

    if Enum.empty?(results) do
      []
    else
      [
        %{
          name: "file_size_check",
          status: :warning,
          exit_code: 0,
          output: "Found #{length(results)} files exceeding #{limit} lines",
          details: results
        }
      ]
    end
  end

  defp check_file_size(file_path, limit) do
    try do
      lines =
        file_path
        |> File.read!()
        |> String.split("\n")
        |> length()

      if lines > limit do
        %{
          file: file_path,
          lines: lines,
          limit: limit,
          exceeds_by: lines - limit
        }
      else
        nil
      end
    rescue
      _ -> nil
    end
  end

  @doc """
  Builds a summary string from check results.
  """
  @spec build_summary([map()], :approve | :changes_requested) :: String.t()
  def build_summary(results, verdict) do
    passed = Enum.count(results, &(&1[:status] == :passed))
    failed = Enum.count(results, &(&1[:status] == :failed))
    errors = Enum.count(results, &(&1[:status] == :error))
    fixed = Enum.count(results, &(&1[:status] == :fixed))

    status_text =
      case verdict do
        :approve -> "✅ APPROVED"
        :changes_requested -> "🔄 CHANGES REQUESTED"
      end

    check_summary =
      [
        if(passed > 0, do: "#{passed} passed", else: nil),
        if(fixed > 0, do: "#{fixed} auto-fixed", else: nil),
        if(failed > 0, do: "#{failed} failed", else: nil),
        if(errors > 0, do: "#{errors} errors", else: nil)
      ]
      |> Enum.reject(&is_nil/1)
      |> Enum.join(", ")

    "#{status_text} - #{check_summary}"
  end
end
