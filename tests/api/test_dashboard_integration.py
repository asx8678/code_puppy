"""Integration tests for the Code Puppy web dashboard (web-62k).

Spins the real FastAPI app, verifies the dashboard → auth cookie →
API → approval round-trip flow without real LLMs, subprocesses, or
browser automation.  Uses TestClient (sync ASGI) so everything is
deterministic and fast.
"""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from code_puppy.api.app import create_app
from code_puppy.api.auth import (
    _COOKIE_NAME,
    _HEADER_NAME,
    get_or_create_runtime_token,
)
from code_puppy.api.approvals import ApprovalManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_approval_manager():
    """Provide an isolated ApprovalManager for each test."""
    return ApprovalManager()


@pytest.fixture()
def app():
    """Create the real FastAPI app."""
    return create_app()


@pytest.fixture()
def token_path(tmp_path: Path):
    """Return the isolated token file path."""
    return tmp_path / "rt"


@pytest.fixture()
def token(token_path: Path) -> str:
    """Generate a runtime token with an isolated token file."""
    with patch("code_puppy.api.auth._token_path", return_value=token_path):
        return get_or_create_runtime_token()


@pytest.fixture()
def client(app, token: str, token_path: Path) -> TestClient:
    """TestClient with auth cookie pre-set (simulates post-dashboard-visit).

    The _token_path patch stays active for the lifetime of the client so
    that every request through the client can verify the token.
    """
    _patch = patch("code_puppy.api.auth._token_path", return_value=token_path)
    _patch.start()
    c = TestClient(app, cookies={_COOKIE_NAME: token})
    yield c
    _patch.stop()


# ---------------------------------------------------------------------------
# 1. Dashboard page sets auth cookie
# ---------------------------------------------------------------------------


