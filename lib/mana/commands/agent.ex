defmodule Mana.Commands.Agent do
  @moduledoc """
  Agent switching and management commands.

  Provides commands for listing, setting, and querying active agents.

  ## Commands

  - `/agent list` - List all available agents
  - `/agent set <name>` - Set the agent for the current session
  - `/agent current` - Show the current agent

  ## Examples

      /agent list
      # Shows: Available agents: planner, husky, code-reviewer, ...

      /agent set husky
      # Shows: Agent set to: husky

      /agent current
      # Shows: Current agent: husky
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.Session.Store, as: SessionStore

  @impl true
  def name, do: "/agent"

  @impl true
  def description, do: "Manage AI agents"

  @impl true
  def usage, do: "/agent [list|set <name>|current]"

  @impl true
  def execute(["list"], _context) do
    agents = AgentsRegistry.list_agents()

    if agents == [] do
      {:ok, "No agents available."}
    else
      formatted =
        Enum.map_join(agents, "\n", fn agent ->
          name = Map.get(agent, :name, "unknown")
          description = Map.get(agent, :description, "")
          "  #{name} - #{description}"
        end)

      {:ok, "Available agents:\n#{formatted}"}
    end
  end

  def execute(["set", name], context) do
    session_id = get_session_id(context)

    case AgentsRegistry.set_agent(session_id, name) do
      :ok ->
        {:ok, "Agent set to: #{name}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  def execute(["current"], context) do
    session_id = get_session_id(context)

    case AgentsRegistry.current_agent(session_id) do
      nil ->
        {:ok, "No agent set (using default)"}

      agent ->
        name = Map.get(agent, "name") || Map.get(agent, :name, "unknown")
        {:ok, "Current agent: #{name}"}
    end
  end

  def execute([], _context) do
    {:ok, "Usage: #{usage()}"}
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end

  defp get_session_id(context) do
    Map.get(context, :session_id) || SessionStore.active_session() || "default"
  end
end
