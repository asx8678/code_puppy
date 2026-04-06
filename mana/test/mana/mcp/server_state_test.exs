defmodule Mana.MCP.ServerStateTest do
  @moduledoc """
  Tests for Mana.MCP.ServerState module.
  """

  use ExUnit.Case, async: true

  alias Mana.MCP.ServerState

  describe "all/0" do
    test "returns all valid states" do
      states = ServerState.all()

      assert :stopped in states
      assert :starting in states
      assert :running in states
      assert :stopping in states
      assert :error in states
      assert :quarantined in states
      assert length(states) == 6
    end
  end

  describe "valid?/1" do
    test "returns true for all valid states" do
      for state <- ServerState.all() do
        assert ServerState.valid?(state), "Expected #{state} to be valid"
      end
    end

    test "returns false for invalid atoms" do
      refute ServerState.valid?(:invalid)
      refute ServerState.valid?(:restarting)
      refute ServerState.valid?(:paused)
    end

    test "returns false for non-atoms" do
      refute ServerState.valid?("stopped")
      refute ServerState.valid?(42)
      refute ServerState.valid?(nil)
      refute ServerState.valid?(%{})
    end
  end

  describe "transitions_from/1" do
    test "stopped can transition to starting and error" do
      transitions = ServerState.transitions_from(:stopped)
      assert :starting in transitions
      assert :error in transitions
      assert length(transitions) == 2
    end

    test "starting can transition to running, error, and stopped" do
      transitions = ServerState.transitions_from(:starting)
      assert :running in transitions
      assert :error in transitions
      assert :stopped in transitions
      assert length(transitions) == 3
    end

    test "running can transition to stopping, error, and quarantined" do
      transitions = ServerState.transitions_from(:running)
      assert :stopping in transitions
      assert :error in transitions
      assert :quarantined in transitions
      assert length(transitions) == 3
    end

    test "stopping can transition to stopped and error" do
      transitions = ServerState.transitions_from(:stopping)
      assert :stopped in transitions
      assert :error in transitions
      assert length(transitions) == 2
    end

    test "error can transition to stopped" do
      transitions = ServerState.transitions_from(:error)
      assert :stopped in transitions
      assert length(transitions) == 1
    end

    test "quarantined can transition to stopped and running" do
      transitions = ServerState.transitions_from(:quarantined)
      assert :stopped in transitions
      assert :running in transitions
      assert length(transitions) == 2
    end
  end

  describe "can_transition?/2" do
    test "allows valid transitions" do
      assert ServerState.can_transition?(:stopped, :starting)
      assert ServerState.can_transition?(:starting, :running)
      assert ServerState.can_transition?(:running, :stopping)
      assert ServerState.can_transition?(:stopping, :stopped)
      assert ServerState.can_transition?(:error, :stopped)
      assert ServerState.can_transition?(:quarantined, :running)
    end

    test "rejects invalid transitions" do
      refute ServerState.can_transition?(:stopped, :running)
      refute ServerState.can_transition?(:stopped, :stopping)
      refute ServerState.can_transition?(:running, :stopped)
      refute ServerState.can_transition?(:error, :running)
      refute ServerState.can_transition?(:error, :quarantined)
    end

    test "rejects transitions from invalid states" do
      refute ServerState.can_transition?(:invalid, :stopped)
      refute ServerState.can_transition?(:stopped, :invalid)
    end
  end

  describe "description/1" do
    test "returns human-readable description for each state" do
      for state <- ServerState.all() do
        desc = ServerState.description(state)
        assert is_binary(desc)
        assert String.length(desc) > 0
      end
    end

    test "returns meaningful descriptions" do
      assert ServerState.description(:stopped) =~ "not running"
      assert ServerState.description(:starting) =~ "initializing"
      assert ServerState.description(:running) =~ "active"
      assert ServerState.description(:stopping) =~ "shutting down"
      assert ServerState.description(:error) =~ "error"
      assert ServerState.description(:quarantined) =~ "disabled"
    end
  end

  describe "active?/1" do
    test "only running state is active" do
      assert ServerState.active?(:running)
      refute ServerState.active?(:stopped)
      refute ServerState.active?(:starting)
      refute ServerState.active?(:stopping)
      refute ServerState.active?(:error)
      refute ServerState.active?(:quarantined)
    end
  end

  describe "terminal?/1" do
    test "only error state is terminal" do
      assert ServerState.terminal?(:error)
      refute ServerState.terminal?(:stopped)
      refute ServerState.terminal?(:starting)
      refute ServerState.terminal?(:running)
      refute ServerState.terminal?(:stopping)
      refute ServerState.terminal?(:quarantined)
    end
  end

  describe "healthy?/1" do
    test "running and starting are healthy" do
      assert ServerState.healthy?(:running)
      assert ServerState.healthy?(:starting)
    end

    test "all other states are not healthy" do
      refute ServerState.healthy?(:stopped)
      refute ServerState.healthy?(:stopping)
      refute ServerState.healthy?(:error)
      refute ServerState.healthy?(:quarantined)
    end
  end
end
