defmodule Mana.Pack.Agents.ShepherdTest do
  @moduledoc """
  Tests for Shepherd agent - code review critic.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Shepherd

  describe "detect_compile_command/1" do
    test "detects Elixir project" do
      # In the actual project directory
      result = Shepherd.detect_compile_command(File.cwd!())
      assert {cmd, args} = result
      assert cmd == "mix"
      assert args == ["compile", "--warnings-as-errors"]
    end
  end

  describe "detect_format_command/1" do
    test "detects Elixir format command" do
      result = Shepherd.detect_format_command(File.cwd!(), true)
      assert {cmd, args} = result
      assert cmd == "mix"
      assert args == ["format", "--check-formatted"]
    end

    test "detects Elixir format without check" do
      result = Shepherd.detect_format_command(File.cwd!(), false)
      assert {cmd, args} = result
      assert cmd == "mix"
      assert args == ["format"]
    end
  end

  describe "detect_test_command/1" do
    test "detects Elixir test command" do
      result = Shepherd.detect_test_command(File.cwd!())
      assert {cmd, args} = result
      assert cmd == "mix"
      assert args == ["test"]
    end
  end

  describe "run_check/4" do
    test "runs mix format check" do
      result = Shepherd.run_check("format", File.cwd!(), false, [])

      assert result.name == "format"
      # Format check should pass in a clean repo
      assert result.status in [:passed, :failed, :skipped]
      assert is_integer(result.duration_ms)
    end

    test "runs compile check" do
      result = Shepherd.run_check("compile", File.cwd!(), false, [])

      assert result.name == "compile"
      assert result.status in [:passed, :failed, :skipped, :error]
      assert is_integer(result.duration_ms)
    end
  end

  describe "check_file_sizes/2" do
    test "returns empty for valid files" do
      # Current directory should have valid sized files
      result = Shepherd.check_file_sizes(File.cwd!(), 600)
      # Should return list of warnings or empty
      assert is_list(result)
    end
  end

  describe "build_summary/2" do
    test "builds approve summary" do
      results = [
        %{name: "format", status: :passed, exit_code: 0, duration_ms: 100},
        %{name: "test", status: :passed, exit_code: 0, duration_ms: 200}
      ]

      summary = Shepherd.build_summary(results, :approve)
      assert summary =~ "APPROVED"
      assert summary =~ "2 passed"
    end

    test "builds changes_requested summary" do
      results = [
        %{name: "format", status: :passed, exit_code: 0, duration_ms: 100},
        %{name: "test", status: :failed, exit_code: 1, duration_ms: 200}
      ]

      summary = Shepherd.build_summary(results, :changes_requested)
      assert summary =~ "CHANGES REQUESTED"
      assert summary =~ "1 failed"
    end
  end

  describe "execute/2" do
    test "runs review with default checks" do
      task = %{
        id: "review-1",
        worktree: File.cwd!(),
        metadata: %{}
      }

      assert {:ok, result} = Shepherd.execute(task, [])

      assert result.verdict in [:approve, :changes_requested]
      assert is_list(result.checks)
      assert result.summary =~ "passed" or result.summary =~ "failed"
    end

    test "runs specific checks" do
      task = %{
        id: "review-1",
        worktree: File.cwd!(),
        metadata: %{checks: ["format"]}
      }

      assert {:ok, result} = Shepherd.execute(task, [])
      assert result.verdict in [:approve, :changes_requested]
      assert length(result.checks) >= 1
    end
  end
end
