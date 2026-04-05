defmodule Mana.Agent.Builder do
  @moduledoc """
  Agent construction from definition + options.

  Provides functions to build agent servers from module definitions
  or map-based definitions (useful for JSON agent configs).

  ## Usage

  Building from a module:

      defmodule MyApp.Agents.Coder do
        use Mana.Agent
        def name, do: "coder"
        def system_prompt, do: "You are a coding assistant."
      end

      {:ok, pid} = Mana.Agent.Builder.build(MyApp.Agents.Coder, model_name: "gpt-4")

  Building from a map:

      agent_def = %{
        name: "custom",
        system_prompt: "You are helpful.",
        available_tools: ["file_read"]
      }
      {:ok, pid} = Mana.Agent.Builder.build_from_map(agent_def)

  ## Model Resolution

  The model is resolved in this priority order:
  1. `:model_name` option passed to build/2
  2. Model from agent's `tools_config()` (module) or `"model"` key (map)
  3. Mana.Config.global_model_name()

  """

  alias Mana.Agent.Server
  alias Mana.Config

  @doc """
  Builds an agent from a module definition.

  ## Parameters

    - `agent_module` - Module that implements Mana.Agent behaviour
    - `opts` - Keyword list of options

  ## Options

    - `:model_name` - Override the model name
    - `:session_id` - Associate with a session
    - Additional options passed to Server.start_link/1

  ## Returns

    `{:ok, pid}` on success, `{:error, reason}` on failure

  """
  @spec build(module(), keyword()) :: GenServer.on_start()
  def build(agent_module, opts \\ []) when is_atom(agent_module) do
    agent_def = %{
      name: agent_module.name(),
      display_name: agent_module.display_name(),
      description: agent_module.description(),
      system_prompt: agent_module.system_prompt(),
      available_tools: agent_module.available_tools(),
      user_prompt: agent_module.user_prompt(),
      tools_config: agent_module.tools_config()
    }

    server_opts =
      Keyword.merge(
        [
          agent_def: agent_def,
          model_name: resolve_model(agent_module, opts),
          session_id: Keyword.get(opts, :session_id)
        ],
        opts
      )

    Server.start_link(server_opts)
  end

  @doc """
  Builds from a map definition (useful for JSON agent configs).

  ## Parameters

    - `agent_def` - Map containing agent definition
    - `opts` - Keyword list of options

  ## Agent Definition Keys

    - `:name` (required) - Agent identifier
    - `:display_name` - Human-readable name
    - `:description` - Brief description
    - `:system_prompt` - System prompt string
    - `:available_tools` - List of tool names
    - `:user_prompt` - Default user prompt
    - `:model` - Model name (used for resolution)
    - `:tools_config` - Tool-specific configuration

  ## Options

    - `:model_name` - Override the model name
    - `:session_id` - Associate with a session

  ## Returns

    `{:ok, pid}` on success, `{:error, reason}` on failure

  """
  @spec build_from_map(map(), keyword()) :: GenServer.on_start()
  def build_from_map(agent_def, opts \\ []) do
    server_opts =
      Keyword.merge(
        [
          agent_def: agent_def,
          model_name: resolve_model_from_map(agent_def, opts),
          session_id: Keyword.get(opts, :session_id)
        ],
        opts
      )

    Server.start_link(server_opts)
  end

  defp resolve_model(agent_module, opts) do
    Keyword.get(opts, :model_name) ||
      Map.get(agent_module.tools_config(), :model) ||
      Config.global_model_name()
  end

  defp resolve_model_from_map(agent_def, opts) do
    Keyword.get(opts, :model_name) ||
      Map.get(agent_def, :model) ||
      Map.get(agent_def, "model") ||
      Config.global_model_name()
  end
end
