defmodule Mana.Web.Router do
  @moduledoc """
  Phoenix Router for the Mana web interface.

  Defines routes and pipelines for the web application:
  - `:browser` pipeline for HTML requests with session/csrf support
  - LiveView route for the chat interface at root path

  ## Routes

  - GET / - Chat interface (LiveView)

  """

  use Phoenix.Router

  import Phoenix.LiveView.Router

  # Browser pipeline with standard web protections
  pipeline :browser do
    plug(:accepts, ["html"])
    plug(Mana.Web.AuthPlug)
    plug(:fetch_session)
    plug(:fetch_live_flash)
    plug(:put_root_layout, html: {Mana.Web.Layouts, :root})
    plug(:protect_from_forgery)
    plug(:put_secure_browser_headers)
  end

  # Main application routes
  scope "/", Mana.Web do
    pipe_through(:browser)

    live("/", Live.ChatLive, :index)
  end

  # Health check endpoints (no auth required)
  scope "/", Mana.Web do
    # Legacy endpoint at /health (preserved for backward compatibility)
    get("/health", HealthController, :index)
  end

  # API health check endpoint with detailed supervisor status
  scope "/api", Mana.Web do
    get("/health", HealthController, :check)
  end
end
