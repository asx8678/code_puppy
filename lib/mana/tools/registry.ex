defmodule Mana.Tools.Registry do
  @moduledoc """
  GenServer for tool registration and execution.

  ## Features

  - Register tool modules implementing `Mana.Tools.Behaviour`
  - Execute tools by name
  - Get tool definitions for agent configuration
  - Track tool call statistics

  ## State Structure

  - `tools`: Map of tool_name => %{module, description, schema}
  - `stats`: Tool execution statistics

  ## Usage

      # Start the registry
      Mana.Tools.Registry.start_link([])

      # Register a tool
      Mana.Tools.Registry.register(Mana.Tools.File)

      # Execute a tool
      Mana.Tools.Registry.execute("read_file", %{"path" => "/tmp/file.txt"})

      # Get tool definitions for an agent
      Mana.Tools.Registry.tool_definitions("agent_name")
  """

  use GenServer

  require Logger

  # Client API

  @doc """
  Starts the Tools Registry GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child specification for supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Registers a tool module that implements the Behaviour.

  Returns `:ok` on success, `{:error, reason}` on failure.
  """
  @spec register(module()) :: :ok | {:error, term()}
  def register(tool_module) do
    GenServer.call(__MODULE__, {:register, tool_module})
  end

  @doc """
  Executes a tool by name with the given arguments.

  Returns the result of tool execution.
  """
  @spec execute(String.t(), map()) :: {:ok, term()} | {:error, term()}
  def execute(tool_name, args \\ %{}) do
    GenServer.call(__MODULE__, {:execute, tool_name, args})
  end

  @doc """
  Gets tool details (module, description, parameters) for a tool.

  Returns `{:ok, details}` or `{:error, :not_found}`.
  """
  @spec get_tool(String.t()) :: {:ok, map()} | {:error, :not_found}
  def get_tool(name) do
    GenServer.call(__MODULE__, {:get_tool, name})
  end

  @doc """
  Gets tool definitions formatted for agent configuration.

  Returns a list of tool definitions that can be passed to agents.
  """
  @spec tool_definitions(String.t()) :: [map()]
  def tool_definitions(_agent_name) do
    GenServer.call(__MODULE__, :tool_definitions)
  end

  @doc """
  Lists all registered tool names.
  """
  @spec list_tools() :: [String.t()]
  def list_tools do
    GenServer.call(__MODULE__, :list_tools)
  end

  @doc """
  Returns current registry statistics.
  """
  @spec get_stats() :: map()
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    state = %{
      tools: %{},
      stats: %{calls: 0, errors: 0}
    }

    # Register stub tools for Phase 1
    state = register_stub_tools(state)

    {:ok, state}
  end

  @impl true
  def handle_call({:register, tool_module}, _from, state) do
    # Verify the module implements the behaviour
    if behaviour_implemented?(tool_module) do
      tool_name = tool_module.name()

      # Check for duplicates
      if Map.has_key?(state.tools, tool_name) do
        {:reply, {:error, :already_registered}, state}
      else
        tool_info = %{
          module: tool_module,
          description: tool_module.description(),
          schema: tool_module.parameters()
        }

        new_tools = Map.put(state.tools, tool_name, tool_info)
        new_state = %{state | tools: new_tools}
        {:reply, :ok, new_state}
      end
    else
      {:reply, {:error, :invalid_behaviour}, state}
    end
  end

  @impl true
  def handle_call({:execute, tool_name, args}, _from, state) do
    case Map.get(state.tools, tool_name) do
      nil ->
        new_stats = %{state.stats | errors: state.stats.errors + 1}
        {:reply, {:error, :unknown_tool}, %{state | stats: new_stats}}

      %{module: module} ->
        try do
          result = module.execute(args)
          new_calls = state.stats.calls + 1
          new_stats = %{state.stats | calls: new_calls}
          {:reply, result, %{state | stats: new_stats}}
        rescue
          error ->
            Logger.error("Tool execution error for #{tool_name}: #{inspect(error)}")
            new_stats = %{state.stats | errors: state.stats.errors + 1}
            {:reply, {:error, :execution_failed}, %{state | stats: new_stats}}
        end
    end
  end

  @impl true
  def handle_call({:get_tool, name}, _from, state) do
    case Map.get(state.tools, name) do
      nil ->
        {:reply, {:error, :not_found}, state}

      tool_info ->
        details = %{
          name: name,
          description: tool_info.description,
          parameters: tool_info.schema,
          module: tool_info.module
        }

        {:reply, {:ok, details}, state}
    end
  end

  @impl true
  def handle_call(:tool_definitions, _from, state) do
    definitions =
      Enum.map(state.tools, fn {name, info} ->
        %{
          type: "function",
          function: %{
            name: name,
            description: info.description,
            parameters: info.schema
          }
        }
      end)

    {:reply, definitions, state}
  end

  @impl true
  def handle_call(:list_tools, _from, state) do
    tools = Map.keys(state.tools) |> Enum.sort()
    {:reply, tools, state}
  end

  @impl true
  def handle_call(:get_stats, _from, state) do
    stats = %{
      tools_registered: map_size(state.tools),
      calls: state.stats.calls,
      errors: state.stats.errors
    }

    {:reply, stats, state}
  end

  # Private Functions

  defp behaviour_implemented?(module) do
    Code.ensure_loaded?(module) and
      function_exported?(module, :name, 0) and
      function_exported?(module, :description, 0) and
      function_exported?(module, :parameters, 0) and
      function_exported?(module, :execute, 1)
  end

  defp register_stub_tools(state) do
    stub_tools = [
      Mana.Tools.Stubs.ListFiles,
      Mana.Tools.Stubs.ReadFile,
      Mana.Tools.Stubs.WriteFile,
      Mana.Tools.Stubs.EditFile,
      Mana.Tools.Stubs.RunShellCommand
    ]

    Enum.reduce(stub_tools, state, fn module, acc_state ->
      if behaviour_implemented?(module) do
        tool_name = module.name()

        tool_info = %{
          module: module,
          description: module.description(),
          schema: module.parameters()
        }

        %{acc_state | tools: Map.put(acc_state.tools, tool_name, tool_info)}
      else
        acc_state
      end
    end)
  end
end
