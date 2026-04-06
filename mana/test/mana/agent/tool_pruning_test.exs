defmodule Mana.Agent.ToolPruningTest do
  @moduledoc """
  Tests for Mana.Agent.ToolPruning module.
  """

  use ExUnit.Case, async: true

  alias Mana.Agent.ToolPruning

  describe "prune_interrupted/1" do
    test "returns empty list for empty input" do
      assert ToolPruning.prune_interrupted([]) == []
    end

    test "returns unchanged when no tool calls" do
      messages = [
        %{"role" => "user", "content" => "Hello"},
        %{"role" => "assistant", "content" => "Hi!"}
      ]

      assert ToolPruning.prune_interrupted(messages) == messages
    end

    test "returns unchanged when all tool calls have returns" do
      messages = [
        %{role: "user", content: "Use a tool"},
        %{
          role: "assistant",
          tool_calls: [%{id: "call_1", function: %{name: "tool1"}}]
        },
        %{role: "tool", tool_call_id: "call_1", content: "result"}
      ]

      assert ToolPruning.prune_interrupted(messages) == messages
    end

    test "removes tool call without matching return" do
      messages = [
        %{role: "user", content: "Use a tool"},
        %{
          role: "assistant",
          tool_calls: [%{id: "call_1", function: %{name: "tool1"}}]
        },
        %{role: "assistant", content: "Done"}
      ]

      result = ToolPruning.prune_interrupted(messages)

      # The assistant message with tool_calls should be removed
      assert length(result) == 2
      assert Enum.at(result, 0) == %{role: "user", content: "Use a tool"}
      assert Enum.at(result, 1) == %{role: "assistant", content: "Done"}
    end

    test "removes tool return without matching call" do
      messages = [
        %{role: "user", content: "Hello"},
        %{role: "tool", tool_call_id: "orphan_call", content: "result"}
      ]

      result = ToolPruning.prune_interrupted(messages)

      assert length(result) == 1
      assert hd(result) == %{role: "user", content: "Hello"}
    end

    test "handles multiple tool calls with partial returns" do
      messages = [
        %{role: "user", content: "Use tools"},
        %{
          role: "assistant",
          tool_calls: [
            %{id: "call_1", function: %{name: "tool1"}},
            %{id: "call_2", function: %{name: "tool2"}}
          ]
        },
        %{role: "tool", tool_call_id: "call_1", content: "result1"},
        %{role: "assistant", content: "Partial result"}
      ]

      result = ToolPruning.prune_interrupted(messages)

      # Should remove the assistant message with both tool calls
      # and the orphaned tool return for call_2
      assert length(result) == 3
      assert Enum.at(result, 0) == %{role: "user", content: "Use tools"}
      assert Enum.at(result, 1) == %{role: "tool", tool_call_id: "call_1", content: "result1"}
      assert Enum.at(result, 2) == %{role: "assistant", content: "Partial result"}
    end

    test "handles empty tool_calls list" do
      messages = [
        %{role: "assistant", tool_calls: [], content: "No tools"}
      ]

      assert ToolPruning.prune_interrupted(messages) == messages
    end
  end

  describe "find_safe_split_index/2" do
    test "returns 0 for empty messages" do
      assert ToolPruning.find_safe_split_index([], 1000) == 0
    end

    test "returns 0 when target is 0" do
      messages = [%{role: "user", content: "Hello"}]
      assert ToolPruning.find_safe_split_index(messages, 0) == 0
    end

    test "finds index based on rough token estimate" do
      # Each message adds 50 tokens roughly
      messages = for i <- 1..10, do: %{role: "user", content: "Message #{i}"}

      # Target 200 tokens should stop at index 4 (4 * 50 = 200)
      index = ToolPruning.find_safe_split_index(messages, 200)
      assert index == 3
    end

    test "never returns negative index" do
      messages = [%{role: "user", content: "Hello"}]
      assert ToolPruning.find_safe_split_index(messages, 25) == 0
    end

    test "handles large message lists" do
      messages = for i <- 1..100, do: %{role: "user", content: "Message #{i}"}

      # Target 2500 tokens (50 messages) should stop around index 50
      index = ToolPruning.find_safe_split_index(messages, 2500)
      # 50 * 50 = 2500, so index should be 49 (50 - 1)
      assert index == 49
    end
  end

  describe "collect_tool_call_ids/1" do
    test "returns empty set for empty messages" do
      assert ToolPruning.collect_tool_call_ids([]) == MapSet.new()
    end

    test "returns empty set when no tool calls" do
      messages = [
        %{role: "user", content: "Hello"},
        %{role: "assistant", content: "Hi!"}
      ]

      assert ToolPruning.collect_tool_call_ids(messages) == MapSet.new()
    end

    test "collects single tool call id" do
      messages = [
        %{
          role: "assistant",
          tool_calls: [%{id: "call_1", function: %{name: "tool1"}}]
        }
      ]

      result = ToolPruning.collect_tool_call_ids(messages)
      assert MapSet.size(result) == 1
      assert MapSet.member?(result, "call_1")
    end

    test "collects multiple tool call ids from single message" do
      messages = [
        %{
          role: "assistant",
          tool_calls: [
            %{id: "call_1", function: %{name: "tool1"}},
            %{id: "call_2", function: %{name: "tool2"}}
          ]
        }
      ]

      result = ToolPruning.collect_tool_call_ids(messages)
      assert MapSet.size(result) == 2
      assert MapSet.member?(result, "call_1")
      assert MapSet.member?(result, "call_2")
    end

    test "collects tool call ids from multiple messages" do
      messages = [
        %{
          role: "assistant",
          tool_calls: [%{id: "call_1", function: %{name: "tool1"}}]
        },
        %{role: "user", content: "Next"},
        %{
          role: "assistant",
          tool_calls: [%{id: "call_2", function: %{name: "tool2"}}]
        }
      ]

      result = ToolPruning.collect_tool_call_ids(messages)
      assert MapSet.size(result) == 2
      assert MapSet.member?(result, "call_1")
      assert MapSet.member?(result, "call_2")
    end

    test "handles tool calls without id" do
      messages = [
        %{
          role: "assistant",
          tool_calls: [%{function: %{name: "tool1"}}]
        }
      ]

      result = ToolPruning.collect_tool_call_ids(messages)
      assert MapSet.size(result) == 0
    end

    test "handles mixed messages with and without tool_calls" do
      messages = [
        %{role: "user", content: "Hello"},
        %{
          role: "assistant",
          tool_calls: [%{id: "call_1", function: %{name: "tool1"}}]
        },
        %{role: "assistant", content: "Done"}
      ]

      result = ToolPruning.collect_tool_call_ids(messages)
      assert MapSet.size(result) == 1
      assert MapSet.member?(result, "call_1")
    end
  end
end
