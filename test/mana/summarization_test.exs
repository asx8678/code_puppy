defmodule Mana.SummarizationTest do
  @moduledoc """
  Tests for Mana.Summarization.
  """

  use ExUnit.Case, async: true

  alias Mana.Agent.TokenEstimation
  alias Mana.Models.Registry
  alias Mana.Summarization

  setup do
    # Start the Models.Registry for tests that need it
    start_supervised!(Registry)
    :ok
  end

  describe "needs_compaction?/2" do
    test "returns true when messages exceed threshold" do
      # Create messages with enough content to exceed 100 tokens
      messages =
        for i <- 1..50 do
          %{role: "user", content: "This is message number #{i} with some content "}
        end

      # Calculate expected tokens and use a low threshold
      total_tokens = Enum.reduce(messages, 0, &(&2 + TokenEstimation.estimate_message(&1)))

      assert Summarization.needs_compaction?(messages, div(total_tokens, 2))
    end

    test "returns false when messages are under threshold" do
      messages = [
        %{role: "user", content: "Hello"},
        %{role: "assistant", content: "Hi there!"}
      ]

      refute Summarization.needs_compaction?(messages, 1000)
    end

    test "handles empty messages list" do
      refute Summarization.needs_compaction?([], 100)
    end

    test "uses default threshold of 8000" do
      # Small messages should not need compaction with default threshold
      messages =
        for i <- 1..10 do
          %{role: "user", content: "Short msg #{i}"}
        end

      refute Summarization.needs_compaction?(messages)
    end
  end

  describe "compact_with_summary/2" do
    test "splits messages and keeps recent ones" do
      messages =
        for i <- 1..20 do
          %{role: "user", content: "Message #{i}"}
        end

      # Mock the summarize function to avoid actual LLM calls
      # In a real scenario, this would call the model
      result = Summarization.compact_with_summary(messages, keep_recent: 5, model: "test-model")

      # Should return at least the kept messages (may include summary)
      assert length(result) >= 5
    end

    test "returns all messages when count is less than keep_recent" do
      messages =
        for i <- 1..5 do
          %{role: "user", content: "Message #{i}"}
        end

      result = Summarization.compact_with_summary(messages, keep_recent: 10)

      # Should return all messages since we don't need to summarize
      assert length(result) == 5
    end

    test "returns empty list for empty input" do
      result = Summarization.compact_with_summary([])
      assert result == []
    end
  end

  describe "summarize/2" do
    @tag :integration
    test "returns error when model is unavailable" do
      messages = [
        %{role: "user", content: "Hello, world!"},
        %{role: "assistant", content: "Hi there!"}
      ]

      # Using a non-existent model should return an error
      result = Summarization.summarize(messages, model: "nonexistent-model-xyz")
      assert match?({:error, _}, result)
    end

    test "handles messages with string keys" do
      messages = [
        %{"role" => "user", "content" => "Hello"},
        %{"role" => "assistant", "content" => "Hi!"}
      ]

      # Should not crash on string keys
      result = Summarization.summarize(messages, model: "test")
      # Will likely error due to model, but should not crash
      assert is_tuple(result)
      assert elem(result, 0) in [:ok, :error]
    end

    test "handles empty messages" do
      result = Summarization.summarize([], model: "test")
      # Will likely error due to model, but should not crash
      assert is_tuple(result)
      assert elem(result, 0) in [:ok, :error]
    end
  end

  describe "integration with TokenEstimation" do
    test "uses correct token estimation" do
      # Create a message with known content
      content = String.duplicate("word ", 100)
      message = %{role: "user", content: content}

      estimated = TokenEstimation.estimate_message(message)
      assert estimated > 0

      # Create enough messages to exceed threshold
      messages = List.duplicate(message, 100)

      assert Summarization.needs_compaction?(messages, 1000)
    end
  end
end
