defmodule Mana.Web.Endpoint do
  @moduledoc """
  Phoenix Endpoint for the Mana web interface.

  Serves as the HTTP entry point, handling:
  - WebSocket connections for LiveView
  - Session management via cookies
  - Request parsing (URL-encoded, multipart, JSON)
  - Static file serving (if configured)
  - Routing to the Router

  ## Configuration

  Configure via config/runtime.exs:

      config :mana, Mana.Web.Endpoint,
        url: [host: "localhost"],
        http: [ip: {127, 0, 0, 1}, port: 4000],
        secret_key_base: "your-secret-key",
        server: true

  ## Usage

  Start with the application supervision tree:

      children = [
        Mana.Web.Endpoint
      ]

  Or manually:

      {:ok, _} = Mana.Web.Endpoint.start_link()

  """

  use Phoenix.Endpoint, otp_app: :mana

  @session_options [
    store: :cookie,
    key: "_mana_key",
    signing_salt: "mana_web_salt",
    same_site: "Lax"
  ]

  # WebSocket socket for LiveView
  socket("/live", Phoenix.LiveView.Socket, websocket: [connect_info: [session: @session_options]])

  # Request pipeline plugs
  plug(Plug.RequestId)
  plug(Plug.Telemetry, event_prefix: [:phoenix, :endpoint])

  plug(Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()
  )

  plug(Plug.MethodOverride)
  plug(Plug.Head)
  plug(Plug.Session, @session_options)

  # Router at the end of the pipeline
  plug(Mana.Web.Router)
end
