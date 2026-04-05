defmodule Mana.Tools.Registry do
  @moduledoc """
  GenServer for tool registration with ETS-backed fast lookups.

  ## Features

  - Register tool modules implementing `Mana.Tools.Behaviour`
  - Execute tools by name (in caller's process for concurrency)
  - Get tool definitions for agent configuration
  - Track tool call statistics

  ## Architecture

  - ETS table `:mana_tools` for fast concurrent reads
  - GenServer only handles registrations (writes)
  - Tool execution happens in caller's process (no bottleneck)
  - Stats updates are asynchronous via cast

  ## Usage

      # Start the registry
      Mana.Tools.Registry.start_link([])

      # Register a tool
      Mana.Tools.Registry.register(Mana.Tools.File)

      # Execute a tool (runs in caller's process)
      Mana.Tools.Registry.execute("read_file", %{"path" => "/tmp/file.txt"})

      # Get tool definitions for an agent
      Mana.Tools.Registry.tool_definitions("agent_name")
  """

  use GenServer

  require Logger

  @table :mana_tools

  # List of expected tool modules that should be registered at startup
  @expected_tools [
    Mana.Tools.FileOps.ListFiles,
    Mana.Tools.FileOps.ReadFile,
    Mana.Tools.FileOps.Grep,
    Mana.Tools.FileEdit.CreateFile,
    Mana.Tools.FileEdit.ReplaceInFile,
    Mana.Tools.FileEdit.DeleteFile,
    Mana.Tools.AgentTools.ListAgents,
    Mana.Tools.AgentTools.InvokeAgent,
    Mana.Tools.AgentTools.AskUser,
    Mana.Tools.ShellExec
  ]

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

  ## Performance Note

  This function performs tool lookup via ETS (no GenServer blocking)
  and executes the tool in the caller's process for maximum concurrency.
  Stats updates are performed asynchronously via cast.
  """
  @spec execute(String.t(), map()) :: {:ok, term()} | {:error, term()}
  def execute(tool_name, args \\ %{}) do
    case :ets.lookup(@table, tool_name) do
      [{^tool_name, tool_info}] ->
        try do
          result = tool_info.module.execute(args)
          # Update stats asynchronously - don't block on this
          GenServer.cast(__MODULE__, {:increment_calls})
          result
        rescue
          error ->
            Logger.error("Tool execution error for #{tool_name}: #{inspect(error)}")
            GenServer.cast(__MODULE__, {:increment_errors})
            {:error, :execution_failed}
        end

      [] ->
        GenServer.cast(__MODULE__, {:increment_errors})
        {:error, :unknown_tool}
    end
  end

  @doc """
  Gets tool details (module, description, parameters) for a tool.

  Returns `{:ok, details}` or `{:error, :not_found}`.

  This is a fast ETS lookup that bypasses the GenServer.
  """
  @spec get_tool(String.t()) :: {:ok, map()} | {:error, :not_found}
  def get_tool(name) do
    case :ets.lookup(@table, name) do
      [{^name, tool_info}] ->
        {:ok,
         %{
           name: name,
           description: tool_info.description,
           parameters: tool_info.schema,
           module: tool_info.module
         }}

      [] ->
        {:error, :not_found}
    end
  end

  @doc """
  Gets tool definitions formatted for agent configuration.

  Returns a list of tool definitions that can be passed to agents.
  """
  @spec tool_definitions(String.t()) :: [map()]
  def tool_definitions(_agent_name) do
    get_definitions()
  end

  @doc """
  Lists all registered tool names.
  """
  @spec list_tools() :: [String.t()]
  def list_tools do
    case :ets.whereis(@table) do
      :undefined -> []
      _table -> :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}]) |> Enum.sort()
    end
  end

  @doc """
  Returns current registry statistics.
  """
  @spec get_stats() :: map()
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  @doc """
  Lists all registered tool names (alias for list_tools/0).
  """
  @spec list() :: [String.t()]
  def list do
    list_tools()
  end

  @doc """
  Returns tool definitions for all registered tools.
  """
  @spec get_definitions() :: [map()]
  def get_definitions do
    list_tools()
    |> Enum.map(fn name ->
      case get_tool(name) do
        {:ok, details} ->
          %{
            type: "function",
            function: %{
              name: name,
              description: details.description,
              parameters: details.parameters
            }
          }

        {:error, _} ->
          nil
      end
    end)
    |> Enum.reject(&is_nil/1)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    # Create ETS table for fast public reads
    :ets.new(@table, [
      :set,
      :named_table,
      :public,
      read_concurrency: true
    ])

    # Register real tool implementations
    register_expected_tools()

    # Verify all expected tools are registered
    verify_tools_registered!()

    {:ok, %{stats: %{calls: 0, errors: 0}}}
  end

  @impl true
  def handle_call({:register, tool_module}, _from, state) do
    # Verify the module implements the behaviour
    if behaviour_implemented?(tool_module) do
      tool_name = tool_module.name()

      # Check for duplicates
      if :ets.member(@table, tool_name) do
        {:reply, {:error, :already_registered}, state}
      else
        tool_info = %{
          module: tool_module,
          description: tool_module.description(),
          schema: tool_module.parameters()
        }

        :ets.insert(@table, {tool_name, tool_info})
        {:reply, :ok, state}
      end
    else
      {:reply, {:error, :invalid_behaviour}, state}
    end
  end

  @impl true
  def handle_call(:get_stats, _from, state) do
    stats = %{
      tools_registered: :ets.info(@table, :size),
      calls: state.stats.calls,
      errors: state.stats.errors
    }

    {:reply, stats, state}
  end

  @impl true
  def handle_cast({:increment_calls}, state) do
    new_stats = %{state.stats | calls: state.stats.calls + 1}
    {:noreply, %{state | stats: new_stats}}
  end

  @impl true
  def handle_cast({:increment_errors}, state) do
    new_stats = %{state.stats | errors: state.stats.errors + 1}
    {:noreply, %{state | stats: new_stats}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # Private Functions

  defp register_expected_tools do
    Enum.each(@expected_tools, fn module ->
      if behaviour_implemented?(module) do
        tool_name = module.name()

        tool_info = %{
          module: module,
          description: module.description(),
          schema: module.parameters()
        }

        :ets.insert(@table, {tool_name, tool_info})
      else
        Logger.warning("Tool #{inspect(module)} does not implement Behaviour, skipping")
      end
    end)
  end

  defp verify_tools_registered! do
    registered =
      case :ets.whereis(@table) do
        :undefined ->
          MapSet.new()

        _table ->
          tool_names = :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}])
          MapSet.new(tool_names)
      end

    expected = Enum.map(@expected_tools, & &1.name()) |> MapSet.new()
    missing = MapSet.difference(expected, registered)

    if MapSet.size(missing) > 0 do
      missing_list = MapSet.to_list(missing) |> Enum.join(", ")
      Logger.error("Tools.Registry: Missing expected tools: #{missing_list}")
      raise "Tool registration incomplete: #{missing_list}"
    else
      tool_count = :ets.info(@table, :size)
      Logger.info("Tools.Registry: All #{tool_count} expected tools registered successfully")
    end
  end

  defp behaviour_implemented?(module) do
    Code.ensure_loaded?(module) and
      function_exported?(module, :name, 0) and
      function_exported?(module, :description, 0) and
      function_exported?(module, :parameters, 0) and
      function_exported?(module, :execute, 1)
  end
end
