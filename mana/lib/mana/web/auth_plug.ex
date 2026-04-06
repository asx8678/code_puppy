defmodule Mana.Web.AuthPlug do
  @moduledoc """
  Token-based authentication plug for the Mana web interface.

  Provides simple authentication for the Phoenix LiveView interface:
  - Checks for auth token in query params, headers, or session
  - If no token is configured (dev mode), allows all access
  - If token is configured, requires matching token
  - Returns 401 if authentication fails

  ## Configuration

  Set the auth token via environment variable:

      MANA_WEB_TOKEN=your-secret-token

  Or in config/runtime.exs:

      config :mana, :web_auth_token, System.get_env("MANA_WEB_TOKEN")

  ## Usage

  Add to your router pipeline:

      pipeline :browser do
        plug(:accepts, ["html"])
        plug(Mana.Web.AuthPlug)
        # ... other plugs
      end

  ## Authentication Methods

  1. Query parameter: `?token=your-secret-token`
  2. Header: `Authorization: Bearer your-secret-token`
  3. Session: previously authenticated via above methods

  """

  import Plug.Conn

  require Logger

  @session_key :mana_web_auth

  @doc """
  Initialize the plug with options.
  """
  @spec init(Keyword.t()) :: Keyword.t()
  def init(opts), do: opts

  @doc """
  Call the plug to authenticate the request.

  If no token is configured, allows all access (development mode).
  If a token is configured, checks for a matching token in:
  - Query parameters (?token=...)
  - Authorization header (Bearer ...)
  - Session (if previously authenticated)

  Returns 401 if authentication fails.
  """
  @spec call(Plug.Conn.t(), Keyword.t()) :: Plug.Conn.t()
  def call(conn, _opts) do
    configured_token = Application.get_env(:mana, :web_auth_token)

    case configured_token do
      nil ->
        # No token configured - dev mode, allow all access
        conn

      "" ->
        # Empty token configured - dev mode, allow all access
        conn

      token when is_binary(token) ->
        # Token configured - require authentication
        authenticate_request(conn, token)
    end
  end

  # Authenticate the request against the configured token
  defp authenticate_request(conn, expected_token) do
    if authenticated?(conn, expected_token) do
      # Mark as authenticated in session for future requests
      conn
      |> put_session(@session_key, true)
      |> put_private(:mana_web_authenticated, true)
    else
      halt_unauthorized(conn)
    end
  end

  # Check if the request is authenticated via any method
  defp authenticated?(conn, expected_token) do
    # Check session first (previously authenticated)
    if get_session(conn, @session_key) do
      true
    else
      # Check query param or header
      token_from_query(conn) == expected_token or
        token_from_header(conn) == expected_token
    end
  end

  # Extract token from query parameters
  defp token_from_query(conn) do
    conn.query_params["token"] || conn.params["token"]
  end

  # Extract token from Authorization header (Bearer token)
  defp token_from_header(conn) do
    case get_req_header(conn, "authorization") do
      ["Bearer " <> token] -> token
      ["bearer " <> token] -> token
      _ -> nil
    end
  end

  # Halt the connection with 401 Unauthorized
  defp halt_unauthorized(conn) do
    Logger.warning("Unauthorized access attempt to Mana web interface from #{conn.remote_ip}")

    conn
    |> put_resp_content_type("text/html")
    |> send_resp(401, unauthorized_html())
    |> halt()
  end

  # HTML response for unauthorized access
  defp unauthorized_html do
    """
    <!DOCTYPE html>
    <html>
    <head>
      <title>401 - Unauthorized</title>
      <style>
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          display: flex;
          justify-content: center;
          align-items: center;
          height: 100vh;
          margin: 0;
          background: #f9fafb;
        }
        .error-container {
          text-align: center;
          padding: 40px;
          background: white;
          border-radius: 12px;
          box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
          max-width: 400px;
        }
        h1 {
          color: #dc2626;
          font-size: 48px;
          margin: 0 0 16px 0;
        }
        h2 {
          color: #374151;
          font-size: 24px;
          margin: 0 0 16px 0;
        }
        p {
          color: #6b7280;
          margin: 0 0 24px 0;
          line-height: 1.5;
        }
        code {
          background: #f3f4f6;
          padding: 2px 6px;
          border-radius: 4px;
          font-family: monospace;
          font-size: 14px;
        }
      </style>
    </head>
    <body>
      <div class="error-container">
        <h1>401</h1>
        <h2>Unauthorized</h2>
        <p>
          Access to the Mana web interface requires authentication.
          Please provide a valid token via query parameter
          (<code>?token=YOUR_TOKEN</code>) or
          Authorization header (<code>Bearer YOUR_TOKEN</code>).
        </p>
        <p>
          Set <code>MANA_WEB_TOKEN</code> environment variable to configure
          the authentication token.
        </p>
      </div>
    </body>
    </html>
    """
  end
end
