defmodule Mana.Agent do
  @moduledoc """
  Agent behaviour definition.

  Defines the contract for creating agents in the Mana system.
  Provides default implementations via the `__using__` macro.

  ## Usage

      defmodule MyApp.Agents.Coder do
        use Mana.Agent

        @impl true
        def name, do: "coder"

        @impl true
        def system_prompt, do: "You are a helpful coding assistant."
      end

  ## Required Callbacks

  - `name/0` - Returns the agent identifier string

  ## Optional Callbacks

  All other callbacks have defaults:
  - `display_name/0` - Human-readable name (defaults to capitalized `name`)
  - `description/0` - Brief description (defaults to "An agent named {name}")
  - `system_prompt/0` - System prompt string or function returning one
  - `available_tools/0` - List of tool names the agent can use
  - `user_prompt/0` - Default user prompt template
  - `tools_config/0` - Tool-specific configuration map

  """

  @doc "Returns the agent's unique identifier"
  @callback name() :: String.t()

  @doc "Returns a human-readable display name"
  @callback display_name() :: String.t()

  @doc "Returns a brief description of the agent"
  @callback description() :: String.t()

  @doc "Returns the system prompt (string or 0-arity function)"
  @callback system_prompt() :: String.t() | (-> String.t())

  @doc "Returns a list of available tool names"
  @callback available_tools() :: [String.t()]

  @doc "Returns the default user prompt template"
  @callback user_prompt() :: String.t()

  @doc "Returns tool-specific configuration"
  @callback tools_config() :: map()

  defmacro __using__(_opts) do
    quote do
      @behaviour Mana.Agent

      @impl true
      def display_name, do: name() |> String.capitalize()

      @impl true
      def description, do: "An agent named #{name()}"

      @impl true
      def system_prompt, do: ""

      @impl true
      def available_tools, do: []

      @impl true
      def user_prompt, do: ""

      @impl true
      def tools_config, do: %{}

      defoverridable display_name: 0,
                     description: 0,
                     system_prompt: 0,
                     available_tools: 0,
                     user_prompt: 0,
                     tools_config: 0
    end
  end
end
