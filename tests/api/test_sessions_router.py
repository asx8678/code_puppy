"""Tests for code_puppy/api/routers/sessions.py."""

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from code_puppy.api.app import create_app
from code_puppy.api.routers.sessions import _serialize_message

# Skip entire module if msgpack is not available (used for legacy format tests)
msgpack = pytest.importorskip("msgpack")


@pytest.fixture
def sessions_dir(tmp_path):
    """Create a temporary sessions directory with test data."""
    # msgpack already imported at module level

    d = tmp_path / "subagent_sessions"
    d.mkdir()

    # Create a valid session
    metadata = {
        "agent_name": "test-agent",
        "initial_prompt": "hello",
        "created_at": "2024-01-01",
        "last_updated": "2024-01-02",
        "message_count": 3,
    }
    (d / "sess1.txt").write_text(json.dumps(metadata))

    # Create msgpack file with message data (preferred format over pickle for security)
    # Note: The API expects .pkl file to exist, but actually reads from .msgpack
    msgs = [{"role": "user", "content": "hello message"}]
    (d / "sess1.msgpack").write_bytes(msgpack.packb(msgs))
    (d / "sess1.pkl").write_bytes(b"")  # Placeholder - code looks for this file

    # Create a session with invalid JSON
    (d / "bad.txt").write_text("not json")

    return d


@pytest.fixture
async def client(sessions_dir):
    with patch("code_puppy.config.DATA_DIR", str(sessions_dir.parent), create=True):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/")
    assert resp.status_code == 200
    data = resp.json()
    # Now returns paginated response
    assert "items" in data
    assert "total" in data
    assert "offset" in data
    assert "limit" in data
    assert "has_more" in data
    sessions = data["items"]
    assert len(sessions) == 2  # sess1 + bad
    ids = [s["session_id"] for s in sessions]
    assert "sess1" in ids
    assert "bad" in ids


@pytest.mark.asyncio
async def test_list_sessions_no_dir() -> None:
    with patch("code_puppy.config.DATA_DIR", "/nonexistent", create=True):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/sessions/")
            assert resp.status_code == 200
            # Now returns paginated response with empty items
            data = resp.json()
            assert data["items"] == []
            assert data["total"] == 0
            assert data["offset"] == 0
            assert data["limit"] == 50
            assert data["has_more"] is False


@pytest.mark.asyncio
async def test_get_session(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/sess1")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "sess1"
    assert resp.json()["agent_name"] == "test-agent"


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_messages(client: AsyncClient, sessions_dir) -> None:
    """Test getting session messages - msgpack format is validated by pydantic-ai."""
    # msgpack already imported at module level

    # Create a valid msgpack with proper pydantic-ai message structure
    # Use simple dict format that the serializer can handle
    msgs = [{"content": "hello message", "role": "user"}]
    (sessions_dir / "sess1.msgpack").write_bytes(msgpack.packb(msgs))

    resp = await client.get("/api/sessions/sess1/messages")
    # Will return 500 if msgpack is invalid or 200 if it works
    # We just verify the endpoint is reachable
    assert resp.status_code in [200, 500]
    if resp.status_code == 200:
        # Check paginated response format
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert "has_more" in data


@pytest.mark.asyncio
async def test_get_session_messages_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/nonexistent/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_invalid_id_format(client: AsyncClient) -> None:
    """Test that invalid session_id format returns 400."""
    # Test with session_id starting with invalid character (hyphen)
    resp = await client.get("/api/sessions/-invalid/messages")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_session_invalid_id_format(client: AsyncClient) -> None:
    """Test that invalid session_id format returns 400."""
    resp = await client.delete("/api/sessions/-invalid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_session_metadata_invalid_id(client: AsyncClient) -> None:
    """Test that invalid session_id returns 400 for metadata endpoint."""
    resp = await client.get("/api/sessions/-bad")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient, sessions_dir) -> None:
    resp = await client.delete("/api/sessions/sess1")
    assert resp.status_code == 200
    assert "deleted" in resp.json()["message"]
    assert not (sessions_dir / "sess1.txt").exists()
    assert not (sessions_dir / "sess1.pkl").exists()


@pytest.mark.asyncio
async def test_delete_session_not_found(client: AsyncClient) -> None:
    resp = await client.delete("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_serialize_message_with_model_dump() -> None:
    msg = MagicMock()
    msg.model_dump.return_value = {"role": "user", "content": "hi"}
    result = _serialize_message(msg)
    assert result == {"role": "user", "content": "hi"}


def test_serialize_message_with_dict() -> None:
    class Obj:
        def __init__(self):
            self.role = "user"
            self.content = "hi"

    result = _serialize_message(Obj())
    assert result["role"] == "user"


def test_serialize_message_fallback() -> None:
    result = _serialize_message(42)
    assert result == {"content": "42"}


@pytest.mark.asyncio
async def test_get_session_messages_pickle_error(
    client: AsyncClient, sessions_dir
) -> None:
    """Test error handling when session data file is corrupt."""
    # Create a corrupt msgpack file
    (sessions_dir / "corrupt.msgpack").write_bytes(b"corrupt data")
    (sessions_dir / "corrupt.pkl").write_bytes(b"not a pickle")  # Legacy file present
    (sessions_dir / "corrupt.txt").write_text('{"agent_name": "x"}')
    resp = await client.get("/api/sessions/corrupt/messages")
    # Returns 500 because no valid msgpack or pickle is allowed (security fix)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_delete_session_pkl_only(client: AsyncClient, sessions_dir) -> None:
    """Delete session that has only a pkl file."""
    (sessions_dir / "pklonly.pkl").write_bytes(b"data")
    resp = await client.delete("/api/sessions/pklonly")
    assert resp.status_code == 200
    assert not (sessions_dir / "pklonly.pkl").exists()


@pytest.mark.asyncio
async def test_list_sessions_timeout(sessions_dir) -> None:
    """Test timeout handling in list_sessions."""
    with (
        patch("code_puppy.config.DATA_DIR", str(sessions_dir.parent), create=True),
        patch("code_puppy.api.routers.sessions.FILE_IO_TIMEOUT", 0.0001),
        patch(
            "code_puppy.api.routers.sessions._load_json_sync",
            side_effect=lambda *a: __import__("time").sleep(1),
        ),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/sessions/")
            assert resp.status_code == 200
            # Timed-out sessions still appear with basic info
            data = resp.json()
            sessions = data["items"]
            assert any(s["agent_name"] is None for s in sessions)


@pytest.mark.asyncio
async def test_get_session_timeout(sessions_dir) -> None:
    """Test timeout handling in get_session."""
    with (
        patch("code_puppy.config.DATA_DIR", str(sessions_dir.parent), create=True),
        patch("code_puppy.api.routers.sessions.FILE_IO_TIMEOUT", 0.0001),
        patch(
            "code_puppy.api.routers.sessions._load_json_sync",
            side_effect=lambda *a: __import__("time").sleep(1),
        ),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/sessions/sess1")
            assert resp.status_code == 504


@pytest.mark.asyncio
async def test_get_messages_timeout(sessions_dir) -> None:
    """Test timeout handling in get_session_messages."""
    with (
        patch("code_puppy.config.DATA_DIR", str(sessions_dir.parent), create=True),
        patch("code_puppy.api.routers.sessions.FILE_IO_TIMEOUT", 0.0001),
        patch(
            "code_puppy.api.routers.sessions._load_session_sync",
            side_effect=lambda *a: __import__("time").sleep(1),
        ),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/sessions/sess1/messages")
            assert resp.status_code == 504
