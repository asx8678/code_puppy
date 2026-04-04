defmodule Mana.MessageTest do
  @moduledoc """
  Tests for Mana message types and factory function.
  """

  use ExUnit.Case, async: true

  alias Mana.Message
  alias Mana.Message.Text
  alias Mana.Message.File
  alias Mana.Message.Shell
  alias Mana.Message.Agent
  alias Mana.Message.UserInteraction
  alias Mana.Message.Control

  describe "generate_uuid/0" do
    test "generates a valid UUID v4 format" do
      uuid = Message.generate_uuid()

      # UUID format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
      assert String.length(uuid) == 36
      assert Regex.match?(~r/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i, uuid)
    end

    test "generates unique UUIDs" do
      uuid1 = Message.generate_uuid()
      uuid2 = Message.generate_uuid()

      assert uuid1 != uuid2
    end
  end

  describe "new/2 for :text messages" do
    test "creates a Text message with default values" do
      message = Message.new(:text, %{content: "Hello", role: :user})

      assert %Text{} = message
      assert message.content == "Hello"
      assert message.role == :user
      assert message.category == :text
      assert is_binary(message.id)
      assert %DateTime{} = message.timestamp
      assert message.session_id == nil
    end

    test "creates a Text message with custom session_id" do
      message = Message.new(:text, %{content: "Hi", role: :assistant, session_id: "session_123"})

      assert message.session_id == "session_123"
    end

    test "preserves provided id and timestamp" do
      id = "custom-id-123"
      timestamp = ~U[2024-01-15 10:30:00Z]

      message = Message.new(:text, %{content: "Test", role: :system, id: id, timestamp: timestamp})

      assert message.id == id
      assert message.timestamp == timestamp
    end

    test "supports all valid roles" do
      user = Message.new(:text, %{content: "User msg", role: :user})
      assistant = Message.new(:text, %{content: "Assistant msg", role: :assistant})
      system = Message.new(:text, %{content: "System msg", role: :system})

      assert user.role == :user
      assert assistant.role == :assistant
      assert system.role == :system
    end
  end

  describe "new/2 for :file messages" do
    test "creates a File message with all fields" do
      message =
        Message.new(:file, %{
          path: "/tmp/test.txt",
          content: "Hello, world!",
          operation: :write,
          session_id: "sess_1"
        })

      assert %File{} = message
      assert message.path == "/tmp/test.txt"
      assert message.content == "Hello, world!"
      assert message.operation == :write
      assert message.category == :file
      assert message.session_id == "sess_1"
      assert is_binary(message.id)
      assert %DateTime{} = message.timestamp
    end

    test "supports all file operations" do
      read = Message.new(:file, %{path: "/a", operation: :read})
      write = Message.new(:file, %{path: "/b", operation: :write})
      edit = Message.new(:file, %{path: "/c", operation: :edit})
      delete = Message.new(:file, %{path: "/d", operation: :delete, content: nil})

      assert read.operation == :read
      assert write.operation == :write
      assert edit.operation == :edit
      assert delete.operation == :delete
    end

    test "allows nil content for delete operations" do
      message = Message.new(:file, %{path: "/tmp/old.txt", operation: :delete, content: nil})

      assert message.content == nil
    end
  end

  describe "new/2 for :shell messages" do
    test "creates a Shell message with all fields" do
      message =
        Message.new(:shell, %{
          command: "ls -la",
          output: "total 0",
          exit_code: 0,
          session_id: "shell_1"
        })

      assert %Shell{} = message
      assert message.command == "ls -la"
      assert message.output == "total 0"
      assert message.exit_code == 0
      assert message.category == :shell
      assert message.session_id == "shell_1"
    end

    test "handles error exit codes" do
      message = Message.new(:shell, %{command: "false", output: "", exit_code: 1})

      assert message.exit_code == 1
    end
  end

  describe "new/2 for :agent messages" do
    test "creates an Agent message with all fields" do
      message =
        Message.new(:agent, %{
          agent_name: "code_puppy",
          action: :invoke,
          payload: %{task: "Implement feature"},
          session_id: "agent_1"
        })

      assert %Agent{} = message
      assert message.agent_name == "code_puppy"
      assert message.action == :invoke
      assert message.payload == %{task: "Implement feature"}
      assert message.category == :agent
      assert message.session_id == "agent_1"
    end

    test "supports all agent actions" do
      invoke = Message.new(:agent, %{agent_name: "a", action: :invoke, payload: %{}})
      result = Message.new(:agent, %{agent_name: "b", action: :result, payload: %{}})
      error = Message.new(:agent, %{agent_name: "c", action: :error, payload: %{}})

      assert invoke.action == :invoke
      assert result.action == :result
      assert error.action == :error
    end
  end

  describe "new/2 for :user_interaction messages" do
    test "creates a UserInteraction message" do
      message =
        Message.new(:user_interaction, %{
          prompt: "Enter your name:",
          response: nil,
          interaction_type: :input,
          session_id: "ui_1"
        })

      assert %UserInteraction{} = message
      assert message.prompt == "Enter your name:"
      assert message.response == nil
      assert message.interaction_type == :input
      assert message.category == :user_interaction
      assert message.session_id == "ui_1"
    end

    test "supports all interaction types" do
      input = Message.new(:user_interaction, %{prompt: "A", interaction_type: :input})
      confirm = Message.new(:user_interaction, %{prompt: "B", interaction_type: :confirmation})
      select = Message.new(:user_interaction, %{prompt: "C", interaction_type: :selection})

      assert input.interaction_type == :input
      assert confirm.interaction_type == :confirmation
      assert select.interaction_type == :selection
    end

    test "can have a response value" do
      message =
        Message.new(:user_interaction, %{
          prompt: "Enter name:",
          response: "John",
          interaction_type: :input
        })

      assert message.response == "John"
    end
  end

  describe "new/2 for :control messages" do
    test "creates a Control message" do
      message =
        Message.new(:control, %{
          command: :start,
          session_id: "ctrl_1"
        })

      assert %Control{} = message
      assert message.command == :start
      assert message.category == :control
      assert message.session_id == "ctrl_1"
    end

    test "supports all control commands" do
      start = Message.new(:control, %{command: :start})
      stop = Message.new(:control, %{command: :stop})
      pause = Message.new(:control, %{command: :pause})
      resume = Message.new(:control, %{command: :resume})

      assert start.command == :start
      assert stop.command == :stop
      assert pause.command == :pause
      assert resume.command == :resume
    end
  end

  describe "new/2 error handling" do
    test "raises for unknown categories" do
      assert_raise ArgumentError, "Unknown message category: :unknown", fn ->
        Message.new(:unknown, %{field: "value"})
      end
    end

    test "raises for invalid category types" do
      assert_raise ArgumentError, ~r/Unknown message category/, fn ->
        Message.new("text", %{})
      end
    end
  end

  describe "message struct types" do
    test "Text struct has correct defaults" do
      text = %Text{}

      assert text.id == nil
      assert text.timestamp == nil
      assert text.category == nil
      assert text.session_id == nil
      assert text.content == nil
      assert text.role == nil
    end

    test "File struct has correct defaults" do
      file = %File{}

      assert file.path == nil
      assert file.content == nil
      assert file.operation == nil
    end

    test "Shell struct has correct defaults" do
      shell = %Shell{}

      assert shell.command == nil
      assert shell.output == nil
      assert shell.exit_code == nil
    end

    test "Agent struct has correct defaults" do
      agent = %Agent{}

      assert agent.agent_name == nil
      assert agent.action == nil
      assert agent.payload == nil
    end

    test "UserInteraction struct has correct defaults" do
      ui = %UserInteraction{}

      assert ui.prompt == nil
      assert ui.response == nil
      assert ui.interaction_type == nil
    end

    test "Control struct has correct defaults" do
      control = %Control{}

      assert control.command == nil
    end
  end
end
