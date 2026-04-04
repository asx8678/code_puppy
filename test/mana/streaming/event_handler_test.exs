defmodule Mana.Streaming.EventHandlerTest do
  @moduledoc """
  Tests for Mana.Streaming.EventHandler module.
  """

  use ExUnit.Case, async: false

  alias Mana.Streaming.EventHandler

  setup do
    # Start the Callbacks Registry
    start_supervised!(Mana.Callbacks.Registry)
    :ok
  end

  # Mock handler for testing
  defmodule MockHandler do
    @behaviour EventHandler

    @impl true
    def handle_part_start(state, part_id, type, meta) do
      new_state =
        state
        |> Map.update(:events, [{:start, part_id, type, meta}], fn events ->
          [{:start, part_id, type, meta} | events]
        end)
        |> Map.update(:active_parts, [part_id], fn parts -> [part_id | parts] end)

      {:ok, new_state}
    end

    @impl true
    def handle_part_delta(state, part_id, content) do
      new_state =
        Map.update(state, :events, [{:delta, part_id, content}], fn events ->
          [{:delta, part_id, content} | events]
        end)

      {:ok, new_state}
    end

    @impl true
    def handle_part_end(state, part_id, meta) do
      new_state =
        state
        |> Map.update(:events, [{:end, part_id, meta}], fn events ->
          [{:end, part_id, meta} | events]
        end)
        |> Map.update(:active_parts, [], fn parts ->
          List.delete(parts, part_id)
        end)

      {:ok, new_state}
    end
  end

  describe "process_events/3" do
    test "processes empty event list" do
      state = %{}
      assert {:ok, ^state} = EventHandler.process_events(MockHandler, state, [])
    end

    test "processes single part_start event" do
      state = %{}
      events = [{:part_start, "part_1", :text, %{extra: "data"}}]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      assert length(new_state.events) == 1
      assert hd(new_state.events) == {:start, "part_1", :text, %{extra: "data"}}
      assert new_state.active_parts == ["part_1"]
    end

    test "processes single part_delta event" do
      state = %{}
      events = [{:part_delta, "part_1", "Hello world"}]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      assert length(new_state.events) == 1
      assert hd(new_state.events) == {:delta, "part_1", "Hello world"}
    end

    test "processes single part_end event" do
      state = %{active_parts: ["part_1"]}
      events = [{:part_end, "part_1", %{result: "success"}}]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      assert length(new_state.events) == 1
      assert hd(new_state.events) == {:end, "part_1", %{result: "success"}}
      assert new_state.active_parts == []
    end

    test "processes complete part lifecycle" do
      state = %{}

      events = [
        {:part_start, "part_1", :text, %{}},
        {:part_delta, "part_1", "Hello"},
        {:part_delta, "part_1", " world"},
        {:part_end, "part_1", %{}}
      ]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      # Events are prepended, so they're in reverse order
      assert new_state.events == [
               {:end, "part_1", %{}},
               {:delta, "part_1", " world"},
               {:delta, "part_1", "Hello"},
               {:start, "part_1", :text, %{}}
               # from init
             ]

      assert new_state.active_parts == []
    end

    test "processes multiple parts" do
      state = %{}

      events = [
        {:part_start, "thinking_1", :thinking, %{}},
        {:part_delta, "thinking_1", "Analyzing..."},
        {:part_start, "text_1", :text, %{}},
        {:part_delta, "text_1", "Result: "},
        {:part_end, "thinking_1", %{}},
        {:part_delta, "text_1", "success"},
        {:part_end, "text_1", %{}},
        {:part_start, "tool_1", :tool, %{name: "shell"}},
        {:part_end, "tool_1", %{}}
      ]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      # Verify all events were processed
      assert length(new_state.events) == 9

      # Verify final active parts state
      assert new_state.active_parts == []
    end

    test "ignores unknown event types" do
      state = %{value: 42}
      events = [{:unknown_event, "data"}, {:another_unknown, 1, 2, 3}]

      # Should pass through unchanged
      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)
      assert new_state == %{value: 42}
    end

    test "handles mixed known and unknown events" do
      state = %{}

      events = [
        {:part_start, "part_1", :text, %{}},
        {:unknown_event, "ignored"},
        {:part_delta, "part_1", "content"},
        {:another_unknown, 1, 2},
        {:part_end, "part_1", %{}}
      ]

      assert {:ok, new_state} = EventHandler.process_events(MockHandler, state, events)

      # Only known events should be in the list
      events_list = Enum.reverse(new_state.events)

      assert {:start, "part_1", :text, %{}} in events_list
      assert {:delta, "part_1", "content"} in events_list
      assert {:end, "part_1", %{}} in events_list
      refute {:unknown_event, "ignored"} in events_list
      refute {:another_unknown, 1, 2} in events_list
    end

    test "maintains state across event processing" do
      state = %{counter: 0, parts: []}

      # Custom handler that increments counter
      custom_handler = fn
        {:part_start, part_id, type, _meta}, {:ok, acc} ->
          new_acc = %{
            counter: acc.counter + 1,
            parts: [part_id | acc.parts]
          }

          {:ok, new_acc}

        {:part_end, part_id, _meta}, {:ok, acc} ->
          new_acc = %{
            counter: acc.counter + 1,
            parts: List.delete(acc.parts, part_id)
          }

          {:ok, new_acc}

        _, acc ->
          acc
      end

      events = [
        {:part_start, "part_1", :text, %{}},
        {:part_start, "part_2", :thinking, %{}},
        {:part_end, "part_1", %{}},
        {:part_end, "part_2", %{}}
      ]

      result = Enum.reduce(events, {:ok, state}, custom_handler)
      assert {:ok, %{counter: 4, parts: []}} = result
    end
  end

  describe "fire_stream_callback/3" do
    setup do
      # Clear any existing callbacks
      Mana.Callbacks.clear(:stream_event)
      :ok
    end

    test "dispatches to registered callbacks" do
      # Register a test callback
      test_pid = self()

      callback = fn event_type, event_data, session_id ->
        send(test_pid, {:stream_event, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback)

      # Fire the callback
      EventHandler.fire_stream_callback(
        :part_start,
        %{part_id: "part_1", type: :text},
        "session_123"
      )

      # Wait for the callback to fire
      assert_receive {:stream_event, :part_start, %{part_id: "part_1", type: :text}, "session_123"}, 500
    end

    test "handles nil session_id" do
      test_pid = self()

      callback = fn event_type, event_data, session_id ->
        send(test_pid, {:stream_event, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback)

      EventHandler.fire_stream_callback(
        :part_delta,
        %{part_id: "part_1", content: "Hello"},
        nil
      )

      assert_receive {:stream_event, :part_delta, %{part_id: "part_1", content: "Hello"}, nil}, 500
    end

    test "dispatches to multiple callbacks" do
      test_pid = self()

      callback1 = fn event_type, event_data, session_id ->
        send(test_pid, {:callback1, event_type, event_data, session_id})
        :ok
      end

      callback2 = fn event_type, event_data, session_id ->
        send(test_pid, {:callback2, event_type, event_data, session_id})
        :ok
      end

      :ok = Mana.Callbacks.register(:stream_event, callback1)
      :ok = Mana.Callbacks.register(:stream_event, callback2)

      EventHandler.fire_stream_callback(:part_end, %{part_id: "part_1"}, "session_456")

      assert_receive {:callback1, :part_end, %{part_id: "part_1"}, "session_456"}, 500
      assert_receive {:callback2, :part_end, %{part_id: "part_1"}, "session_456"}, 500
    end
  end
end
