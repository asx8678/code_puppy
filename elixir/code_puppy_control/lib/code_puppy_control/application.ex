defmodule CodePuppyControl.Application do
  @moduledoc """
  OTP Application for CodePuppy Control Plane.

  Supervision tree:
  1. CodePuppyControl.HttpClient - Finch HTTP connection pool (bd-69)
  2. CodePuppyControl.Repo - SQLite database for state persistence
  2. Phoenix.PubSub - Event distribution
  3. CodePuppyControl.EventStore - ETS-based event history for replay
  4. CodePuppyControl.RuntimeState - Global runtime state (autosave ID, session model)
  5. CodePuppyControl.PolicyEngine - Priority-based policy rule engine
  6. CodePuppyControl.AgentModelPinning - Agent-to-model pin configuration (ETS-backed)
  6a. CodePuppyControl.ModelRegistry - Model configuration registry (ETS-backed)
  6b. CodePuppyControl.Tools.AgentCatalogue - Agent catalogue with descriptions
  7. CodePuppyControl.RoundRobinModel - Round-robin model rotation (ETS-backed)
  7a. CodePuppyControl.ModelsDevParser.Registry - Models.dev API registry (bd-74)
  8. CodePuppyControl.Run.Registry - Process registry for run tracking
  9. CodePuppyControl.Run.Supervisor - DynamicSupervisor for run processes
  10. CodePuppyControl.PythonWorker.Supervisor - DynamicSupervisor for Python workers
  11. CodePuppyControl.MCP.Registry - Process registry for MCP servers
  12. CodePuppyControl.MCP.Supervisor - DynamicSupervisor for MCP servers
  13. CodePuppyControl.Concurrency.Supervisor - Concurrency limiter (ETS-backed)
  14. CodePuppyControl.RequestTracker - Tracks JSON-RPC request/response correlation
  15. CodePuppyControl.Tools.CommandRunner.ProcessManager - Shell process tracking (bd-64)
  16. Oban - Job processing engine with SQLite Lite engine
  17. CodePuppyControl.Scheduler.CronScheduler - Periodic scheduler for cron tasks
  18. CodePuppyControlWeb.Endpoint - HTTP API endpoint
  """

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      # HTTP client connection pool (Finch)
      CodePuppyControl.HttpClient.child_spec(),
      CodePuppyControl.Repo,
      {Phoenix.PubSub, name: CodePuppyControl.PubSub},
      CodePuppyControl.EventStore,
      CodePuppyControl.RuntimeState,
      CodePuppyControl.PolicyEngine,
      CodePuppyControl.AgentModelPinning,
      CodePuppyControl.ModelRegistry,
      CodePuppyControl.Tools.AgentCatalogue,
      CodePuppyControl.RoundRobinModel,
      CodePuppyControl.ModelsDevParser.Registry,
      CodePuppyControl.Run.Registry,
      {CodePuppyControl.Run.Supervisor, []},
      CodePuppyControl.PythonWorker.Supervisor,
      # MCP Server supervision
      {Registry, keys: :unique, name: CodePuppyControl.MCP.Registry},
      CodePuppyControl.MCP.Supervisor,
      # Concurrency limiter (ETS-backed semaphores for file_ops, api_calls, tool_calls)
      CodePuppyControl.Concurrency.Supervisor,
      CodePuppyControl.RequestTracker,
      # Shell command runner process tracking (bd-64)
      CodePuppyControl.Tools.CommandRunner.ProcessManager,
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
