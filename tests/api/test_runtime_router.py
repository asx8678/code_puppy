"""Tests for code_puppy/api/routers/runtime.py — runtime API endpoints.

All runtime endpoints now require authentication via the
X-Code-Puppy-Runtime-Token header or cookie.  Tests patch the auth
dependency to bypass it for unit testing the route logic.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from code_puppy.api.routers.runtime import router


@pytest.fixture
def authed_app() -> FastAPI:
    """App with auth dependency overridden for route-logic testing."""
    from code_puppy.api.auth import require_runtime_auth

    app = FastAPI()
    app.include_router(router, prefix="/api/runtime")
    app.dependency_overrides[require_runtime_auth] = lambda: None
    return app


@pytest.fixture
async def authed_client(authed_app: FastAPI):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_status(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.get_status.return_value = {
            "running": False,
            "current_run": None,
            "recent_runs": [],
            "pending_approvals": [],
        }
        resp = await authed_client.get("/api/runtime/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False


@pytest.mark.asyncio
async def test_submit_prompt_success(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.submit_prompt = AsyncMock(
            return_value={"run_id": "abc", "status": "queued", "prompt_preview": "hi"}
        )
        resp = await authed_client.post(
            "/api/runtime/prompt",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "abc"


@pytest.mark.asyncio
async def test_submit_prompt_conflict(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.submit_prompt = AsyncMock(
            side_effect=RuntimeError("A prompt is already running")
        )
        resp = await authed_client.post(
            "/api/runtime/prompt",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_submit_prompt_empty(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.submit_prompt = AsyncMock(
            side_effect=ValueError("Prompt cannot be empty")
        )
        resp = await authed_client.post(
            "/api/runtime/prompt",
            json={"prompt": ""},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_run(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.cancel_current_run = AsyncMock(
            return_value={"cancelled": True, "run_id": "r1"}
        )
        resp = await authed_client.post("/api/runtime/cancel", json={"reason": "stop"})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True


@pytest.mark.asyncio
async def test_respond_to_bus_request(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_bus_request.return_value = {
            "ok": True,
            "prompt_id": "p1",
        }
        resp = await authed_client.post(
            "/api/runtime/respond",
            json={"prompt_id": "p1", "response_type": "input", "value": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_respond_to_bus_bad_type(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_bus_request.side_effect = ValueError(
            "Unsupported response type"
        )
        resp = await authed_client.post(
            "/api/runtime/respond",
            json={"prompt_id": "p1", "response_type": "bad"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_respond_to_approval_success(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_approval.return_value = {
            "ok": True,
            "approval_id": "a1",
            "approved": True,
        }
        resp = await authed_client.post(
            "/api/runtime/approval",
            json={"approval_id": "a1", "approved": True},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_respond_to_approval_not_found(authed_client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_approval.side_effect = ValueError(
            "Approval request not found"
        )
        resp = await authed_client.post(
            "/api/runtime/approval",
            json={"approval_id": "missing", "approved": False},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_events(authed_client: AsyncClient) -> None:
    with patch(
        "code_puppy.plugins.frontend_emitter.emitter.clear_recent_events"
    ) as mock_clear:
        resp = await authed_client.delete("/api/runtime/events")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_clear.assert_called_once()


# ---------------------------------------------------------------------------
# Auth-gated endpoint tests (without patching auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_prompt_too_long(authed_client: AsyncClient) -> None:
    """Prompt exceeding max_length=100_000 is rejected by Pydantic validation."""
    resp = await authed_client.post(
        "/api/runtime/prompt",
        json={"prompt": "x" * 100_001},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_status_requires_auth() -> None:
    """GET /api/runtime/status returns 401 without a token."""
    import tempfile

    app = FastAPI()
    app.include_router(router, prefix="/api/runtime")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "code_puppy.api.auth._token_path",
                return_value=Path(tmpdir) / "rt",
            ):
                from code_puppy.api.auth import get_or_create_runtime_token

                get_or_create_runtime_token()
                resp = await c.get("/api/runtime/status")
                assert resp.status_code == 401


@pytest.mark.asyncio
async def test_status_with_valid_token() -> None:
    """GET /api/runtime/status returns 200 with a valid token."""
    import tempfile

    from code_puppy.api.auth import _HEADER_NAME, get_or_create_runtime_token

    app = FastAPI()
    app.include_router(router, prefix="/api/runtime")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "code_puppy.api.auth._token_path",
                return_value=Path(tmpdir) / "rt",
            ):
                token = get_or_create_runtime_token()
                with patch(
                    "code_puppy.api.routers.runtime.get_runtime_manager"
                ) as mock_mgr:
                    mock_mgr.return_value.get_status.return_value = {
                        "running": False,
                        "current_run": None,
                        "recent_runs": [],
                        "pending_approvals": [],
                    }
                    resp = await c.get(
                        "/api/runtime/status",
                        headers={_HEADER_NAME: token},
                    )
                    assert resp.status_code == 200
