defmodule CodePuppyControlWeb.HealthControllerTest do
  use CodePuppyControlWeb.ConnCase, async: true

  describe "GET /health/runtime" do
    test "returns 200 with runtime snapshot" do
      conn =
        build_conn()
        |> get("/health/runtime")

      body = json_response(conn, 200)

      assert %{"processes" => %{"current" => _, "limit" => _}} = body
      assert %{"supervisors" => supervisors} = body
      assert Map.has_key?(supervisors, "python_workers")
      assert %{"limits" => limits} = body
      assert Map.has_key?(limits, "max_python_workers")
    end
  end
end
