defmodule Mana.MessageBusTest do
  @moduledoc """
  Tests for Mana.MessageBus module.
  """

  use ExUnit.Case, async: false

  alias Mana.Message
  alias Mana.MessageBus

  setup do
    # Start the MessageBus for each test
    start_supervised!(MessageBus)

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(MessageBus) != nil
    end

    test "returns child_spec for supervision trees" do
      spec = MessageBus.child_spec([])

      assert spec.id == MessageBus
      assert spec.type == :worker
      assert spec.restart == :permanent
      assert spec.start == {MessageBus, :start_link, [[]]}
    end
  end

  describe "emit/1" do
    test "emits message to registered listeners" do
      # Add ourselves as a listener
      :ok = MessageBus.add_listener(self())

      message = Message.new(:text, %{content: "Hello", role: :user})
      :ok = MessageBus.emit(message)

      # Wait for the message
      assert_receive {:message, received}, 1000
      assert received.id == message.id
      assert received.content == "Hello"
      assert received.role == :user
    end

    test "emits to multiple listeners" do
      # Create a sub-process that will also listen
      test_pid = self()

      spawn(fn ->
        :ok = MessageBus.add_listener(self())
        send(test_pid, :listener_ready)

        receive do
          {:message, msg} -> send(test_pid, {:received, msg.id})
        after
          1000 -> send(test_pid, :timeout)
        end
      end)

      # Also add ourselves
      :ok = MessageBus.add_listener(self())

      # Wait for listener to be ready
      assert_receive :listener_ready, 1000

      message = Message.new(:text, %{content: "Broadcast", role: :system})
      :ok = MessageBus.emit(message)

      # Both should receive
      assert_receive {:message, received}, 1000
      assert received.id == message.id

      assert_receive {:received, id}, 1000
      assert id == message.id
    end

    test "handles emit without any listeners" do
      message = Message.new(:text, %{content: "No listeners", role: :system})

      # Should not crash
      assert :ok = MessageBus.emit(message)
    end
  end

  describe "emit_text/2" do
    test "emits text message with default role" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_text("Hello world")

      assert_receive {:message, received}, 1000
      assert received.content == "Hello world"
      assert received.role == :system
      assert received.category == :text
    end

    test "emits text message with custom role" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_text("User says", role: :user)

      assert_receive {:message, received}, 1000
      assert received.role == :user
    end

    test "emits text message with session_id" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_text("Session test", session_id: "sess_123")

      assert_receive {:message, received}, 1000
      assert received.session_id == "sess_123"
    end
  end

  describe "emit_info/1" do
    test "emits info text message" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_info("Info message")

      assert_receive {:message, received}, 1000
      assert received.content == "Info message"
      assert received.role == :system
    end
  end

  describe "emit_warning/1" do
    test "emits warning text message with prefix" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_warning("Low disk space")

      assert_receive {:message, received}, 1000
      assert received.content == "⚠️  Low disk space"
      assert received.role == :system
    end
  end

  describe "emit_error/1" do
    test "emits error text message with prefix" do
      :ok = MessageBus.add_listener(self())

      :ok = MessageBus.emit_error("Connection failed")

      assert_receive {:message, received}, 1000
      assert received.content == "❌ Connection failed"
      assert received.role == :system
    end
  end

  describe "request_input/2" do
    test "requests input and blocks until response" do
      :ok = MessageBus.add_listener(self())

      # Request input in a separate task
      requester =
        Task.async(fn ->
          MessageBus.request_input("Enter name:", timeout: 5000)
        end)

      # Wait for the request message
      assert_receive {:message, request}, 1000
      assert request.interaction_type == :input
      assert request.prompt == "Enter name:"
      assert request.id != nil

      # Provide the response
      :ok = MessageBus.provide_response(request.id, "John")

      # Verify the requester got the response
      assert {:ok, "John"} = Task.await(requester, 1000)
    end

    test "handles multiple concurrent input requests" do
      :ok = MessageBus.add_listener(self())

      # Start two concurrent requests
      requester1 =
        Task.async(fn ->
          MessageBus.request_input("First:", timeout: 5000)
        end)

      requester2 =
        Task.async(fn ->
          MessageBus.request_input("Second:", timeout: 5000)
        end)

      # Receive both requests
      assert_receive {:message, req1}, 1000
      assert_receive {:message, req2}, 1000

      # Verify they're different requests
      assert req1.id != req2.id

      # Provide responses in reverse order
      :ok = MessageBus.provide_response(req2.id, "Second response")
      :ok = MessageBus.provide_response(req1.id, "First response")

      # Verify responses
      assert {:ok, "First response"} = Task.await(requester1, 1000)
      assert {:ok, "Second response"} = Task.await(requester2, 1000)
    end

    test "returns error on timeout" do
      # Request with very short timeout
      result = MessageBus.request_input("Test:", timeout: 50)

      assert result == {:error, :timeout}
    end

    test "includes session_id in request" do
      :ok = MessageBus.add_listener(self())

      requester =
        Task.async(fn ->
          MessageBus.request_input("Test:", timeout: 5000, session_id: "sess_123")
        end)

      assert_receive {:message, request}, 1000
      assert request.session_id == "sess_123"

      :ok = MessageBus.provide_response(request.id, "response")
      Task.await(requester, 1000)
    end
  end

  describe "request_confirmation/2" do
    test "requests confirmation and blocks until response" do
      :ok = MessageBus.add_listener(self())

      requester =
        Task.async(fn ->
          MessageBus.request_confirmation("Delete file?", timeout: 5000)
        end)

      assert_receive {:message, request}, 1000
      assert request.interaction_type == :confirmation
      assert request.prompt == "Delete file?"

      :ok = MessageBus.provide_response(request.id, true)

      assert {:ok, true} = Task.await(requester, 1000)
    end

    test "receives false for cancel" do
      :ok = MessageBus.add_listener(self())

      requester =
        Task.async(fn ->
          MessageBus.request_confirmation("Proceed?", timeout: 5000)
        end)

      assert_receive {:message, request}, 1000

      :ok = MessageBus.provide_response(request.id, false)

      assert {:ok, false} = Task.await(requester, 1000)
    end

    test "returns error on timeout" do
      result = MessageBus.request_confirmation("Test?", timeout: 50)

      assert result == {:error, :timeout}
    end
  end

  describe "request_selection/3" do
    test "requests selection and blocks until response" do
      :ok = MessageBus.add_listener(self())

      requester =
        Task.async(fn ->
          MessageBus.request_selection("Pick one:", ["A", "B", "C"], timeout: 5000)
        end)

      assert_receive {:message, request}, 1000
      assert request.interaction_type == :selection
      assert request.prompt == "Pick one:"
      assert request.payload.choices == ["A", "B", "C"]

      :ok = MessageBus.provide_response(request.id, "B")

      assert {:ok, "B"} = Task.await(requester, 1000)
    end

    test "returns error on timeout" do
      result = MessageBus.request_selection("Pick:", ["A", "B"], timeout: 50)

      assert result == {:error, :timeout}
    end
  end

  describe "provide_response/2" do
    test "returns error for unknown request_id" do
      result = MessageBus.provide_response("nonexistent_id", "response")

      assert result == {:error, :not_found}
    end

    test "returns ok after resolving pending request" do
      :ok = MessageBus.add_listener(self())

      requester =
        Task.async(fn ->
          MessageBus.request_input("Test:", timeout: 5000)
        end)

      assert_receive {:message, request}, 1000

      assert :ok = MessageBus.provide_response(request.id, "answer")
      Task.await(requester, 1000)
    end
  end

  describe "add_listener/1 and remove_listener/1" do
    test "adds and removes listener successfully" do
      assert :ok = MessageBus.add_listener(self())
      assert :ok = MessageBus.remove_listener(self())

      # After removal, should not receive messages
      message = Message.new(:text, %{content: "Test", role: :system})
      :ok = MessageBus.emit(message)

      refute_receive {:message, _}, 200
    end

    test "automatically cleans up dead listeners" do
      # Create a temporary process that will be a listener
      temp_pid =
        spawn(fn ->
          :ok = MessageBus.add_listener(self())

          receive do
            :stop -> :ok
          end
        end)

      # Let it register
      Process.sleep(50)

      # Kill the process
      Process.exit(temp_pid, :kill)

      # Wait for DOWN message to be processed
      Process.sleep(100)

      # Emit should not crash even with dead listener in list
      message = Message.new(:text, %{content: "Test", role: :system})
      assert :ok = MessageBus.emit(message)
    end
  end

  describe "list_pending_requests/0" do
    test "lists all pending request IDs" do
      :ok = MessageBus.add_listener(self())

      # Start two requests
      _requester1 =
        Task.async(fn ->
          MessageBus.request_input("First:", timeout: 5000)
        end)

      _requester2 =
        Task.async(fn ->
          MessageBus.request_input("Second:", timeout: 5000)
        end)

      # Receive both requests to ensure they're registered
      assert_receive {:message, req1}, 1000
      assert_receive {:message, req2}, 1000

      # Get pending list
      pending = MessageBus.list_pending_requests()

      assert length(pending) == 2
      assert req1.id in pending
      assert req2.id in pending
    end

    test "returns empty list when no pending requests" do
      assert MessageBus.list_pending_requests() == []
    end
  end

  describe "end-to-end flow" do
    test "complete message flow with multiple message types" do
      :ok = MessageBus.add_listener(self())

      # Emit various message types
      text_msg = Message.new(:text, %{content: "Hello", role: :user})
      :ok = MessageBus.emit(text_msg)

      file_msg = Message.new(:file, %{path: "/tmp/test.txt", operation: :read})
      :ok = MessageBus.emit(file_msg)

      shell_msg = Message.new(:shell, %{command: "ls", output: "file.txt", exit_code: 0})
      :ok = MessageBus.emit(shell_msg)

      # Receive all messages
      assert_receive {:message, received1}, 1000
      assert_receive {:message, received2}, 1000
      assert_receive {:message, received3}, 1000

      # Verify they arrived
      message_ids = [received1.id, received2.id, received3.id]
      assert text_msg.id in message_ids
      assert file_msg.id in message_ids
      assert shell_msg.id in message_ids
    end

    test "session correlation via session_id" do
      :ok = MessageBus.add_listener(self())

      session_id = "session_abc_123"

      # Emit messages with same session_id
      :ok = MessageBus.emit_text("Msg 1", session_id: session_id)
      :ok = MessageBus.emit_info("Msg 2", session_id: session_id)

      requester =
        Task.async(fn ->
          MessageBus.request_input("Input:", timeout: 5000, session_id: session_id)
        end)

      # Verify all messages have the same session_id
      assert_receive {:message, msg1}, 1000
      assert_receive {:message, msg2}, 1000
      assert_receive {:message, msg3}, 1000

      assert msg1.session_id == session_id
      assert msg2.session_id == session_id
      assert msg3.session_id == session_id

      # Complete the request
      :ok = MessageBus.provide_response(msg3.id, "done")
      Task.await(requester, 1000)
    end
  end
end
