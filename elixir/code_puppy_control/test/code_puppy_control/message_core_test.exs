defmodule CodePuppyControl.MessageCoreTest do
  @moduledoc """
  Smoke and delegation tests for the MessageCore namespace.

  These tests verify that:
    1. All MessageCore modules compile and are accessible
    2. Delegation to existing implementations works correctly
    3. The new namespace returns the same results as the old namespace

  This ensures backward compatibility while allowing migration to the new namespace.
  """

  use ExUnit.Case

  alias CodePuppyControl.MessageCore.{
    Hasher,
    TokenEstimator,
    Serializer,
    Pruner,
    MessageBatch
  }

  # Keep old namespace aliases to verify compatibility
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
  # Namespace Structure Smoke Tests
  # ============================================================================

  describe "namespace structure" do
    test "root module loads" do
      assert CodePuppyControl.MessageCore.module_info(:module) == CodePuppyControl.MessageCore
    end

    test "all submodules are accessible and delegate correctly" do
      msg = sample_message()

      # Hasher delegation smoke test
      assert is_integer(Hasher.hash_message(msg))
      assert Hasher.hash_message(msg) == OldHasher.hash_message(msg)

      # TokenEstimator delegation smoke test
      assert is_integer(TokenEstimator.estimate_tokens("hello"))
      assert TokenEstimator.estimate_tokens("hello") == OldEstimator.estimate_tokens("hello")

      # Serializer delegation smoke test
      {:ok, binary} = Serializer.serialize_session([msg])
      assert is_binary(binary)
      {:ok, old_binary} = OldSerializer.serialize_session([msg])
      assert binary == old_binary

      # Pruner delegation smoke test
      assert is_map(Pruner.prune_and_filter([], 50000))
      assert Pruner.prune_and_filter([], 50000) == OldPruner.prune_and_filter([], 50000)

      # MessageBatch placeholder namespace only
      assert is_atom(MessageBatch)
    end
  end

  # ============================================================================
  # End-to-End Delegation Smoke Test
  # ============================================================================

  test "full pipeline with new namespace delegates correctly" do
    messages = [sample_message(), sample_message_with_tools()]

    # Hash - verify delegation to old namespace
    new_hashes = Enum.map(messages, &Hasher.hash_message/1)
    old_hashes = Enum.map(messages, &OldHasher.hash_message/1)
    assert new_hashes == old_hashes

    # Token estimation - verify delegation
    assert TokenEstimator.estimate_message_tokens(sample_message()) ==
             OldEstimator.estimate_message_tokens(sample_message())

    # Batch processing - verify delegation
    new_batch = TokenEstimator.process_messages_batch(messages, [], [], "Test prompt")
    old_batch = OldEstimator.process_messages_batch(messages, [], [], "Test prompt")
    assert new_batch == old_batch

    # Serialization - verify round-trip and delegation
    {:ok, binary} = Serializer.serialize_session(messages)
    {:ok, old_binary} = OldSerializer.serialize_session(messages)
    assert binary == old_binary

    {:ok, decoded} = Serializer.deserialize_session(binary)
    {:ok, old_decoded} = OldSerializer.deserialize_session(binary)
    assert decoded == old_decoded
  end
end
