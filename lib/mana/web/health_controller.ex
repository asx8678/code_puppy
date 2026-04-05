defmodule Mana.Web.HealthController do
  @moduledoc """
  Simple health check controller for the web interface.

  Returns 200 OK for load balancers and monitoring systems.
  """

  use Phoenix.Controller, formats: [:json]

  @doc """
  Health check endpoint.

  Returns a 200 OK response indicating the service is running.
  """
  def index(conn, _params) do
    conn
    |> put_status(:ok)
    |> json(%{status: "ok", service: "mana"})
  end
end
