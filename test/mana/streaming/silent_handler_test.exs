defmodule Mana.Streaming.SilentHandlerTest do
  @moduledoc """
  Tests for Mana.Streaming.SilentHandler module.
  """

  use ExUnit.Case, async: true

  alias Mana.MessageBus
  alias Mana.Streaming.PartTracker
  alias Mana.Streaming.SilentHandler

  setup do
    # Ensure MessageBus is not started for these tests
    # since SilentHandler should not emit to it
    :ok
  end

  describe "new/1" do
    test "creates handler with default values" do
      handler = SilentHandler.new()

      assert handler.session_id == nil
      assert handler.events == []
      assert handler.part_tracker == PartTracker.new()
    end

    test "creates handler with session_id" do
      handler = SilentHandler.new(session_id: "session_123")

      assert handler.session_id == "session_123"
    end
  end

  describe "events/1" do
    test "returns empty list for new handler" do
      handler = SilentHandler.new()
      assert SilentHandler.events(handler) == []
    end

    test "returns events in chronological order" do
      handler =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{a: 1})
        |> elem(1)
        |> SilentHandler.handle_part_start("part_2", :thinking, %{b: 2})
        |> elem(1)

      events = SilentHandler.events(handler)

      assert length(events) == 2
      assert {:part_start, "part_1", :text, %{a: 1}} in events
      assert {:part_start, "part_2", :thinking, %{b: 2}} in events
    end
  end

  describe "part_tracker/1" do
    test "returns the part tracker from state" do
      handler = SilentHandler.new()
      tracker = SilentHandler.part_tracker(handler)

      assert tracker == PartTracker.new()
    end
  end

  describe "handle_part_start/4" do
    test "tracks part in part_tracker" do
      state = SilentHandler.new()

      {:ok, new_state} = SilentHandler.handle_part_start(state, "part_1", :text, %{extra: "data"})

      assert new_state.part_tracker.part_counter == 1
      assert new_state.part_tracker.active_parts["part_1"].type == :text
    end

    test "accumulates event in state" do
      state = SilentHandler.new()

      {:ok, new_state} = SilentHandler.handle_part_start(state, "part_1", :text, %{meta: "value"})

      events = SilentHandler.events(new_state)
      assert length(events) == 1
      assert hd(events) == {:part_start, "part_1", :text, %{meta: "value"}}
    end

    test "does not emit to MessageBus" do
      # Start MessageBus just to verify no messages arrive
      start_supervised!(MessageBus)
      :ok = MessageBus.add_listener(self())

      state = SilentHandler.new()
      {:ok, _} = SilentHandler.handle_part_start(state, "part_1", :text, %{})

      refute_receive {:message, _}, 200
    end
  end

  describe "handle_part_delta/3" do
    test "updates token counts" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      {:ok, new_state} = SilentHandler.handle_part_delta(state, "part_1", "Hello")

      assert new_state.part_tracker.token_counts["part_1"].output == 1
      assert new_state.part_tracker.total_output_tokens == 1
    end

    test "accumulates token counts across multiple deltas" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      {:ok, state} = SilentHandler.handle_part_delta(state, "part_1", "Hello")
      {:ok, state} = SilentHandler.handle_part_delta(state, "part_1", " ")
      {:ok, new_state} = SilentHandler.handle_part_delta(state, "part_1", "world!")

      assert new_state.part_tracker.token_counts["part_1"].output == 3
      assert new_state.part_tracker.total_output_tokens == 3
    end

    test "tracks tokens independently for different parts" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)
        |> SilentHandler.handle_part_start("part_2", :thinking, %{})
        |> elem(1)

      {:ok, state} = SilentHandler.handle_part_delta(state, "part_1", "content1")
      {:ok, new_state} = SilentHandler.handle_part_delta(state, "part_2", "content2")

      assert new_state.part_tracker.token_counts["part_1"].output == 1
      assert new_state.part_tracker.token_counts["part_2"].output == 1
      assert new_state.part_tracker.total_output_tokens == 2
    end

    test "does not accumulate event in state" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      {:ok, new_state} = SilentHandler.handle_part_delta(state, "part_1", "Hello")

      # Should still only have the start event
      assert length(SilentHandler.events(new_state)) == 1
    end

    test "does not emit to MessageBus" do
      start_supervised!(MessageBus)
      :ok = MessageBus.add_listener(self())

      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      {:ok, _} = SilentHandler.handle_part_delta(state, "part_1", "content")

      # Only the part_start event might emit if we were using ConsoleHandler
      # but SilentHandler should emit nothing
      refute_receive {:message, _}, 200
    end
  end

  describe "handle_part_end/3" do
    test "removes part from tracker" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      assert state.part_tracker.active_parts["part_1"] != nil

      {:ok, new_state} = SilentHandler.handle_part_end(state, "part_1", %{result: "done"})

      assert new_state.part_tracker.active_parts["part_1"] == nil
    end

    test "accumulates end event in state" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      {:ok, new_state} = SilentHandler.handle_part_end(state, "part_1", %{result: "success"})

      events = SilentHandler.events(new_state)
      assert length(events) == 2
      assert {:part_end, "part_1", %{result: "success"}} in events
    end
  end

  describe "complete workflow" do
    test "handles full streaming lifecycle without emitting" do
      start_supervised!(MessageBus)
      :ok = MessageBus.add_listener(self())

      state = SilentHandler.new(session_id: "silent_session")

      # Start part
      {:ok, state} = SilentHandler.handle_part_start(state, "part_1", :text, %{initial: true})
      # Verify no message was emitted
      refute_receive {:message, _}, 100

      # Multiple deltas - track tokens
      {:ok, state} = SilentHandler.handle_part_delta(state, "part_1", "Hello")
      refute_receive {:message, _}, 100

      {:ok, state} = SilentHandler.handle_part_delta(state, "part_1", " world!")
      refute_receive {:message, _}, 100

      # End part
      {:ok, final_state} = SilentHandler.handle_part_end(state, "part_1", %{complete: true})
      refute_receive {:message, _}, 100

      # Verify final state
      assert final_state.part_tracker.active_parts == %{}
      assert final_state.part_tracker.total_output_tokens == 2

      # Verify events were recorded
      events = SilentHandler.events(final_state)
      assert length(events) == 2
      assert {:part_start, "part_1", :text, %{initial: true}} in events
      assert {:part_end, "part_1", %{complete: true}} in events
    end

    test "handles thinking -> tool -> text workflow" do
      state = SilentHandler.new()

      # Start thinking
      {:ok, state} = SilentHandler.handle_part_start(state, "thinking_1", :thinking, %{})
      {:ok, state} = SilentHandler.handle_part_delta(state, "thinking_1", "Analyzing...")
      {:ok, state} = SilentHandler.handle_part_end(state, "thinking_1", %{})

      # Start tool
      {:ok, state} = SilentHandler.handle_part_start(state, "tool_1", :tool, %{name: "shell"})
      {:ok, state} = SilentHandler.handle_part_delta(state, "tool_1", "output")
      {:ok, state} = SilentHandler.handle_part_end(state, "tool_1", %{})

      # Start text
      {:ok, state} = SilentHandler.handle_part_start(state, "text_1", :text, %{})
      {:ok, state} = SilentHandler.handle_part_delta(state, "text_1", "Result")
      {:ok, final_state} = SilentHandler.handle_part_end(state, "text_1", %{})

      # Verify all parts ended
      assert final_state.part_tracker.active_parts == %{}

      # Verify token counts (3 deltas)
      {input, output} = SilentHandler.get_metrics(final_state)
      assert input == 0
      assert output == 3

      # Verify all events recorded
      events = SilentHandler.events(final_state)
      # 3 starts + 3 ends
      assert length(events) == 6
    end
  end

  describe "get_metrics/1" do
    test "returns zero for new handler" do
      state = SilentHandler.new()
      assert SilentHandler.get_metrics(state) == {0, 0}
    end

    test "returns correct metrics after processing" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)
        |> SilentHandler.handle_part_delta("part_1", "Hello")
        |> elem(1)
        |> SilentHandler.handle_part_delta("part_1", " world")
        |> elem(1)
        |> SilentHandler.handle_part_start("part_2", :thinking, %{})
        |> elem(1)
        |> SilentHandler.handle_part_delta("part_2", "Thinking...")
        |> elem(1)

      assert SilentHandler.get_metrics(state) == {0, 3}
    end
  end

  describe "event_count/1" do
    test "returns zero for new handler" do
      state = SilentHandler.new()
      assert SilentHandler.event_count(state) == 0
    end

    test "returns count of accumulated events" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)
        |> SilentHandler.handle_part_end("part_1", %{})
        |> elem(1)

      assert SilentHandler.event_count(state) == 2
    end
  end

  describe "active_type?/2" do
    test "returns true for active type" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("thinking_1", :thinking, %{})
        |> elem(1)

      assert SilentHandler.active_type?(state, :thinking) == true
    end

    test "returns false for inactive type" do
      state = SilentHandler.new()
      assert SilentHandler.active_type?(state, :text) == false
    end

    test "returns false after part ends" do
      state =
        SilentHandler.new()
        |> SilentHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)
        |> SilentHandler.handle_part_end("part_1", %{})
        |> elem(1)

      assert SilentHandler.active_type?(state, :text) == false
    end
  end

  describe "sub-agent use case" do
    test "tracks metrics without console output" do
      # Simulate a sub-agent run that should not output to console
      state = SilentHandler.new(session_id: "sub_agent_session")

      # Process a typical LLM response silently
      {:ok, state} = SilentHandler.handle_part_start(state, "thinking_1", :thinking, %{})
      {:ok, state} = SilentHandler.handle_part_delta(state, "thinking_1", "Let me analyze...")
      {:ok, state} = SilentHandler.handle_part_delta(state, "thinking_1", " The code looks good.")
      {:ok, state} = SilentHandler.handle_part_end(state, "thinking_1", %{})

      {:ok, state} = SilentHandler.handle_part_start(state, "text_1", :text, %{})
      {:ok, state} = SilentHandler.handle_part_delta(state, "text_1", "Analysis complete.")
      {:ok, final_state} = SilentHandler.handle_part_end(state, "text_1", %{result: "success"})

      # Get metrics for parent agent
      {input, output} = SilentHandler.get_metrics(final_state)
      assert input == 0
      # 2 thinking deltas + 1 text delta
      assert output == 3

      # Can review events if needed
      events = SilentHandler.events(final_state)
      # 2 starts + 2 ends
      assert length(events) == 4

      # But no console output was produced (verified in other tests)
    end
  end
end
