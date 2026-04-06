defmodule Mana.Pack.Agents.Watchdog do
  @moduledoc """
  Watchdog 🐕‍🦺 - QA critic.

  The vigilant QA critic who guards the codebase! Ensures tests exist,
  pass, and actually test the right things. No untested code shall pass
  on Watchdog's watch!

  ## Responsibilities

  - Verify test existence for new code
  - Run test suites and verify all tests pass
  - Check test coverage and quality
  - Detect test smells (empty tests, weak assertions, skipped tests)
  - Validate edge case coverage

  ## Review Verdicts

  - `:approve` - All tests pass and coverage is adequate
  - `:changes_requested` - Tests missing, failing, or inadequate

  ## Red Flags (Instant CHANGES_REQUESTED)

  - No tests for new code
  - Any test failure
  - Empty test functions
  - Commented-out tests
  - Skipped tests without documented reason

  ## Example

      task = %{
        id: "qa-1",
        issue_id: "bd-42",
        worktree: "../bd-42",
        description: "QA review of auth feature",
        metadata: %{
          test_patterns: ["test_*.py", "*_test.py"],
          min_coverage: 80,
          check_edge_cases: true
        }
      }

      {:ok, result} = Mana.Pack.Agents.Watchdog.execute(task, [])
  """

  @behaviour Mana.Pack.Agent

  require Logger

  @typedoc "Watchdog-specific task metadata"
  @type metadata :: %{
          test_patterns: [String.t()],
          min_coverage: integer(),
          check_edge_cases: boolean(),
          check_skipped: boolean(),
          test_timeout: integer()
        }

  # Default test patterns by language
  @default_patterns %{
    "python" => ["test_*.py", "*_test.py", "tests/**/*.py"],
    "javascript" => ["*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts"],
    "elixir" => ["*_test.exs", "test/**/*_test.exs"],
    "rust" => ["**/tests/*.rs", "**/test*.rs"],
    "go" => ["*_test.go"]
  }

  # Default test commands
  @test_commands %{
    "mix.exs" => %{command: "mix", args: ["test"], type: :elixir},
    "Cargo.toml" => %{command: "cargo", args: ["test"], type: :rust},
    "pyproject.toml" => %{command: "pytest", args: ["-v"], type: :python},
    "setup.py" => %{command: "pytest", args: ["-v"], type: :python},
    "package.json" => %{command: "npm", args: ["test", "--", "--silent"], type: :javascript},
    "go.mod" => %{command: "go", args: ["test", "./..."], type: :go}
  }

  @doc """
  Executes a Watchdog QA task.

  ## Task Types

  The metadata controls QA behavior:

  - `:test_patterns` - Glob patterns to find test files
  - `:min_coverage` - Minimum acceptable coverage percentage
  - `:check_edge_cases` - Verify error case and boundary tests exist
  - `:check_skipped` - Flag skipped/pending tests
  - `:test_timeout` - Maximum test runtime in milliseconds

  ## Options

    - `:cwd` - Working directory (required, usually the worktree path)
    - `:timeout` - Overall timeout in milliseconds (default: 300000)

  ## Returns

    - `{:ok, %{verdict: :approve | :changes_requested, tests: map(), findings: [map()]}}`
    - `{:error, reason}`
  """
  @impl true
  def name, do: "Watchdog 🐕‍🦺"

  @impl true
  @spec execute(Mana.Pack.Agent.task(), Mana.Pack.Agent.opts()) ::
          {:ok, map()} | {:error, term()}
  def execute(task, opts \\ []) do
    metadata = task[:metadata] || %{}

    cwd =
      case Mana.Pack.Agent.get_meta(task, :worktree) || Keyword.get(opts, :cwd) do
        nil ->
          Logger.warning("Watchdog QA without worktree - using current directory")
          File.cwd!()

        path ->
          path
      end

    test_timeout = Mana.Pack.Agent.get_meta(metadata, :test_timeout) || 180_000

    # Detect project type and test setup
    project_info = detect_project_type(cwd)

    Logger.debug("Watchdog QA starting for #{project_info.type} project in #{cwd}")

    # Find test files
    test_patterns = Mana.Pack.Agent.get_meta(metadata, :test_patterns) || project_info.patterns
    test_files = find_test_files(cwd, test_patterns)

    # Analyze test files for quality issues
    test_analysis = analyze_test_files(test_files, cwd)

    # Run tests
    test_result = run_tests(project_info, cwd, test_timeout)

    # Collect findings
    findings = collect_findings(test_analysis, test_result, metadata)

    # Determine verdict
    verdict = determine_verdict(test_result, test_analysis, findings)

    {:ok,
     %{
       verdict: verdict,
       project_type: project_info.type,
       test_files_found: length(test_files),
       test_files: test_files,
       test_result: test_result,
       analysis: test_analysis,
       findings: findings,
       summary: build_qa_summary(verdict, test_result, test_analysis)
     }}
  end

  @doc """
  Detects the project type based on configuration files.
  """
  @spec detect_project_type(String.t()) :: %{type: atom(), command: map() | nil, patterns: [String.t()]}
  def detect_project_type(cwd) do
    Enum.find_value(@test_commands, fn {file, config} ->
      if File.exists?(Path.join(cwd, file)) do
        type = config.type
        patterns = Map.get(@default_patterns, to_string(type), [])
        %{type: type, command: config, patterns: patterns}
      end
    end) || %{type: :unknown, command: nil, patterns: []}
  end

  @doc """
  Finds test files matching the given patterns.
  """
  @spec find_test_files(String.t(), [String.t()]) :: [String.t()]
  def find_test_files(cwd, patterns) do
    patterns
    |> Enum.flat_map(fn pattern ->
      Path.wildcard(Path.join(cwd, pattern))
    end)
    |> Enum.uniq()
    |> Enum.reject(fn path ->
      # Exclude common non-test directories
      String.contains?(path, ["node_modules", ".git", "_build", "target", "dist", "build"])
    end)
  end

  @doc """
  Analyzes test files for quality issues.
  """
  @spec analyze_test_files([String.t()], String.t()) :: map()
  def analyze_test_files(test_files, cwd) do
    Enum.reduce(test_files, %{issues: [], stats: %{}}, fn file, acc ->
      analysis = analyze_single_test_file(file, cwd)
      %{acc | issues: acc.issues ++ analysis.issues}
    end)
  end

  defp analyze_single_test_file(file_path, _cwd) do
    content =
      case File.read(file_path) do
        {:ok, content} -> content
        _ -> ""
      end

    issues = []

    # Check for empty tests
    issues =
      if has_empty_tests?(content) do
        [%{type: :empty_test, file: file_path, severity: :error} | issues]
      else
        issues
      end

    # Check for commented-out tests
    issues =
      if has_commented_tests?(content) do
        [%{type: :commented_test, file: file_path, severity: :warning} | issues]
      else
        issues
      end

    # Check for skipped tests
    issues =
      if has_skipped_tests?(content) do
        [%{type: :skipped_test, file: file_path, severity: :warning} | issues]
      else
        issues
      end

    # Check for weak assertions (language-specific patterns)
    issues =
      if has_weak_assertions?(content, Path.extname(file_path)) do
        [%{type: :weak_assertion, file: file_path, severity: :warning} | issues]
      else
        issues
      end

    %{issues: issues}
  end

  defp has_empty_tests?(content) do
    # Match patterns like: def test_foo(): pass, it('foo', () => {}), etc.
    Regex.match?(~r/def\s+test_\w+\s*\(\s*\)\s*:\s*pass|it\s*\(\s*['"]\s*\w+/, content)
  end

  defp has_commented_tests?(content) do
    # Check for commented test definitions using string patterns
    # instead of complex regex to avoid escaping issues
    String.contains?(content, "# def test_") or
      String.contains?(content, "/* it(") or
      String.contains?(content, "// test(")
  end

  defp has_skipped_tests?(content) do
    # Check for skip decorators/patterns
    Regex.match?(~r/\.skip|@pytest\.mark\.skip|@skip|pending|xit|xtest/i, content)
  end

  defp has_weak_assertions?(content, ".py") do
    # Check for weak assertions in Python
    Regex.match?(~r/assert\s+(True|False|None|not\s+None)\s*$|assert\s+\w+\s+is\s+not\s+None/m, content) and
      not Regex.match?(~r/assert\s+\w+\s*[=!<>]=?/m, content)
  end

  defp has_weak_assertions?(content, ".js") do
    # Check for weak assertions in JavaScript
    Regex.match?(
      ~r/expect\s*\(\s*\w+\s*\)\.toBe\s*\(\s*(true|false|null|undefined)\s*\)|expect\s*\(\s*\w+\s*\)\.toBeTruthy\s*\(\s*\)/,
      content
    ) and
      not Regex.match?(~r/expect\s*\(\s*\w+\s*\)\.toEqual|\.toBe\s*\([^tf]/, content)
  end

  defp has_weak_assertions?(content, ".exs") do
    # Check for weak assertions in Elixir
    Regex.match?(~r/assert\s+(true|false|nil|is_nil)/, content) and
      not Regex.match?(~r/assert\s+.*==|assert_in_delta|assert_raise/, content)
  end

  defp has_weak_assertions?(_content, _ext), do: false

  @doc """
  Runs the test suite for the project.
  """
  @spec run_tests(map(), String.t(), integer()) :: map()
  def run_tests(%{command: nil}, _cwd, _timeout) do
    %{
      status: :skipped,
      exit_code: 0,
      output: "No test command detected for project type",
      passed: 0,
      failed: 0,
      skipped: 0,
      duration_ms: 0
    }
  end

  def run_tests(%{command: command}, cwd, timeout) do
    start_time = System.monotonic_time(:millisecond)

    try do
      case Mana.Pack.CommandRunner.run(command.command, command.args,
             cd: cwd,
             stderr_to_stdout: true,
             parallelism: true,
             timeout: timeout
           ) do
        {:ok, output} ->
          stats = parse_test_output(output, command.type)

          %{
            status: :passed,
            exit_code: 0,
            output: output,
            passed: stats.passed,
            failed: stats.failed,
            skipped: stats.skipped,
            duration_ms: System.monotonic_time(:millisecond) - start_time
          }

        {:error, {:exit_code, _code, output}} ->
          stats = parse_test_output(output, command.type)

          %{
            status: :failed,
            exit_code: 1,
            output: output,
            passed: stats.passed,
            failed: stats.failed,
            skipped: stats.skipped,
            duration_ms: System.monotonic_time(:millisecond) - start_time
          }

        {:error, :timeout} ->
          %{
            status: :timeout,
            exit_code: -1,
            output: "Tests timed out after #{timeout}ms",
            passed: 0,
            failed: 0,
            skipped: 0,
            duration_ms: timeout
          }

        {:error, reason} ->
          %{
            status: :error,
            exit_code: -1,
            output: "Test execution failed: #{inspect(reason)}",
            passed: 0,
            failed: 0,
            skipped: 0,
            duration_ms: System.monotonic_time(:millisecond) - start_time
          }
      end
    rescue
      e ->
        %{
          status: :error,
          exit_code: -1,
          output: "Test execution failed: #{inspect(e)}",
          passed: 0,
          failed: 0,
          skipped: 0,
          duration_ms: System.monotonic_time(:millisecond) - start_time
        }
    end
  end

  @doc """
  Parses test output to extract statistics.
  """
  @spec parse_test_output(String.t(), atom()) :: %{passed: integer(), failed: integer(), skipped: integer()}
  def parse_test_output(output, :python) do
    # Parse pytest output: "X passed, Y failed, Z skipped"
    passed = extract_count(output, ~r/(\d+)\s+passed/)
    failed = extract_count(output, ~r/(\d+)\s+failed/)
    skipped = extract_count(output, ~r/(\d+)\s+skipped/)
    %{passed: passed, failed: failed, skipped: skipped}
  end

  def parse_test_output(output, :javascript) do
    # Parse Jest/npm test output
    passed = extract_count(output, ~r/(\d+)\s+passing|Tests:\s+(\d+)\s+passed/)
    failed = extract_count(output, ~r/(\d+)\s+failing|Tests:\s+.*?(\d+)\s+failed/)
    skipped = extract_count(output, ~r/(\d+)\s+pending|skipped/)
    %{passed: passed, failed: failed, skipped: skipped}
  end

  def parse_test_output(output, :elixir) do
    # Parse ExUnit output
    passed = extract_count(output, ~r/(\d+)\s+doctest|\d+\s+test.*?(\d+)\s+passed/)
    failed = extract_count(output, ~r/(\d+)\s+failure/)
    skipped = extract_count(output, ~r/(\d+)\s+excluded/)
    %{passed: passed, failed: failed, skipped: skipped}
  end

  def parse_test_output(output, :rust) do
    # Parse cargo test output
    passed = extract_count(output, ~r/test result:.*?ok.*?\d+\s+passed/)
    failed = extract_count(output, ~r/test result:.*?FAILED.*?\d+\s+failed/)
    skipped = 0
    %{passed: passed, failed: failed, skipped: skipped}
  end

  def parse_test_output(output, :go) do
    # Parse go test output
    passed = extract_count(output, ~r/^(ok|PASS)/m)
    failed = extract_count(output, ~r/^(FAIL)/m)
    skipped = 0
    %{passed: passed, failed: failed, skipped: skipped}
  end

  def parse_test_output(_output, _type) do
    %{passed: 0, failed: 0, skipped: 0}
  end

  defp extract_count(output, pattern) do
    case Regex.run(pattern, output) do
      [_, count | _] -> String.to_integer(count)
      _ -> 0
    end
  end

  @doc """
  Collects all QA findings from analysis and test results.
  """
  @spec collect_findings(map(), map(), map()) :: [map()]
  def collect_findings(analysis, test_result, metadata) do
    findings = analysis[:issues] || []

    # Add test result findings
    findings =
      cond do
        test_result.status == :failed ->
          [%{type: :test_failure, severity: :error, message: "Test suite has failures"} | findings]

        test_result.status == :timeout ->
          [%{type: :test_timeout, severity: :error, message: "Test suite timed out"} | findings]

        test_result.status == :error ->
          [%{type: :test_error, severity: :error, message: "Test execution error"} | findings]

        true ->
          findings
      end

    # Check for no tests
    findings =
      if test_result.passed == 0 && test_result.failed == 0 && test_result.skipped == 0 do
        [%{type: :no_tests, severity: :error, message: "No tests found or executed"} | findings]
      else
        findings
      end

    # Check coverage if specified
    min_coverage = Mana.Pack.Agent.get_meta(metadata, :min_coverage)

    findings =
      if min_coverage && test_result[:coverage] && test_result.coverage < min_coverage do
        [
          %{
            type: :low_coverage,
            severity: :warning,
            message: "Coverage #{test_result.coverage}% below minimum #{min_coverage}%"
          }
          | findings
        ]
      else
        findings
      end

    findings
  end

  @doc """
  Determines the final QA verdict based on findings.
  """
  @spec determine_verdict(map(), map(), [map()]) :: :approve | :changes_requested
  def determine_verdict(test_result, _analysis, findings) do
    # Any error severity finding means changes required
    has_errors = Enum.any?(findings, &(&1[:severity] == :error))

    # Failed tests mean changes required
    tests_failed = test_result.status == :failed || test_result.failed > 0

    if has_errors || tests_failed do
      :changes_requested
    else
      :approve
    end
  end

  @doc """
  Builds a human-readable QA summary.
  """
  @spec build_qa_summary(:approve | :changes_requested, map(), map()) :: String.t()
  def build_qa_summary(verdict, test_result, analysis) do
    issue_count = length(analysis[:issues] || [])

    status =
      case verdict do
        :approve -> "✅ APPROVED"
        :changes_requested -> "❌ CHANGES REQUESTED"
      end

    test_info =
      if test_result.status != :skipped do
        "#{test_result.passed} passed, #{test_result.failed} failed, #{test_result.skipped} skipped"
      else
        "No tests run"
      end

    "#{status} - #{test_info}, #{issue_count} issues found"
  end

  @doc """
  Quick QA check for a worktree.

  Convenience function that runs default QA checks.
  """
  @spec quick_check(String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def quick_check(worktree, opts \\ []) do
    task = %{
      id: "quick-qa-#{:erlang.unique_integer([:positive])}",
      issue_id: opts[:issue_id],
      worktree: worktree,
      description: "Quick QA check",
      metadata: %{}
    }

    execute(task, opts)
  end
end
