defmodule Mana.Scheduler.Supervisor do
  @moduledoc """
  Supervisor for the Mana scheduler subsystem.

  Starts and supervises the `Mana.Scheduler.Runner` GenServer.

  ## Supervision strategy

  Uses `:one_for_one` strategy — if the Runner crashes, it is restarted
  independently. The runner is stateless (all state is persisted to the Store),
  so restarts are safe.

  ## In the application tree

  This supervisor is added to the main `Mana.Application` supervision tree:

      children = [
        # ... other children ...
        {Mana.Scheduler.Supervisor, []}
      ]
  """

  use Supervisor

  alias Mana.Scheduler.Runner

  @doc """
  Starts the Scheduler Supervisor.
  """
  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts \\ []) do
    Supervisor.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    children = [
      {Runner, []}
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end
