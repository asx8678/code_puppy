defmodule Mana do
  @moduledoc """
  Mana - The Plugin System for Agent Orchestration.

  Mana is an Elixir/Phoenix plugin system that mirrors Code Puppy's callback
  architecture, providing extension points for:

  - Agent lifecycle events (`:agent_run_start`, `:agent_run_end`)
  - Tool execution hooks (`:pre_tool_call`, `:post_tool_call`)
  - System startup/shutdown (`:startup`, `:shutdown`)
  - Custom tool and agent registration
  - File operation permissions
  - Streaming events
  - Model configuration and more

  ## Quick Start

  1. Add Mana to your supervision tree:

      children = [
        Mana.Plugin.Manager
      ]

  2. Create a plugin:

      defmodule MyApp.Plugins.Logger do
        @behaviour Mana.Plugin.Behaviour

        @impl true
        def name, do: "logger"

        @impl true
        def init(_config) do
          {:ok, %{}}
        end

        @impl true
        def hooks do
          [
            {:agent_run_start, &__MODULE__.on_run_start/3},
            {:agent_run_end, &__MODULE__.on_run_end/7}
          ]
        end

        def on_run_start(agent_name, _model, _session) do
          IO.puts("Starting: \#{agent_name}")
          :ok
        end

        def on_run_end(agent_name, _model, _session, success, _error, _response, _meta) do
          IO.puts("Completed: \#{agent_name} (success: \#{success})")
          :ok
        end
      end

  3. Trigger hooks from your application:

      Mana.Plugin.Manager.trigger(:agent_run_start, ["my_agent", "gpt-4", nil])

  ## Configuration

  Configure in `config/config.exs`:

      config :mana, Mana.Plugin.Manager,
        plugins: [:discover, MyApp.Plugins.Logger],
        backlog_ttl: 30_000,
        max_backlog_size: 100

  ## Available Hooks

  See `Mana.Plugin.Hook` for the complete list of available hooks.

  ## Architecture

  - `Mana.Plugin.Behaviour` - Plugin behaviour definition
  - `Mana.Plugin.Manager` - GenServer for discovery and dispatch
  - `Mana.Plugin.Hook` - Hook definitions and utilities
  """

  @version "0.1.0"

  @doc """
  Returns the Mana version.
  """
  @spec version() :: String.t()
  def version, do: @version
end
