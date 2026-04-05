defmodule Mana.Commands.AgentTest do
  @moduledoc """
  Tests for Mana.Commands.Agent module.
  """

  use ExUnit.Case, async: false

  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.Commands.Agent
  alias Mana.Session.Store, as: SessionStore

  setup do
    # Start required GenServers with default names
    start_supervised!({AgentsRegistry, []})
    start_supervised!({SessionStore, []})

    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded?(Agent)
      assert function_exported?(Agent, :name, 0)
      assert function_exported?(Agent, :description, 0)
      assert function_exported?(Agent, :usage, 0)
      assert function_exported?(Agent, :execute, 2)
    end

    test "name returns '/agent'" do
      assert Agent.name() == "/agent"
    end

    test "description returns expected string" do
      assert Agent.description() == "Manage AI agents"
    end

    test "usage returns expected string" do
      assert Agent.usage() == "/agent [list|set <name>|current]"
    end
  end

  describe "execute/2 - list" do
    test "returns list of available agents" do
      assert {:ok, result} = Agent.execute(["list"], %{})

      # Should have some agents (at least the default assistant)
      assert result =~ "Available agents:"
    end
  end

  describe "execute/2 - set" do
    test "sets agent for session" do
      # Create a session
      session_id = SessionStore.create_session()

      assert {:ok, result} = Agent.execute(["set", "assistant"], %{session_id: session_id})
      assert result == "Agent set to: assistant"
    end

    test "returns error for unknown agent" do
      session_id = SessionStore.create_session()

      assert {:error, message} =
               Agent.execute(["set", "nonexistent-agent-12345"], %{
                 session_id: session_id
               })

      assert message =~ "Agent not found"
    end
  end

  describe "execute/2 - current" do
    test "shows current agent when set" do
      # Create a session and set an agent
      session_id = SessionStore.create_session()
      AgentsRegistry.set_agent(session_id, "assistant")

      assert {:ok, result} = Agent.execute(["current"], %{session_id: session_id})
      assert result == "Current agent: assistant"
    end

    test "shows default agent when session is new" do
      # Create a new session without setting an agent explicitly
      # The registry defaults to assistant
      session_id = SessionStore.create_session()

      assert {:ok, result} = Agent.execute(["current"], %{session_id: session_id})
      assert result == "Current agent: assistant"
    end
  end

  describe "execute/2 - usage" do
    test "returns usage when called with no args" do
      assert {:ok, result} = Agent.execute([], %{})
      assert result == "Usage: #{Agent.usage()}"
    end

    test "returns usage when called with invalid args" do
      assert {:ok, result} = Agent.execute(["invalid"], %{})
      assert result == "Usage: #{Agent.usage()}"
    end
  end
end
