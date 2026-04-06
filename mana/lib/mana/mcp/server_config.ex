defmodule Mana.MCP.ServerConfig do
  @moduledoc """
  Configuration for an MCP server instance.

  This struct defines the configuration parameters for all MCP server types
  (stdio, SSE, HTTP). Not all fields are required for every server type;
  the specific fields used depend on the server type.

  ## Server Types

  - `:stdio` - Local process-based server (command + args)
  - `:sse` - Server-Sent Events server (URL-based)
  - `:http` - HTTP/StreamableHTTP server (URL-based)

  ## Examples

  ### STDIO Server

      %Mana.MCP.ServerConfig{
        id: "filesystem",
        name: "filesystem",
        type: :stdio,
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        env: %{"NODE_ENV" => "production"},
        timeout: 60_000
      }

  ### SSE Server

      %Mana.MCP.ServerConfig{
        id: "weather",
        name: "weather",
        type: :sse,
        url: "http://localhost:3001/sse",
        headers: %{"Authorization" => "Bearer token"},
        timeout: 30_000
      }

  """

  alias Mana.MCP.ServerState

  @typedoc "MCP server type"
  @type server_type :: :stdio | :sse | :http

  @typedoc "Environment variable map for stdio servers"
  @type env_map :: %{String.t() => String.t()}

  @typedoc "HTTP header map for SSE/HTTP servers"
  @type headers_map :: %{String.t() => String.t()}

  @enforce_keys [:id, :name, :type]
  defstruct [
    # Required fields
    :id,
    :name,
    :type,

    # STDIO server fields
    :command,
    :args,
    :env,
    :cwd,

    # SSE/HTTP server fields
    :url,
    :headers,

    # Optional fields with defaults
    enabled: true,
    quarantined: false,
    timeout: 60_000,
    read_timeout: nil,
    config: %{}
  ]

  @typedoc "ServerConfig struct type"
  @type t :: %__MODULE__{
          id: String.t(),
          name: String.t(),
          type: server_type(),
          command: String.t() | nil,
          args: [String.t()] | nil,
          env: env_map() | nil,
          cwd: String.t() | nil,
          url: String.t() | nil,
          headers: headers_map() | nil,
          enabled: boolean(),
          quarantined: boolean(),
          timeout: non_neg_integer(),
          read_timeout: non_neg_integer() | nil,
          config: map()
        }

  @doc """
  Creates a new ServerConfig struct with validation.

  ## Options

  All struct fields can be passed as keyword options.

  ## Returns

  - `{:ok, %ServerConfig{}}` - Valid config created
  - `{:error, term()}` - Invalid configuration

  ## Examples

      iex> {:ok, config} = Mana.MCP.ServerConfig.new(
      ...>   id: "test",
      ...>   name: "Test Server",
      ...>   type: :stdio,
      ...>   command: "npx",
      ...>   args: ["server"]
      ...> )
      iex> config.id
      "test"

      iex> Mana.MCP.ServerConfig.new(id: "test", name: "Test", type: :invalid)
      {:error, :invalid_server_type}
  """
  @spec new(keyword()) :: {:ok, t()} | {:error, term()}
  def new(opts) when is_list(opts) do
    config = struct(__MODULE__, opts)
    validate(config)
  end

  @doc """
  Creates a new ServerConfig struct, raising on invalid input.

  ## Examples

      iex> config = Mana.MCP.ServerConfig.new!(id: "test", name: "Test", type: :stdio, command: "cmd")
      iex> config.type
      :stdio
  """
  @spec new!(keyword()) :: t()
  def new!(opts) when is_list(opts) do
    case new(opts) do
      {:ok, config} -> config
      {:error, reason} -> raise ArgumentError, "Invalid server config: #{inspect(reason)}"
    end
  end

  @doc """
  Validates a ServerConfig struct.

  Checks:
  - Required fields are present
  - Server type is valid
  - Type-specific required fields are present
  - Timeouts are positive integers

  ## Returns

  - `{:ok, config}` - Config is valid
  - `{:error, reason}` - Config is invalid

  ## Examples

      iex> config = %Mana.MCP.ServerConfig{id: "test", name: "Test", type: :stdio, command: "cmd"}
      iex> Mana.MCP.ServerConfig.validate(config)
      {:ok, config}

      iex> config = %Mana.MCP.ServerConfig{id: "test", name: "Test", type: :stdio}
      iex> Mana.MCP.ServerConfig.validate(config)
      {:error, {:missing_required_field, :command}}
  """
  @spec validate(t()) :: {:ok, t()} | {:error, term()}
  def validate(%__MODULE__{} = config) do
    with :ok <- validate_required(config),
         :ok <- validate_type(config),
         :ok <- validate_type_specific(config),
         :ok <- validate_timeouts(config) do
      {:ok, config}
    end
  end

  @doc """
  Checks if a config represents an enabled, non-quarantined server.

  ## Examples

      iex> config = %Mana.MCP.ServerConfig{id: "test", name: "Test", type: :stdio, command: "echo", enabled: true, quarantined: false}
      iex> Mana.MCP.ServerConfig.available?(config)
      true

      iex> config = %Mana.MCP.ServerConfig{id: "test", name: "Test", type: :stdio, command: "echo", enabled: false, quarantined: false}
      iex> Mana.MCP.ServerConfig.available?(config)
      false
  """
  @spec available?(t()) :: boolean()
  def available?(%__MODULE__{enabled: true, quarantined: false}), do: true
  def available?(%__MODULE__{}), do: false

  @doc """
  Returns the initial state for a server based on its configuration.

  Servers always start in `:stopped` state and must be explicitly started.

  ## Examples

      iex> config = %Mana.MCP.ServerConfig{id: "test", name: "Test", type: :stdio, command: "echo", enabled: true}
      iex> Mana.MCP.ServerConfig.initial_state(config)
      :stopped
  """
  @spec initial_state(t()) :: ServerState.t()
  def initial_state(%__MODULE__{}), do: :stopped

  @doc """
  Returns type-specific required fields.

  ## Examples

      iex> Mana.MCP.ServerConfig.required_fields_for(:stdio)
      [:command]

      iex> Mana.MCP.ServerConfig.required_fields_for(:sse)
      [:url]
  """
  @spec required_fields_for(server_type()) :: [atom()]
  def required_fields_for(:stdio), do: [:command]
  def required_fields_for(:sse), do: [:url]
  def required_fields_for(:http), do: [:url]

  # ----------------------------------------------------------------------------
  # Private functions
  # ----------------------------------------------------------------------------

  defp validate_required(%__MODULE__{id: nil}), do: {:error, {:missing_required_field, :id}}
  defp validate_required(%__MODULE__{name: nil}), do: {:error, {:missing_required_field, :name}}
  defp validate_required(%__MODULE__{type: nil}), do: {:error, {:missing_required_field, :type}}
  defp validate_required(%__MODULE__{}), do: :ok

  defp validate_type(%__MODULE__{type: type}) when type in [:stdio, :sse, :http], do: :ok
  defp validate_type(%__MODULE__{type: type}) when is_atom(type), do: {:error, :invalid_server_type}
  defp validate_type(%__MODULE__{type: type}), do: {:error, {:invalid_type, type}}

  defp validate_type_specific(%__MODULE__{type: type} = config) do
    required = required_fields_for(type)

    case Enum.find(required, &(Map.get(config, &1) == nil)) do
      nil -> :ok
      field -> {:error, {:missing_required_field, field}}
    end
  end

  defp validate_timeouts(%__MODULE__{timeout: timeout}) when not is_integer(timeout) or timeout < 0 do
    {:error, {:invalid_timeout, timeout}}
  end

  defp validate_timeouts(%__MODULE__{read_timeout: nil}), do: :ok

  defp validate_timeouts(%__MODULE__{read_timeout: read_timeout})
       when is_integer(read_timeout) and read_timeout > 0,
       do: :ok

  defp validate_timeouts(%__MODULE__{read_timeout: read_timeout}) do
    {:error, {:invalid_read_timeout, read_timeout}}
  end
end
