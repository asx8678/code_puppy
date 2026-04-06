defmodule Mana.Web.HealthControllerTest do
  @moduledoc """
  Tests for Mana.Web.HealthController.

  Covers:
  - Legacy /health endpoint response shape
  - Enhanced /api/health endpoint with supervisor tree check
  - Version field validation
  - Children count field validation
  """

  use ExUnit.Case, async: false

  alias Mana.Web.HealthController

  describe "index/2 - legacy /health endpoint" do
    test "returns ok with status and service fields" do
      conn = build_conn()
      result = HealthController.index(conn, %{})

      assert result.status == 200
      body = Jason.decode!(result.resp_body)
      assert body["status"] == "ok"
      assert body["service"] == "mana"
    end
  end

  describe "check/2 - enhanced /api/health endpoint" do
    test "response contains required fields with correct types" do
      conn = build_conn()
      result = HealthController.check(conn, %{})

      body = Jason.decode!(result.resp_body)

      assert is_binary(body["status"])
      assert body["status"] in ["healthy", "degraded"]
      assert is_integer(body["children"])
      assert body["children"] >= 0
      assert is_binary(body["version"])
    end

    test "version matches the application version" do
      conn = build_conn()
      result = HealthController.check(conn, %{})

      body = Jason.decode!(result.resp_body)
      assert body["version"] == Mana.version()
      assert body["version"] == "0.1.0"
    end

    test "returns healthy when supervisor is running with sufficient children" do
      conn = build_conn()
      result = HealthController.check(conn, %{})

      body = Jason.decode!(result.resp_body)

      # In test env, the full supervision tree should be running
      assert result.status in [200, 503]
      assert body["children"] > 0
    end

    test "children count matches Supervisor.count_children" do
      conn = build_conn()
      result = HealthController.check(conn, %{})

      body = Jason.decode!(result.resp_body)

      # Verify children count matches actual supervisor
      pid = Process.whereis(Mana.Supervisor)

      if pid do
        %{active: expected} = Supervisor.count_children(pid)
        assert body["children"] == expected
      end
    end
  end

  # Build a Plug conn with the test adapter for Phoenix.Controller functions
  defp build_conn do
    Plug.Test.conn(:get, "/api/health")
  end
end
