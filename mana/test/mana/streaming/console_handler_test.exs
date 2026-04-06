defmodule Mana.Streaming.ConsoleHandlerTest do
  @moduledoc """
  Tests for Mana.Streaming.ConsoleHandler module.
  """

  use ExUnit.Case, async: false

  alias Mana.MessageBus
  alias Mana.Streaming.ConsoleHandler
  alias Mana.Streaming.PartTracker

  setup do
    # Start the MessageBus and Callbacks Registry for each test
    start_supervised!(MessageBus)
    start_supervised!(Mana.Callbacks.Registry)

    :ok
  end

  describe "new/1" do
    test "creates handler with default values" do
      handler = ConsoleHandler.new()

      assert handler.session_id == nil
      assert handler.part_tracker == PartTracker.new()
    end

    test "creates handler with session_id" do
      handler = ConsoleHandler.new(session_id: "session_123")

      assert handler.session_id == "session_123"
    end
  end

  describe "part_tracker/1" do
    test "returns the part tracker from state" do
      handler = ConsoleHandler.new()
      tracker = ConsoleHandler.part_tracker(handler)

      assert tracker == PartTracker.new()
    end
  end

  describe "handle_part_start/4" do
    test "emits system message on part start" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new()

      {:ok, new_state} = ConsoleHandler.handle_part_start(state, "part_1", :text, %{extra: "data"})

      # Verify part tracker was updated
      assert new_state.part_tracker.part_counter == 1
      assert new_state.part_tracker.active_parts["part_1"].type == :text

      # Verify system message was emitted
      assert_receive {:message, message}, 1000
      assert message.role == :system
      assert message.content == "[text] starting..."
      assert message.category == :text
    end

    test "emits with different types" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new()

      {:ok, _} = ConsoleHandler.handle_part_start(state, "thinking_1", :thinking, %{})
      assert_receive {:message, msg1}, 1000
      assert msg1.content == "[thinking] starting..."

      {:ok, _} = ConsoleHandler.handle_part_start(state, "tool_1", :tool, %{})
      assert_receive {:message, msg2}, 1000
      assert msg2.content == "[tool] starting..."
    end

    test "includes session_id in emitted message" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new(session_id: "session_123")

      {:ok, _} = ConsoleHandler.handle_part_start(state, "part_1", :text, %{})

      assert_receive {:message, message}, 1000
      assert message.session_id == "session_123"
    end
  end

  describe "handle_part_delta/3" do
    test "emits assistant message with content" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new()

      {:ok, _} = ConsoleHandler.handle_part_delta(state, "part_1", "Hello world")

      assert_receive {:message, message}, 1000
      assert message.role == :assistant
      assert message.content == "Hello world"
      assert message.category == :text
    end

    test "emits multiple deltas" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new()

      {:ok, state1} = ConsoleHandler.handle_part_delta(state, "part_1", "Hello")
      {:ok, state2} = ConsoleHandler.handle_part_delta(state1, "part_1", " ")
      {:ok, _} = ConsoleHandler.handle_part_delta(state2, "part_1", "world")

      assert_receive {:message, msg1}, 1000
      assert msg1.content == "Hello"

      assert_receive {:message, msg2}, 1000
      assert msg2.content == " "

      assert_receive {:message, msg3}, 1000
      assert msg3.content == "world"
    end

    test "includes session_id in emitted message" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new(session_id: "session_456")

      {:ok, _} = ConsoleHandler.handle_part_delta(state, "part_1", "content")

      assert_receive {:message, message}, 1000
      assert message.session_id == "session_456"
    end
  end

  describe "handle_part_end/3" do
    test "removes part from tracker" do
      # Add listener first to capture any messages
      :ok = MessageBus.add_listener(self())

      state =
        ConsoleHandler.new()
        |> ConsoleHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      # Clear message from part_start
      assert_receive {:message, _}, 1000

      assert state.part_tracker.active_parts["part_1"] != nil

      {:ok, new_state} = ConsoleHandler.handle_part_end(state, "part_1", %{result: "done"})

      assert new_state.part_tracker.active_parts["part_1"] == nil
    end

    test "handles metadata in end event" do
      # Add listener first to capture any messages
      :ok = MessageBus.add_listener(self())

      state =
        ConsoleHandler.new()
        |> ConsoleHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      # Clear message from part_start
      assert_receive {:message, _}, 1000

      {:ok, new_state} = ConsoleHandler.handle_part_end(state, "part_1", %{result: "success", tokens: 150})

      assert new_state.part_tracker.active_parts["part_1"] == nil
    end
  end

  describe "complete workflow" do
    test "handles full streaming lifecycle" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new(session_id: "workflow_session")

      # Start part
      {:ok, state} = ConsoleHandler.handle_part_start(state, "part_1", :text, %{initial: true})
      assert_receive {:message, start_msg}, 1000
      assert start_msg.content == "[text] starting..."
      assert start_msg.role == :system

      # Multiple deltas
      {:ok, state} = ConsoleHandler.handle_part_delta(state, "part_1", "Hello")
      assert_receive {:message, delta1}, 1000
      assert delta1.content == "Hello"
      assert delta1.role == :assistant

      {:ok, state} = ConsoleHandler.handle_part_delta(state, "part_1", " world!")
      assert_receive {:message, delta2}, 1000
      assert delta2.content == " world!"

      # End part
      {:ok, final_state} = ConsoleHandler.handle_part_end(state, "part_1", %{complete: true})
      assert final_state.part_tracker.active_parts == %{}

      # Verify session_id is preserved throughout
      assert start_msg.session_id == "workflow_session"
      assert delta1.session_id == "workflow_session"
      assert delta2.session_id == "workflow_session"
    end

    test "handles thinking -> text workflow" do
      :ok = MessageBus.add_listener(self())

      state = ConsoleHandler.new()

      # Start thinking
      {:ok, state} = ConsoleHandler.handle_part_start(state, "thinking_1", :thinking, %{})
      assert_receive {:message, thinking_start}, 1000
      assert thinking_start.content == "[thinking] starting..."

      {:ok, state} = ConsoleHandler.handle_part_delta(state, "thinking_1", "Analyzing...")
      assert_receive {:message, thinking_delta}, 1000
      assert thinking_delta.content == "Analyzing..."

      {:ok, state} = ConsoleHandler.handle_part_end(state, "thinking_1", %{})
      assert PartTracker.active_type?(state.part_tracker, :thinking) == false

      # Start text response
      {:ok, state} = ConsoleHandler.handle_part_start(state, "text_1", :text, %{})
      assert_receive {:message, text_start}, 1000
      assert text_start.content == "[text] starting..."

      {:ok, state} = ConsoleHandler.handle_part_delta(state, "text_1", "Result: success")
      assert_receive {:message, text_delta}, 1000
      assert text_delta.content == "Result: success"

      {:ok, final_state} = ConsoleHandler.handle_part_end(state, "text_1", %{})
      assert final_state.part_tracker.active_parts == %{}
    end
  end

  describe "active_type?/2" do
    test "returns true for active type" do
      state =
        ConsoleHandler.new()
        |> ConsoleHandler.handle_part_start("thinking_1", :thinking, %{})
        |> elem(1)

      assert ConsoleHandler.active_type?(state, :thinking) == true
    end

    test "returns false for inactive type" do
      state = ConsoleHandler.new()
      assert ConsoleHandler.active_type?(state, :text) == false
    end
  end

  describe "total_tokens/1" do
    test "returns zero for new handler" do
      state = ConsoleHandler.new()
      assert ConsoleHandler.total_tokens(state) == {0, 0}
    end

    test "returns tracker totals" do
      # Note: ConsoleHandler doesn't directly update tokens during deltas
      # but we can verify it delegates to the tracker
      state =
        ConsoleHandler.new()
        |> ConsoleHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      assert ConsoleHandler.total_tokens(state) == {0, 0}
    end
  end

  describe "callback integration" do
    setup do
      Mana.Callbacks.clear(:stream_event)
      :ok
    end

    test "fires stream_event callback on part_start" do
      test_pid = self()

      callback = fn event_type, event_data, session_id ->
        send(test_pid, {:stream_event, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback)

      state = ConsoleHandler.new(session_id: "callback_session")
      ConsoleHandler.handle_part_start(state, "part_1", :text, %{meta: "data"})

      assert_receive {:stream_event, :part_start, %{part_id: "part_1", type: :text}, "callback_session"}, 500
    end

    test "fires stream_event callback on part_delta" do
      test_pid = self()

      callback = fn event_type, event_data, session_id ->
        send(test_pid, {:stream_event, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback)

      state = ConsoleHandler.new(session_id: "callback_session")
      ConsoleHandler.handle_part_delta(state, "part_1", "content")

      assert_receive {:stream_event, :part_delta, %{part_id: "part_1", content: "content"}, "callback_session"}, 500
    end

    test "fires stream_event callback on part_end" do
      test_pid = self()

      callback = fn event_type, event_data, session_id ->
        send(test_pid, {:stream_event, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback)

      state =
        ConsoleHandler.new(session_id: "callback_session")
        |> ConsoleHandler.handle_part_start("part_1", :text, %{})
        |> elem(1)

      ConsoleHandler.handle_part_end(state, "part_1", %{result: "done"})

      assert_receive {:stream_event, :part_end, %{part_id: "part_1"}, "callback_session"}, 500
    end
  end
end
