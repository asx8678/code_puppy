defmodule CodePuppyControl.Application do
  @moduledoc """
  OTP Application for CodePuppy Control Plane.

  Supervision tree:
  1. CodePuppyControl.Repo - SQLite database for state persistence
  2. Phoenix.PubSub - Event distribution
  3. CodePuppyControl.EventStore - ETS-based event history for replay
  4. CodePuppyControl.Run.Registry - Process registry for run tracking
  4. CodePuppyControl.Run.Supervisor - DynamicSupervisor for run processes
  5. CodePuppyControl.PythonWorker.Supervisor - DynamicSupervisor for Python workers
  6. CodePuppyControl.MCP.Registry - Process registry for MCP servers
  7. CodePuppyControl.MCP.Supervisor - DynamicSupervisor for MCP servers
  8. CodePuppyControl.RequestTracker - Tracks JSON-RPC request/response correlation
  9. Oban - Job processing engine with SQLite Lite engine
  10. CodePuppyControl.Scheduler.CronScheduler - Periodic scheduler for cron tasks
  11. CodePuppyControlWeb.Endpoint - HTTP API endpoint
  """

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      CodePuppyControl.Repo,
      {Phoenix.PubSub, name: CodePuppyControl.PubSub},
      CodePuppyControl.EventStore,
      CodePuppyControl.Run.Registry,
      {CodePuppyControl.Run.Supervisor, []},
      CodePuppyControl.PythonWorker.Supervisor,
      # MCP Server supervision
      {Registry, keys: :unique, name: CodePuppyControl.MCP.Registry},
      CodePuppyControl.MCP.Supervisor,
      CodePuppyControl.RequestTracker,
      # Oban job processing with SQLite engine
      {Oban, Application.fetch_env!(:code_puppy_control, Oban)},
      # Periodic scheduler for cron tasks
      {CodePuppyControl.Scheduler.CronScheduler, []},
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
