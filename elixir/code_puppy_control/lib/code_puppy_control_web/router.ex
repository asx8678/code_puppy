defmodule CodePuppyControlWeb.Router do
  @moduledoc """
  Router for CodePuppy Control Plane API.

  ## API Endpoints

  ### Run Management
  - `POST /api/runs` - Create a new run
  - `GET /api/runs/:id` - Get run status
  - `DELETE /api/runs/:id` - Stop and cleanup a run

  ### Tool Execution
  - `POST /api/runs/:id/execute` - Execute a tool via Python worker
  - `GET /api/runs/:id/history` - Get run request/response history

  ### Health & Metrics
  - `GET /health` - Health check
  - `GET /metrics` - Prometheus metrics (if configured)
  """

  use Phoenix.Router

  import Plug.Conn
  import Phoenix.Controller

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", CodePuppyControlWeb do
    pipe_through :api

    get "/health", HealthController, :index
  end

  scope "/api", CodePuppyControlWeb do
    pipe_through :api

    resources "/runs", RunController, only: [:create, :show, :delete]
    post "/runs/:id/execute", RunController, :execute
    get "/runs/:id/history", RunController, :history

    # MCP Server endpoints
    resources "/mcp", MCPController, only: [:index, :create, :show, :delete]
    post "/mcp/:id/call", MCPController, :call_tool
    post "/mcp/:id/restart", MCPController, :restart
    get "/mcp/health", MCPController, :health
  end

  # LiveDashboard is available in development for monitoring
  # To enable, add :phoenix_live_dashboard to deps and uncomment below:
  # if Mix.env() == :dev do
  #   import Phoenix.LiveDashboard.Router
  #
  #   scope "/dev" do
  #     pipe_through [:fetch_session, :protect_from_forgery]
  #
  #     live_dashboard "/dashboard",
  #       metrics: CodePuppyControlWeb.Telemetry,
  #       ecto_repos: [CodePuppyControl.Repo]
  #   end
  # end
end
