"""Tests for code_puppy/api/websocket.py."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.api.app import create_app
from code_puppy.api.websocket import _MAX_INPUT_BYTES, _clamp_resize


# ---------------------------------------------------------------------------
# Resize clamping
# ---------------------------------------------------------------------------


class TestClampResize:
    """Tests for terminal resize value clamping."""

    def test_normal_values_unchanged(self) -> None:
        assert _clamp_resize(80, 24) == (80, 24)
        assert _clamp_resize(120, 40) == (120, 40)

    def test_zero_clamped_to_min(self) -> None:
        assert _clamp_resize(0, 0) == (1, 1)

    def test_negative_clamped_to_min(self) -> None:
        assert _clamp_resize(-5, -3) == (1, 1)

    def test_oversized_clamped_to_max(self) -> None:
        assert _clamp_resize(5000, 1000) == (1000, 500)

    def test_float_truncated_to_int(self) -> None:
        assert _clamp_resize(80.7, 24.3) == (80, 24)


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_ws_health(app) -> None:
    """Test WebSocket health endpoint echoes messages."""
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.websocket_connect("/ws/health") as ws:
            ws.send_text("hello")
            data = ws.receive_text()
            assert data == "echo: hello"


@pytest.mark.asyncio
async def test_ws_events(app) -> None:
    """Test WebSocket events endpoint streams events and recent events."""
    from starlette.testclient import TestClient

    event_queue = asyncio.Queue()
    await event_queue.put({"type": "test", "data": "hello"})

    recent = [{"type": "recent", "data": "old"}]

    with (
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.subscribe",
            return_value=event_queue,
            create=True,
        ),
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True
        ) as mock_unsub,
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
            return_value=recent,
            create=True,
        ),
        patch("code_puppy.api.auth.verify_token", return_value=True, create=True),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events") as ws:
                # First receives recent events
                data = ws.receive_json()
                assert data["type"] == "recent"
                # Then queued event
                data = ws.receive_json()
                assert data["type"] == "test"
        mock_unsub.assert_called_once()


@pytest.mark.asyncio
async def test_ws_terminal(app) -> None:
    """Test WebSocket terminal endpoint creates a session."""
    from starlette.testclient import TestClient

    mock_session = MagicMock()
    mock_manager = MagicMock()
    mock_manager.create_session = AsyncMock(return_value=mock_session)
    mock_manager.write = AsyncMock()
    mock_manager.resize = AsyncMock()
    mock_manager.close_session = AsyncMock()

    with (
        patch(
            "code_puppy.api.pty_manager.get_pty_manager",
            return_value=mock_manager,
            create=True,
        ),
        patch("code_puppy.api.auth.verify_token", return_value=True, create=True),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/terminal") as ws:
                # Should receive session info
                data = ws.receive_json()
                assert data["type"] == "session"
                assert "id" in data

                # Send input
                ws.send_json({"type": "input", "data": "ls\n"})

                # Send resize
                ws.send_json({"type": "resize", "cols": 120, "rows": 40})

            # After disconnect, session should be closed
            mock_manager.close_session.assert_called_once()


@pytest.mark.asyncio
async def test_ws_terminal_input_capped(app) -> None:
    """Terminal WS truncates input exceeding _MAX_INPUT_BYTES."""
    from starlette.testclient import TestClient

    mock_session = MagicMock()
    mock_manager = MagicMock()
    mock_manager.create_session = AsyncMock(return_value=mock_session)
    mock_manager.write = AsyncMock()
    mock_manager.resize = AsyncMock()
    mock_manager.close_session = AsyncMock()

    with (
        patch(
            "code_puppy.api.pty_manager.get_pty_manager",
            return_value=mock_manager,
            create=True,
        ),
        patch("code_puppy.api.auth.verify_token", return_value=True, create=True),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/terminal") as ws:
                data = ws.receive_json()
                assert data["type"] == "session"

                # Send oversized input
                oversized = "x" * (_MAX_INPUT_BYTES + 1000)
                ws.send_json({"type": "input", "data": oversized})

            # Verify write was called with truncated data
            mock_manager.write.assert_called_once()
            written_data = mock_manager.write.call_args[0][1]
            assert len(written_data) == _MAX_INPUT_BYTES


@pytest.mark.asyncio
async def test_ws_terminal_resize_clamped(app) -> None:
    """Terminal WS clamps resize values to sane bounds."""
    from starlette.testclient import TestClient

    mock_session = MagicMock()
    mock_manager = MagicMock()
    mock_manager.create_session = AsyncMock(return_value=mock_session)
    mock_manager.write = AsyncMock()
    mock_manager.resize = AsyncMock()
    mock_manager.close_session = AsyncMock()

    with (
        patch(
            "code_puppy.api.pty_manager.get_pty_manager",
            return_value=mock_manager,
            create=True,
        ),
        patch("code_puppy.api.auth.verify_token", return_value=True, create=True),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/terminal") as ws:
                data = ws.receive_json()
                assert data["type"] == "session"

                # Send out-of-bounds resize
                ws.send_json({"type": "resize", "cols": 5000, "rows": -5})

            # Verify resize was called with clamped values
            mock_manager.resize.assert_called_once_with(
                mock_manager.resize.call_args[0][0],
                1000,  # clamped from 5000
                1,  # clamped from -5
            )


@pytest.mark.asyncio
async def test_ws_events_ping_on_timeout(app) -> None:
    """Events WS sends ping on queue timeout."""
    from starlette.testclient import TestClient

    # Empty queue - will timeout and send ping
    event_queue = asyncio.Queue()

    with (
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.subscribe",
            return_value=event_queue,
            create=True,
        ),
        patch("code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True),
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
            return_value=[],
            create=True,
        ),
        patch("code_puppy.api.auth.verify_token", return_value=True, create=True),
        patch(
            "asyncio.wait_for",
            side_effect=[asyncio.TimeoutError, asyncio.CancelledError],
        ),
    ):
        with TestClient(app) as client:
            try:
                with client.websocket_connect("/ws/events") as ws:
                    data = ws.receive_json()
                    assert data["type"] == "ping"
            except Exception:
                pass  # Connection closes after ping


# ---------------------------------------------------------------------------
# Auth/origin rejection tests for /ws/terminal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_terminal_rejects_no_token() -> None:
    """/ws/terminal rejects unauthenticated connections."""
    from starlette.testclient import TestClient

    app = create_app()
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch(
                "code_puppy.api.auth._token_path",
                return_value=Path(tmpdir) / "rt",
            ),
            patch("code_puppy.api.auth.verify_token", return_value=False, create=True),
        ):
            with TestClient(app) as client:
                with pytest.raises(Exception):
                    # Connection should be closed/rejected
                    with client.websocket_connect("/ws/terminal"):
                        pass


@pytest.mark.asyncio
async def test_ws_terminal_rejects_cross_origin() -> None:
    """/ws/terminal rejects cross-origin connections."""
    from starlette.testclient import TestClient

    app = create_app()
    with patch(
        "code_puppy.api.auth.validate_origin_against_host",
        return_value=False,
        create=True,
    ):
        with TestClient(app) as client:
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/ws/terminal",
                    headers={"origin": "https://evil.com"},
                ) as _:
                    pass


# ---------------------------------------------------------------------------
# Auth/origin rejection tests for /ws/events (existing, updated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_events_rejects_no_token() -> None:
    """WS /ws/events rejects unauthenticated connections."""
    from starlette.testclient import TestClient

    app = create_app()
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch(
                "code_puppy.api.auth._token_path",
                return_value=Path(tmpdir) / "rt",
            ),
            patch("code_puppy.api.auth.verify_token", return_value=False, create=True),
        ):
            with TestClient(app) as client:
                with pytest.raises(Exception):
                    # Connection should be closed/rejected
                    with client.websocket_connect("/ws/events"):
                        pass


@pytest.mark.asyncio
async def test_ws_events_rejects_cross_origin() -> None:
    """WS /ws/events rejects cross-origin connections."""
    from starlette.testclient import TestClient

    app = create_app()
    with patch(
        "code_puppy.api.auth.validate_origin_against_host",
        return_value=False,
        create=True,
    ):
        with TestClient(app) as client:
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/ws/events",
                    headers={"origin": "https://evil.com"},
                ) as _:
                    pass
