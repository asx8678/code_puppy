defmodule CodePuppyControl.Config.MCP do
  @moduledoc """
  MCP (Model Context Protocol) server configuration.

  Manages loading and caching of MCP server definitions from
  `mcp_servers.json`. Uses mtime-based cache invalidation to avoid
  repeated disk reads.

  ## File Format

  ```json
  {
    "mcp_servers": {
      "server_name": "http://localhost:8080",
      "another_server": {
        "url": "http://localhost:9000",
        "auth": "bearer_token"
      }
    }
  }
  ```

  ## Cache

  The loaded config is cached in `:persistent_term` with mtime tracking.
  Cache is invalidated when the file changes or on explicit reload.
  """

  require Logger

  alias CodePuppyControl.Config.Paths

  @persistent_term_key {:code_puppy_control, :mcp_servers}
  @persistent_term_mtime_key {:code_puppy_control, :mcp_servers_mtime}

  @doc """
  Load MCP server configurations from `mcp_servers.json`.

  Returns a map of server names to their configurations.
  Uses mtime-based caching to avoid repeated disk reads.
  If the file doesn't exist, returns an empty map.
  """
  @spec load_server_configs() :: map()
  def load_server_configs do
    mtime = get_mtime()

    case :persistent_term.get(@persistent_term_mtime_key, :not_loaded) do
      ^mtime ->
        :persistent_term.get(@persistent_term_key, %{})

      _ ->
        config = do_load()
        :persistent_term.put(@persistent_term_key, config)
        :persistent_term.put(@persistent_term_mtime_key, mtime)
        config
    end
  end

  @doc """
  Reload MCP server configurations from disk, ignoring cache.
  """
  @spec reload() :: map()
  def reload do
    config = do_load()
    mtime = get_mtime()
    :persistent_term.put(@persistent_term_key, config)
    :persistent_term.put(@persistent_term_mtime_key, mtime)
    config
  end

  @doc """
  Clear the cached MCP server configurations.
  """
  @spec clear_cache() :: :ok
  def clear_cache do
    :persistent_term.erase(@persistent_term_key)
    :persistent_term.erase(@persistent_term_mtime_key)
    :ok
  end

  @doc """
  Get a specific MCP server configuration by name.

  Returns `nil` if the server is not configured.
  """
  @spec get_server(String.t()) :: map() | String.t() | nil
  def get_server(name) do
    load_server_configs() |> Map.get(name)
  end

  @doc """
  Check if MCP is disabled via config.

  Checks the `disable_mcp` key in `puppy.cfg`.
  Default is `false` (MCP enabled).
  """
  @spec disabled?() :: boolean()
  def disabled? do
    CodePuppyControl.Config.Debug.mcp_disabled?()
  end

  # ── Private ─────────────────────────────────────────────────────────────

  defp do_load do
    path = get_mcp_servers_path()

    case File.read(path) do
      {:ok, content} ->
        case Jason.decode(content) do
          {:ok, %{"mcp_servers" => servers}} when is_map(servers) ->
            servers

          {:ok, %{} = config} ->
            # Allow bare map without mcp_servers key for backwards compat
            config

          {:error, %Jason.DecodeError{} = error} ->
            Logger.warning("Failed to parse MCP servers config: #{inspect(error)}")
            %{}

          {:error, reason} ->
            Logger.warning("Failed to parse MCP servers config: #{reason}")
            %{}

          _ ->
            %{}
        end

      {:error, :enoent} ->
        %{}

      {:error, reason} ->
        Logger.warning("Failed to read MCP servers config: #{reason}")
        %{}
    end
  end

  defp get_mtime do
    path = get_mcp_servers_path()

    case :file.read_file_info(String.to_charlist(path)) do
      {:ok, info} ->
        # info is a :file_info record, mtime is at index 4 (5th element)
        elem(info, 4)

      {:error, _} ->
        0
    end
  end

  defp get_mcp_servers_path do
    case Application.get_env(:code_puppy_control, :mcp_servers_file_override) do
      nil -> Paths.mcp_servers_file()
      override when is_binary(override) -> override
    end
  end
end
