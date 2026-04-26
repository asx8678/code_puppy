defmodule CodePuppyControl.Agent.RuntimeState.Registry do
  @moduledoc """
  Registry for per-agent RuntimeState processes.

  Each agent gets its own RuntimeState GenServer, keyed by `agent_name`.
  The Registry uses `:unique` keys with partition-based concurrency.
  """

  def child_spec(_opts) do
    Registry.child_spec(
      keys: :unique,
      name: __MODULE__,
      partitions: System.schedulers_online()
    )
  end
end
