defmodule Mana.Plugin.Behaviour do
  @moduledoc """
  Defines the behaviour that all Mana plugins must implement.

  Plugins are Elixir modules that implement this behaviour and provide
  hooks into various lifecycle events of the agent system.

  ## Example

      defmodule MyApp.Plugins.Logger do
        @behaviour Mana.Plugin.Behaviour

        @impl true
        def name, do: "logger"

        @impl true
        def init(config) do
          IO.puts("Logger plugin initializing with config: \#{inspect(config)}")
          {:ok, %{enabled: true}}
        end

        @impl true
        def hooks do
          [
            {:agent_run_start, &__MODULE__.on_agent_run_start/3},
            {:agent_run_end, &__MODULE__.on_agent_run_end/7},
            {:pre_tool_call, &__MODULE__.on_pre_tool_call/3}
          ]
        end

        def on_agent_run_start(agent_name, _model_name, _session_id) do
          IO.puts("Agent run started: \#{agent_name}")
          :ok
        end

        def on_agent_run_end(agent_name, _model_name, _session_id, success, _error, _response_text, _metadata) do
          IO.puts("Agent run ended: \#{agent_name}, success: \#{success}")
          :ok
        end

        def on_pre_tool_call(tool_name, tool_args, _context) do
          IO.puts("About to call tool: \#{tool_name} with args: \#{inspect(tool_args)}")
          :ok
        end
      end

  ## Callbacks

  - `name/0` - Returns the plugin's unique name
  - `init/1` - Called at startup with configuration, returns `{:ok, state}` or `{:error, reason}`
  - `hooks/0` - Returns a list of `{hook_name, function}` tuples mapping hooks to handler functions
  """

  alias Mana.Plugin.Hook

  @doc """
  Returns the unique name of the plugin.

  This name is used for identification, logging, and configuration lookup.
  It should be unique across all loaded plugins.

  ## Returns

  - `String.t()` - The plugin name

  ## Example

      @impl true
      def name, do: "my_custom_plugin"
  """
  @callback name() :: String.t()

  @doc """
  Initializes the plugin with the provided configuration.

  Called once at system startup after plugin discovery. The plugin can
  perform setup, spawn processes, or initialize state based on the config.

  ## Parameters

  - `config` - A map containing configuration for this plugin from the
    application environment or plugin manager

  ## Returns

  - `{:ok, state}` - Successfully initialized with any state to be preserved
  - `{:error, reason}` - Failed to initialize, plugin will not be loaded

  ## Example

      @impl true
      def init(config) do
        timeout = Map.get(config, :timeout, 5000)
        {:ok, %{timeout: timeout, counter: 0}}
      end
  """
  @callback init(config :: map()) :: {:ok, term()} | {:error, term()}

  @doc """
  Returns the list of hooks this plugin provides.

  Each hook is a tuple of `{hook_phase, function}` where:
  - `hook_phase` - An atom from `Mana.Plugin.Hook.all_hooks/0`
  - `function` - An arity-appropriate function that handles the hook

  The function will receive arguments based on the hook phase. See
  `Mana.Plugin.Hook.callback_signature/1` for expected signatures.

  ## Returns

  - `[{Hook.hook_phase(), function()}]` - List of hook-function pairs

  ## Example

      @impl true
      def hooks do
        [
          {:startup, &__MODULE__.on_startup/0},
          {:agent_run_start, &__MODULE__.on_run_start/3},
          {:agent_run_end, &__MODULE__.on_run_end/7}
        ]
      end

      def on_startup do
        IO.puts("Plugin starting up!")
        :ok
      end

      def on_run_start(agent_name, _model_name, _session_id) do
        IO.puts("Run starting for: \#{agent_name}")
        :ok
      end

      def on_run_end(agent_name, _model_name, _session_id, success, error, _response, _meta) do
        IO.puts("Run ended for: \#{agent_name}, success: \#{success}")
        :ok
      end
  """
  @callback hooks() :: [{Hook.hook_phase(), function()}]

  @doc """
  Optional callback to gracefully shut down the plugin.

  Called during system shutdown to allow cleanup of resources,
  stopping of processes, and graceful termination.

  ## Returns

  - `:ok` - Successfully shut down

  ## Example

      @impl true
      def terminate do
        IO.puts("Logger plugin shutting down")
        :ok
      end
  """
  @callback terminate() :: :ok

  @optional_callbacks terminate: 0
end
