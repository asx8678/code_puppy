defmodule CodePuppyControl.Application do
  @moduledoc """
  OTP Application for CodePuppy Control Plane.

  Supervision tree:
  1. CodePuppyControl.HttpClient - Finch HTTP connection pool (bd-69)
  2. CodePuppyControl.Parsing.ParserRegistry - Language parser registry (Agent-backed)
  3. CodePuppyControl.Repo - SQLite database for state persistence
  4. Phoenix.PubSub - Event distribution
  5. CodePuppyControl.EventStore - ETS-based event history for replay
  6. CodePuppyControl.RuntimeState - Global runtime state (autosave ID, session model)
  7. CodePuppyControl.PolicyEngine - Priority-based policy rule engine
  8. CodePuppyControl.AgentModelPinning - Agent-to-model pin configuration (ETS-backed)
  9a. CodePuppyControl.ModelRegistry - Model configuration registry (ETS-backed) (bd-96)
  9b. CodePuppyControl.ModelAvailability - Model health circuit breaker (ETS-backed)
  9c. CodePuppyControl.ModelPacks - Role-based model packs (bd-100)
  9d. CodePuppyControl.Tools.AgentCatalogue - Agent catalogue with descriptions
  10. CodePuppyControl.RoundRobinModel - Round-robin model rotation (ETS-backed)
  11a. CodePuppyControl.ModelsDevParser.Registry - Models.dev API registry (bd-74)
  12. CodePuppyControl.Run.Registry - Process registry for run tracking
  13. CodePuppyControl.Run.Supervisor - DynamicSupervisor for run processes
  14. CodePuppyControl.PythonWorker.Supervisor - DynamicSupervisor for Python workers
  15. CodePuppyControl.MCP.Registry - Process registry for MCP servers
  16. CodePuppyControl.MCP.Supervisor - DynamicSupervisor for MCP servers
  17. CodePuppyControl.Concurrency.Supervisor - Concurrency limiter (ETS-backed)
  18. CodePuppyControl.RequestTracker - Tracks JSON-RPC request/response correlation
  19. CodePuppyControl.Tools.CommandRunner.ProcessManager - Shell process tracking (bd-64)
  20. Oban - Job processing engine with SQLite Lite engine
  21. CodePuppyControl.Scheduler.CronScheduler - Periodic scheduler for cron tasks
  22. CodePuppyControlWeb.Endpoint - HTTP API endpoint
  """

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      # HTTP client connection pool (Finch)
      CodePuppyControl.HttpClient.child_spec(),
      # Parser registry (must start before any parsing operations)
      CodePuppyControl.Parsing.ParserRegistry,
      CodePuppyControl.Repo,
      {Phoenix.PubSub, name: CodePuppyControl.PubSub},
      CodePuppyControl.EventStore,
      CodePuppyControl.RuntimeState,
      CodePuppyControl.PolicyEngine,
      CodePuppyControl.AgentModelPinning,
      CodePuppyControl.ModelRegistry,
      CodePuppyControl.ModelAvailability,
      CodePuppyControl.ModelPacks,
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
