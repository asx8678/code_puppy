defmodule Mana.Web.HealthController do
  @moduledoc """
  Health check controller for the web interface.

  Returns health status including:
  - Service status (healthy/degraded)
  - Number of live children in the supervisor tree
  - Mana version

  Used by load balancers and monitoring systems.

  The actual introspection logic lives in `Mana.Health` so it can be
  shared with the `synthetic_status` plugin without duplication.
  """

  use Phoenix.Controller, formats: [:json]

  alias Mana.Health

  @doc """
  Basic health check endpoint (legacy).

  Returns a simple 200 OK response indicating the service is running.
  """
  def index(conn, _params) do
    conn
    |> put_status(:ok)
    |> json(%{status: "ok", service: "mana"})
  end

  @doc """
  Enhanced health check endpoint with supervisor tree status.

  Returns detailed health information:
  - `status`: "healthy" | "degraded"
  - `children`: count of live processes in the supervisor tree
  - `version`: the current Mana version

  ## Health Determination

  Status is "healthy" if the main supervisor (`Mana.Supervisor`) has at least
  the expected minimum number of children running. This indicates the core
  services (Plugin.Manager, Callbacks.Registry, MessageBus, etc.) are operational.

  Status is "degraded" if the supervisor tree is not fully operational.
  """
  def check(conn, _params) do
    health_info = Health.check()

    status_code = if health_info.status == "healthy", do: 200, else: 503

    conn
    |> put_status(status_code)
    |> json(health_info)
  end
end
