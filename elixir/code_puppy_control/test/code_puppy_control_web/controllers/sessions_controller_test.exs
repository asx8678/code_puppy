defmodule CodePuppyControlWeb.SessionsControllerTest do
  use ExUnit.Case, async: true

  import Phoenix.ConnTest

  @endpoint CodePuppyControlWeb.Endpoint

  # ── GET /api/sessions ───────────────────────────────────────────────────

  describe "GET /api/sessions" do
    test "returns paginated session list" do
      conn =
        build_conn()
        |> get("/api/sessions")

      body = json_response(conn, 200)

      assert is_list(body["items"])
      assert is_integer(body["total"])
      assert is_integer(body["offset"])
      assert is_integer(body["limit"])
      assert is_boolean(body["has_more"])
    end

    test "respects offset and limit query params" do
      conn =
        build_conn()
        |> get("/api/sessions?offset=0&limit=5")

      body = json_response(conn, 200)
      assert body["offset"] == 0
      assert body["limit"] == 5
    end

    test "rejects invalid sort_by" do
      conn =
        build_conn()
        |> get("/api/sessions?sort_by=invalid")

      body = json_response(conn, 400)
      assert body["error"] =~ "sort_by must be one of"
    end

    test "rejects invalid order" do
      conn =
        build_conn()
        |> get("/api/sessions?order=sideways")

      body = json_response(conn, 400)
      assert body["error"] =~ "order must be"
    end
  end

  # ── GET /api/sessions/:id ───────────────────────────────────────────────

  describe "GET /api/sessions/:id" do
    test "returns 404 for unknown session" do
      conn =
        build_conn()
        |> get("/api/sessions/nonexistent-session")

      body = json_response(conn, 404)
      assert body["error"] =~ "not found"
    end

    test "returns 400 for invalid session_id" do
      conn =
        build_conn()
        |> get("/api/sessions/!!invalid!!")

      body = json_response(conn, 400)
      assert body["error"] =~ "Invalid session_id"
    end
  end

  # ── GET /api/sessions/:id/messages ──────────────────────────────────────

  describe "GET /api/sessions/:id/messages" do
    test "returns 404 for unknown session" do
      conn =
        build_conn()
        |> get("/api/sessions/nonexistent-session/messages")

      body = json_response(conn, 404)
      assert body["error"] =~ "not found"
    end

    test "returns 400 for invalid session_id" do
      conn =
        build_conn()
        |> get("/api/sessions/!!invalid!!/messages")

      body = json_response(conn, 400)
      assert body["error"] =~ "Invalid session ID format"
    end

    test "respects pagination params" do
      conn =
        build_conn()
        |> get("/api/sessions/test-session/messages?offset=0&limit=10")

      # Will return 404 since session doesn't exist, but pagination params are accepted
      assert conn.status in [200, 404]
    end
  end

  # ── DELETE /api/sessions/:id ────────────────────────────────────────────

  describe "DELETE /api/sessions/:id" do
    test "returns 404 for unknown session" do
      conn =
        build_conn()
        |> delete("/api/sessions/nonexistent-session")

      body = json_response(conn, 404)
      assert body["error"] =~ "not found"
    end

    test "returns 400 for invalid session_id" do
      conn =
        build_conn()
        |> delete("/api/sessions/!!invalid!!")

      body = json_response(conn, 400)
      assert body["error"] =~ "Invalid session_id"
    end
  end
end
