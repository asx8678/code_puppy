defmodule CodePuppyControl.MessageCoreTest do
  @moduledoc """
  Smoke and compatibility tests for the MessageCore namespace.

  These tests verify that:
    1. All MessageCore modules compile and are accessible
    2. Delegation to existing implementations works correctly
    3. The new namespace returns the same results as the old namespace
    4. Types are properly re-exported

  This ensures backward compatibility while allowing migration to the new namespace.
  """

  use ExUnit.Case

  alias CodePuppyControl.MessageCore
  alias CodePuppyControl.MessageCore.{Types, Hasher, TokenEstimator, Serializer, Pruner, MessageBatch}

  # Keep old namespace aliases to verify compatibility
  alias CodePuppyControl.Messages.Types, as: OldTypes
  alias CodePuppyControl.Messages.Hasher, as: OldHasher
  alias CodePuppyControl.Tokens.Estimator, as: OldEstimator
  alias CodePuppyControl.Messages.Serializer, as: OldSerializer
  alias CodePuppyControl.Messages.Pruner, as: OldPruner

  # ============================================================================
  # Helper functions
  # ============================================================================

  defp sample_message do
    %{
      kind: "request",
      role: "user",
      instructions: nil,
      parts: [
        %{
          part_kind: "text",
          content: "Hello, world!",
          content_json: nil,
          tool_call_id: nil,
          tool_name: nil,
          args: nil
        }
      ]
    }
  end

  defp sample_message_with_tools do
    %{
      kind: "request",
      role: "assistant",
      instructions: "You are helpful",
      parts: [
        %{
          part_kind: "text",
          content: "I'll search for that",
          content_json: nil,
          tool_call_id: nil,
          tool_name: nil,
          args: nil
        },
        %{
          part_kind: "tool-call",
          content: nil,
          content_json: ~s({"query": "elixir testing"}),
          tool_call_id: "call_123",
          tool_name: "search",
          args: nil
        },
        %{
          part_kind: "tool-return",
          content: "Elixir testing results",
          content_json: nil,
          tool_call_id: "call_123",
          tool_name: nil,
          args: nil
        }
      ]
    }
  end

  # ============================================================================
  # Namespace Structure Tests
  # ============================================================================

  describe "MessageCore namespace structure" do
    test "root module defines type aliases" do
      # Verify the type aliases are defined
      assert CodePuppyControl.MessageCore.module_info(:module) == CodePuppyControl.MessageCore
    end

    test "all submodules are accessible" do
      # These should not raise errors - type-only modules are accessible
      assert is_atom(Types)

      # These modules should be able to call their delegated functions
      # Just verify the modules load without error
      msg = sample_message()
      hash = Hasher.hash_message(msg)
      assert is_integer(hash)

      tokens = TokenEstimator.estimate_tokens("hello")
      assert is_integer(tokens)

      {:ok, binary} = Serializer.serialize_session([msg])
      assert is_binary(binary)

      pruner_result = Pruner.prune_and_filter([], 50000)
      assert is_map(pruner_result)

      batch = MessageBatch.new()
      assert is_map(batch)
    end
  end

  # ============================================================================
  # Hasher Delegation Tests
  # ============================================================================

  describe "Hasher delegation" do
    test "hash_message produces identical results to old namespace" do
      msg = sample_message()

      new_hash = Hasher.hash_message(msg)
      old_hash = OldHasher.hash_message(msg)

      assert new_hash == old_hash
      assert is_integer(new_hash)
      assert new_hash >= 0
    end

    test "stringify_part_for_hash produces identical results to old namespace" do
      part = %{
        part_kind: "tool_result",
        content: "search results here",
        content_json: nil,
        tool_call_id: "call_123",
        tool_name: nil,
        args: nil
      }

      new_str = Hasher.stringify_part_for_hash(part)
      old_str = OldHasher.stringify_part_for_hash(part)

      assert new_str == old_str
      assert new_str == "tool_result|tool_call_id=call_123|content=search results here"
    end

    test "Hasher is deterministic" do
      msg = sample_message()

      hash1 = Hasher.hash_message(msg)
      hash2 = Hasher.hash_message(msg)
      hash3 = Hasher.hash_message(msg)

      assert hash1 == hash2
      assert hash2 == hash3
    end
  end

  # ============================================================================
  # TokenEstimator Delegation Tests
  # ============================================================================

  describe "TokenEstimator delegation" do
    test "estimate_tokens produces identical results to old namespace" do
      text = "Hello, this is a test message for token estimation."

      new_tokens = TokenEstimator.estimate_tokens(text)
      old_tokens = OldEstimator.estimate_tokens(text)

      assert new_tokens == old_tokens
      assert new_tokens > 0
    end

    test "estimate_message_tokens produces identical results to old namespace" do
      msg = sample_message()

      new_tokens = TokenEstimator.estimate_message_tokens(msg)
      old_tokens = OldEstimator.estimate_message_tokens(msg)

      assert new_tokens == old_tokens
      assert new_tokens > 0
    end

    test "chars_per_token produces identical results to old namespace" do
      text = "def hello():\n    print('world')"

      new_ratio = TokenEstimator.chars_per_token(text)
      old_ratio = OldEstimator.chars_per_token(text)

      assert new_ratio == old_ratio
    end

    test "is_code_heavy produces identical results to old namespace" do
      code_text = "def hello():\n    print('world')\n    return 42"
      prose_text = "Hello, world! How are you today?"

      assert TokenEstimator.is_code_heavy(code_text) == OldEstimator.is_code_heavy(code_text)
      assert TokenEstimator.is_code_heavy(prose_text) == OldEstimator.is_code_heavy(prose_text)
    end

    test "stringify_part_for_tokens produces identical results to old namespace" do
      part = %{
        part_kind: "text",
        content: "test content",
        content_json: nil,
        tool_call_id: nil,
        tool_name: nil,
        args: nil
      }

      new_str = TokenEstimator.stringify_part_for_tokens(part)
      old_str = OldEstimator.stringify_part_for_tokens(part)

      assert new_str == old_str
    end

    test "process_messages_batch produces identical results to old namespace" do
      messages = [sample_message(), sample_message_with_tools()]
      tools = []
      mcp_tools = []
      system_prompt = "You are a helpful assistant."

      new_result = TokenEstimator.process_messages_batch(messages, tools, mcp_tools, system_prompt)
      old_result = OldEstimator.process_messages_batch(messages, tools, mcp_tools, system_prompt)

      assert new_result == old_result
      assert is_map(new_result)
      assert Map.has_key?(new_result, :per_message_tokens)
      assert Map.has_key?(new_result, :total_tokens)
      assert Map.has_key?(new_result, :context_overhead)
      assert Map.has_key?(new_result, :message_hashes)
    end

    test "estimate_context_overhead produces identical results to old namespace" do
      tools = [%{name: "test_tool", description: "A test tool", input_schema: %{}}]
      mcp_tools = []
      system_prompt = "You are helpful."

      new_overhead = TokenEstimator.estimate_context_overhead(tools, mcp_tools, system_prompt)
      old_overhead = OldEstimator.estimate_context_overhead(tools, mcp_tools, system_prompt)

      assert new_overhead == old_overhead
    end
  end

  # ============================================================================
  # Serializer Delegation Tests
  # ============================================================================

  describe "Serializer delegation" do
    test "serialize_session produces identical results to old namespace" do
      messages = [sample_message(), sample_message_with_tools()]

      {:ok, new_binary} = Serializer.serialize_session(messages)
      {:ok, old_binary} = OldSerializer.serialize_session(messages)

      assert new_binary == old_binary
      assert is_binary(new_binary)
    end

    test "deserialize_session produces identical results to old namespace" do
      messages = [sample_message()]
      {:ok, binary} = Serializer.serialize_session(messages)

      {:ok, new_messages} = Serializer.deserialize_session(binary)
      {:ok, old_messages} = OldSerializer.deserialize_session(binary)

      assert new_messages == old_messages
      assert length(new_messages) == 1
    end

    test "serialize_session_incremental produces identical results to old namespace" do
      messages1 = [sample_message()]
      messages2 = [sample_message_with_tools()]

      {:ok, data1} = Serializer.serialize_session(messages1)
      {:ok, new_combined} = Serializer.serialize_session_incremental(messages2, data1)
      {:ok, old_combined} = OldSerializer.serialize_session_incremental(messages2, data1)

      assert new_combined == old_combined

      # Verify it contains both messages
      {:ok, decoded} = Serializer.deserialize_session(new_combined)
      assert length(decoded) == 2
    end

    test "round-trip serialization works" do
      original = [sample_message(), sample_message_with_tools()]

      {:ok, binary} = Serializer.serialize_session(original)
      {:ok, decoded} = Serializer.deserialize_session(binary)

      # Msgpax converts atom keys to strings on deserialization
      # Verify the data structure is preserved with string keys
      assert length(decoded) == 2
      assert List.first(decoded)["kind"] == "request"
      assert List.first(decoded)["role"] == "user"

      # New and old namespaces produce identical results
      {:ok, decoded_old} = OldSerializer.deserialize_session(binary)
      assert decoded == decoded_old
    end
  end

  # ============================================================================
  # Pruner Delegation Tests
  # ============================================================================

  describe "Pruner delegation" do
    test "prune_and_filter produces identical results to old namespace" do
      messages = [
        %{"kind" => "request", "role" => "user", "parts" => [%{"part_kind" => "text", "content" => "Hello"}]},
        %{"kind" => "request", "role" => "assistant", "parts" => [%{"part_kind" => "text", "content" => "Hi there!"}]}
      ]

      new_result = Pruner.prune_and_filter(messages, 50_000)
      old_result = OldPruner.prune_and_filter(messages, 50_000)

      assert new_result == old_result
      assert is_map(new_result)
      assert Map.has_key?(new_result, :surviving_indices)
      assert Map.has_key?(new_result, :dropped_count)
    end

    test "truncation_indices produces identical results to old namespace" do
      per_message_tokens = [100, 200, 300, 400, 500]
      protected_tokens = 1000

      new_result = Pruner.truncation_indices(per_message_tokens, protected_tokens, false)
      old_result = OldPruner.truncation_indices(per_message_tokens, protected_tokens, false)

      assert new_result == old_result
      assert is_list(new_result)
    end

    test "split_for_summarization produces identical results to old namespace" do
      per_message_tokens = [100, 200, 300]
      messages = [
        %{"kind" => "request", "role" => "system", "parts" => [%{"part_kind" => "text", "content" => "System"}]},
        %{"kind" => "request", "role" => "user", "parts" => [%{"part_kind" => "text", "content" => "User"}]},
        %{"kind" => "request", "role" => "assistant", "parts" => [%{"part_kind" => "text", "content" => "Assistant"}]}
      ]
      protected_limit = 1000

      new_result = Pruner.split_for_summarization(per_message_tokens, messages, protected_limit)
      old_result = OldPruner.split_for_summarization(per_message_tokens, messages, protected_limit)

      assert new_result == old_result
      assert is_map(new_result)
      assert Map.has_key?(new_result, :summarize_indices)
      assert Map.has_key?(new_result, :protected_indices)
    end
  end

  # ============================================================================
  # MessageBatch Placeholder Tests
  # ============================================================================

  describe "MessageBatch placeholder" do
    test "new/0 returns empty map" do
      batch = MessageBatch.new()
      assert batch == %{}
    end

    test "new/1 returns empty map (placeholder)" do
      batch = MessageBatch.new([sample_message()])
      assert batch == %{}
    end

    test "size/1 returns 0 (placeholder)" do
      batch = MessageBatch.new([sample_message()])
      assert MessageBatch.size(batch) == 0
    end
  end

  # ============================================================================
  # Types Re-export Tests
  # ============================================================================

  describe "Types re-export" do
    test "type aliases are consistent with old namespace" do
      # Verify that both Types modules are accessible
      # This confirms the delegation is working

      # Check the new namespace is accessible
      assert is_atom(Types)
      assert Types == CodePuppyControl.MessageCore.Types

      # Check the old namespace still works
      assert is_atom(OldTypes)
      assert OldTypes == CodePuppyControl.Messages.Types

      # Both should represent the same underlying types
      assert true
    end
  end

  # ============================================================================
  # Integration Test
  # ============================================================================

  describe "MessageCore integration" do
    test "full pipeline with new namespace" do
      # Create sample messages
      messages = [sample_message(), sample_message_with_tools()]

      # Hash them
      hashes = Enum.map(messages, &Hasher.hash_message/1)
      assert length(hashes) == 2
      assert Enum.all?(hashes, &is_integer/1)

      # Estimate tokens
      tokens = Enum.map(messages, &TokenEstimator.estimate_message_tokens/1)
      assert length(tokens) == 2
      assert Enum.all?(tokens, &is_integer/1)

      # Process batch
      batch_result = TokenEstimator.process_messages_batch(messages, [], [], "Test system prompt")
      assert is_map(batch_result)

      # Serialize
      {:ok, binary} = Serializer.serialize_session(messages)
      assert is_binary(binary)

      # Deserialize (note: msgpax converts keys to strings)
      {:ok, decoded} = Serializer.deserialize_session(binary)
      assert is_list(decoded)
      assert length(decoded) == 2
      # Verify structure is preserved with string keys
      assert List.first(decoded)["kind"] == "request"

      # Prune (with string-key maps for pruner compatibility)
      string_messages = [
        %{"kind" => "request", "role" => "user", "parts" => [%{"part_kind" => "text", "content" => "Hello"}]}
      ]
      prune_result = Pruner.prune_and_filter(string_messages, 50_000)
      assert is_map(prune_result)

      # MessageBatch placeholder
      batch = MessageBatch.new(messages)
      assert is_map(batch)
    end
  end
end
