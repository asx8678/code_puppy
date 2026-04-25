"""Tests for code_puppy/api/routers/runtime.py — runtime API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from code_puppy.api.routers.runtime import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/runtime")
    return app


@pytest.fixture
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_status(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.get_status.return_value = {
            "running": False,
            "current_run": None,
            "recent_runs": [],
            "pending_approvals": [],
        }
        resp = await client.get("/api/runtime/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False


@pytest.mark.asyncio
async def test_submit_prompt_success(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_return = MagicMock()
        mock_return.__await__ = lambda _: (
            r for r in [{"run_id": "abc", "status": "queued", "prompt_preview": "hi"}]
        )
        # Make submit_prompt a proper async function
        mock_mgr.return_value.submit_prompt = AsyncMock(
            return_value={"run_id": "abc", "status": "queued", "prompt_preview": "hi"}
        )
        resp = await client.post(
            "/api/runtime/prompt",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "abc"


@pytest.mark.asyncio
async def test_submit_prompt_conflict(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.submit_prompt = AsyncMock(
            side_effect=RuntimeError("A prompt is already running")
        )
        resp = await client.post(
            "/api/runtime/prompt",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_submit_prompt_empty(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.submit_prompt = AsyncMock(
            side_effect=ValueError("Prompt cannot be empty")
        )
        resp = await client.post(
            "/api/runtime/prompt",
            json={"prompt": ""},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_run(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.cancel_current_run = AsyncMock(
            return_value={"cancelled": True, "run_id": "r1"}
        )
        resp = await client.post("/api/runtime/cancel", json={"reason": "stop"})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True


@pytest.mark.asyncio
async def test_respond_to_bus_request(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_bus_request.return_value = {
            "ok": True,
            "prompt_id": "p1",
        }
        resp = await client.post(
            "/api/runtime/respond",
            json={"prompt_id": "p1", "response_type": "input", "value": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_respond_to_bus_bad_type(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_bus_request.side_effect = ValueError(
            "Unsupported response type"
        )
        resp = await client.post(
            "/api/runtime/respond",
            json={"prompt_id": "p1", "response_type": "bad"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_respond_to_approval_success(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_approval.return_value = {
            "ok": True,
            "approval_id": "a1",
            "approved": True,
        }
        resp = await client.post(
            "/api/runtime/approval",
            json={"approval_id": "a1", "approved": True},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_respond_to_approval_not_found(client: AsyncClient) -> None:
    with patch("code_puppy.api.routers.runtime.get_runtime_manager") as mock_mgr:
        mock_mgr.return_value.respond_to_approval.side_effect = ValueError(
            "Approval request not found"
        )
        resp = await client.post(
            "/api/runtime/approval",
            json={"approval_id": "missing", "approved": False},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clear_events(client: AsyncClient) -> None:
    with patch(
        "code_puppy.plugins.frontend_emitter.emitter.clear_recent_events"
    ) as mock_clear:
        resp = await client.delete("/api/runtime/events")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_clear.assert_called_once()
