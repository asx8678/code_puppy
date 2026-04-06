defmodule Mana.TTSR.StreamWatcherTest do
  use ExUnit.Case, async: false

  alias Mana.TTSR.{Rule, StreamWatcher}

  # Helper to create a test rule
  defp make_rule(opts \\ []) do
    %Rule{
      name: Keyword.get(opts, :name, "test_rule"),
      trigger: Regex.compile!(Keyword.get(opts, :trigger, "test")),
      content: Keyword.get(opts, :content, "Test content"),
      source: "/path/to/rule.md",
      scope: Keyword.get(opts, :scope, :text),
      repeat: Keyword.get(opts, :repeat, :once),
      triggered_at_turn: nil,
      pending: false
    }
  end

  setup_all do
    # Ensure the TTSR registry is started once for all tests
    case Registry.start_link(keys: :unique, name: Mana.TTSR.Registry) do
      {:ok, _} -> :ok
      {:error, {:already_started, _}} -> :ok
    end

    :ok
  end

  setup do
    # Generate unique session IDs for each test to avoid conflicts
    session_id = "test_session_#{System.unique_integer([:positive])}"
    {:ok, session_id: session_id}
  end

  describe "start_link/2" do
    test "starts a watcher for a session", %{session_id: session_id} do
      rules = [make_rule(trigger: "error")]

      assert {:ok, pid} = StreamWatcher.start_link(session_id, rules)
      assert Process.alive?(pid)

      # Can find it via find_watcher
      assert StreamWatcher.find_watcher(session_id) == pid
    end
  end

  describe "watch_event/2" do
    test "processes text stream chunks", %{session_id: session_id} do
      rules = [make_rule(trigger: "error|fail")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Send a chunk that doesn't match
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "hello world"})
      assert StreamWatcher.get_pending(session_id) == []

      # Send a chunk that matches
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "there was an error"})

      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 1
      assert hd(pending).name == "test_rule"
    end

    test "matches across chunk boundaries", %{session_id: session_id} do
      # Test that patterns straddling chunk boundaries are caught
      rules = [make_rule(trigger: "error")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Split "error" across two chunks
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "err"})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "or"})

      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 1
    end

    test "handles different scopes", %{session_id: session_id} do
      rules = [
        make_rule(name: "text_rule", trigger: "text", scope: :text),
        make_rule(name: "thinking_rule", trigger: "thought", scope: :thinking),
        make_rule(name: "tool_rule", trigger: "tool", scope: :tool),
        make_rule(name: "all_rule", trigger: "anywhere", scope: :all, repeat: {:gap, 0})
      ]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Text scope - text_rule and all_rule should match
      :ok = StreamWatcher.watch_event(session_id, {:part_start, 0, :text, %{}})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "some text anywhere"})
      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 2
      assert Enum.any?(pending, &(&1.name == "text_rule"))
      assert Enum.any?(pending, &(&1.name == "all_rule"))

      # Thinking scope - thinking_rule and all_rule should match
      :ok = StreamWatcher.watch_event(session_id, {:part_start, 1, :thinking, %{}})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "deep thought anywhere"})
      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 2
      assert Enum.any?(pending, &(&1.name == "thinking_rule"))
      assert Enum.any?(pending, &(&1.name == "all_rule"))

      # Tool scope - tool_rule and all_rule should match
      :ok = StreamWatcher.watch_event(session_id, {:part_start, 2, :tool, %{}})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 2, "using a tool anywhere"})
      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 2
      assert Enum.any?(pending, &(&1.name == "tool_rule"))
      assert Enum.any?(pending, &(&1.name == "all_rule"))
    end

    test "does not trigger same rule twice", %{session_id: session_id} do
      rules = [make_rule(trigger: "error")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # First match
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "error"})
      pending1 = StreamWatcher.get_pending(session_id)
      assert length(pending1) == 1

      # Same rule should not be pending again (cleared by get_pending)
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "error"})
      pending2 = StreamWatcher.get_pending(session_id)
      assert pending2 == []
    end

    test "ignores unknown event types", %{session_id: session_id} do
      rules = [make_rule(trigger: "test")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Should not crash on unknown event type
      :ok = StreamWatcher.watch_event(session_id, {:unknown_event, :data})
      :ok = StreamWatcher.watch_event(session_id, {:another_event, nil})

      assert StreamWatcher.get_pending(session_id) == []
    end

    test "handles empty session gracefully" do
      # No watcher started for this session
      result = StreamWatcher.watch_event("nonexistent_session_xyz", {:part_delta, 0, "test"})
      assert result == :ok
    end

    test "respects :once repeat policy", %{session_id: session_id} do
      rules = [%{make_rule(trigger: "test", repeat: :once) | triggered_at_turn: 0}]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Should not trigger since already triggered at turn 0
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "test"})
      assert StreamWatcher.get_pending(session_id) == []
    end

    test "respects {:gap, n} repeat policy", %{session_id: session_id} do
      # Rule triggered at turn 0 with gap of 3
      rules = [%{make_rule(name: "gap_rule", trigger: "test", repeat: {:gap, 3}) | triggered_at_turn: 0}]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Current turn is 0, same as triggered_at_turn
      # Gap of 3 means needs 3 turns after turn 0, so not eligible at turn 0
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "test"})
      assert StreamWatcher.get_pending(session_id) == []
    end
  end

  describe "increment_turn/1" do
    test "increments turn and clears buffers", %{session_id: session_id} do
      rules = [make_rule(trigger: "test")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Add some content to buffer
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "initial content"})

      # Increment turn
      :ok = StreamWatcher.increment_turn(session_id)

      # After turn increment, buffers should be cleared
      # Pattern that would have matched across boundary now won't match
      # because buffer was reset
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "est"})

      # "test" won't match because "in" was cleared
      assert StreamWatcher.get_pending(session_id) == []
    end

    test "handles non-existent session gracefully" do
      assert StreamWatcher.increment_turn("nonexistent_session_xyz") == :ok
    end
  end

  describe "get_pending/1" do
    test "returns pending rules and clears them", %{session_id: session_id} do
      rules = [
        make_rule(name: "rule1", trigger: "one"),
        make_rule(name: "rule2", trigger: "two")
      ]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Trigger both rules
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, "one two"})

      pending1 = StreamWatcher.get_pending(session_id)
      assert length(pending1) == 2

      # Second call returns empty (already cleared)
      pending2 = StreamWatcher.get_pending(session_id)
      assert pending2 == []
    end

    test "returns empty list for non-existent session" do
      assert StreamWatcher.get_pending("nonexistent_session_xyz") == []
    end
  end

  describe "find_watcher/1" do
    test "returns nil for non-existent session" do
      assert StreamWatcher.find_watcher("never_created_session_xyz") == nil
    end

    test "returns pid for existing session", %{session_id: session_id} do
      rules = [make_rule()]

      {:ok, pid} = StreamWatcher.start_link(session_id, rules)
      assert StreamWatcher.find_watcher(session_id) == pid
    end

    test "returns nil for dead process", %{session_id: session_id} do
      rules = [make_rule()]

      {:ok, pid} = StreamWatcher.start_link(session_id, rules)
      assert StreamWatcher.find_watcher(session_id) == pid

      # Stop the process gracefully
      GenServer.stop(pid, :normal)

      assert StreamWatcher.find_watcher(session_id) == nil
    end
  end

  describe "ring buffer behavior" do
    test "maintains max 512 character buffer", %{session_id: session_id} do
      rules = [make_rule(trigger: "test")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Send more than 512 characters
      long_content = String.duplicate("a", 600)
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, long_content})

      # Internal buffer should be limited to 512
      # Send a pattern that matches in the recent 512 chars
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "test"})

      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 1
    end

    test "catches patterns at buffer boundaries", %{session_id: session_id} do
      # Test that patterns straddling the 512 boundary are caught
      rules = [make_rule(trigger: "boundary")]

      {:ok, _pid} = StreamWatcher.start_link(session_id, rules)

      # Fill buffer with exactly 510 chars, then send "boun" and "dary"
      fill = String.duplicate("x", 510)
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 0, fill})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 1, "boun"})
      :ok = StreamWatcher.watch_event(session_id, {:part_delta, 2, "dary"})

      pending = StreamWatcher.get_pending(session_id)
      assert length(pending) == 1
    end
  end
end
