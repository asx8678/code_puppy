defmodule Mana.Plugins.FrontendEmitterTest do
  use ExUnit.Case

  alias Mana.Plugins.FrontendEmitter

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = FrontendEmitter.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(FrontendEmitter, :name, 0)
      assert function_exported?(FrontendEmitter, :init, 1)
      assert function_exported?(FrontendEmitter, :hooks, 0)
      assert function_exported?(FrontendEmitter, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert FrontendEmitter.name() == "frontend_emitter"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = FrontendEmitter.init(%{})
      assert state.pubsub == :mana_pubsub
      assert state.topic_prefix == "events:"
      assert state.sanitize == true
    end

    test "initializes with custom config" do
      config = %{
        pubsub_name: :my_pubsub,
        topic_prefix: "custom:",
        sanitize_args: false
      }

      assert {:ok, state} = FrontendEmitter.init(config)
      assert state.pubsub == :my_pubsub
      assert state.topic_prefix == "custom:"
      assert state.sanitize == false
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = FrontendEmitter.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :pre_tool_call in hook_names
      assert :post_tool_call in hook_names
      assert :stream_event in hook_names
      assert :invoke_agent in hook_names
    end
  end

  describe "on_pre_tool_call/3" do
    test "returns :ok" do
      assert :ok == FrontendEmitter.on_pre_tool_call("read_file", %{"path" => "test.ex"}, %{})
    end
  end

  describe "on_post_tool_call/5" do
    test "returns :ok with string result" do
      assert :ok ==
               FrontendEmitter.on_post_tool_call(
                 "read_file",
                 %{"path" => "test.ex"},
                 "file contents",
                 150,
                 %{}
               )
    end

    test "returns :ok with map result" do
      assert :ok ==
               FrontendEmitter.on_post_tool_call(
                 "shell",
                 %{"command" => "ls"},
                 %{"output" => "file1.ex"},
                 50,
                 %{}
               )
    end
  end

  describe "on_stream_event/3" do
    test "returns :ok" do
      assert :ok ==
               FrontendEmitter.on_stream_event("text_delta", "hello world", "session_123")
    end

    test "handles nil session_id" do
      assert :ok == FrontendEmitter.on_stream_event("text_delta", "data", nil)
    end
  end

  describe "on_invoke_agent/2" do
    test "returns :ok with list args" do
      assert :ok == FrontendEmitter.on_invoke_agent(["turbo-executor", "session_1", "prompt"], [])
    end

    test "returns :ok with keyword kwargs" do
      assert :ok ==
               FrontendEmitter.on_invoke_agent(
                 [],
                 agent_name: "turbo-executor",
                 session_id: "sess_1",
                 prompt: "do something"
               )
    end

    test "returns :ok with empty args" do
      assert :ok == FrontendEmitter.on_invoke_agent([], [])
    end
  end

  describe "emit/3" do
    test "returns :ok even without pubsub running" do
      assert :ok == FrontendEmitter.emit("test_event", %{data: "test"}, "session_1")
    end

    test "returns :ok with nil session_id" do
      assert :ok == FrontendEmitter.emit("test_event", %{data: "test"}, nil)
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert FrontendEmitter.terminate() == :ok
    end
  end
end
