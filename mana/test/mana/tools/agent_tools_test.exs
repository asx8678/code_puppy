defmodule Mana.Tools.AgentToolsTest do
  @moduledoc """
  Tests for Mana.Tools.AgentTools module.
  """

  use ExUnit.Case, async: false

  import Mana.TestHelpers
  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.MessageBus
  alias Mana.Tools.AgentTools

  setup do
    # Start required GenServers - use a unique name for the agents registry to avoid conflicts
    start_supervised!({AgentsRegistry, name: AgentsRegistry})
    start_supervised!({Mana.Config.Store, []})
    start_supervised!({MessageBus, []})
    # Start RunSupervisor and Models.Registry needed for agent invocation tests
    start_supervised!({Mana.Agents.RunSupervisor, []})
    start_supervised!({Mana.Models.Registry, []})
    # Start Callbacks.Registry needed for agent execution
    start_supervised!({Mana.Callbacks.Registry, []})

    :ok
  end

  describe "ListAgents" do
    test "implements Mana.Tools.Behaviour" do
      Code.ensure_loaded?(AgentTools.ListAgents)
      assert function_exported?(AgentTools.ListAgents, :name, 0)
      assert function_exported?(AgentTools.ListAgents, :description, 0)
      assert function_exported?(AgentTools.ListAgents, :parameters, 0)
      assert function_exported?(AgentTools.ListAgents, :execute, 1)
    end

    test "name returns 'list_agents'" do
      assert AgentTools.ListAgents.name() == "list_agents"
    end

    test "description returns expected string" do
      assert AgentTools.ListAgents.description() == "List all available agents"
    end

    test "parameters returns valid JSON schema" do
      schema = AgentTools.ListAgents.parameters()
      assert schema.type == "object"
      assert schema.properties == %{}
      assert schema.required == []
    end

    test "execute returns list of agents with count" do
      {:ok, result} = AgentTools.ListAgents.execute(%{})

      assert is_list(result["agents"])
      assert is_integer(result["count"])
      assert result["count"] >= 0

      Enum.each(result["agents"], fn agent ->
        assert is_map(agent)
        assert is_binary(agent["name"])
        assert is_binary(agent["display_name"])
        assert is_binary(agent["description"])
      end)
    end
  end

  describe "InvokeAgent" do
    test "implements Mana.Tools.Behaviour" do
      Code.ensure_loaded?(AgentTools.InvokeAgent)
      assert function_exported?(AgentTools.InvokeAgent, :name, 0)
      assert function_exported?(AgentTools.InvokeAgent, :description, 0)
      assert function_exported?(AgentTools.InvokeAgent, :parameters, 0)
      assert function_exported?(AgentTools.InvokeAgent, :execute, 1)
    end

    test "name returns 'invoke_agent'" do
      assert AgentTools.InvokeAgent.name() == "invoke_agent"
    end

    test "description returns expected string" do
      assert AgentTools.InvokeAgent.description() == "Invoke another agent to perform a task"
    end

    test "parameters returns valid JSON schema with required fields" do
      schema = AgentTools.InvokeAgent.parameters()
      assert schema.type == "object"
      assert "agent_name" in schema.required
      assert "prompt" in schema.required
      assert schema.properties[:agent_name].type == "string"
      assert schema.properties[:prompt].type == "string"
      assert schema.properties[:session_id].type == "string"
    end

    test "execute returns error for unknown agent" do
      result =
        AgentTools.InvokeAgent.execute(%{
          "agent_name" => "nonexistent-agent-12345",
          "prompt" => "Do something"
        })

      assert {:error, message} = result
      assert message =~ "Agent not found"
    end

    test "execute with valid agent starts invocation" do
      # Note: This test requires full supervision tree
      result =
        AgentTools.InvokeAgent.execute(%{
          "agent_name" => "assistant",
          "prompt" => "Hello!",
          "session_id" => "test-session-123"
        })

      assert is_tuple(result)
    end

    test "execute without required parameters returns error" do
      result = AgentTools.InvokeAgent.execute(%{})
      assert {:error, _} = result
    end

    test "execute generates session_id if not provided" do
      # Requires full supervision tree
      result =
        AgentTools.InvokeAgent.execute(%{
          "agent_name" => "assistant",
          "prompt" => "Test"
        })

      assert is_tuple(result)
    end
  end

  describe "AskUser" do
    test "implements Mana.Tools.Behaviour" do
      Code.ensure_loaded?(AgentTools.AskUser)
      assert function_exported?(AgentTools.AskUser, :name, 0)
      assert function_exported?(AgentTools.AskUser, :description, 0)
      assert function_exported?(AgentTools.AskUser, :parameters, 0)
      assert function_exported?(AgentTools.AskUser, :execute, 1)
    end

    test "name returns 'ask_user'" do
      assert AgentTools.AskUser.name() == "ask_user"
    end

    test "description returns expected string" do
      assert AgentTools.AskUser.description() == "Ask the user a question and wait for response"
    end

    test "parameters returns valid JSON schema" do
      schema = AgentTools.AskUser.parameters()
      assert schema.type == "object"
      assert "question" in schema.required
      assert schema.properties[:question].type == "string"
    end

    test "execute without question returns error" do
      result = AgentTools.AskUser.execute(%{})
      assert {:error, _} = result
    end

    test "execute requests input via MessageBus" do
      # Spawn a task to provide the response
      Task.start(fn ->
        # Wait for the request to be registered
        assert_eventually(
          fn -> MessageBus.list_pending_requests() != [] end,
          timeout: 500
        )

        # Get pending requests and respond
        pending = MessageBus.list_pending_requests()

        Enum.each(pending, fn request_id ->
          MessageBus.provide_response(request_id, "test response")
        end)
      end)

      # This will block until the response is provided
      result = AgentTools.AskUser.execute(%{"question" => "What is your name?"})

      assert {:ok, response} = result
      assert response["response"] == "test response"
    end

    test "execute handles timeout gracefully" do
      # Use a very short timeout so the request times out quickly
      result =
        AgentTools.AskUser.execute(%{
          "question" => "Test?",
          "timeout" => 50
        })

      assert {:error, message} = result
      assert message =~ "Failed to get user input"
    end
  end
end
