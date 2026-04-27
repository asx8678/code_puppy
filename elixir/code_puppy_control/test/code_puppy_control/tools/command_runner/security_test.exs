defmodule CodePuppyControl.Tools.CommandRunner.SecurityTest do
  @moduledoc """
  Tests for CommandRunner.Security.

  Covers:
  - PolicyEngine integration (allow/deny/ask_user)
  - Callback hook integration
  - Validator integration (always runs)
  - Fail-closed semantics
  - PUP_ env var handling
  - Yolo mode
  """

  use CodePuppyControl.StatefulCase

  alias CodePuppyControl.Tools.CommandRunner.Security
  alias CodePuppyControl.PolicyEngine
  alias CodePuppyControl.PolicyEngine.PolicyRule

  # Ensure PolicyEngine is started for these tests
  setup do
    # PolicyEngine should be running via application supervision tree
    # Just verify it's available
    assert Process.whereis(PolicyEngine) != nil
    :ok
  end

  describe "check/2 with valid commands" do
    test "allows simple echo command" do
      result = Security.check("echo hello")
      # PolicyEngine default should allow
      assert result.allowed == true or match?(%{decision: {:ask_user, _}}, result)
    end

    test "rejects empty command via validator" do
      result = Security.check("")

      assert result.allowed == false
      assert match?({:denied, _}, result.decision)
    end

    test "rejects whitespace-only command via validator" do
      result = Security.check("   ")

      assert result.allowed == false
    end

    test "rejects command with forbidden chars via validator" do
      result = Security.check("echo \x00 test")

      assert result.allowed == false
      assert result.reason =~ "forbidden"
    end

    test "rejects command with dangerous patterns via validator" do
      result = Security.check("cat <(echo test)")

      assert result.allowed == false
      assert result.reason =~ "dangerous pattern"
    end

    test "rejects excessively long command via validator" do
      long_cmd = String.duplicate("a", 9000)
      result = Security.check(long_cmd)

      assert result.allowed == false
      assert result.reason =~ "exceeds maximum length"
    end
  end

  describe "check/2 with PUP_SKIP_SHELL_SAFETY" do
    test "skips policy/callbacks when env var is set" do
      original = System.get_env("PUP_SKIP_SHELL_SAFETY")

      try do
        System.put_env("PUP_SKIP_SHELL_SAFETY", "1")

        # A valid command should pass
        result = Security.check("echo hello")
        assert result.allowed == true
      after
        if original do
          System.put_env("PUP_SKIP_SHELL_SAFETY", original)
        else
          System.delete_env("PUP_SKIP_SHELL_SAFETY")
        end
      end
    end

    test "still runs validator even with skip_safety" do
      original = System.get_env("PUP_SKIP_SHELL_SAFETY")

      try do
        System.put_env("PUP_SKIP_SHELL_SAFETY", "1")

        # An invalid command should still be rejected by validator
        result = Security.check("echo \x00 test")
        assert result.allowed == false
      after
        if original do
          System.put_env("PUP_SKIP_SHELL_SAFETY", original)
        else
          System.delete_env("PUP_SKIP_SHELL_SAFETY")
        end
      end
    end
  end

  describe "yolo_mode?/0" do
    test "returns false by default" do
      original = System.get_env("PUP_YOLO_MODE")

      try do
        System.delete_env("PUP_YOLO_MODE")
        refute Security.yolo_mode?()
      after
        if original, do: System.put_env("PUP_YOLO_MODE", original)
      end
    end

    test "returns true when PUP_YOLO_MODE=1" do
      original = System.get_env("PUP_YOLO_MODE")

      try do
        System.put_env("PUP_YOLO_MODE", "1")
        assert Security.yolo_mode?()
      after
        if original do
          System.put_env("PUP_YOLO_MODE", original)
        else
          System.delete_env("PUP_YOLO_MODE")
        end
      end
    end
  end

  describe "skip_shell_safety?/0" do
    test "returns false by default" do
      original = System.get_env("PUP_SKIP_SHELL_SAFETY")

      try do
        System.delete_env("PUP_SKIP_SHELL_SAFETY")
        refute Security.skip_shell_safety?()
      after
        if original, do: System.put_env("PUP_SKIP_SHELL_SAFETY", original)
      end
    end

    test "returns true when PUP_SKIP_SHELL_SAFETY=1" do
      original = System.get_env("PUP_SKIP_SHELL_SAFETY")

      try do
        System.put_env("PUP_SKIP_SHELL_SAFETY", "1")
        assert Security.skip_shell_safety?()
      after
        if original do
          System.put_env("PUP_SKIP_SHELL_SAFETY", original)
        else
          System.delete_env("PUP_SKIP_SHELL_SAFETY")
        end
      end
    end
  end

  describe "fail-closed semantics" do
    test "validator rejection is fail-closed (denied, not ask_user)" do
      result = Security.check("echo \x00 test")

      assert result.allowed == false
      # Validator failures should be denied, not ask_user
      assert match?({:denied, _}, result.decision)
    end
  end
end
