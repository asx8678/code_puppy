defmodule Mana.TestSupport.MockPlugin do
  @moduledoc """
  Mock plugin for testing the plugin system.
  """

  @behaviour Mana.Plugin.Behaviour

  defstruct [:name, :calls]

  @impl true
  def name, do: "mock_plugin"

  @impl true
  def init(config) do
    {:ok, %{config: config, calls: []}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:agent_run_start, &__MODULE__.on_run_start/3},
      {:agent_run_end, &__MODULE__.on_run_end/7}
    ]
  end

  @impl true
  def terminate do
    :ok
  end

  def on_startup do
    send_test_event({:hook_called, :startup, []})
    :ok
  end

  def on_run_start(agent_name, model_name, session_id) do
    send_test_event({:hook_called, :agent_run_start, [agent_name, model_name, session_id]})
    :ok
  end

  def on_run_end(agent_name, model_name, session_id, success, error, response, metadata) do
    send_test_event({:hook_called, :agent_run_end, [agent_name, model_name, session_id, success, error, response, metadata]})
    :ok
  end

  defp send_test_event(event) do
    # In tests, we'll use the test process to verify calls
    if Process.whereis(:test_collector) do
      send(:test_collector, event)
    end
    :ok
  end
end
