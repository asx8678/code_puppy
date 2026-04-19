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
  13. CodePuppyControl.Tool.Registry - ETS-backed tool registry (bd-149)
  14. CodePuppyControl.Run.Supervisor - DynamicSupervisor for run processes
  15. CodePuppyControl.PythonWorker.Supervisor - DynamicSupervisor for Python workers
  16. CodePuppyControl.MCP.Registry - Process registry for MCP servers
  17. CodePuppyControl.MCP.Supervisor - DynamicSupervisor for MCP servers
  18. CodePuppyControl.Concurrency.Supervisor - Concurrency limiter (ETS-backed)
  19. CodePuppyControl.TokenLedger - Token usage accounting (bd-152)
  20. CodePuppyControl.RequestTracker - Tracks JSON-RPC request/response correlation
  21. CodePuppyControl.Tools.CommandRunner.ProcessManager - Shell process tracking (bd-64)
  22. Oban - Job processing engine with SQLite Lite engine
  23. CodePuppyControl.Scheduler.CronScheduler - Periodic scheduler for cron tasks
  24. CodePuppyControlWeb.Endpoint - HTTP API endpoint
  """

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      # HTTP client connection pool (Finch)
      CodePuppyControl.HttpClient.child_spec(),
      # Parser registry (must start before any parsing operations)
      CodePuppyControl.Parsing.ParserRegistry,
      # Register built-in parsers (must come after ParserRegistry)
      CodePuppyControl.Parsing.Parsers,
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
      # Tool registry (ETS-backed) for agent tool dispatch (bd-149)
      CodePuppyControl.Tool.Registry,
      # Staged changes sandbox for diff-preview system (bd-150)
      CodePuppyControl.Tools.StagedChanges,
      {CodePuppyControl.Run.Supervisor, []},
      CodePuppyControl.PythonWorker.Supervisor,
      # MCP Server supervision
      {Registry, keys: :unique, name: CodePuppyControl.MCP.Registry},
      CodePuppyControl.MCP.Supervisor,
      # MCP Client supervision (bd-155)
      {Registry, keys: :unique, name: CodePuppyControl.MCP.ClientRegistry},
      CodePuppyControl.MCP.ToolIndex,
      CodePuppyControl.MCP.ClientSupervisor,
      # Concurrency limiter (ETS-backed semaphores for file_ops, api_calls, tool_calls)
      CodePuppyControl.Concurrency.Supervisor,
      # Adaptive rate limiter with circuit breaker (bd-151)
      CodePuppyControl.RateLimiter.Supervisor,
      # Token ledger for per-run/session token accounting (bd-152)
      CodePuppyControl.TokenLedger,
      CodePuppyControl.RequestTracker,

      # Shell command runner process tracking (bd-64)
      CodePuppyControl.Tools.CommandRunner.ProcessManager,
      # Auth rate limiter ETS table (bd-218)
      {Task, fn -> CodePuppyControlWeb.Plugs.RateLimiter.create_table() end},
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
