defmodule CodePuppyControl.Tools.AgentCatalogueTest do
  @moduledoc """
  Tests for the AgentCatalogue module.

  Covers:
  - Agent registration
  - Agent listing
  - Agent info retrieval
  - Agent unregistration
  - Batch registration
  - Catalogue clearing
  """

  use ExUnit.Case

  alias CodePuppyControl.Tools.AgentCatalogue

  # Setup to ensure clean state for each test
  setup do
    # Clear the catalogue before each test
    :ok = AgentCatalogue.clear_catalogue()
    :ok
  end

  describe "register_agent/3" do
    test "registers a new agent" do
      assert :ok =
               AgentCatalogue.register_agent("elixir-dev", "Elixir Developer", "Elixir expert")
    end

    test "overwrites existing agent registration" do
      AgentCatalogue.register_agent("test-agent", "Old Name", "Old description")
      AgentCatalogue.register_agent("test-agent", "New Name", "New description")

      {:ok, info} = AgentCatalogue.get_agent_info("test-agent")
      assert info.display_name == "New Name"
      assert info.description == "New description"
    end
  end

  describe "list_agents/0" do
    test "returns empty list when no agents registered" do
      assert [] = AgentCatalogue.list_agents()
    end

    test "returns list of registered agents" do
      AgentCatalogue.register_agent("agent-1", "Agent One", "Description one")
      AgentCatalogue.register_agent("agent-2", "Agent Two", "Description two")

      agents = AgentCatalogue.list_agents()
      assert length(agents) == 2

      names = Enum.map(agents, fn a -> a.name end)
      assert "agent-1" in names
      assert "agent-2" in names
    end

    test "returns agents sorted by name" do
      AgentCatalogue.register_agent("charlie-agent", "Charlie", "Desc")
      AgentCatalogue.register_agent("alpha-agent", "Alpha", "Desc")
      AgentCatalogue.register_agent("bravo-agent", "Bravo", "Desc")

      agents = AgentCatalogue.list_agents()
      names = Enum.map(agents, fn a -> a.name end)
      assert names == ["alpha-agent", "bravo-agent", "charlie-agent"]
    end
  end

  describe "get_agent_info/1" do
    test "returns agent info for existing agent" do
      AgentCatalogue.register_agent("elixir-dev", "Elixir Developer", "Elixir/OTP expert")

      assert {:ok, info} = AgentCatalogue.get_agent_info("elixir-dev")
      assert info.name == "elixir-dev"
      assert info.display_name == "Elixir Developer"
      assert info.description == "Elixir/OTP expert"
    end

    test "returns :not_found for unregistered agent" do
      assert :not_found = AgentCatalogue.get_agent_info("non-existent")
    end
  end

  describe "unregister_agent/1" do
    test "removes a registered agent" do
      AgentCatalogue.register_agent("test-agent", "Test", "Description")
      assert :ok = AgentCatalogue.unregister_agent("test-agent")
      assert :not_found = AgentCatalogue.get_agent_info("test-agent")
    end

    test "succeeds even if agent doesn't exist" do
      assert :ok = AgentCatalogue.unregister_agent("never-registered")
    end
  end

  describe "clear_catalogue/0" do
    test "removes all registered agents" do
      AgentCatalogue.register_agent("agent-1", "Agent One", "Desc")
      AgentCatalogue.register_agent("agent-2", "Agent Two", "Desc")

      assert :ok = AgentCatalogue.clear_catalogue()

      assert [] = AgentCatalogue.list_agents()
      assert :not_found = AgentCatalogue.get_agent_info("agent-1")
      assert :not_found = AgentCatalogue.get_agent_info("agent-2")
    end
  end

  describe "register_agents/1" do
    test "registers multiple agents at once" do
      agents = [
        {"agent-1", "Agent One", "First agent"},
        {"agent-2", "Agent Two", "Second agent"},
        {"agent-3", "Agent Three", "Third agent"}
      ]

      assert {:ok, 3} = AgentCatalogue.register_agents(agents)

      assert length(AgentCatalogue.list_agents()) == 3
    end

    test "returns count of registered agents" do
      agents = [
        {"agent-a", "Agent A", "Desc A"},
        {"agent-b", "Agent B", "Desc B"}
      ]

      assert {:ok, 2} = AgentCatalogue.register_agents(agents)
    end

    test "handles empty list" do
      assert {:ok, 0} = AgentCatalogue.register_agents([])
    end
  end

  describe "AgentInfo struct" do
    alias CodePuppyControl.Tools.AgentCatalogue.AgentInfo

    test "can be created with new/3" do
      info = AgentInfo.new("my-agent", "My Agent", "Does things")
      assert info.name == "my-agent"
      assert info.display_name == "My Agent"
      assert info.description == "Does things"
    end

    test "is JSON encodable" do
      info = AgentInfo.new("test-agent", "Test", "Description")
      json = Jason.encode!(info)
      assert is_binary(json)
      assert json =~ "test-agent"
      assert json =~ "Test"
      assert json =~ "Description"
    end
  end
end
