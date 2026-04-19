defmodule CodePuppyControl.RateLimiter.Supervisor do
  @moduledoc """
  Supervisor for the adaptive rate limiter subsystem.

  Starts and monitors the `CodePuppyControl.RateLimiter` GenServer.
  Uses `:one_for_one` — if the limiter crashes, only the limiter is
  restarted. ETS tables are recreated on init.

  ## Supervision Strategy

  The rate limiter is a critical reliability component — it prevents
  rate-limit storms from cascading across providers. Restart intensity
  is kept low (5 restarts in 10 seconds) to surface persistent issues.
  """

  use Supervisor

  @doc """
  Starts the rate limiter supervisor.
  """
  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts \\ []) do
    Supervisor.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    children = [
      CodePuppyControl.RateLimiter
    ]

    Supervisor.init(children, strategy: :one_for_one, max_restarts: 5, max_seconds: 10)
  end
end
