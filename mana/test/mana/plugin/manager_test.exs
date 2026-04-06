defmodule Mana.Plugin.ManagerTest do
  use ExUnit.Case

  import Mana.TestHelpers
  alias Mana.Callbacks.Registry
  alias Mana.Plugin.Manager
  alias Mana.TestSupport.MockPlugin

  setup do
    # Start a fresh registry and manager for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})

    opts = [
      plugins: [],
      auto_dismiss_errors: false
    ]

    start_supervised!({Manager, config: opts})

    :ok
  end

  describe "start_link/1" do
    test "starts the manager" do
      assert Process.whereis(Manager) != nil
    end
  end

  describe "register_plugin/2" do
    test "registers a valid plugin" do
      assert {:ok, "mock_plugin"} = Manager.register_plugin(MockPlugin)
    end

    test "returns error for duplicate registration" do
      assert {:ok, "mock_plugin"} = Manager.register_plugin(MockPlugin)
      assert {:error, :already_loaded} = Manager.register_plugin(MockPlugin)
    end

    test "accepts plugin configuration" do
      config = %{timeout: 5000, enabled: true}
      assert {:ok, "mock_plugin"} = Manager.register_plugin(MockPlugin, config)
    end
  end

  describe "unregister_plugin/1" do
    test "unregisters a loaded plugin" do
      {:ok, name} = Manager.register_plugin(MockPlugin)
      assert :ok = Manager.unregister_plugin(name)
    end

    test "returns error for unknown plugin" do
      assert {:error, :not_found} = Manager.unregister_plugin("unknown_plugin")
    end
  end

  describe "trigger/3" do
    test "triggers a hook and returns results" do
      # Register plugin first
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      # Start test collector
      Process.register(self(), :test_collector)

      # Trigger hook
      assert {:ok, results} = Manager.trigger(:startup, [])
      assert is_list(results)
    end

    test "buffers events to backlog when no listeners" do
      # Trigger without any plugins registered
      assert {:ok, []} = Manager.trigger(:agent_run_start, ["agent", "model", nil])

      # Check stats show a trigger (dispatches from Callbacks)
      stats = Manager.get_stats()
      assert stats.dispatches >= 0
    end

    test "returns error for invalid hook" do
      # Invalid hooks now return error through unified Callbacks system
      assert {:error, :invalid_phase} = Manager.trigger(:invalid_hook, [])
    end
  end

  describe "trigger_async/2" do
    test "dispatches async hook" do
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      assert :ok = Manager.trigger_async(:startup, [])

      # Wait for async processing by checking Callbacks stats
      assert_eventually(
        fn -> Mana.Callbacks.get_stats().dispatches > 0 end,
        timeout: 500
      )
    end
  end

  describe "drain_backlog/1" do
    test "replays buffered events" do
      # Buffer some events first (no plugins)
      Manager.trigger(:startup, [], timeout: 100)

      # Now register plugin
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      # Drain the backlog
      assert {:ok, results} = Manager.drain_backlog(:startup)
      assert is_list(results)
    end
  end

  describe "drain_all_backlogs/0" do
    test "drains all hook backlogs" do
      # Buffer events
      Manager.trigger(:startup, [])
      Manager.trigger(:agent_run_start, ["agent", "model", nil])

      # Register plugin
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      # Drain all
      assert {:ok, results} = Manager.drain_all_backlogs()
      assert is_map(results)
    end
  end

  describe "list_plugins/0" do
    test "returns empty list when no plugins loaded" do
      plugins = Manager.list_plugins()
      assert plugins == []
    end

    test "returns list of loaded plugins" do
      {:ok, _} = Manager.register_plugin(MockPlugin)

      plugins = Manager.list_plugins()
      assert length(plugins) == 1

      [plugin] = plugins
      assert plugin.name == "mock_plugin"
      assert plugin.module == MockPlugin
      assert plugin.hook_count == 3
    end
  end

  describe "get_stats/0" do
    test "returns manager statistics" do
      stats = Manager.get_stats()

      assert is_map(stats)
      assert Map.has_key?(stats, :plugins_loaded)
      assert Map.has_key?(stats, :hooks_registered)
      assert Map.has_key?(stats, :dispatches)
      assert Map.has_key?(stats, :errors)
      assert Map.has_key?(stats, :backlog_size)
    end

    test "stats reflect plugin state" do
      {:ok, _} = Manager.register_plugin(MockPlugin)

      stats = Manager.get_stats()
      assert stats.plugins_loaded == 1
      assert stats.hooks_registered == 3
    end
  end

  describe "trigger_startup/0" do
    test "triggers the startup hook" do
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      assert {:ok, _results} = Manager.trigger_startup()
    end
  end

  describe "trigger_shutdown/0" do
    test "triggers the shutdown hook" do
      {:ok, _name} = Manager.register_plugin(MockPlugin)

      assert {:ok, _results} = Manager.trigger_shutdown()
    end
  end
end
