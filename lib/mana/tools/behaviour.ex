defmodule Mana.Tools.Behaviour do
  @moduledoc """
  Defines the behaviour that all Mana tools must implement.

  Tools are modules that implement this behaviour and provide
  capabilities that agents can use to interact with the system.

  ## Example

      defmodule Mana.Tools.File do
        @behaviour Mana.Tools.Behaviour

        @impl true
        def name, do: "read_file"

        @impl true
        def description, do: "Read contents of a file"

        @impl true
        def parameters do
          %{
            type: "object",
            properties: %{
              path: %{type: "string", description: "Path to the file"}
            },
            required: ["path"]
          }
        end

        @impl true
        def execute(%{"path" => path}) do
          case File.read(path) do
            {:ok, contents} -> {:ok, contents}
            {:error, reason} -> {:error, reason}
          end
        end
      end

  ## Callbacks

  - `name/0` - Returns the tool's unique name
  - `description/0` - Returns a description of what the tool does
  - `parameters/0` - Returns JSON Schema for tool parameters
  - `execute/1` - Executes the tool with given arguments map
  """

  @doc """
  Returns the unique name of the tool.

  ## Returns

  - `String.t()` - The tool name

  ## Example

      @impl true
      def name, do: "read_file"
  """
  @callback name() :: String.t()

  @doc """
  Returns a description of what the tool does.

  ## Returns

  - `String.t()` - The tool description

  ## Example

      @impl true
      def description, do: "Read file contents from disk"
  """
  @callback description() :: String.t()

  @doc """
  Returns JSON Schema describing the tool's parameters.

  ## Returns

  - `map()` - JSON Schema object defining parameters

  ## Example

      @impl true
      def parameters do
        %{
          type: "object",
          properties: %{
            path: %{type: "string", description: "File path"}
          },
          required: ["path"]
        }
      end
  """
  @callback parameters() :: map()

  @doc """
  Executes the tool with the given arguments.

  ## Parameters

  - `args` - Map of arguments matching the parameters schema

  ## Returns

  - `{:ok, term()}` - Tool executed successfully with result
  - `{:error, term()}` - Tool failed with error reason

  ## Example

      @impl true
      def execute(%{"path" => path}) do
        File.read(path)
      end
  """
  @callback execute(args :: map()) :: {:ok, term()} | {:error, term()}
end
