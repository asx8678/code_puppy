defmodule Mana.Agent.HistoryTest do
  @moduledoc """
  Tests for Mana.Agent.History module.
  """

  use ExUnit.Case, async: true

  alias Mana.Agent.History

  describe "hash_message/1" do
    test "returns consistent hash for same message" do
      msg = %{role: "user", content: "Hello"}
      hash1 = History.hash_message(msg)
      hash2 = History.hash_message(msg)
      assert hash1 == hash2
    end

    test "returns different hashes for different messages" do
      msg1 = %{role: "user", content: "Hello"}
      msg2 = %{role: "user", content: "World"}
      hash1 = History.hash_message(msg1)
      hash2 = History.hash_message(msg2)
      assert hash1 != hash2
    end

    test "returns integer hash" do
      msg = %{role: "assistant", content: "Test"}
      hash = History.hash_message(msg)
      assert is_integer(hash)
    end
  end

  describe "deduplicate/2" do
    test "returns empty list for empty input" do
      assert History.deduplicate([]) == {[], MapSet.new()}
    end

    test "returns single message unchanged" do
      msg = %{role: "user", content: "Hello"}
      {result, seen} = History.deduplicate([msg])
      assert result == [msg]
      assert MapSet.size(seen) == 1
    end

    test "removes duplicate messages" do
      msg = %{role: "user", content: "Hello"}
      {result, _} = History.deduplicate([msg, msg])
      assert length(result) == 1
    end

    test "preserves order of unique messages" do
      msg1 = %{role: "user", content: "First"}
      msg2 = %{role: "user", content: "Second"}
      msg3 = %{role: "assistant", content: "Third"}

      {result, _} = History.deduplicate([msg1, msg2, msg3])
      assert result == [msg1, msg2, msg3]
    end

    test "respects existing seen hashes" do
      msg1 = %{role: "user", content: "Hello"}
      msg2 = %{role: "user", content: "World"}

      seen = MapSet.new([History.hash_message(msg1)])
      {result, new_seen} = History.deduplicate([msg1, msg2], seen)

      assert length(result) == 1
      assert List.first(result) == msg2
      assert MapSet.size(new_seen) == 2
    end
  end

  describe "ensure_ends_with_request/1" do
    test "returns empty list for empty input" do
      assert History.ensure_ends_with_request([]) == []
    end

    test "returns unchanged when last message is user" do
      messages = [
        %{role: "user", content: "Hello"},
        %{role: "assistant", content: "Hi"},
        %{role: "user", content: "How are you?"}
      ]

      assert History.ensure_ends_with_request(messages) == messages
    end

    test "appends continue message when last is assistant" do
      messages = [
        %{role: "user", content: "Hello"},
        %{role: "assistant", content: "Hi there!"}
      ]

      result = History.ensure_ends_with_request(messages)

      assert length(result) == 3
      assert List.last(result) == %{role: "user", content: "Continue"}
    end

    test "appends continue message when last has no role" do
      messages = [%{content: "Some content"}]
      result = History.ensure_ends_with_request(messages)

      assert length(result) == 2
      assert List.last(result) == %{role: "user", content: "Continue"}
    end
  end

  describe "clean_binaries/1" do
    test "returns empty list for empty input" do
      assert History.clean_binaries([]) == []
    end

    test "leaves small content unchanged" do
      msg = %{role: "user", content: "Hello world"}
      assert History.clean_binaries([msg]) == [msg]
    end

    test "truncates large binary content" do
      large_content = String.duplicate("a", 15_000)
      msg = %{role: "user", content: large_content}

      [result] = History.clean_binaries([msg])

      assert result.content == "[content truncated: 15000 bytes]"
      assert result.role == "user"
    end

    test "handles message without content" do
      msg = %{role: "assistant", tool_calls: [%{id: "1"}]}
      assert History.clean_binaries([msg]) == [msg]
    end

    test "handles multiple messages with mixed content sizes" do
      small = %{role: "user", content: "Small"}
      large = %{role: "assistant", content: String.duplicate("b", 20_000)}

      result = History.clean_binaries([small, large])

      assert Enum.at(result, 0) == small
      assert Enum.at(result, 1).content == "[content truncated: 20000 bytes]"
    end
  end

  describe "accumulate/3" do
    test "accumulates messages into empty history" do
      new = [%{role: "user", content: "Hello"}]
      assert History.accumulate([], new) == new
    end

    test "accumulates new messages onto existing history" do
      history = [%{role: "user", content: "Hello"}]
      new = [%{role: "assistant", content: "Hi!"}]

      result = History.accumulate(history, new)

      assert length(result) == 2
      assert Enum.at(result, 0) == %{role: "user", content: "Hello"}
      assert Enum.at(result, 1) == %{role: "assistant", content: "Hi!"}
    end

    test "deduplicates accumulated messages" do
      msg = %{role: "user", content: "Hello"}
      result = History.accumulate([msg], [msg])

      assert length(result) == 1
    end

    test "truncates to max_history limit" do
      history = for i <- 1..50, do: %{role: "user", content: "Message #{i}"}
      new = for i <- 51..60, do: %{role: "user", content: "New #{i}"}

      result = History.accumulate(history, new, max_history: 20)

      assert length(result) == 20
      # Last 20 of 60 total: Message 41 through New 60
      assert Enum.at(result, 0).content == "Message 41"
      assert Enum.at(result, 19).content == "New 60"
    end

    test "uses default max_history of 100" do
      history = for i <- 1..80, do: %{role: "user", content: "Message #{i}"}
      new = for i <- 81..120, do: %{role: "user", content: "New #{i}"}

      result = History.accumulate(history, new)

      assert length(result) == 100
    end

    test "preserves recent messages when truncating" do
      history = for i <- 1..80, do: %{role: "user", content: "Old #{i}"}
      new = for i <- 81..120, do: %{role: "user", content: "New #{i}"}

      result = History.accumulate(history, new, max_history: 50)

      # Should keep the most recent 50 (Old 71 through New 120)
      assert Enum.at(result, 0).content == "Old 71"
      assert Enum.at(result, 49).content == "New 120"
    end
  end
end
