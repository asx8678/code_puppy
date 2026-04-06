defmodule Mana.MCP.ServerBehaviour do
  @moduledoc """
  Behaviour that any MCP server implementation must satisfy.

  This behaviour defines the contract for managed MCP servers in the Mana
  application. Implementations must provide lifecycle management, state
  inspection, and tool execution capabilities.

  ## Implementing the Behaviour

      defmodule Mana.MCP.STDIOServer do
        @behaviour Mana.MCP.ServerBehaviour

        alias Mana.MCP.{ServerConfig, ServerState}

        @impl true
        def start_link(%ServerConfig{} = config) do
          GenServer.start_link(__MODULE__, config, name: via_tuple(config.id))
        end

        @impl true
        def stop(pid) when is_pid(pid) do
          GenServer.call(pid, :stop)
        end

        @impl true
        def get_state(pid) when is_pid(pid) do
          GenServer.call(pid, :get_state)
        end

        @impl true
        def list_tools(pid) when is_pid(pid) do
          GenServer.call(pid, :list_tools)
        end

        @impl true
        def call_tool(pid, tool_name, arguments) when is_pid(pid) do
          GenServer.call(pid, {:call_tool, tool_name, arguments})
        end

        @impl true
        def enable(pid) when is_pid(pid) do
          GenServer.call(pid, :enable)
        end

        @impl true
        def disable(pid) when is_pid(pid) do
          GenServer.call(pid, :disable)
        end

        @impl true
        def quarantine(pid, duration_ms) when is_pid(pid) and is_integer(duration_ms) do
          GenServer.call(pid, {:quarantine, duration_ms})
        end

        @impl true
        def get_status(pid) when is_pid(pid) do
          GenServer.call(pid, :get_status)
        end

        # GenServer callbacks...
      end

  ## Callbacks

  All callbacks are required unless marked as optional.

  """

  alias Mana.MCP.{ServerConfig, ServerState}

  @typedoc "Server process identifier (PID)"
  @type server_pid :: pid()

  @typedoc "Tool name string"
  @type tool_name :: String.t()

  @typedoc "Tool arguments map"
  @type tool_args :: %{String.t() => term()}

  @typedoc "Tool result"
  @type tool_result :: {:ok, term()} | {:error, term()}

  @typedoc "List of tool definitions"
  @type tool_list :: [map()]

  @typedoc "Server status map"
  @type status_map :: %{
          id: String.t(),
          name: String.t(),
          type: atom(),
          state: ServerState.t(),
          enabled: boolean(),
          quarantined: boolean(),
          uptime_ms: non_neg_integer() | nil,
          error: String.t() | nil,
          server_available: boolean()
        }

  @doc """
  Starts the server process linked to the current process.

  Called by the supervisor when adding a new server to the tree.

  ## Parameters

  - `config` - The server configuration containing all setup parameters
  - `opts` - Options, including `:name` for process registration

  ## Returns

  - `{:ok, pid}` - Server started successfully
  - `{:error, term()}` - Server failed to start

  """
  @callback start_link(config :: ServerConfig.t(), opts :: keyword()) :: GenServer.on_start()

  @doc """
  Gracefully stops the server process.

  Should clean up resources, close connections, and terminate the process.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  - `:ok` - Server stopped successfully
  - `{:error, term()}` - Failed to stop server

  """
  @callback stop(server_pid()) :: :ok | {:error, term()}

  @doc """
  Returns the current state of the server.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  The current `t:Mana.MCP.ServerState.t/0` of the server.

  """
  @callback get_state(server_pid()) :: ServerState.t()

  @doc """
  Lists all tools available from this server.

  Queries the MCP server for its tool manifest and returns tool definitions
  that can be presented to agents.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  - `{:ok, tools}` - List of tool definitions
  - `{:error, reason}` - Failed to list tools

  """
  @callback list_tools(server_pid()) :: {:ok, tool_list()} | {:error, term()}

  @doc """
  Calls a tool on the MCP server.

  Invokes a specific tool with the provided arguments and returns the result.

  ## Parameters

  - `pid` - The server process identifier
  - `tool_name` - Name of the tool to invoke
  - `arguments` - Map of argument names to values

  ## Returns

  - `{:ok, result}` - Tool executed successfully with result
  - `{:error, reason}` - Tool execution failed

  """
  @callback call_tool(server_pid(), tool_name(), tool_args()) :: tool_result()

  @doc """
  Enables the server for agent use.

  An enabled server can be discovered by agents and will participate in
  tool execution. Does not automatically start the server process.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  - `:ok` - Server enabled successfully
  - `{:error, term()}` - Failed to enable server

  """
  @callback enable(server_pid()) :: :ok | {:error, term()}

  @doc """
  Disables the server.

  A disabled server will not be discovered by agents and will not
  participate in tool execution. The server process may continue running
  for management purposes.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  - `:ok` - Server disabled successfully
  - `{:error, term()}` - Failed to disable server

  """
  @callback disable(server_pid()) :: :ok | {:error, term()}

  @doc """
  Temporarily quarantines the server.

  Quarantine acts as a circuit breaker — the server is temporarily
  disabled for a specified duration. After the duration expires, the
  server returns to its previous enabled/disabled state.

  ## Parameters

  - `pid` - The server process identifier
  - `duration_ms` - Quarantine duration in milliseconds

  ## Returns

  - `:ok` - Server quarantined successfully
  - `{:error, term()}` - Failed to quarantine server

  """
  @callback quarantine(server_pid(), duration_ms :: non_neg_integer()) ::
              :ok | {:error, term()}

  @doc """
  Returns comprehensive status information about the server.

  Status includes state, uptime, error messages, and availability for
  agent use.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  A map containing server status information.

  """
  @callback get_status(server_pid()) :: status_map()

  @doc """
  Waits until the server is ready to accept requests.

  For stdio servers, this waits for process initialization.
  For SSE/HTTP servers, this waits for connection establishment.

  ## Parameters

  - `pid` - The server process identifier
  - `timeout_ms` - Maximum time to wait in milliseconds (default: 30_000)

  ## Returns

  - `:ok` - Server is ready
  - `{:error, :timeout}` - Server did not become ready in time
  - `{:error, term()}` - Server initialization failed

  """
  @callback wait_until_ready(server_pid(), timeout_ms :: non_neg_integer()) ::
              :ok | {:error, term()}

  @optional_callbacks wait_until_ready: 2

  @doc """
  Returns captured stderr output (stdio servers only).

  For stdio servers, captures stderr for debugging. Returns empty list
  for SSE/HTTP servers.

  ## Parameters

  - `pid` - The server process identifier

  ## Returns

  List of captured stderr lines as strings.

  """
  @callback get_captured_stderr(server_pid()) :: [String.t()]

  @optional_callbacks get_captured_stderr: 1
end
