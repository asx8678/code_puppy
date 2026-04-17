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

  alias CodePuppyControl.Parsing.ParserRegistry
  alias CodePuppyControl.Parsing.Parsers.ErlangParser

  @impl true
  def start(_type, _args) do
    children = [
      # HTTP client connection pool (Finch)
      CodePuppyControl.HttpClient.child_spec(),
      # Parser registry (must start before any parsing operations)
      ParserRegistry,
      # Parser registration (runs after registry starts)
      %{id: :parser_registration, start: {__MODULE__, :register_parsers, []}},
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

  @doc """
  Registers all built-in parsers with the ParserRegistry.
  Called as a child_spec in the supervision tree after ParserRegistry starts.
  """
  def register_parsers do
    # Wait for registry to be available (it's a sibling process)
    # Use a simple retry loop since we're in the same supervision tree
    wait_for_registry(10)

    # Ensure parser modules are loaded before registration
    Code.ensure_loaded(ErlangParser)

    # Register Erlang parser (bd-105)
    case ParserRegistry.register(ErlangParser) do
      :ok -> :ignore
      {:error, :unsupported} -> :ignore
      {:error, :invalid_module} -> :ignore
    end
  end

  defp wait_for_registry(0), do: :ok

  defp wait_for_registry(retries) do
    case Process.whereis(ParserRegistry) do
      nil ->
        Process.sleep(50)
        wait_for_registry(retries - 1)

      _pid ->
        :ok
    end
  end

  @impl true
  def config_change(changed, _new, removed) do
    CodePuppyControlWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
