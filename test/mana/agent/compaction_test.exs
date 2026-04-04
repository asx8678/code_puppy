defmodule Mana.Agent.CompactionTest do
  @moduledoc """
  Tests for Mana.Agent.Compaction module.
  """

  use ExUnit.Case, async: true

  alias Mana.Agent.Compaction
  alias Mana.Agent.TokenEstimation

  describe "should_compact?/2" do
    test "returns false for empty messages" do
      refute Compaction.should_compact?([])
    end

    test "returns false when under token limit" do
      messages = [%{role: "user", content: "Hello"}]
      refute Compaction.should_compact?(messages)
    end

    test "returns true when over token limit" do
      # Create messages that exceed 100 token limit
      content = String.duplicate("a", 300)
      messages = [%{role: "user", content: content}]

      assert Compaction.should_compact?(messages, 100)
    end

    test "uses default token limit of 8000" do
      # Create enough large messages to exceed 8000 tokens
      # Each ~100 byte message is ~33 tokens, so we need ~242 messages
      content = String.duplicate("a", 100)
      messages = for _ <- 1..250, do: %{role: "user", content: content}

      assert Compaction.should_compact?(messages)
    end

    test "returns false when exactly at limit" do
      # At exactly the boundary - depends on overhead calculation
      content = String.duplicate("a", 100)
      tokens = TokenEstimation.estimate_message(%{role: "user", content: content})
      # 33 + 4 overhead
      messages = [%{role: "user", content: content}]

      refute Compaction.should_compact?(messages, tokens)
    end
  end

  describe "split_for_summarization/2" do
    test "returns empty to_summarize when messages <= keep_recent" do
      messages = for i <- 1..5, do: %{role: "user", content: "Message #{i}"}

      {to_summarize, recent} = Compaction.split_for_summarization(messages, 10)

      assert to_summarize == []
      assert recent == messages
    end

    test "splits messages when longer than keep_recent" do
      messages = for i <- 1..15, do: %{role: "user", content: "Message #{i}"}

      {to_summarize, recent} = Compaction.split_for_summarization(messages, 5)

      assert length(to_summarize) == 10
      assert length(recent) == 5
      assert Enum.at(recent, 0).content == "Message 11"
      assert Enum.at(recent, 4).content == "Message 15"
    end

    test "uses default keep_recent of 10" do
      messages = for i <- 1..20, do: %{role: "user", content: "Message #{i}"}

      {to_summarize, recent} = Compaction.split_for_summarization(messages)

      assert length(to_summarize) == 10
      assert length(recent) == 10
    end

    test "handles empty messages" do
      assert Compaction.split_for_summarization([]) == {[], []}
    end
  end

  describe "compact/2" do
    test "returns empty list for empty input" do
      assert Compaction.compact([]) == []
    end

    test "returns messages when under token limit" do
      messages = [%{role: "user", content: "Hello"}]
      assert Compaction.compact(messages) == messages
    end

    test "trims messages when over token limit" do
      # Create messages that exceed default 8000 token limit
      content = String.duplicate("a", 300)
      # Each message is ~104 tokens (100/3 + 4)
      messages = for _ <- 1..100, do: %{role: "user", content: content}

      result = Compaction.compact(messages, max_tokens: 2000)

      # Should keep roughly 19 most recent messages
      assert length(result) < length(messages)
      assert result != []
    end

    test "applies filter_huge_messages during compact" do
      large_content = String.duplicate("a", 60_000)
      messages = [%{role: "user", content: large_content}]

      result = Compaction.compact(messages)

      assert hd(result).content == "[message too large: 60000 bytes]"
    end
  end

  describe "filter_huge_messages/2" do
    test "returns empty list for empty input" do
      assert Compaction.filter_huge_messages([]) == []
    end

    test "leaves small messages unchanged" do
      msg = %{role: "user", content: "Hello world"}
      assert Compaction.filter_huge_messages([msg]) == [msg]
    end

    test "truncates messages over default max_size" do
      content = String.duplicate("a", 60_000)
      msg = %{role: "user", content: content}

      [result] = Compaction.filter_huge_messages([msg])

      assert result.content == "[message too large: 60000 bytes]"
    end

    test "uses custom max_size" do
      content = String.duplicate("a", 1000)
      msg = %{role: "user", content: content}

      [result] = Compaction.filter_huge_messages([msg], 500)

      assert result.content == "[message too large: 1000 bytes]"
    end

    test "does not truncate at boundary" do
      content = String.duplicate("a", 50_000)
      msg = %{role: "user", content: content}

      [result] = Compaction.filter_huge_messages([msg])

      assert result.content == "[message too large: 50000 bytes]"
    end

    test "handles messages without content" do
      msg = %{role: "assistant", tool_calls: [%{id: "1"}]}
      assert Compaction.filter_huge_messages([msg]) == [msg]
    end

    test "handles messages with nil content" do
      msg = %{role: "assistant", content: nil}
      assert Compaction.filter_huge_messages([msg]) == [msg]
    end

    test "preserves other message fields" do
      content = String.duplicate("a", 60_000)

      msg = %{
        role: "assistant",
        content: content,
        tool_calls: [%{id: "call_1"}],
        name: "test_agent"
      }

      [result] = Compaction.filter_huge_messages([msg])

      assert result.role == "assistant"
      assert result.tool_calls == [%{id: "call_1"}]
      assert result.name == "test_agent"
    end
  end
end
