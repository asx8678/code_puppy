defmodule Mana.Plugins.RememberAgent do
  @moduledoc "Saves and restores last selected agent"
  @behaviour Mana.Plugin.Behaviour

  @default_session_id "default"
  @config_key :last_agent

  @impl true
  def name, do: "remember_agent"

  @impl true
  def init(config) do
    {:ok, %{config: config, session_id: Map.get(config, :session_id, @default_session_id)}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.restore_agent/0},
      {:shutdown, &__MODULE__.save_agent/0}
    ]
  end

  @doc """
  Restores the last selected agent from config on startup.
  """
  def restore_agent do
    case Mana.Config.get(@config_key) do
      nil ->
        :ok

      agent_name when is_binary(agent_name) ->
        case Mana.Agents.Registry.get_agent(agent_name) do
          nil -> :ok
          _agent -> Mana.Agents.Registry.set_agent(@default_session_id, agent_name)
        end

      _ ->
        :ok
    end
  end

  @doc """
  Saves the current agent to config on shutdown.
  """
  def save_agent do
    case Mana.Agents.Registry.current_agent(@default_session_id) do
      nil ->
        :ok

      agent ->
        agent_name = Map.get(agent, "name") || Map.get(agent, :name)
        if agent_name, do: Mana.Config.put(@config_key, agent_name)
        :ok
    end
  end

  @impl true
  def terminate do
    save_agent()
    :ok
  end
end
