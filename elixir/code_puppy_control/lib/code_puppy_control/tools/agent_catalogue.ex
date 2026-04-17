defmodule CodePuppyControl.Tools.AgentCatalogue do
  @moduledoc """
  Agent catalogue service for CodePuppy.

  This module maintains a registry of available agents with their metadata:
  - name: The internal agent identifier (e.g., "elixir-dev")
  - display_name: Human-readable name (e.g., "Elixir Developer")
  - description: What this agent does

  ## Purpose

  - Provides discovery of available sub-agents
  - Enables introspection of agent capabilities
  - Integrates with the JSON-RPC transport for agent listing

  ## Storage

  Uses ETS for fast concurrent reads and GenServer-coordinated writes.
  The ETS table is `:set` type with `agent_name -> agent_info` mapping.

  ## API

  - `register_agent/3` - Register an agent with the catalogue
  - `list_agents/0` - List all registered agents
  - `get_agent_info/1` - Get info about a specific agent
  - `unregister_agent/1` - Remove an agent from the catalogue
  - `clear_catalogue/0` - Clear all registered agents

  ## RPC Methods

  The stdio service exposes these JSON-RPC methods:
  - `agent.list` - List all available agents
  - `agent.get_info` - Get info about a specific agent
  """

  use GenServer

  require Logger

  alias __MODULE__.AgentInfo

  @table :agent_catalogue

  @typedoc "Agent information record"
  @type agent_info :: %AgentInfo{
          name: String.t(),
          display_name: String.t(),
          description: String.t()
        }

  # ============================================================================
  # AgentInfo Struct
  # ============================================================================

  defmodule AgentInfo do
    @moduledoc """
    Information about an available agent.

    Fields:
    - `name`: The internal agent identifier (e.g., "elixir-dev")
    - `display_name`: Human-readable name (e.g., "Elixir Developer")
    - `description`: What this agent does
    """

    @derive Jason.Encoder
    defstruct [:name, :display_name, :description]

    @type t :: %__MODULE__{
            name: String.t(),
            display_name: String.t(),
            description: String.t()
          }

    @doc """
    Creates a new AgentInfo struct.
    """
    @spec new(String.t(), String.t(), String.t()) :: t()
    def new(name, display_name, description) do
      %__MODULE__{
        name: name,
        display_name: display_name,
        description: description
      }
    end
  end

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the AgentCatalogue GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Registers an agent with the catalogue.

  ## Parameters
  - `name`: The internal agent identifier (e.g., "elixir-dev")
  - `display_name`: Human-readable name (e.g., "Elixir Developer")
  - `description`: What this agent does

  ## Returns
  - `:ok` on success

  ## Examples
      iex> AgentCatalogue.register_agent("elixir-dev", "Elixir Developer", "Elixir/OTP expert")
      :ok
  """
  @spec register_agent(String.t(), String.t(), String.t()) :: :ok
  def register_agent(name, display_name, description)
      when is_binary(name) and is_binary(display_name) and is_binary(description) do
    GenServer.call(__MODULE__, {:register, name, display_name, description})
  end

  @doc """
  Lists all registered agents.

  ## Returns
  - List of AgentInfo structs

  ## Examples
      iex> AgentCatalogue.list_agents()
      [%AgentInfo{name: "elixir-dev", display_name: "Elixir Developer", ...}]
  """
  @spec list_agents() :: list(agent_info())
  def list_agents do
    @table
    |> :ets.tab2list()
    |> Enum.map(fn {_name, info} -> info end)
    |> Enum.sort_by(fn info -> info.name end)
  end

  @doc """
  Gets information about a specific agent.

  ## Parameters
  - `name`: The agent identifier

  ## Returns
  - `{:ok, AgentInfo}` if found
  - `:not_found` if agent is not registered

  ## Examples
      iex> AgentCatalogue.get_agent_info("elixir-dev")
      {:ok, %AgentInfo{name: "elixir-dev", ...}}

      iex> AgentCatalogue.get_agent_info("unknown")
      :not_found
  """
  @spec get_agent_info(String.t()) :: {:ok, agent_info()} | :not_found
  def get_agent_info(name) when is_binary(name) do
    case :ets.lookup(@table, name) do
      [{^name, info}] -> {:ok, info}
      [] -> :not_found
    end
  end

  @doc """
  Unregisters an agent from the catalogue.

  ## Parameters
  - `name`: The agent identifier to remove

  ## Returns
  - `:ok` on success
  """
  @spec unregister_agent(String.t()) :: :ok
  def unregister_agent(name) when is_binary(name) do
    GenServer.call(__MODULE__, {:unregister, name})
  end

  @doc """
  Clears all registered agents from the catalogue.

  ## Returns
  - `:ok` on success
  """
  @spec clear_catalogue() :: :ok
  def clear_catalogue do
    GenServer.call(__MODULE__, :clear)
  end

  @doc """
  Batch registers multiple agents at once.

  ## Parameters
  - `agents`: List of `{name, display_name, description}` tuples

  ## Returns
  - `{:ok, count}` with number of agents registered

  ## Examples
      iex> AgentCatalogue.register_agents([
      ...>   {"elixir-dev", "Elixir Developer", "Elixir/OTP expert"},
      ...>   {"python-dev", "Python Developer", "Python expert"}
      ...> ])
      {:ok, 2}
  """
  @spec register_agents(list({String.t(), String.t(), String.t()})) ::
          {:ok, non_neg_integer()}
  def register_agents(agents) when is_list(agents) do
    GenServer.call(__MODULE__, {:register_batch, agents})
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(opts) do
    # Create public set table for concurrent reads
    table =
      :ets.new(@table, [
        :named_table,
        :set,
        :public,
        read_concurrency: true,
        write_concurrency: true
      ])

    # Load initial agents from application environment
    initial_agents = Keyword.get(opts, :initial_agents, load_initial_agents())

    for {name, display_name, description} <- initial_agents do
      info = AgentInfo.new(to_string(name), to_string(display_name), to_string(description))
      :ets.insert(table, {info.name, info})
    end

    Logger.info("AgentCatalogue initialized with #{length(initial_agents)} initial agents")

    {:ok, %{table: table}}
  end

  @impl true
  def handle_call({:register, name, display_name, description}, _from, state) do
    info = AgentInfo.new(name, display_name, description)
    :ets.insert(@table, {name, info})
    Logger.debug("AgentCatalogue: registered agent #{name}")
    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:unregister, name}, _from, state) do
    :ets.delete(@table, name)
    Logger.debug("AgentCatalogue: unregistered agent #{name}")
    {:reply, :ok, state}
  end

  @impl true
  def handle_call(:clear, _from, state) do
    :ets.delete_all_objects(@table)
    Logger.debug("AgentCatalogue: cleared all agents")
    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:register_batch, agents}, _from, state) do
    count =
      Enum.reduce(agents, 0, fn {name, display_name, description}, acc ->
        info = AgentInfo.new(name, display_name, description)
        :ets.insert(@table, {name, info})
        acc + 1
      end)

    Logger.debug("AgentCatalogue: batch registered #{count} agents")
    {:reply, {:ok, count}, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp load_initial_agents do
    Application.get_env(:code_puppy_control, :initial_agents, [])
  end
end
