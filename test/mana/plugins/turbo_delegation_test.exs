defmodule Mana.Plugins.TurboDelegationTest do
  @moduledoc """
  Tests for Mana.Plugins.TurboDelegation plugin.
  """

  use ExUnit.Case, async: true

  alias Mana.Plugins.TurboDelegation

  describe "behaviour implementation" do
    test "implements Mana.Plugin.Behaviour" do
      Code.ensure_loaded(TurboDelegation)

      assert function_exported?(TurboDelegation, :name, 0)
      assert function_exported?(TurboDelegation, :init, 1)
      assert function_exported?(TurboDelegation, :hooks, 0)
      assert function_exported?(TurboDelegation, :terminate, 0)
    end

    test "name returns 'turbo_delegation'" do
      assert TurboDelegation.name() == "turbo_delegation"
    end
  end

  describe "init/1" do
    test "returns ok with config" do
      assert {:ok, state} = TurboDelegation.init(%{})
      assert is_map(state)
    end

    test "stores config in state" do
      config = %{"some_key" => "some_value"}
      assert {:ok, state} = TurboDelegation.init(config)
      assert state.config == config
    end
  end

  describe "hooks/0" do
    test "returns load_prompt hook" do
      hooks = TurboDelegation.hooks()

      phases = Enum.map(hooks, fn {phase, _} -> phase end)

      assert :load_prompt in phases
    end

    test "hook function is callable" do
      [{_phase, func} | _] = TurboDelegation.hooks()
      assert is_function(func)
    end
  end

  describe "inject_turbo_guidance/0" do
    test "returns guidance string" do
      guidance = TurboDelegation.inject_turbo_guidance()

      assert is_binary(guidance)
      assert guidance =~ "Turbo Executor"
      assert guidance =~ "turbo-executor"
      assert guidance =~ "batch"
    end

    test "mentions delegation threshold" do
      guidance = TurboDelegation.inject_turbo_guidance()
      # Should mention the 5-file threshold
      assert guidance =~ "5"
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert TurboDelegation.terminate() == :ok
    end
  end
end
