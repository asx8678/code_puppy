defmodule Mana.TTSR.RuleTest do
  use ExUnit.Case, async: true

  alias Mana.TTSR.Rule

  describe "new/1" do
    test "creates a rule with required trigger" do
      rule =
        Rule.new(
          name: "test_rule",
          trigger: "error|fail",
          content: "Watch for errors",
          source: "/path/to/rule.md"
        )

      assert rule.name == "test_rule"
      assert rule.content == "Watch for errors"
      assert rule.source == "/path/to/rule.md"
      assert rule.scope == :text
      assert rule.repeat == :once
      assert is_nil(rule.triggered_at_turn)
      assert rule.pending == false

      # Verify trigger was compiled
      assert %Regex{} = rule.trigger
      assert Regex.match?(rule.trigger, "error")
      assert Regex.match?(rule.trigger, "fail")
    end

    test "accepts custom scope" do
      rule =
        Rule.new(
          name: "thinking_rule",
          trigger: "plan|strategy",
          content: "Strategy content",
          source: "/rules/strategy.md",
          scope: :thinking
        )

      assert rule.scope == :thinking
    end

    test "accepts custom repeat" do
      rule =
        Rule.new(
          name: "repeating_rule",
          trigger: "todo",
          content: "Todo content",
          source: "/rules/todo.md",
          repeat: {:gap, 3}
        )

      assert rule.repeat == {:gap, 3}
    end

    test "raises on missing trigger" do
      assert_raise KeyError, fn ->
        Rule.new(name: "no_trigger", content: "test")
      end
    end

    test "raises on invalid regex" do
      assert_raise Regex.CompileError, fn ->
        Rule.new(name: "bad_regex", trigger: "[invalid")
      end
    end
  end

  describe "eligible?/2" do
    test "returns true for :once rule that has never fired" do
      rule = %Rule{
        name: "once_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: :once,
        triggered_at_turn: nil
      }

      assert Rule.eligible?(rule, 0)
      assert Rule.eligible?(rule, 5)
    end

    test "returns false for :once rule that has already fired" do
      rule = %Rule{
        name: "once_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: :once,
        triggered_at_turn: 2
      }

      refute Rule.eligible?(rule, 3)
      refute Rule.eligible?(rule, 10)
    end

    test "returns true for {:gap, n} rule that has never fired" do
      rule = %Rule{
        name: "gap_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: {:gap, 3},
        triggered_at_turn: nil
      }

      assert Rule.eligible?(rule, 0)
    end

    test "returns false for {:gap, n} rule within gap period" do
      rule = %Rule{
        name: "gap_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: {:gap, 3},
        triggered_at_turn: 2
      }

      # Gap of 3 means need 3 turns after turn 2
      # 3 - 2 = 1 < 3
      refute Rule.eligible?(rule, 3)
      # 4 - 2 = 2 < 3
      refute Rule.eligible?(rule, 4)
    end

    test "returns true for {:gap, n} rule after gap period" do
      rule = %Rule{
        name: "gap_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: {:gap, 3},
        triggered_at_turn: 2
      }

      # 5 - 2 = 3 >= 3
      assert Rule.eligible?(rule, 5)
      # 6 - 2 = 4 >= 3
      assert Rule.eligible?(rule, 6)
    end

    test "gap of 0 allows immediate re-trigger" do
      rule = %Rule{
        name: "always_rule",
        trigger: ~r/error/,
        content: "Content",
        source: "/path",
        repeat: {:gap, 0},
        triggered_at_turn: 2
      }

      # 2 - 2 = 0 >= 0
      assert Rule.eligible?(rule, 2)
      assert Rule.eligible?(rule, 3)
    end
  end
end
