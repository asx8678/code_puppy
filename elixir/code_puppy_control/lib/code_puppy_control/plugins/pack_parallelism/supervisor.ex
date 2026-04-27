defmodule CodePuppyControl.Plugins.PackParallelism.Supervisor do
  @moduledoc """
  Supervisor for the Pack Parallelism concurrency limiter.

  Starts and monitors the `CodePuppyControl.Plugins.PackParallelism` GenServer,
  restarting it on crashes to maintain concurrency control availability.

  ## Supervision Strategy

  Uses `:one_for_one` — if the GenServer crashes, only it is restarted.
  The ETS table is recreated on restart (stateless counters).

  ## Example

      # In application.ex
      children = [
        CodePuppyControl.Plugins.PackParallelism.Supervisor,
        # ... other children
      ]
  """

  use Supervisor

  @doc """
  Starts the pack parallelism supervisor.
  """
  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts \\ []) do
    Supervisor.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    children = [
      CodePuppyControl.Plugins.PackParallelism
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end
