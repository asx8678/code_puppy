defmodule CodePuppyControl.Tools.CpAgentOps do
  @moduledoc """
  `:cp_`-prefixed Tool-behaviour wrappers for agent operations.

  These modules expose agent invocation and listing through the Tool
  behaviour so the CodePuppy agent can call `cp_invoke_agent` and
  `cp_list_agents` via the tool registry.

  Refs: code_puppy-4s8.7 (Phase C CI gate)
  """

  defmodule CpInvokeAgent do
    @moduledoc """
    Invokes a sub-agent for a specialized task.

    Delegates to `CodePuppyControl.Workers.AgentInvocation`.
    """

    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_invoke_agent

    @impl true
    def description do
      "Invoke a specialized sub-agent to handle a focused task. " <>
        "Use cp_list_agents to see available agents."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "agent_name" => %{
            "type" => "string",
            "description" => "Name of the agent to invoke"
          },
          "prompt" => %{
            "type" => "string",
            "description" => "Task description for the sub-agent"
          }
        },
        "required" => ["agent_name", "prompt"]
      }
    end

    @impl true
    def invoke(args, context) do
      agent_name = Map.get(args, "agent_name", "")
      prompt = Map.get(args, "prompt", "")
      session_id = Map.get(context, :agent_session_id) || Map.get(context, "agent_session_id")

      case CodePuppyControl.Tools.AgentCatalogue.get_agent_module(agent_name) do
        {:ok, _module} ->
          # Start an agent run via Run.Manager
          config = %{"prompt" => prompt}

          case CodePuppyControl.Run.Manager.start_run(session_id, agent_name, config: config) do
            {:ok, run_id} ->
              {:ok, %{run_id: run_id, agent_name: agent_name, status: :started}}

            {:error, reason} ->
              {:error, "Failed to start agent run: #{inspect(reason)}"}
          end

        {:error, :no_module} ->
          {:error, "Agent found but has no module: #{agent_name}"}

        :not_found ->
          {:error, "Agent not found: #{agent_name}"}
      end
    end
  end

  defmodule CpListAgents do
    @moduledoc """
    Lists available sub-agents.

    Delegates to `CodePuppyControl.Tools.AgentCatalogue.list_agents/0`.
    """

    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_list_agents

    @impl true
    def description do
      "List all available sub-agents that can be invoked " <>
        "for specialized tasks."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{},
        "required" => []
      }
    end

    @impl true
    def invoke(_args, _context) do
      agents = CodePuppyControl.Tools.AgentCatalogue.list_agents()

      {:ok,
       %{
         agents:
           Enum.map(agents, fn info ->
             %{
               name: info.name,
               display_name: info.display_name,
               description: info.description
             }
           end),
         count: length(agents)
       }}
    end
  end
end
