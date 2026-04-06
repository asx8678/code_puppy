defmodule Mana.MCP.Supervisor do
  @moduledoc """
  Top-level supervisor for all MCP server processes.

  This supervisor manages the lifecycle of MCP (Model Context Protocol)
  server connections. It uses a `:one_for_one` restart strategy where
  each server runs as an independent child process.

  ## Supervision Strategy

  `:one_for_one` is chosen because:

  1. MCP servers are independent — failure of one server doesn't affect others
  2. Servers may have different lifetimes (stdio vs SSE/HTTP)
  3. Individual server restarts are safer than group restarts
  4. External servers (SSE/HTTP) may fail independently of stdio servers

  ## Dynamic Child Management

  Servers are added and removed dynamically via `start_server/2` and
  `stop_server/2`. The supervisor starts empty and children are added
  as servers are registered.

  ## Usage

      # Start the supervisor (usually done by Application.start/2)
      {:ok, _pid} = Mana.MCP.Supervisor.start_link()

      # Start a managed server
      config = %Mana.MCP.ServerConfig{
        id: "filesystem",
        name: "filesystem",
        type: :stdio,
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-filesystem"]
      }
      {:ok, pid} = Mana.MCP.Supervisor.start_server(config)

      # Stop a server
      :ok = Mana.MCP.Supervisor.stop_server("filesystem")

  ## Integration with Application Supervision Tree

  This supervisor can be started under the main application supervision tree
  after `Mana.Plugin.Manager` (since plugins may register MCP servers).

      children = [
        # ... other children ...
        {Mana.Plugin.Manager, []},
        {Mana.MCP.Supervisor, []},  # MCP servers after plugins
        # ... other children ...
      ]

  > **Note:** In production, the Registry should be started as a sibling of
  > this supervisor under the application tree. The inline `Registry.start_link`
  > in `start_link/1` is a dev/standalone convenience.

  """

  use DynamicSupervisor

  require Logger

  alias Mana.MCP.ServerConfig

  @typedoc "Server ID string"
  @type server_id :: String.t()

  # Default registry name
  @default_registry Mana.MCP.Registry

  # ============================================================================
  # DynamicSupervisor callbacks
  # ============================================================================

  @doc """
  Starts the MCP Supervisor.

  ## Options

    - `:name` - The name to register the process under (default: `__MODULE__`)
    - `:registry` - Registry name to use (default: `Mana.MCP.Registry`)
    - `:max_children` - Maximum concurrent servers (default: 100)

  """
  @spec start_link(keyword()) :: DynamicSupervisor.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    registry = Keyword.get(opts, :registry, @default_registry)

    with :ok <- ensure_registry(registry) do
      DynamicSupervisor.start_link(__MODULE__, opts, name: name)
    end
  end

  defp ensure_registry(registry) do
    case Registry.start_link(keys: :unique, name: registry) do
      {:ok, _} ->
        Logger.debug("Started MCP Registry: #{inspect(registry)}")
        :ok

      {:error, {:already_started, _}} ->
        Logger.debug("MCP Registry already running: #{inspect(registry)}")
        :ok

      {:error, reason} ->
        Logger.error("Failed to start MCP Registry: #{inspect(reason)}")
        {:error, {:registry_start_failed, reason}}
    end
  end

  @impl true
  def init(opts) do
    max_children = Keyword.get(opts, :max_children, 100)

    DynamicSupervisor.init(
      strategy: :one_for_one,
      max_children: max_children
    )
  end

  # ============================================================================
  # Public API
  # ============================================================================

  @doc """
  Starts a new MCP server under the supervisor.

  The server implementation module is determined by the config type:
  - `:stdio` → `Mana.MCP.STDIOServer` (to be implemented in bd-2qfc)
  - `:sse` → `Mana.MCP.SSEServer` (to be implemented)
  - `:http` → `Mana.MCP.HTTPServer` (to be implemented)

  ## Parameters

  - `config` - `Mana.MCP.ServerConfig` struct with server configuration
  - `opts` - Options:
    - `:supervisor` - Supervisor to start under (default: `__MODULE__`)
    - `:module` - Override module to use (default: determined by config.type)
    - `:registry` - Registry name to use (default: `Mana.MCP.Registry`)

  ## Returns

  - `{:ok, pid}` - Server started successfully
  - `{:error, :max_children}` - Maximum number of servers reached
  - `{:error, :not_yet_implemented}` - Server type module not yet available
  - `{:error, term()}` - Failed to start server

  ## Examples

      config = %Mana.MCP.ServerConfig{
        id: "test",
        name: "Test Server",
        type: :stdio,
        command: "echo",
        args: ["hello"]
      }
      {:ok, pid} = Mana.MCP.Supervisor.start_server(config)
  """
  @spec start_server(ServerConfig.t(), keyword()) :: DynamicSupervisor.on_start_child()
  def start_server(%ServerConfig{id: id, type: type} = config, opts \\ []) do
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)
    registry = Keyword.get(opts, :registry, @default_registry)

    # Allow module injection for testing
    server_module = Keyword.get(opts, :module) || server_module_for_type(type)

    case server_module do
      :not_yet_implemented ->
        Logger.warning("MCP server type #{type} not yet implemented for #{id}")
        {:error, :not_yet_implemented}

      :invalid_type ->
        {:error, {:invalid_type, type}}

      module ->
        # Validate the config first
        case ServerConfig.validate(config) do
          {:ok, _} ->
            # Use Registry for name registration - child will register itself
            via_name = {:via, Registry, {registry, id}}

            child_spec = %{
              id: Mana.MCP.Server,
              start: {module, :start_link, [config, [name: via_name]]},
              restart: :transient,
              type: :worker
            }

            case DynamicSupervisor.start_child(supervisor, child_spec) do
              {:ok, pid} ->
                Logger.info("Started MCP server: #{config.name} (ID: #{id}, type: #{type})")
                {:ok, pid}

              {:ok, pid, _info} ->
                Logger.info("Started MCP server: #{config.name} (ID: #{id}, type: #{type})")
                {:ok, pid}

              {:error, {:already_started, pid}} ->
                Logger.warning("MCP server #{id} already running at #{inspect(pid)}")
                {:error, {:already_started, pid}}

              {:error, reason} = error ->
                Logger.error("Failed to start MCP server #{id}: #{inspect(reason)}")
                error
            end

          {:error, reason} ->
            Logger.error("Invalid MCP server config for #{id}: #{inspect(reason)}")
            {:error, {:invalid_config, reason}}
        end
    end
  end

  @doc """
  Stops a running MCP server.

  ## Parameters

  - `server_id` - The unique ID of the server to stop
  - `opts` - Options:
    - `:supervisor` - Supervisor managing the server (default: `__MODULE__`)
    - `:registry` - Registry name to use (default: `Mana.MCP.Registry`)

  ## Returns

  - `:ok` - Server stopped successfully
  - `{:error, :not_found}` - Server not found

  ## Examples

      :ok = Mana.MCP.Supervisor.stop_server("filesystem")
  """
  @spec stop_server(server_id(), keyword()) :: :ok | {:error, :not_found | term()}
  def stop_server(server_id, opts \\ []) do
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)
    registry = Keyword.get(opts, :registry, @default_registry)

    case find_server_pid(registry, server_id) do
      {:ok, pid} ->
        case DynamicSupervisor.terminate_child(supervisor, pid) do
          :ok ->
            # Unregister from Registry (terminate_child should also stop the process)
            Logger.info("Stopped MCP server: #{server_id}")
            :ok

          {:error, reason} = error ->
            Logger.error("Failed to stop MCP server #{server_id}: #{inspect(reason)}")
            error
        end

      :error ->
        Logger.warning("MCP server not found for stopping: #{server_id}")
        {:error, :not_found}
    end
  end

  @doc """
  Returns a list of all running MCP server PIDs.

  ## Parameters

  - `opts` - Options:
    - `:registry` - Registry to query (default: `Mana.MCP.Registry`)

  ## Returns

  List of `{server_id, pid}` tuples for all running servers.

  ## Examples

      [{"filesystem", #PID<0.123.0>}, {"weather", #PID<0.124.0>}] =
        Mana.MCP.Supervisor.which_servers()
  """
  @spec which_servers(keyword()) :: [{server_id(), pid()}]
  def which_servers(opts \\ []) do
    registry = Keyword.get(opts, :registry, @default_registry)

    Registry.select(registry, [
      {{:"$1", :"$2", :_}, [], [{{:"$1", :"$2"}}]}
    ])
    # defensive: ensure Registry key is always a String
    |> Enum.map(fn {id, pid} -> {to_string(id), pid} end)
  end

  @doc """
  Checks if a server with the given ID is running.

  ## Parameters

  - `server_id` - The unique ID of the server to check
  - `opts` - Options:
    - `:registry` - Registry to query (default: `Mana.MCP.Registry`)

  ## Returns

  `true` if the server is running, `false` otherwise.

  ## Examples

      true = Mana.MCP.Supervisor.server_running?("filesystem")
  """
  @spec server_running?(server_id(), keyword()) :: boolean()
  def server_running?(server_id, opts \\ []) do
    registry = Keyword.get(opts, :registry, @default_registry)

    case Registry.lookup(registry, server_id) do
      [{pid, _value}] when is_pid(pid) -> Process.alive?(pid)
      _ -> false
    end
  end

  @doc """
  Returns the number of running MCP servers.

  ## Parameters

  - `opts` - Options:
    - `:supervisor` - Supervisor to query (default: `__MODULE__`)

  ## Returns

  The count of active server processes.
  """
  @spec count_servers(keyword()) :: non_neg_integer()
  def count_servers(opts \\ []) do
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)
    DynamicSupervisor.count_children(supervisor) |> Map.get(:active, 0)
  end

  # ----------------------------------------------------------------------------
  # Private functions
  # ----------------------------------------------------------------------------

  # Returns the server implementation module for a given server type.
  # These modules will be implemented in subsequent bd issues.
  # For now, return :not_yet_implemented for real types.
  defp server_module_for_type(:stdio), do: :not_yet_implemented
  defp server_module_for_type(:sse), do: :not_yet_implemented
  defp server_module_for_type(:http), do: :not_yet_implemented
  defp server_module_for_type(_), do: :invalid_type

  # Looks up a running server pid by server_id using the Registry.
  defp find_server_pid(registry, server_id) do
    case Registry.lookup(registry, server_id) do
      [{pid, _value}] when is_pid(pid) ->
        if Process.alive?(pid), do: {:ok, pid}, else: :error

      _ ->
        :error
    end
  end
end