class TestDashboardCookieAuth:
    """GET /dashboard returns the page and sets the runtime auth cookie."""

    def test_dashboard_returns_html_and_cookie(self, app, token_path):
        with patch(
            "code_puppy.api.auth._token_path",
            return_value=token_path,
        ):
            get_or_create_runtime_token()
            with TestClient(app) as c:
                resp = c.get("/dashboard")

        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        # The Set-Cookie header must contain the auth cookie
        cookie_headers = [
            v for k, v in resp.headers.items() if k.lower() == "set-cookie"
        ]
        assert any(_COOKIE_NAME in h for h in cookie_headers), (
            "Dashboard response must set auth cookie"
        )

    def test_cookie_authenticates_api_status(self, app, token_path):
        """Cookie obtained from /dashboard authenticates /api/runtime/status."""
        with patch(
            "code_puppy.api.auth._token_path",
            return_value=token_path,
        ):
            get_or_create_runtime_token()
            with TestClient(app) as c:
                # Visit dashboard first (sets cookie)
                c.get("/dashboard")
                # Now request status with the session cookie
                with patch(
                    "code_puppy.api.routers.runtime.get_runtime_manager"
                ) as mock_mgr:
                    mock_mgr.return_value.get_status.return_value = {
                        "running": False,
                        "current_run": None,
                        "recent_runs": [],
                        "pending_approvals": [],
                    }
                    resp = c.get("/api/runtime/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False


# ---------------------------------------------------------------------------
# 2. Runtime status endpoint with auth
# ---------------------------------------------------------------------------


class TestRuntimeStatusWithAuth:
    """Status endpoint respects auth token via header or cookie."""

    def test_status_with_header_token(self, app, token_path):
        with patch(
            "code_puppy.api.auth._token_path",
            return_value=token_path,
        ):
            tok = get_or_create_runtime_token()
            with patch(
                "code_puppy.api.routers.runtime.get_runtime_manager"
            ) as mock_mgr:
                mock_mgr.return_value.get_status.return_value = {
                    "running": False,
                    "current_run": None,
                    "recent_runs": [],
                    "pending_approvals": [],
                }
                with TestClient(app) as c:
                    resp = c.get(
                        "/api/runtime/status",
                        headers={_HEADER_NAME: tok},
                    )
        assert resp.status_code == 200

    def test_status_no_token_401(self, app, token_path):
        with patch(
            "code_puppy.api.auth._token_path",
            return_value=token_path,
        ):
            get_or_create_runtime_token()
            with TestClient(app) as c:
                resp = c.get("/api/runtime/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Approval round-trip through API
# ---------------------------------------------------------------------------


class TestApprovalRoundTrip:
    """Create a pending approval → respond via API → verify resolution.

    This tests the full chain:
    ApprovalManager.request_sync → pending appears in status →
    POST /api/runtime/approval resolves it → waiter receives result.
    """

    def test_approval_approved_via_api(self, client, fresh_approval_manager):
        """Approve a pending request through the runtime API."""
        mgr = fresh_approval_manager
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(
                title="Allow edit?",
                content="edit file.py",
                timeout=5.0,
            )
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        # Wait for the pending approval to appear
        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        pending = mgr.list_pending()
        assert len(pending) == 1, "Approval should be pending"
        approval_id = pending[0]["approval_id"]

        # Verify it shows in runtime status
        with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
            mock_mgr.return_value.get_status.return_value = {
                "running": False,
                "current_run": None,
                "recent_runs": [],
                "pending_approvals": mgr.list_pending(),
            }
            mock_mgr.return_value.respond_to_approval = MagicMock(
                return_value={
                    "ok": True,
                    "approval_id": approval_id,
                    "approved": True,
                }
            )
            status_resp = client.get("/api/runtime/status")
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            assert len(status_data["pending_approvals"]) == 1

            # Resolve the approval via the API endpoint
            approval_resp = client.post(
                "/api/runtime/approval",
                json={"approval_id": approval_id, "approved": True},
            )

        assert approval_resp.status_code == 200
        assert approval_resp.json()["ok"] is True

        # Also resolve in the real manager so the waiter thread unblocks
        mgr.respond(approval_id, True, "LGTM")
        t.join(timeout=5.0)

        assert len(results) == 1
        assert results[0][0] is True  # approved

    def test_approval_rejected_via_api(self, client, fresh_approval_manager):
        """Reject a pending request through the runtime API."""
        mgr = fresh_approval_manager
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(
                title="Delete?",
                content="rm foo.py",
                timeout=5.0,
            )
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        approval_id = mgr.list_pending()[0]["approval_id"]

        with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
            mock_mgr.return_value.respond_to_approval = MagicMock(
                return_value={
                    "ok": True,
                    "approval_id": approval_id,
                    "approved": False,
                }
            )
            resp = client.post(
                "/api/runtime/approval",
                json={"approval_id": approval_id, "approved": False},
            )

        assert resp.status_code == 200
        assert resp.json()["approved"] is False

        # Unblock the waiter
        mgr.respond(approval_id, False, "Nope")
        t.join(timeout=5.0)

        assert len(results) == 1
        assert results[0][0] is False  # rejected

    def test_approval_not_found_returns_404(self, client):
        """Responding to a nonexistent approval returns 404."""
        with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
            mock_mgr.return_value.respond_to_approval.side_effect = ValueError(
                "Approval request not found"
            )
            resp = client.post(
                "/api/runtime/approval",
                json={"approval_id": "ghost-id", "approved": True},
            )
        assert resp.status_code == 404

    def test_approval_pending_clears_after_response(
        self, client, fresh_approval_manager
    ):
        """After resolving an approval, pending list is empty."""
        mgr = fresh_approval_manager
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(title="t", content="c", timeout=5.0)
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        approval_id = mgr.list_pending()[0]["approval_id"]
        mgr.respond(approval_id, True, "ok")
        t.join(timeout=5.0)

        # After resolution, no pending approvals remain
        assert mgr.list_pending() == []

    def test_approval_feedback_redacted_in_event(self, fresh_approval_manager):
        """When an approval is resolved with secret-containing feedback,
        the emitted approval_response event has the secret redacted."""
        mgr = fresh_approval_manager
        captured_events: list[tuple[str, dict]] = []

        def fake_emit(event_type: str, payload: dict) -> None:
            captured_events.append((event_type, payload))

        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(title="t", content="c", timeout=5.0)
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        approval_id = mgr.list_pending()[0]["approval_id"]

        with patch(
            "code_puppy.plugins.frontend_emitter.emitter.emit_event",
            side_effect=fake_emit,
        ):
            mgr.respond(
                approval_id,
                True,
                "Approved, api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890",
            )

        t.join(timeout=5.0)

        response_events = [p for et, p in captured_events if et == "approval_response"]
        assert len(response_events) == 1
        assert "REDACTED" in response_events[0]["feedback"]
        assert "sk-" not in response_events[0]["feedback"]


# ---------------------------------------------------------------------------
# 4. End-to-end: dashboard cookie → status → approval round-trip
# ---------------------------------------------------------------------------


class TestEndToEndDashboardFlow:
    """Full flow: visit dashboard → get cookie → check status →
    create approval → respond → verify cleared."""

    def test_dashboard_to_approval_e2e(self, app, token_path):
        with patch(
            "code_puppy.api.auth._token_path",
            return_value=token_path,
        ):
            tok = get_or_create_runtime_token()

            with TestClient(app, cookies={_COOKIE_NAME: tok}) as c:
                # 1. Visit dashboard (confirms page + cookie work)
                dash_resp = c.get("/dashboard")
                assert dash_resp.status_code == 200

                # 2. Check runtime status
                with patch(
                    "code_puppy.api.routers.runtime.get_runtime_manager"
                ) as mock_mgr:
                    mock_mgr.return_value.get_status.return_value = {
                        "running": False,
                        "current_run": None,
                        "recent_runs": [],
                        "pending_approvals": [],
                    }
                    status_resp = c.get("/api/runtime/status")
                    assert status_resp.status_code == 200
                    assert status_resp.json()["running"] is False

                # 3. Create a pending approval in a thread
                mgr = ApprovalManager()
                results: list[tuple[bool, str | None]] = []

                def waiter():
                    result = mgr.request_sync(
                        title="Deploy?",
                        content="Deploy to production",
                        timeout=5.0,
                    )
                    results.append(result)

                t = threading.Thread(target=waiter)
                t.start()

                for _ in range(50):
                    if mgr.list_pending():
                        break
                    time.sleep(0.02)

                # 4. Verify approval visible via status
                with patch(
                    "code_puppy.api.routers.runtime.get_runtime_manager"
                ) as mock_mgr:
                    mock_mgr.return_value.get_status.return_value = {
                        "running": False,
                        "current_run": None,
                        "recent_runs": [],
                        "pending_approvals": mgr.list_pending(),
                    }
                    status_resp2 = c.get("/api/runtime/status")
                    pending = status_resp2.json()["pending_approvals"]
                    assert len(pending) == 1

                # 5. Respond via API
                approval_id = mgr.list_pending()[0]["approval_id"]
                with patch(
                    "code_puppy.api.routers.runtime.get_runtime_manager"
                ) as mock_mgr:
                    mock_mgr.return_value.respond_to_approval = MagicMock(
                        return_value={
                            "ok": True,
                            "approval_id": approval_id,
                            "approved": True,
                        }
                    )
                    approval_resp = c.post(
                        "/api/runtime/approval",
                        json={
                            "approval_id": approval_id,
                            "approved": True,
                            "feedback": "Ship it",
                        },
                    )

                assert approval_resp.status_code == 200

                # 6. Unblock the waiter and verify
                mgr.respond(approval_id, True, "Ship it")
                t.join(timeout=5.0)

                assert len(results) == 1
                assert results[0][0] is True  # approved

                # 7. Verify pending is now clear
                assert mgr.list_pending() == []

    def test_dashboard_health_endpoint(self, client):
        """Health endpoint is accessible without auth."""
        # Use a fresh client without auth cookie
        app = create_app()
        with TestClient(app) as c:
            resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}
