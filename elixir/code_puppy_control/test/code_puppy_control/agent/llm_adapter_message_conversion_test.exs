defmodule CodePuppyControl.Agent.LLMAdapterMessageConversionTest do
  @moduledoc """
  Tests for LLMAdapter message conversion logic.

  Covers:
  - parts-format → content-format flattening (legacy)
  - : canonical part_kind/content flattening
  - : canonical tool-return part flattening
  - : next-turn replay with compacted history
  - atom-keyed → string-keyed role conversion
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.LLMAdapter
  alias CodePuppyControl.Test.LLMAdapterTestHelper.ProviderMock

  import CodePuppyControl.Test.LLMAdapterTestHelper, only: [setup_mock_provider: 0]

  setup do
    setup_mock_provider()
  end

  # ===========================================================================
  # 1. Message conversion: parts-format → content-format
  # ===========================================================================

  describe "message conversion: parts-format → content-format" do
    test "flattens single text part into content field" do
      msgs = [%{"role" => "user", "parts" => [%{"type" => "text", "text" => "hello world"}]}]
      ProviderMock.set_response(%{id: "r1", content: "hi", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      captured = ProviderMock.captured_messages()
      assert length(captured) == 1
      assert [%{role: "user", content: "hello world"}] = captured
    end

    test "joins multiple text parts into single content string" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"type" => "text", "text" => "part one"},
            %{"type" => "text", "text" => "part two"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "part onepart two"}] = ProviderMock.captured_messages()
    end

    test "preserves tool_call_id from parts-format message" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [%{"type" => "text", "text" => "tool output"}],
          "tool_call_id" => "call_abc123"
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.content == "tool output"
      assert captured.tool_call_id == "call_abc123"
    end

    test "handles mixed atom-keyed parts within string-keyed message" do
      # Agent.State may store parts with atom keys inside string-keyed envelope
      msgs = [
        %{
          "role" => "user",
          "parts" => [%{type: :text, text: "atom parts"}]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "atom parts"}] = ProviderMock.captured_messages()
    end

    test "skips non-text part types gracefully" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"type" => "text", "text" => "visible"},
            %{"type" => "image", "url" => "http://example.com/img.png"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      # Non-text parts filtered out; only text is kept
      assert [%{role: "user", content: "visible"}] = ProviderMock.captured_messages()
    end
  end

  # ===========================================================================
  # 1b. regression: canonical part_kind/content flattening
  # ===========================================================================

  describe "canonical part_kind/content flattening" do
    test "flattens single canonical text part (string keys)" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [%{"part_kind" => "text", "content" => "hello from canonical"}]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "hello from canonical"}] = ProviderMock.captured_messages()
    end

    test "flattens canonical text part with atom keys" do
      msgs = [
        %{"role" => "user", "parts" => [%{part_kind: "text", content: "atom canonical"}]}
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "atom canonical"}] = ProviderMock.captured_messages()
    end

    test "joins multiple canonical text parts into single content string" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"part_kind" => "text", "content" => "part A"},
            %{"part_kind" => "text", "content" => "part B"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "part Apart B"}] = ProviderMock.captured_messages()
    end

    test "canonical part with nil content produces empty string, not crash" do
      msgs = [
        %{"role" => "assistant", "parts" => [%{"part_kind" => "text", "content" => nil}]}
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "assistant", content: ""}] = ProviderMock.captured_messages()
    end

    test "skips non-text canonical part_kind gracefully" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"part_kind" => "text", "content" => "visible"},
            %{"part_kind" => "tool-call", "content" => "call data"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      # Only text part_kind is flattened; tool-call is skipped
      assert [%{role: "user", content: "visible"}] = ProviderMock.captured_messages()
    end

    test "preserves tool_call_id from canonical parts-format message" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [%{"part_kind" => "text", "content" => "tool output"}],
          "tool_call_id" => "call_canonical_999"
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.content == "tool output"
      assert captured.tool_call_id == "call_canonical_999"
    end

    test "mixes canonical and legacy parts in same message" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"part_kind" => "text", "content" => "canonical "},
            %{"type" => "text", "text" => "legacy"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "canonical legacy"}] = ProviderMock.captured_messages()
    end
  end

  # ===========================================================================
  # 1b-ii. regression: canonical tool-return part flattening
  # ===========================================================================

  describe "canonical tool-return part flattening" do
    test "single tool-return part produces provider message with content and tool_call_id" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "tool-return", "tool_call_id" => "tc1", "content" => "tool result"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.content == "tool result"
      assert captured.tool_call_id == "tc1"
    end

    test "tool-return part with atom keys" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{part_kind: "tool-return", tool_call_id: "tc_atom", content: "atom result"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.content == "atom result"
      assert captured.tool_call_id == "tc_atom"
    end

    test "multiple tool-return parts each produce separate provider messages" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "tool-return", "tool_call_id" => "tc1", "content" => "result A"},
            %{"part_kind" => "tool-return", "tool_call_id" => "tc2", "content" => "result B"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [msg_a, msg_b] = ProviderMock.captured_messages()
      assert msg_a.role == "tool"
      assert msg_a.content == "result A"
      assert msg_a.tool_call_id == "tc1"
      assert msg_b.role == "tool"
      assert msg_b.content == "result B"
      assert msg_b.tool_call_id == "tc2"
    end

    test "tool-return part falls back to message-root tool_call_id" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "tool-return", "content" => "no part-level id"}
          ],
          "tool_call_id" => "root_id"
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.tool_call_id == "root_id"
    end

    test "part-level tool_call_id takes precedence over message-root" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "tool-return", "tool_call_id" => "part_id", "content" => "data"}
          ],
          "tool_call_id" => "root_id"
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.tool_call_id == "part_id"
    end

    test "tool-return part with nil content produces empty string" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "tool-return", "tool_call_id" => "tc_nil", "content" => nil}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.content == ""
      assert captured.tool_call_id == "tc_nil"
    end

    test "mixed text and tool-return parts: text message first, then tool-return messages" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [
            %{"part_kind" => "text", "content" => "explanation"},
            %{"part_kind" => "tool-return", "tool_call_id" => "tc1", "content" => "result"}
          ]
        }
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [text_msg, tool_msg] = ProviderMock.captured_messages()
      assert text_msg.role == "tool"
      assert text_msg.content == "explanation"
      assert tool_msg.role == "tool"
      assert tool_msg.content == "result"
      assert tool_msg.tool_call_id == "tc1"
    end
  end

  # ===========================================================================
  # 1c. regression: next-turn with compacted history
  # ===========================================================================

  describe "next-turn replay with compacted history" do
    test "compacted history messages are replayed with non-empty content" do
      # Simulates the scenario from : after compaction, persisted
      # messages use canonical part_kind/content format. On the next turn,
      # these must flatten to provider messages with non-empty content.
      compacted_history = [
        %{
          "role" => "system",
          "parts" => [%{"part_kind" => "text", "content" => "You are a coding assistant."}]
        },
        %{
          "role" => "user",
          "parts" => [%{"part_kind" => "text", "content" => "What is Elixir?"}]
        },
        %{
          "role" => "assistant",
          "parts" => [%{"part_kind" => "text", "content" => "Elixir is a functional language."}]
        }
      ]

      # New user turn appended after compaction
      new_turn = %{
        "role" => "user",
        "parts" => [%{"part_kind" => "text", "content" => "Tell me more."}]
      }

      all_messages = compacted_history ++ [new_turn]

      ProviderMock.set_response(%{id: "r1", content: "Sure!", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(all_messages, [], [model: "test"], fn _ -> :ok end)

      captured = ProviderMock.captured_messages()
      assert length(captured) == 4

      # Every message must have non-empty content — the core regression
      for msg <- captured do
        assert msg.content != "",
               "Expected non-empty content for role=#{msg.role}, got empty string"
      end

      assert Enum.at(captured, 0) == %{role: "system", content: "You are a coding assistant."}
      assert Enum.at(captured, 1) == %{role: "user", content: "What is Elixir?"}

      assert Enum.at(captured, 2) == %{
               role: "assistant",
               content: "Elixir is a functional language."
             }

      assert Enum.at(captured, 3) == %{role: "user", content: "Tell me more."}
    end

    test "compacted history with tool-return parts replays with content and tool_call_id" do
      # Full conversation including tool-return: user → assistant (tool call) → tool (result)
      compacted_history = [
        %{"role" => "user", "parts" => [%{"part_kind" => "text", "content" => "List files."}]},
        %{
          "role" => "assistant",
          "parts" => [%{"part_kind" => "text", "content" => "Let me check."}]
        },
        %{
          "role" => "tool",
          "parts" => [
            %{
              "part_kind" => "tool-return",
              "tool_call_id" => "tc1",
              "content" => "file1.ex\nfile2.ex"
            }
          ]
        },
        %{"role" => "user", "parts" => [%{"part_kind" => "text", "content" => "Thanks!"}]}
      ]

      ProviderMock.set_response(%{id: "r1", content: "You're welcome!", tool_calls: []})

      assert {:ok, _} =
               LLMAdapter.stream_chat(compacted_history, [], [model: "test"], fn _ -> :ok end)

      captured = ProviderMock.captured_messages()
      # 4 messages: user, assistant, tool, user
      assert length(captured) == 4

      tool_msg = Enum.at(captured, 2)
      assert tool_msg.role == "tool"
      assert tool_msg.content == "file1.ex\nfile2.ex"
      assert tool_msg.tool_call_id == "tc1"

      # Every message must have non-empty content
      for msg <- captured do
        assert msg.content != "",
               "Expected non-empty content for role=#{msg.role}, got empty string"
      end
    end

    test "mixed compacted + fresh messages all produce non-empty content" do
      # Compacted history in canonical format + fresh messages in legacy format
      messages = [
        %{
          "role" => "system",
          "parts" => [%{"part_kind" => "text", "content" => "System prompt."}]
        },
        %{
          "role" => "user",
          "parts" => [%{"type" => "text", "text" => "Legacy format question."}]
        },
        %{
          "role" => "assistant",
          "parts" => [%{"part_kind" => "text", "content" => "Canonical format answer."}]
        },
        %{"role" => "user", "content" => "Flat content follow-up."}
      ]

      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(messages, [], [model: "test"], fn _ -> :ok end)

      captured = ProviderMock.captured_messages()
      assert length(captured) == 4

      for msg <- captured do
        assert msg.content != "",
               "Expected non-empty content for role=#{msg.role}, got empty string"
      end
    end
  end

  # ===========================================================================
  # 2. Message conversion: atom-keyed → string-keyed
  # ===========================================================================

  describe "message conversion: atom-keyed → string-keyed" do
    test "converts atom role to string role" do
      msgs = [%{role: :assistant, content: "I can help!"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "assistant", content: "I can help!"}] = ProviderMock.captured_messages()
    end

    test "converts :user atom role" do
      msgs = [%{role: :user, content: "Hello!"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "Hello!"}] = ProviderMock.captured_messages()
    end

    test "preserves tool_call_id from atom-keyed message" do
      msgs = [%{role: :tool, content: "result", tool_call_id: "call_xyz"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.tool_call_id == "call_xyz"
    end

    test "string-keyed content messages pass through with atom keys" do
      # Already string-keyed content format — should get atom-keyed output
      msgs = [%{"role" => "system", "content" => "You are helpful."}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "system", content: "You are helpful."}] = ProviderMock.captured_messages()
    end

    test "mixed key styles in tool_call_id extraction" do
      msgs = [%{:role => :tool, :content => "result", "tool_call_id" => "call_mixed"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.tool_call_id == "call_mixed"
    end
  end
end
