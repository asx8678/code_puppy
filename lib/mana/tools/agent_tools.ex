defmodule Mana.Tools.AgentTools do
  @moduledoc """
  Agent interaction tools for invoking other agents and user interaction.

  This module provides three tools:
  - `ListAgents` - List all available agents in the system
  - `InvokeAgent` - Invoke another agent to perform a task
  - `AskUser` - Ask the user a question and wait for response

  ## Usage

      # List available agents
      Mana.Tools.AgentTools.ListAgents.execute(%{})
      # => {:ok, %{"agents" => [...], "count" => 5}}

      # Invoke an agent
      Mana.Tools.AgentTools.InvokeAgent.execute(%{
        "agent_name" => "planner",
        "prompt" => "Create a plan for the project",
        "session_id" => "optional-session-id"
      })

      # Ask the user
      Mana.Tools.AgentTools.AskUser.execute(%{"question" => "What is your name?"})
  """

  alias Mana.Agent.Server, as: AgentServer
  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.Agents.RunSupervisor
  alias Mana.MessageBus

  defmodule ListAgents do
    @moduledoc "Tool to list all available agents"
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "list_agents"

    @impl true
    def description, do: "List all available agents"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{},
        required: []
      }
    end

    @impl true
    def execute(_args) do
      agents = AgentsRegistry.list_agents()

      agent_data =
        Enum.map(agents, fn agent ->
          %{
            "name" => agent.name,
            "display_name" => Map.get(agent, :display_name, agent.name),
            "description" => Map.get(agent, :description, "")
          }
        end)

      {:ok, %{"agents" => agent_data, "count" => length(agent_data)}}
    end
  end

  defmodule InvokeAgent do
    @moduledoc "Tool to invoke another agent to perform a task"
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "invoke_agent"

    @impl true
    def description, do: "Invoke another agent to perform a task"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          "agent_name" => %{
            type: "string",
            description: "Name of agent to invoke"
          },
          "prompt" => %{
            type: "string",
            description: "Task prompt for the agent"
          },
          "session_id" => %{
            type: "string",
            description: "Session ID for the agent run (optional)"
          }
        },
        required: ["agent_name", "prompt"]
      }
    end

    @impl true
    def execute(%{"agent_name" => name, "prompt" => prompt} = args) do
      session_id = Map.get(args, "session_id", generate_session_id())

      with {:ok, agent} <- fetch_agent(name),
           {:ok, pid} <- start_agent_server(agent),
           {:ok, _run_pid} <- start_run(pid, prompt, session_id) do
        {:ok, %{"invoked" => name, "session_id" => session_id}}
      else
        {:error, reason} -> {:error, reason}
      end
    end

    def execute(_args) do
      {:error, "Missing required parameters: agent_name, prompt"}
    end

    defp fetch_agent(name) do
      case AgentsRegistry.get_agent(name) do
        nil -> {:error, "Agent not found: #{name}"}
        agent -> {:ok, agent}
      end
    end

    defp start_agent_server(agent) do
      case AgentServer.start_link(agent_def: agent) do
        {:ok, pid} -> {:ok, pid}
        {:error, reason} -> {:error, "Failed to start agent: #{inspect(reason)}"}
      end
    end

    defp start_run(pid, prompt, session_id) do
      case RunSupervisor.start_run(pid, prompt, session_id: session_id) do
        {:ok, run_pid} -> {:ok, run_pid}
        {:error, reason} -> {:error, "Failed to invoke agent: #{inspect(reason)}"}
      end
    end

    defp generate_session_id do
      timestamp = System.system_time(:millisecond)
      random = :rand.uniform(999_999)
      "session_#{timestamp}_#{random}"
    end
  end

  defmodule AskUser do
    @moduledoc "Tool to ask the user a question and wait for response"
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "ask_user"

    @impl true
    def description, do: "Ask the user a question and wait for response"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          "question" => %{
            type: "string",
            description: "Question to ask the user"
          }
        },
        required: ["question"]
      }
    end

    @impl true
    def execute(%{"question" => question}) do
      case MessageBus.request_input(question) do
        {:ok, response} ->
          {:ok, %{"response" => response}}

        {:error, reason} ->
          {:error, "Failed to get user input: #{inspect(reason)}"}
      end
    end

    def execute(_args) do
      {:error, "Missing required parameter: question"}
    end
  end
end
