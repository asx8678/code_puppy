defmodule Mana.Commands.Behaviour do
  @moduledoc """
  Defines the behaviour that all Mana commands must implement.

  Commands are modules that implement this behaviour and provide
  functionality accessible via slash commands in the terminal interface.

  ## Example

      defmodule Mana.Commands.Core.Help do
        @behaviour Mana.Commands.Behaviour

        @impl true
        def name, do: "/help"

        @impl true
        def description, do: "Show help information for all commands"

        @impl true
        def usage, do: "/help [command]"

        @impl true
        def execute(args, context) do
          # Show help based on args
          {:ok, "Help text here"}
        end
      end

  ## Callbacks

  - `name/0` - Returns the command's unique name (must start with "/")
  - `description/0` - Returns a short description of what the command does
  - `usage/0` - Returns usage information string
  - `execute/2` - Executes the command with given arguments and context
  """

  @doc """
  Returns the unique name of the command.

  Command names must start with "/" to be recognized as slash commands.

  ## Returns

  - `String.t()` - The command name starting with "/"

  ## Example

      @impl true
      def name, do: "/help"
  """
  @callback name() :: String.t()

  @doc """
  Returns a short description of what the command does.

  This is displayed in the help output.

  ## Returns

  - `String.t()` - The command description

  ## Example

      @impl true
      def description, do: "Display help information"
  """
  @callback description() :: String.t()

  @doc """
  Returns usage information for the command.

  Shows users how to invoke the command with its arguments.

  ## Returns

  - `String.t()` - The usage string

  ## Example

      @impl true
      def usage, do: "/set <key> <value>"
  """
  @callback usage() :: String.t()

  @doc """
  Executes the command with the given arguments and context.

  ## Parameters

  - `args` - List of string arguments passed to the command
  - `context` - Map containing execution context (session_id, etc.)

  ## Returns

  - `:ok` - Command executed successfully with no output
  - `{:ok, term()}` - Command executed successfully with result
  - `{:error, term()}` - Command failed with error reason

  ## Example

      @impl true
      def execute([key, value], _context) do
        Mana.Config.Store.put_by_name(key, value)
      end
  """
  @callback execute(args :: [String.t()], context :: map()) ::
              :ok | {:ok, term()} | {:error, term()}
end
