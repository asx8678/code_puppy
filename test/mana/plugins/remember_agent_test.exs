defmodule Mana.Plugins.RememberAgentTest do
  @moduledoc """
  Tests for Mana.Plugins.RememberAgent plugin.
  """

  use ExUnit.Case, async: false

  alias Mana.Plugins.RememberAgent

  setup do
    # Config.Store is needed for restore_agent / save_agent
    start_supervised!({Mana.Config.Store, []})
    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Plugin.Behaviour" do
      Code.ensure_loaded(RememberAgent)

      assert function_exported?(RememberAgent, :name, 0)
      assert function_exported?(RememberAgent, :init, 1)
      assert function_exported?(RememberAgent, :hooks, 0)
      assert function_exported?(RememberAgent, :terminate, 0)
    end

    test "name returns 'remember_agent'" do
      assert RememberAgent.name() == "remember_agent"
    end
  end

  describe "init/1" do
    test "returns ok with default config" do
      assert {:ok, state} = RememberAgent.init(%{})
      assert is_map(state)
    end

    test "sets default session_id" do
      assert {:ok, state} = RememberAgent.init(%{})
      assert state.session_id == "default"
    end

    test "accepts custom session_id" do
      assert {:ok, state} = RememberAgent.init(%{session_id: "custom-session"})
      assert state.session_id == "custom-session"
    end

    test "stores config" do
      config = %{session_id: "test", extra: "value"}
      assert {:ok, state} = RememberAgent.init(config)
      assert state.config == config
    end
  end

  describe "hooks/0" do
    test "returns startup and shutdown hooks" do
      hooks = RememberAgent.hooks()

      phases = Enum.map(hooks, fn {phase, _} -> phase end)

      assert :startup in phases
      assert :shutdown in phases
    end

    test "all hook functions are callable" do
      hooks = RememberAgent.hooks()

      for {_phase, func} <- hooks do
        assert is_function(func)
      end
    end
  end

  describe "restore_agent/0" do
    test "returns :ok when no last agent configured" do
      assert :ok = RememberAgent.restore_agent()
    end
  end

  describe "terminate/0" do
    test "terminate is a callable function" do
      assert function_exported?(RememberAgent, :terminate, 0)
    end
  end
end
