defmodule CodePuppyControlWeb.CommandsControllerTest do
  use CodePuppyControlWeb.ConnCase, async: true

  # ── GET /api/commands ───────────────────────────────────────────────────

  describe "GET /api/commands" do
    test "returns a list (may include agents from AgentCatalogue)" do
      conn =
        build_conn()
        |> get("/api/commands")

      body = json_response(conn, 200)
      assert is_list(body)
    end
  end

  # ── GET /api/commands/:name ─────────────────────────────────────────────

  describe "GET /api/commands/:name" do
    test "returns 404 for any command name (stub)" do
      conn =
        build_conn()
        |> get("/api/commands/help")

      body = json_response(conn, 404)
      assert body["error"] =~ "not found"
    end
  end

  # ── POST /api/commands/execute ──────────────────────────────────────────

  describe "POST /api/commands/execute" do
    test "returns 501 Not Implemented (stub)" do
      conn =
        build_conn()
        |> post_json("/api/commands/execute", %{command: "/help"})

      body = json_response(conn, 501)
      assert body["error"] =~ "not yet implemented"
    end
  end

  # ── POST /api/commands/autocomplete ─────────────────────────────────────

  describe "POST /api/commands/autocomplete" do
    test "returns empty suggestions (stub)" do
      conn =
        build_conn()
        |> post_json("/api/commands/autocomplete", %{partial: "/se"})

      body = json_response(conn, 200)
      assert is_list(body["suggestions"])
      assert body["suggestions"] == []
    end
  end
end
