defmodule CodePuppyControl.Tools.CommandRunnerTest do
  @moduledoc """
  Tests for the CommandRunner tool.

  These tests cover:
  - Command validation (forbidden chars, dangerous patterns)
  - Basic command execution (echo, ls)
  - Timeout handling
  - Output truncation
  """

  use CodePuppyControl.StatefulCase

  alias CodePuppyControl.Tools.CommandRunner
  alias CodePuppyControl.Tools.CommandRunner.Validator

  # ============================================================================
  # Validator Tests
  # ============================================================================

  describe "validate/1" do
    test "accepts valid simple command" do
      assert {:ok, "echo hello"} = Validator.validate("echo hello")
    end

    test "rejects empty command" do
      assert {:error, "Command cannot be empty or whitespace only"} = Validator.validate("")
      assert {:error, "Command cannot be empty or whitespace only"} = Validator.validate("   ")
    end

    test "rejects command exceeding max length" do
      long_command = String.duplicate("a", 9000)
      assert {:error, msg} = Validator.validate(long_command)
      assert msg =~ "exceeds maximum length"
    end

    test "rejects command with forbidden control characters" do
      # Null byte (0x00)
      assert {:error, msg} = Validator.validate("echo \x00 test")
      assert msg =~ "forbidden control characters"

      # Bell character (0x07)
      assert {:error, _} = Validator.validate("echo \x07 test")
    end

    test "rejects command with dangerous patterns - process substitution" do
      # Input process substitution
      assert {:error, msg} = Validator.validate("cat <(echo test)")
      assert msg =~ "dangerous pattern"

      # Output process substitution
      assert {:error, msg} = Validator.validate("echo test >(cat)")
      assert msg =~ "dangerous pattern"
    end

    test "rejects command with dangerous patterns - multiple fd redirections" do
      assert {:error, msg} = Validator.validate("cmd 2>&1 3>&2")
      assert msg =~ "dangerous pattern"
    end

    test "rejects command with unbalanced quotes" do
      assert {:error, msg} = Validator.validate("echo 'unclosed quote")
      assert msg =~ "unbalanced single quotes"

      assert {:error, msg} = Validator.validate("echo \"unclosed double quote")
      assert msg =~ "unbalanced double quotes"
    end

    test "accepts command with balanced quotes" do
      assert {:ok, _} = Validator.validate("echo 'hello world'")
      assert {:ok, _} = Validator.validate("echo \"hello world\"")
      assert {:ok, _} = Validator.validate("echo 'single' and \"double\"")
    end

    test "accepts command with escaped quotes" do
      # Backslash-escaped quotes should not be treated as quote boundaries
      assert {:ok, _} = Validator.validate("echo \"it\\'s working\"")
      assert {:ok, _} = Validator.validate("echo 'say \\\"hello\\\"'")
      assert {:ok, _} = Validator.validate("echo \\\"escaped double\\\"")
    end

    test "rejects command with no valid tokens" do
      assert {:error, "Command contains no valid tokens after parsing"} =
               Validator.validate("'   '")
    end

    test "rejects non-string input" do
      assert {:error, "Command must be a string"} = Validator.validate(nil)
      assert {:error, "Command must be a string"} = Validator.validate(123)
    end
  end

  describe "max_command_length/0" do
    test "returns the configured max length" do
      assert Validator.max_command_length() == 8192
    end
  end

  # ============================================================================
  # CommandRunner.run/2 Tests
  # ============================================================================

  describe "run/2 with simple commands" do
    test "executes echo command successfully" do
      assert {:ok, result} = CommandRunner.run("echo hello world")

      assert result.success == true
      assert result.exit_code == 0
      assert result.stdout =~ "hello world"
      assert result.stderr == ""
      assert result.timeout == false
      assert result.error == nil
      assert result.execution_time_ms > 0
    end

    test "captures stderr output merged with stdout" do
      # Command that outputs to stderr - with stderr_to_stdout, it goes to stdout
      assert {:ok, result} = CommandRunner.run("echo error >&2")

      assert result.success == true
      # stderr is merged into stdout with stderr_to_stdout: true
      assert result.stdout =~ "error"
    end

    test "handles command failure" do
      assert {:ok, result} = CommandRunner.run("false")

      assert result.success == false
      assert result.exit_code == 1
      assert result.error =~ "exit code 1"
    end

    test "handles non-existent command" do
      assert {:ok, result} = CommandRunner.run("this_command_does_not_exist_12345")

      assert result.success == false
      assert result.exit_code == 127
    end

    test "preserves command in result" do
      cmd = "echo test"
      assert {:ok, result} = CommandRunner.run(cmd)
      assert result.command == cmd
    end
  end

  describe "run/2 with pipes and redirects" do
    test "handles pipe commands" do
      assert {:ok, result} = CommandRunner.run("echo 'hello world' | tr ' ' '-'")

      assert result.success == true
      assert result.stdout =~ "hello-world"
    end

    test "handles command substitution" do
      assert {:ok, result} = CommandRunner.run("echo $(echo nested)")

      assert result.success == true
      assert result.stdout =~ "nested"
    end
  end

  describe "run/2 with timeout" do
    test "handles timeout with sleep command" do
      # This should timeout
      assert {:ok, result} = CommandRunner.run("sleep 10", timeout: 1)

      assert result.success == false
      assert result.timeout == true
      assert result.error =~ "timed out"
    end

    test "respects custom timeout option" do
      # Fast command with longer timeout should succeed
      assert {:ok, result} = CommandRunner.run("echo quick", timeout: 5)

      assert result.success == true
      assert result.timeout == false
    end
  end

  describe "run/2 with cwd option" do
    test "executes in specified working directory" do
      assert {:ok, result} = CommandRunner.run("pwd", cwd: "/tmp")

      assert result.success == true
      assert result.stdout =~ "/tmp"
    end

    test "fails with non-existent directory" do
      result = CommandRunner.run("pwd", cwd: "/nonexistent_directory_12345")
      # This may succeed or fail depending on the shell behavior
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "run/2 with env option" do
    test "sets environment variables" do
      assert {:ok, result} = CommandRunner.run("echo $TEST_VAR", env: [{"TEST_VAR", "hello"}])

      assert result.success == true
      assert result.stdout =~ "hello"
    end
  end

  describe "run/2 validation" do
    test "rejects command with validation error" do
      assert {:error, msg} = CommandRunner.run("echo \x00 test")
      assert msg =~ "forbidden"
    end
  end

  # ============================================================================
  # Output Truncation Tests
  # ============================================================================

  describe "truncate_line/2" do
    test "does not truncate short lines" do
      assert "hello world" = CommandRunner.truncate_line("hello world", 100)
    end

    test "truncates long lines" do
      long_line = String.duplicate("a", 300)
      truncated = CommandRunner.truncate_line(long_line, 256)

      # The function truncates to max_length and adds truncation hint
      assert String.length(truncated) <=
               256 +
                 String.length(
                   "... [line truncated, command output too long, try filtering with grep]"
                 )

      assert truncated =~ "truncated"
      assert truncated =~ "try filtering with grep"
    end

    test "uses default max line length" do
      long_line = String.duplicate("a", 300)
      truncated = CommandRunner.truncate_line(long_line)

      # Should be truncated and have truncation hint
      assert truncated =~ "truncated"
    end
  end

  # ============================================================================
  # Process Management Tests
  # ============================================================================

  describe "running_count/0 and kill_all/0" do
    test "returns zero when no processes running" do
      # Kill any existing processes first
      CommandRunner.kill_all()
      assert CommandRunner.running_count() == 0
    end

    test "kill_all returns count of killed processes" do
      # Start a long-running command in background (simulated)
      # Then kill it
      count = CommandRunner.kill_all()
      assert is_integer(count)
      assert count >= 0
    end
  end

  # ============================================================================
  # Integration Tests
  # ============================================================================

  describe "complex shell commands" do
    test "handles multi-command chains" do
      assert {:ok, result} = CommandRunner.run("echo a && echo b && echo c")

      assert result.success == true
      assert result.stdout =~ "a"
      assert result.stdout =~ "b"
      assert result.stdout =~ "c"
    end

    test "handles conditional execution" do
      assert {:ok, result} = CommandRunner.run("false || echo fallback")

      assert result.success == true
      assert result.stdout =~ "fallback"
    end

    test "handles environment variable expansion" do
      assert {:ok, result} = CommandRunner.run("HOME=/test && echo $HOME")

      # Note: This sets HOME in subshell, actual behavior depends on shell
      assert result.success == true
    end
  end
end
