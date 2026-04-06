defmodule Mana.Agents.Registry do
  @moduledoc """
  GenServer for agent discovery and session management.

  Maintains a registry of all available agents (from JSON configs and
  Elixir modules), and tracks which agent is active for each session.

  ## Agent Discovery

  The registry discovers agents from:
  1. JSON configuration files (via `JsonLoader.discover/0`)
  2. Elixir modules that implement the `Mana.Agent` behaviour

  ## Session Management

  Each session can have an active agent assigned. Sessions default to
  the `"assistant"` agent if not explicitly set.

  ## Usage

      # Start the registry
      {:ok, _pid} = Mana.Agents.Registry.start_link()

      # List all available agents
      agents = Mana.Agents.Registry.list_agents()

      # Get a specific agent by name
      agent = Mana.Agents.Registry.get_agent("husky")

      # Set agent for a session
      :ok = Mana.Agents.Registry.set_agent("session-123", "husky")

      # Get current agent for a session
      agent = Mana.Agents.Registry.current_agent("session-123")

      # Refresh agent discovery
      :ok = Mana.Agents.Registry.refresh()

  """

  use GenServer

  require Logger

  alias Mana.Agents.JsonLoader

  defstruct agents: %{}, sessions: %{}, last_refresh: nil

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the Agents Registry GenServer.

  ## Options

    - `:name` - The name to register the process under (default: `__MODULE__`)

  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  List all discovered agents.

  Returns a list of agent summaries with `:name`, `:display_name`,
  and `:description` keys.

  """
  @spec list_agents() :: [map()]
  def list_agents do
    GenServer.call(__MODULE__, :list_agents)
  end

  @doc """
  Get an agent by name.

  Returns the full agent configuration map, or `nil` if not found.

  """
  @spec get_agent(String.t()) :: map() | nil
  def get_agent(name) do
    GenServer.call(__MODULE__, {:get_agent, name})
  end

  @doc """
  Get the current agent for a session.

  Returns the full agent configuration map for the agent assigned
  to the given session. Defaults to the `"assistant"` agent if no
  agent has been explicitly set for the session.

  """
  @spec current_agent(String.t()) :: map() | nil
  def current_agent(session_id) do
    GenServer.call(__MODULE__, {:current_agent, session_id})
  end

  @doc """
  Set the agent for a session.

  ## Returns

    - `:ok` - Agent was set successfully
    - `{:error, String.t()}` - Agent not found

  """
  @spec set_agent(String.t(), String.t()) :: :ok | {:error, String.t()}
  def set_agent(session_id, agent_name) do
    GenServer.call(__MODULE__, {:set_agent, session_id, agent_name})
  end

  @doc """
  Refresh agent discovery.

  Re-runs agent discovery from all sources (JSON files and modules).

  """
  @spec refresh() :: :ok
  def refresh do
    GenServer.call(__MODULE__, :refresh)
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    agents = discover_all()
    {:ok, %__MODULE__{agents: agents, last_refresh: DateTime.utc_now()}}
  end

  @impl true
  def handle_call(:list_agents, _from, state) do
    agent_list =
      Enum.map(state.agents, fn {name, config} ->
        %{
          name: name,
          display_name: Map.get(config, "display_name") || Map.get(config, :display_name, name),
          description: Map.get(config, "description") || Map.get(config, :description, "")
        }
      end)

    {:reply, agent_list, state}
  end

  @impl true
  def handle_call({:get_agent, name}, _from, state) do
    {:reply, Map.get(state.agents, name), state}
  end

  @impl true
  def handle_call({:current_agent, session_id}, _from, state) do
    agent_name = Map.get(state.sessions, session_id, "assistant")
    agent = Map.get(state.agents, agent_name)
    {:reply, agent, state}
  end

  @impl true
  def handle_call({:set_agent, session_id, agent_name}, _from, state) do
    if Map.has_key?(state.agents, agent_name) do
      new_sessions = Map.put(state.sessions, session_id, agent_name)
      Logger.info("Session #{session_id}: agent set to #{agent_name}")
      {:reply, :ok, %{state | sessions: new_sessions}}
    else
      {:reply, {:error, "Agent not found: #{agent_name}"}, state}
    end
  end

  @impl true
  def handle_call(:refresh, _from, state) do
    agents = discover_all()
    Logger.info("Agent registry refreshed: #{map_size(agents)} agents discovered")
    {:reply, :ok, %{state | agents: agents, last_refresh: DateTime.utc_now()}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  # Discover all agents from JSON configs and Elixir modules
  defp discover_all do
    # Discover JSON agents
    json_agents = discover_json_agents()

    # Discover module agents (any module using Mana.Agent)
    module_agents = discover_module_agents()

    # Merge (JSON overrides module)
    all = module_agents ++ json_agents

    Map.new(all, fn agent ->
      name = agent["name"] || agent.name
      {name, agent}
    end)
  end

  # Discover agents from JSON configuration files
  defp discover_json_agents do
    JsonLoader.discover()
  end

  # Discover agent modules from the application configuration
  defp discover_module_agents do
    case Application.get_env(:mana, :agent_modules, []) do
      modules when is_list(modules) ->
        Enum.flat_map(modules, fn mod ->
          if Code.ensure_loaded?(mod) and function_exported?(mod, :name, 0) do
            [
              %{
                "name" => mod.name(),
                "display_name" => mod.display_name(),
                "description" => mod.description(),
                "system_prompt" => mod.system_prompt(),
                "available_tools" => mod.available_tools(),
                "_source" => "module:#{inspect(mod)}"
              }
            ]
          else
            Logger.warning("Agent module #{inspect(mod)} is not properly loaded")
            []
          end
        end)

      _ ->
        []
    end
  end
end
