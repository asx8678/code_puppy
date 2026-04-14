defmodule CodePuppyControl.MCP.Manager do
  @moduledoc """
  High-level API for managing MCP servers.

  This module provides a simple interface for:
  - Registering/unregistering MCP servers
  - Calling tools on MCP servers
  - Querying server status and health
  - Bulk health check operations

  ## Usage

      # Register a new MCP server
      {:ok, server_id} = MCP.Manager.register_server(
        "filesystem",
        "npx",
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
      )

      # Call a tool
      {:ok, result} = MCP.Manager.call_tool(server_id, "read_file", %{"path" => "/tmp/test.txt"})

      # Check status
      status = MCP.Manager.get_server_status(server_id)

      # Cleanup
      :ok = MCP.Manager.unregister_server(server_id)

  ## PubSub Events

  Subscribe to `CodePuppyControl.PubSub` with topic `"mcp:<server_id>"` to receive:
  - `{:mcp_notification, server_id, params}` - Server notifications
  - `{:mcp_quarantined, server_id, until}` - Quarantine events
  """

  require Logger

  alias CodePuppyControl.MCP.{Server, Supervisor}

  @doc """
  Registers a new MCP server with the system.

  Generates a unique server_id and starts the server under supervision.

  ## Parameters

    * `name` - Human-readable name for the server.
    * `command` - The MCP server executable command.
    * `opts` - Optional keyword list:
      * `:server_id` - Override auto-generated ID.
      * `:args` - Command line arguments.
      * `:env` - Environment variables.

  ## Returns

    * `{:ok, server_id}` - Server started successfully.
    * `{:error, reason}` - Failed to start server.

  ## Examples

      {:ok, server_id} = MCP.Manager.register_server(
        "filesystem",
        "npx",
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        env: %{"HOME" => "/home/user"}
      )
  """
  @spec register_server(String.t(), String.t(), keyword()) :: {:ok, String.t()} | {:error, term()}
  def register_server(name, command, opts \\ []) do
    server_id = opts[:server_id] || generate_server_id(name)

    Logger.info("Registering MCP server #{name} as #{server_id}")

    server_opts = [
      server_id: server_id,
      name: name,
      command: command,
      args: opts[:args] || [],
      env: opts[:env] || %{}
    ]

    case Supervisor.start_server(server_opts) do
      {:ok, _pid} -> {:ok, server_id}
      {:error, _} = error -> error
    end
  end

  @doc """
  Unregisters an MCP server and stops it.

  ## Returns

    * `:ok` - Server stopped successfully.
    * `{:error, :not_found}` - Server not found.
  """
  @spec unregister_server(String.t()) :: :ok | {:error, :not_found}
  def unregister_server(server_id) do
    Logger.info("Unregistering MCP server #{server_id}")
    Supervisor.stop_server(server_id)
  end

  @doc """
  Calls a tool on an MCP server.

  ## Parameters

    * `server_id` - The server identifier.
    * `method` - Tool method name.
    * `params` - Tool parameters.
    * `opts` - Optional:
      * `:timeout` - Request timeout in milliseconds (default 30_000).

  ## Returns

    * `{:ok, result}` - Tool executed successfully.
    * `{:error, :quarantined}` - Server is quarantined.
    * `{:error, reason}` - Tool execution failed.

  ## Examples

      {:ok, %{"content" => content}} = MCP.Manager.call_tool(
        server_id,
        "read_file",
        %{"path" => "/tmp/test.txt"}
      )
  """
  @spec call_tool(String.t(), String.t(), map(), keyword()) :: {:ok, term()} | {:error, term()}
  def call_tool(server_id, method, params, opts \\ []) do
    timeout = opts[:timeout] || 30_000
    Server.call_tool(server_id, method, params, timeout)
  end

  @doc """
  Gets the status of an MCP server.

  Returns a map with server details or `{:error, :not_found}`.
  """
  @spec get_server_status(String.t()) :: map() | {:error, :not_found}
  def get_server_status(server_id) do
    Server.get_status(server_id)
  end

  @doc """
  Lists all registered MCP servers with their status.

  Returns a list of status maps, one for each server.
  """
  @spec list_servers() :: list(map())
  def list_servers do
    Supervisor.list_servers()
    |> Enum.map(&Server.get_status/1)
    |> Enum.reject(&match?({:error, _}, &1))
  end

  @doc """
  Performs health checks on all MCP servers.

  Returns a list of `{server_id, health}` tuples where health is:
  - `:healthy` - Server is healthy
  - `{:unhealthy, reason}` - Server is unhealthy

  ## Examples

      results = MCP.Manager.health_check_all()
      # [{"files-abc123", :healthy}, {"git-xyz789", {:unhealthy, :timeout}}]
  """
  @spec health_check_all() :: list({String.t(), :healthy | {:unhealthy, term()}})
  def health_check_all do
    Supervisor.list_servers()
    |> Enum.map(fn server_id ->
      {server_id, Server.health_check(server_id)}
    end)
  end

  @doc """
  Gets summary statistics for all MCP servers.

  Returns a map with counts by health status.
  """
  @spec stats() :: map()
  def stats do
    servers = list_servers()

    total = length(servers)
    healthy = Enum.count(servers, &(&1.health == :healthy))
    degraded = Enum.count(servers, &(&1.health == :degraded))
    unhealthy = Enum.count(servers, &(&1.health == :unhealthy))
    quarantined = Enum.count(servers, & &1.quarantined)

    %{
      total: total,
      healthy: healthy,
      degraded: degraded,
      unhealthy: unhealthy,
      quarantined: quarantined
    }
  end

  @doc """
  Restarts an MCP server.

  Useful for recovering from quarantine or other error states.
  """
  @spec restart_server(String.t()) :: {:ok, pid()} | {:error, term()}
  def restart_server(server_id) do
    Supervisor.restart_server(server_id)
  end

  @doc """
  Stops all MCP servers.

  This is useful for shutdown or cleanup operations.
  """
  @spec stop_all() :: :ok
  def stop_all do
    Supervisor.list_servers()
    |> Enum.each(&unregister_server/1)

    :ok
  end

  # Private functions

  defp generate_server_id(name) do
    random_suffix = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)
    "#{name}-#{random_suffix}"
  end
end
