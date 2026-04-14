defmodule CodePuppyControl.Application do
  @moduledoc """
  OTP Application for CodePuppy Control Plane.

  Supervision tree:
  1. CodePuppyControl.Repo - SQLite database for Oban and state persistence
  2. Phoenix.PubSub - Event distribution
  3. CodePuppyControl.Run.Registry - Process registry for run tracking
  4. CodePuppyControl.PythonWorker.Supervisor - DynamicSupervisor for Python workers
  5. Oban - Job processing
  6. CodePuppyControlWeb.Endpoint - HTTP API endpoint
  """

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      CodePuppyControl.Repo,
      {Phoenix.PubSub, name: CodePuppyControl.PubSub},
      CodePuppyControl.Run.Registry,
      {DynamicSupervisor, strategy: :one_for_one, name: CodePuppyControl.Run.Supervisor},
      CodePuppyControl.PythonWorker.Supervisor,
      CodePuppyControl.RequestTracker,
      {Oban, Application.fetch_env!(:code_puppy_control, Oban)},
      CodePuppyControlWeb.Endpoint
    ]

    opts = [strategy: :one_for_one, name: CodePuppyControl.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    CodePuppyControlWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
