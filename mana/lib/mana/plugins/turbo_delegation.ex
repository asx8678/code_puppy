defmodule Mana.Plugins.TurboDelegation do
  @moduledoc "Injects turbo executor delegation guidance"
  @behaviour Mana.Plugin.Behaviour

  @impl true
  def name, do: "turbo_delegation"

  @impl true
  def init(config) do
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [{:load_prompt, &__MODULE__.inject_turbo_guidance/0}]
  end

  @doc """
  Injects turbo executor delegation guidance into the system prompt.
  """
  def inject_turbo_guidance do
    """
    ## Turbo Executor Delegation
    For batch file operations (>5 files), delegate to the turbo-executor agent.
    Use invoke_agent("turbo-executor", prompt) for complex multi-file tasks.
    """
  end

  @impl true
  def terminate do
    :ok
  end
end
