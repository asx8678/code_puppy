defmodule Mana.Web.HealthController do
  @moduledoc """
  Health check controller for the web interface.

  Returns health status including:
  - Service status (healthy/degraded)
  - Number of live children in the supervisor tree
  - Mana version

  Used by load balancers and monitoring systems.
  """

  use Phoenix.Controller, formats: [:json]

  require Logger

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
    health_info = build_health_response()

    status_code = if health_info.status == "healthy", do: 200, else: 503

    conn
    |> put_status(status_code)
    |> json(health_info)
  end

  # Builds the health response by checking the supervisor tree
  defp build_health_response do
    version = Mana.version()
    supervisor_children = get_supervisor_children_count()
    status = determine_health_status(supervisor_children)

    %{
      status: status,
      children: supervisor_children,
      version: version
    }
  end

  # Gets the count of active children in Mana.Supervisor
  # Returns 0 if the supervisor is not running (indicating degraded state)
  defp get_supervisor_children_count do
    case Process.whereis(Mana.Supervisor) do
      nil ->
        Logger.warning("Health check: Mana.Supervisor is not registered")
        0

      pid ->
        %{active: active} = Supervisor.count_children(pid)
        active
    end
  end

  # Minimum expected children for a healthy system.
  # Based on children defined in Mana.Application.start/2
  # Adjust this based on configuration (auto_start, web endpoint, etc.)
  @min_expected_children 3

  defp determine_health_status(0), do: "degraded"

  defp determine_health_status(count) when is_integer(count) and count > 0 do
    if count >= @min_expected_children do
      "healthy"
    else
      "degraded"
    end
  end

  defp determine_health_status(_), do: "degraded"
end
