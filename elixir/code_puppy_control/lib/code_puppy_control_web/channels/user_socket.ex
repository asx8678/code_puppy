defmodule CodePuppyControlWeb.UserSocket do
  @moduledoc """
  Phoenix Socket for WebSocket connections.

  This socket handles client connections to the real-time event system.
  Clients connect via WebSocket and then join channels for sessions or runs.

  ## Channels

  - `"session:*"` - SessionChannel: Events for all runs in a session
  - `"run:*"` - RunChannel: Events for a specific run only

  ## Connection

  No authentication is currently required - any client can connect.
  Future versions may add token-based authentication.

  ## Example Client Usage (JavaScript)

      let socket = new Phoenix.Socket("/socket")
      socket.connect()

      let sessionChannel = socket.channel("session:session-123", {replay: true})
      sessionChannel.join()
        .receive("ok", resp => console.log("Joined session", resp))
        .receive("error", resp => console.log("Failed to join", resp))

      sessionChannel.on("event", event => console.log("Got event:", event))
      sessionChannel.on("replay", ({events, cursor}) => {
        console.log("Replayed", events.length, "events")
      })

  ## Protocol

  Messages follow Phoenix Channel protocol:
  - Heartbeat every 30s
  - Events pushed from server: `{"event", payload}`
  - Messages from client: `{"event_name", payload}` with reply
  """

  use Phoenix.Socket

  require Logger

  # ============================================================================
  # Channels
  # ============================================================================

  channel "session:*", CodePuppyControlWeb.SessionChannel
  channel "run:*", CodePuppyControlWeb.RunChannel

  # ============================================================================
  # Connection
  # ============================================================================

  @doc """
  Verify and identify the socket connection.

  Currently accepts all connections without authentication.
  Future versions may:
  - Validate API tokens
  - Check session permissions
  - Rate limit connections

  ## Socket ID

  Returns `nil` since we don't track socket identities yet.
  This means broadcasts to `socket_id` won't reach any socket.
  """
  @impl true
  def connect(params, socket, connect_info) do
    Logger.debug("UserSocket: client connecting with params #{inspect(params)}")

    # Store connection metadata
    socket =
      socket
      |> assign(:connected_at, DateTime.utc_now())
      |> assign(:connect_info, connect_info)
      |> assign(:client_params, params)

    # Future: Add authentication here
    # token = params["token"]
    # case authenticate(token) do
    #   {:ok, user} -> {:ok, assign(socket, :current_user, user)}
    #   {:error, reason} -> {:error, reason}
    # end

    {:ok, socket}
  end

  @doc """
  Return the socket ID for identifying the socket server side.

  Currently returns `nil` as we don't need to identify specific sockets.
  If we add user authentication, this would return a unique identifier
  for broadcasting to specific users.
  """
  @impl true
  def id(_socket) do
    # Future: Return user-specific ID for targeted broadcasts
    # "user_socket:#{socket.assigns.current_user.id}"
    nil
  end

  # ============================================================================
  # Private Functions (for future use)
  # ============================================================================

  # defp authenticate(nil), do: {:error, :missing_token}
  # defp authenticate(token) do
  #   # Validate JWT or API token
  #   case Phoenix.Token.verify(socket, "user salt", token, max_age: 86400) do
  #     {:ok, user_id} -> {:ok, %{id: user_id}}
  #     {:error, reason} -> {:error, reason}
  #   end
  # end
end
