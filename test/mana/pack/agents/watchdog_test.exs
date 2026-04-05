defmodule Mana.Pack.Agents.WatchdogTest do
  @moduledoc """
  Tests for Watchdog agent - QA critic.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Watchdog

  describe "detect_project_type/1" do
    test "detects Elixir project" do
      result = Watchdog.detect_project_type(File.cwd!())
      assert result.type == :elixir
      assert result.command.command == "mix"
      assert result.command.args == ["test"]
    end
  end

  describe "find_test_files/2" do
    test "finds test files in Elixir project" do
      patterns = ["*_test.exs", "test/**/*_test.exs"]
      files = Watchdog.find_test_files(File.cwd!(), patterns)

      assert is_list(files)
      # Should find test files
      assert files != []
    end
  end

  describe "parse_test_output/2" do
    test "parses ExUnit output" do
      output = """
      ........

      Finished in 0.5 seconds
      8 doctests, 10 tests, 0 failures
      """

      stats = Watchdog.parse_test_output(output, :elixir)
      # 8 doctests + 10 tests
      assert stats.passed >= 8
      assert stats.failed == 0
    end

    test "parses failed ExUnit output" do
      output = """
      ..F..

      1) test something (Module)
         Assertion failed

      Finished in 0.3 seconds
      5 tests, 1 failure
      """

      stats = Watchdog.parse_test_output(output, :elixir)
      assert stats.failed == 1
    end

    test "parses pytest output" do
      output = """
      test_file.py::test_one PASSED
      test_file.py::test_two FAILED
      test_file.py::test_three SKIPPED

      3 passed, 1 failed, 1 skipped
      """

      stats = Watchdog.parse_test_output(output, :python)
      assert stats.passed == 3
      assert stats.failed == 1
      assert stats.skipped == 1
    end
  end

  describe "collect_findings/3" do
    test "collects test failure findings" do
      test_result = %{status: :failed, passed: 5, failed: 2, skipped: 0}
      analysis = %{issues: []}
      metadata = %{}

      findings = Watchdog.collect_findings(analysis, test_result, metadata)

      assert findings != []
      assert Enum.any?(findings, &(&1[:type] == :test_failure))
    end

    test "collects no tests finding" do
      test_result = %{status: :passed, passed: 0, failed: 0, skipped: 0}
      analysis = %{issues: []}
      metadata = %{}

      findings = Watchdog.collect_findings(analysis, test_result, metadata)

      assert Enum.any?(findings, &(&1[:type] == :no_tests))
    end
  end

  describe "determine_verdict/3" do
    test "returns approve when all tests pass" do
      test_result = %{status: :passed, failed: 0}
      analysis = %{issues: []}
      findings = []

      assert Watchdog.determine_verdict(test_result, analysis, findings) == :approve
    end

    test "returns changes_requested when tests fail" do
      test_result = %{status: :failed, failed: 2}
      analysis = %{issues: []}
      findings = []

      assert Watchdog.determine_verdict(test_result, analysis, findings) == :changes_requested
    end

    test "returns changes_requested for error findings" do
      test_result = %{status: :passed, failed: 0}
      analysis = %{issues: []}
      findings = [%{type: :test_error, severity: :error}]

      assert Watchdog.determine_verdict(test_result, analysis, findings) == :changes_requested
    end
  end

  describe "build_qa_summary/3" do
    test "builds approve summary" do
      test_result = %{passed: 10, failed: 0, skipped: 1, status: :passed}
      analysis = %{issues: []}

      summary = Watchdog.build_qa_summary(:approve, test_result, analysis)
      assert summary =~ "APPROVED"
      assert summary =~ "10 passed"
    end

    test "builds changes_requested summary" do
      test_result = %{passed: 8, failed: 2, skipped: 0, status: :failed}
      analysis = %{issues: [%{type: :empty_test}]}

      summary = Watchdog.build_qa_summary(:changes_requested, test_result, analysis)
      assert summary =~ "CHANGES REQUESTED"
    end
  end

  describe "quick_check/2" do
    test "runs quick QA check" do
      result = Watchdog.quick_check(File.cwd!(), [])

      assert {:ok, %{verdict: verdict, test_result: test_result}} = result
      assert verdict in [:approve, :changes_requested]
      assert is_map(test_result)
    end
  end

  describe "execute/2" do
    test "runs full QA review" do
      task = %{
        id: "qa-1",
        worktree: File.cwd!(),
        metadata: %{}
      }

      assert {:ok, result} = Watchdog.execute(task, [])

      assert result.project_type == :elixir
      assert result.verdict in [:approve, :changes_requested]
      # Should find some test files in the project
      assert is_list(result.test_files)
    end
  end
end
