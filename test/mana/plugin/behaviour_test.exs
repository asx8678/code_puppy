defmodule Mana.Plugin.BehaviourTest do
  use ExUnit.Case

  alias Mana.TestSupport.MockPlugin

  describe "mock_plugin implementation" do
    test "implements the behaviour" do
      behaviours = MockPlugin.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "name/0 returns a string" do
      assert MockPlugin.name() == "mock_plugin"
    end

    test "init/1 returns {:ok, state}" do
      config = %{test: true}
      assert {:ok, state} = MockPlugin.init(config)
      assert state.config == config
      assert is_list(state.calls)
    end

    test "hooks/0 returns a list of hook tuples" do
      hooks = MockPlugin.hooks()
      assert is_list(hooks)
      assert length(hooks) == 3

      # Each hook is a {hook_name, function} tuple
      Enum.each(hooks, fn {hook, func} ->
        assert is_atom(hook)
        assert is_function(func)
      end)
    end

    test "hooks include expected hooks" do
      hooks = MockPlugin.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)

      assert :startup in hook_names
      assert :agent_run_start in hook_names
      assert :agent_run_end in hook_names
    end

    test "terminate/0 returns :ok" do
      assert MockPlugin.terminate() == :ok
    end
  end

  describe "behaviour callbacks exist" do
    test "all required callbacks are exported" do
      assert function_exported?(MockPlugin, :name, 0)
      assert function_exported?(MockPlugin, :init, 1)
      assert function_exported?(MockPlugin, :hooks, 0)
    end

    test "optional callbacks are exported" do
      assert function_exported?(MockPlugin, :terminate, 0)
    end
  end

  describe "hook functions work correctly" do
    setup do
      # Register test process as the collector
      Process.register(self(), :test_collector)
      :ok
    end

    test "on_startup/0 sends event" do
      assert :ok = MockPlugin.on_startup()
      assert_receive {:hook_called, :startup, []}
    end

    test "on_run_start/3 sends event" do
      assert :ok = MockPlugin.on_run_start("test_agent", "gpt-4", "session_123")
      assert_receive {:hook_called, :agent_run_start, ["test_agent", "gpt-4", "session_123"]}
    end

    test "on_run_end/7 sends event" do
      assert :ok =
               MockPlugin.on_run_end(
                 "test_agent",
                 "gpt-4",
                 "session_123",
                 true,
                 nil,
                 "response",
                 %{}
               )

      assert_receive {:hook_called, :agent_run_end, ["test_agent", "gpt-4", "session_123", true, nil, "response", %{}]}
    end
  end

  describe "Mana.Plugins.Logger behaviour compliance" do
    alias Mana.Plugins.Logger

    test "implements the behaviour" do
      behaviours = Logger.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(Logger, :name, 0)
      assert function_exported?(Logger, :init, 1)
      assert function_exported?(Logger, :hooks, 0)
      assert function_exported?(Logger, :terminate, 0)
    end

    test "init/1 accepts configuration" do
      config = %{level: :debug, log_tool_calls: true}
      assert {:ok, state} = Logger.init(config)
      assert state.level == :debug
      assert state.log_tool_calls == true
    end

    test "returns hooks list" do
      hooks = Logger.hooks()
      assert is_list(hooks)
      assert length(hooks) >= 3

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :startup in hook_names
      assert :agent_run_start in hook_names
      assert :agent_run_end in hook_names
    end
  end
end
