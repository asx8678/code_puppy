defmodule Mana.Agent.TokenEstimationTest do
  @moduledoc """
  Tests for Mana.Agent.TokenEstimation module.
  """

  use ExUnit.Case, async: true

  alias Mana.Agent.TokenEstimation

  describe "estimate_count/1" do
    test "estimates tokens from empty string" do
      assert TokenEstimation.estimate_count("") == 0
    end

    test "estimates tokens using byte_size / 3" do
      # 9 bytes / 3 = 3 tokens
      assert TokenEstimation.estimate_count("hello wor") == 3
    end

    test "estimates tokens for longer text" do
      text = String.duplicate("a", 300)
      assert TokenEstimation.estimate_count(text) == 100
    end

    test "handles unicode text correctly" do
      # Unicode characters may have multi-byte representation
      text = "Hello 世界"
      expected = div(byte_size(text), 3)
      assert TokenEstimation.estimate_count(text) == expected
    end
  end

  describe "estimate_message/1" do
    test "estimates message with content" do
      message = %{content: "Hello world"}
      content_tokens = TokenEstimation.estimate_count("Hello world")
      assert TokenEstimation.estimate_message(message) == content_tokens + 4
    end

    test "estimates message without content" do
      message = %{role: "user"}
      assert TokenEstimation.estimate_message(message) == 4
    end

    test "estimates message with nil content" do
      message = %{content: nil}
      assert TokenEstimation.estimate_message(message) == 4
    end

    test "estimates empty content message" do
      message = %{content: ""}
      assert TokenEstimation.estimate_message(message) == 4
    end

    test "estimates large message" do
      content = String.duplicate("a", 300)
      message = %{content: content}
      assert TokenEstimation.estimate_message(message) == 100 + 4
    end
  end

  describe "estimate_context_overhead/2" do
    test "estimates with nil system prompt" do
      assert TokenEstimation.estimate_context_overhead(nil) == 100
    end

    test "estimates with empty system prompt" do
      assert TokenEstimation.estimate_context_overhead("") == 100
    end

    test "estimates with system prompt" do
      prompt = "You are a helpful assistant"
      prompt_tokens = TokenEstimation.estimate_count(prompt)
      assert TokenEstimation.estimate_context_overhead(prompt) == prompt_tokens + 100
    end

    test "estimates with empty tools list" do
      assert TokenEstimation.estimate_context_overhead("prompt", []) ==
               TokenEstimation.estimate_count("prompt") + 100
    end

    test "estimates with tools" do
      tools = [
        %{name: "tool1", description: "First tool"},
        %{name: "tool2", description: "Second tool"}
      ]

      tool_tokens =
        TokenEstimation.estimate_count("tool1") +
          TokenEstimation.estimate_count("First tool") +
          TokenEstimation.estimate_count("tool2") +
          TokenEstimation.estimate_count("Second tool")

      prompt_tokens = TokenEstimation.estimate_count("system prompt")

      assert TokenEstimation.estimate_context_overhead("system prompt", tools) ==
               prompt_tokens + tool_tokens + 100
    end

    test "handles tools without description" do
      tools = [%{name: "tool1"}]
      prompt_tokens = TokenEstimation.estimate_count("prompt")
      tool_tokens = TokenEstimation.estimate_count("tool1") + TokenEstimation.estimate_count("")

      assert TokenEstimation.estimate_context_overhead("prompt", tools) ==
               prompt_tokens + tool_tokens + 100
    end

    test "handles tools without name" do
      tools = [%{description: "A tool without name"}]
      prompt_tokens = TokenEstimation.estimate_count("prompt")
      tool_tokens = TokenEstimation.estimate_count("") + TokenEstimation.estimate_count("A tool without name")

      assert TokenEstimation.estimate_context_overhead("prompt", tools) ==
               prompt_tokens + tool_tokens + 100
    end
  end
end
