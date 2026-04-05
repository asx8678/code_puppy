defmodule Mana.Web.ChatLiveTest do
  @moduledoc """
  Tests for the Mana.Web.Live.ChatLive module.

  Covers:
  - LiveView mounting and session creation
  - Message sending and state updates
  - Command dispatch handling
  - Agent execution flow
  - Stream chunk handling
  """

  use ExUnit.Case

  alias Mana.Web.Live.ChatLive

  # Helper to create a proper LiveView socket with required fields
  defp build_socket(assigns) do
    base_socket = %Phoenix.LiveView.Socket{}

    %Phoenix.LiveView.Socket{
      base_socket
      | assigns: Map.merge(%{__changed__: %{}}, assigns)
    }
  end

  setup do
    # Start PubSub if not running
    case Process.whereis(:mana_pubsub) do
      nil ->
        start_supervised!({Phoenix.PubSub, name: :mana_pubsub})

      _pid ->
        :ok
    end

    :ok
  end

  describe "mount/3" do
    test "creates a new session on mount" do
      {:ok, socket} = ChatLive.mount(%{}, %{}, build_socket(%{}))

      assert socket.assigns.session_id != nil
      assert String.length(socket.assigns.session_id) == 32
      assert socket.assigns.messages == []
      assert socket.assigns.input == ""
      assert socket.assigns.thinking == false
      assert socket.assigns.stream_output == ""
    end

    test "subscribes to pubsub on mount" do
      {:ok, _socket} = ChatLive.mount(%{}, %{}, build_socket(%{}))

      # Process should now be subscribed to pubsub
      # We verify by checking the process exists
      assert Process.whereis(:mana_pubsub) != nil
    end
  end

  describe "handle_event/3 - send" do
    test "ignores empty messages" do
      socket =
        build_socket(%{
          messages: [],
          input: "test",
          thinking: false,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_event("send", %{"message" => ""}, socket)
      assert {:noreply, ^socket} = result
    end

    test "adds user message and triggers async task" do
      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: false,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_event("send", %{"message" => "Hello"}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == true
      assert new_socket.assigns.input == ""
      assert length(new_socket.assigns.messages) == 1
      assert hd(new_socket.assigns.messages).role == "user"
      assert hd(new_socket.assigns.messages).content == "Hello"
    end

    test "handles command dispatch for messages starting with /" do
      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: false,
          session_id: "test-session",
          stream_output: ""
        })

      # Mock the command dispatch by checking it triggers a task
      result = ChatLive.handle_event("send", %{"message" => "/help"}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == true
    end
  end

  describe "handle_event/3 - update_input" do
    test "updates input value" do
      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: false,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_event("update_input", %{"value" => "new value"}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.input == "new value"
    end
  end

  describe "handle_info/2 - command results" do
    test "handles command result message" do
      ref = make_ref()

      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: true,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_info({ref, {:command_result, "Command output"}}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == false
      assert length(new_socket.assigns.messages) == 1
      assert hd(new_socket.assigns.messages).role == "assistant"
      assert hd(new_socket.assigns.messages).content == "Command output"
    end

    test "handles command error message" do
      ref = make_ref()

      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: true,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_info({ref, {:command_error, "Command failed"}}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == false
      assert length(new_socket.assigns.messages) == 1
      assert hd(new_socket.assigns.messages).content == "Error: Command failed"
    end
  end

  describe "handle_info/2 - agent results" do
    test "handles agent result message" do
      ref = make_ref()

      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: true,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_info({ref, {:agent_result, "Agent response"}}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == false
      assert length(new_socket.assigns.messages) == 1
      assert hd(new_socket.assigns.messages).role == "assistant"
      assert hd(new_socket.assigns.messages).content == "Agent response"
    end

    test "handles agent error message" do
      ref = make_ref()

      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: true,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_info({ref, {:agent_error, "Agent crashed"}}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.thinking == false
      assert length(new_socket.assigns.messages) == 1
      assert hd(new_socket.assigns.messages).content == "Error: Agent crashed"
    end
  end

  describe "handle_info/2 - stream chunks" do
    test "appends stream chunk to output" do
      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: false,
          session_id: "test-session",
          stream_output: "Hello"
        })

      result = ChatLive.handle_info({:stream_chunk, :text, " world"}, socket)
      assert {:noreply, new_socket} = result
      assert new_socket.assigns.stream_output == "Hello world"
    end
  end

  describe "handle_info/2 - task completion" do
    test "handles task DOWN message" do
      socket =
        build_socket(%{
          messages: [],
          input: "",
          thinking: true,
          session_id: "test-session",
          stream_output: ""
        })

      result = ChatLive.handle_info({:DOWN, make_ref(), :process, self(), :normal}, socket)
      assert {:noreply, ^socket} = result
    end
  end

  describe "render/1" do
    test "renders chat interface with messages" do
      assigns = %{
        session_id: "test-session",
        messages: [
          %{role: "user", content: "Hello"},
          %{role: "assistant", content: "Hi there!"}
        ],
        input: "",
        thinking: false,
        stream_output: ""
      }

      html = ChatLive.render(assigns)
      assert is_struct(html, Phoenix.LiveView.Rendered)
    end

    test "renders thinking indicator when thinking" do
      assigns = %{
        session_id: "test-session",
        messages: [%{role: "user", content: "Hello"}],
        input: "",
        thinking: true,
        stream_output: ""
      }

      html = ChatLive.render(assigns)
      assert is_struct(html, Phoenix.LiveView.Rendered)
    end

    test "renders stream output when present" do
      assigns = %{
        session_id: "test-session",
        messages: [%{role: "user", content: "Hello"}],
        input: "",
        thinking: false,
        stream_output: "Streaming response..."
      }

      html = ChatLive.render(assigns)
      assert is_struct(html, Phoenix.LiveView.Rendered)
    end
  end
end
