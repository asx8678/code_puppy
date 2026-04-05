defmodule Mana.Agents.RegistryTest do
  @moduledoc """
  Tests for Mana.Agents.Registry GenServer.
  """

  use ExUnit.Case, async: false

  import Mana.TestHelpers
  alias Mana.Agents.Registry

  setup do
    # Start the registry for each test
    {:ok, pid} = Registry.start_link(name: __MODULE__)

    on_exit(fn ->
      if Process.alive?(pid), do: GenServer.stop(pid)
    end)

    {:ok, registry: pid}
  end

  describe "start_link/1" do
    test "starts with discovered agents" do
      {:ok, pid} = Registry.start_link(name: :test_registry_init)

      # Registry should have discovered agents on init
      agents = GenServer.call(pid, :list_agents)
      assert is_list(agents)
      assert agents != []

      GenServer.stop(pid)
    end
  end

  describe "list_agents/0" do
    test "returns list of agent summaries", %{registry: pid} do
      agents = GenServer.call(pid, :list_agents)

      assert is_list(agents)
      assert agents != []

      # Each agent should have the summary fields
      Enum.each(agents, fn agent ->
        assert is_atom(agent.name) or is_binary(agent.name)
        assert is_binary(agent.display_name)
        assert is_binary(agent.description)
      end)
    end

    test "includes discovered JSON agents", %{registry: pid} do
      agents = GenServer.call(pid, :list_agents)
      names = Enum.map(agents, &to_string(&1.name))

      assert "assistant" in names
    end
  end

  describe "get_agent/1" do
    test "returns agent by name", %{registry: pid} do
      agent = GenServer.call(pid, {:get_agent, "assistant"})

      assert agent != nil
      assert agent["name"] == "assistant"
    end

    test "returns nil for unknown agent", %{registry: pid} do
      agent = GenServer.call(pid, {:get_agent, "nonexistent-agent-12345"})
      assert agent == nil
    end
  end

  describe "current_agent/1" do
    test "returns default assistant agent for new session", %{registry: pid} do
      agent = GenServer.call(pid, {:current_agent, "new-session-123"})

      assert agent != nil
      assert agent["name"] == "assistant"
    end

    test "returns nil if default agent not found", %{registry: pid} do
      # This shouldn't happen in practice, but test the fallback
      state = :sys.get_state(pid)
      state_without_assistant = %{state | agents: Map.delete(state.agents, "assistant")}
      :sys.replace_state(pid, fn _ -> state_without_assistant end)

      agent = GenServer.call(pid, {:current_agent, "another-session"})
      assert agent == nil
    end
  end

  describe "set_agent/2" do
    test "sets agent for a session", %{registry: pid} do
      result = GenServer.call(pid, {:set_agent, "session-1", "husky"})
      assert result == :ok

      # Verify the agent was set
      agent = GenServer.call(pid, {:current_agent, "session-1"})
      assert agent["name"] == "husky"
    end

    test "returns error for unknown agent", %{registry: pid} do
      result = GenServer.call(pid, {:set_agent, "session-2", "nonexistent-agent-xyz"})
      assert result == {:error, "Agent not found: nonexistent-agent-xyz"}
    end

    test "can change agent for existing session", %{registry: pid} do
      # Set initial agent
      :ok = GenServer.call(pid, {:set_agent, "session-3", "assistant"})

      # Change to different agent
      :ok = GenServer.call(pid, {:set_agent, "session-3", "planner"})

      agent = GenServer.call(pid, {:current_agent, "session-3"})
      assert agent["name"] == "planner"
    end
  end

  describe "refresh/0" do
    test "refreshes agent discovery", %{registry: pid} do
      result = GenServer.call(pid, :refresh)
      assert result == :ok

      # Should still have agents after refresh
      agents = GenServer.call(pid, :list_agents)
      assert is_list(agents)
      assert agents != []
    end

    test "updates last_refresh timestamp", %{registry: pid} do
      old_state = :sys.get_state(pid)
      old_time = old_state.last_refresh

      :ok = GenServer.call(pid, :refresh)

      assert_eventually(
        fn ->
          new_state = :sys.get_state(pid)
          DateTime.compare(new_state.last_refresh, old_time) == :gt
        end,
        timeout: 100
      )
    end
  end

  describe "state management" do
    test "tracks sessions separately", %{registry: pid} do
      # Set different agents for different sessions
      :ok = GenServer.call(pid, {:set_agent, "session-a", "assistant"})
      :ok = GenServer.call(pid, {:set_agent, "session-b", "husky"})

      # Each session should have its own agent
      agent_a = GenServer.call(pid, {:current_agent, "session-a"})
      agent_b = GenServer.call(pid, {:current_agent, "session-b"})

      assert agent_a["name"] == "assistant"
      assert agent_b["name"] == "husky"
    end
  end
end
