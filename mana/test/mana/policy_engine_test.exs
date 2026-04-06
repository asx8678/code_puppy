defmodule Mana.PolicyEngineTest do
  use ExUnit.Case

  alias Mana.PolicyEngine

  describe "struct defaults" do
    test "has correct default values" do
      policy = %PolicyEngine{}
      assert policy.rules == []
      assert policy.default_action == :ask_user
    end
  end

  describe "load/0" do
    test "returns default policy when no files exist" do
      # Ensure test doesn't find policy files
      policy = PolicyEngine.load()
      assert policy.rules == []
      assert policy.default_action == :ask_user
    end
  end

  describe "evaluate/3" do
    test "returns default action when no rules match" do
      policy = %PolicyEngine{rules: [], default_action: :ask_user}
      assert {:ask_user, "No matching policy rule"} = PolicyEngine.evaluate(policy, "test_tool", %{"key" => "value"})
    end

    test "returns allow action when rule matches" do
      rule = %{
        pattern: ".*",
        tool: "test_tool",
        action: :allow,
        reason: "Test rule"
      }

      policy = %PolicyEngine{rules: [rule], default_action: :ask_user}
      assert {:allow, "Test rule"} = PolicyEngine.evaluate(policy, "test_tool", %{"key" => "value"})
    end

    test "returns deny action when rule matches" do
      rule = %{
        pattern: "dangerous",
        tool: :any,
        action: :deny,
        reason: "Dangerous pattern detected"
      }

      policy = %PolicyEngine{rules: [rule], default_action: :allow}

      assert {:deny, "Dangerous pattern detected"} =
               PolicyEngine.evaluate(policy, "any_tool", %{"data" => "dangerous content"})
    end

    test "tool-specific rules take precedence over :any" do
      specific_rule = %{
        pattern: ".*",
        tool: "specific_tool",
        action: :deny,
        reason: "Specific rule"
      }

      general_rule = %{
        pattern: ".*",
        tool: :any,
        action: :allow,
        reason: "General rule"
      }

      policy = %PolicyEngine{rules: [specific_rule, general_rule], default_action: :ask_user}
      assert {:deny, "Specific rule"} = PolicyEngine.evaluate(policy, "specific_tool", %{"key" => "value"})
    end

    test "first matching rule wins" do
      rule1 = %{
        pattern: "pattern1",
        tool: :any,
        action: :allow,
        reason: "First rule"
      }

      rule2 = %{
        pattern: "pattern1",
        tool: :any,
        action: :deny,
        reason: "Second rule"
      }

      policy = %PolicyEngine{rules: [rule1, rule2], default_action: :ask_user}
      assert {:allow, "First rule"} = PolicyEngine.evaluate(policy, "test_tool", %{"key" => "pattern1"})
    end

    test "non-matching pattern returns default action" do
      rule = %{
        pattern: "nomatch",
        tool: :any,
        action: :deny,
        reason: "Should not match"
      }

      policy = %PolicyEngine{rules: [rule], default_action: :allow}
      assert {:allow, "No matching policy rule"} = PolicyEngine.evaluate(policy, "test_tool", %{"key" => "different"})
    end

    test "handles invalid regex patterns gracefully" do
      rule = %{
        pattern: "[invalid(regex",
        tool: :any,
        action: :deny,
        reason: "Invalid pattern"
      }

      policy = %PolicyEngine{rules: [rule], default_action: :allow}
      # Invalid regex should be treated as non-matching
      assert {:allow, "No matching policy rule"} = PolicyEngine.evaluate(policy, "test_tool", %{"key" => "value"})
    end
  end

  describe "reload/1" do
    test "reloads policy from files" do
      policy = %PolicyEngine{rules: [], default_action: :deny}
      reloaded = PolicyEngine.reload(policy)

      # Should load from files (which don't exist in test, so defaults)
      assert reloaded.default_action == :ask_user
    end
  end

  describe "integration with Config.Paths" do
    test "uses config directory for global policy" do
      # Just verify load() doesn't crash when accessing paths
      policy = PolicyEngine.load()
      assert is_struct(policy, PolicyEngine)
    end
  end
end
