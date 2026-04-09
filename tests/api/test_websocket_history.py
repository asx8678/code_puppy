"""Tests for WebSocket history replay functionality.

Tests the SessionHistoryBuffer and WebSocket history replay integration
to ensure seamless client reconnection.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from code_puppy.api.app import create_app
from code_puppy.messaging.history_buffer import (
    SessionHistoryBuffer,
    get_history_buffer,
    reset_history_buffer,
)


# =============================================================================
# SessionHistoryBuffer Unit Tests
# =============================================================================


class TestSessionHistoryBuffer:
    """Unit tests for SessionHistoryBuffer."""

    def test_record_and_get_history(self):
        """Basic record and retrieve."""
        buf = SessionHistoryBuffer(maxlen=10)

        # Empty initially
        assert buf.get_history("session-1") == []

        # Record events
        buf.record("session-1", {"type": "event1", "data": "a"})
        buf.record("session-1", {"type": "event2", "data": "b"})

        # Retrieve in order
        history = buf.get_history("session-1")
        assert len(history) == 2
        assert history[0]["type"] == "event1"
        assert history[1]["type"] == "event2"

    def test_multi_session_isolation(self):
        """Sessions don't see each other's history."""
        buf = SessionHistoryBuffer(maxlen=10)

        buf.record("session-a", {"type": "a-only"})
        buf.record("session-b", {"type": "b-only"})

        assert len(buf.get_history("session-a")) == 1
        assert len(buf.get_history("session-b")) == 1
        assert buf.get_history("session-a")[0]["type"] == "a-only"
        assert buf.get_history("session-b")[0]["type"] == "b-only"

    def test_maxlen_eviction(self):
        """Only keeps last N events per session."""
        buf = SessionHistoryBuffer(maxlen=5)

        for i in range(10):
            buf.record("session-x", {"type": f"event-{i}"})

        history = buf.get_history("session-x")
        assert len(history) == 5
        assert history[0]["type"] == "event-5"  # Oldest kept
        assert history[4]["type"] == "event-9"  # Newest

    def test_clear_session(self):
        """Clear removes session history."""
        buf = SessionHistoryBuffer(maxlen=10)

        buf.record("session-1", {"type": "event"})
        assert buf.has_session("session-1")

        assert buf.clear_session("session-1") is True
        assert buf.clear_session("session-1") is False  # Already gone
        assert not buf.has_session("session-1")
        assert buf.get_history("session-1") == []

    def test_clear_all(self):
        """Clear all removes all sessions."""
        buf = SessionHistoryBuffer(maxlen=10)

        buf.record("s1", {"type": "a"})
        buf.record("s2", {"type": "b"})

        assert buf.session_count() == 2
        cleared = buf.clear_all()
        assert cleared == 2
        assert buf.session_count() == 0

    def test_event_count(self):
        """Event count tracks correctly."""
        buf = SessionHistoryBuffer(maxlen=10)

        assert buf.event_count("unknown") == 0

        for i in range(3):
            buf.record("session", {"type": f"e{i}"})

        assert buf.event_count("session") == 3

    def test_thread_safety(self):
        """Concurrent records from multiple threads don't corrupt or lose events."""
        buf = SessionHistoryBuffer(maxlen=200)
        session_id = "concurrent-test"
        errors = []
        record_count = threading.Lock()
        expected_count = [0]  # Use list for mutable reference

        def record_events(n, thread_id):
            try:
                for i in range(n):
                    buf.record(session_id, {"type": f"thread-{thread_id}", "n": i})
                    with record_count:
                        expected_count[0] += 1
            except Exception as e:
                with record_count:
                    errors.append(str(e))

        # Record from 5 threads simultaneously
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(record_events, 20, t) for t in range(5)]
            for f in futures:
                f.result()

        assert not errors, f"Errors during concurrent record: {errors}"

        history = buf.get_history(session_id)
        # Should have all events that were successfully recorded
        assert len(history) == expected_count[0], (
            f"Expected {expected_count[0]} events, got {len(history)}"
        )


# =============================================================================
# WebSocket Integration Tests
# =============================================================================


@pytest.fixture
def app():
    """Create app with fresh history buffer for each test."""
    reset_history_buffer()
    return create_app()


@pytest.fixture(autouse=True)
def reset_buffer_after():
    """Reset history buffer after each test."""
    yield
    reset_history_buffer()


@pytest.mark.asyncio
async def test_ws_empty_history_replay(app) -> None:
    """New session: no history to replay, just live streaming works."""
    from starlette.testclient import TestClient

    event_queue = asyncio.Queue()
    await event_queue.put({"type": "live_event", "data": "fresh"})

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
    ):
        with TestClient(app) as client:
            # Connect with new session_id
            with client.websocket_connect("/ws/events?session_id=new-session") as ws:
                # Should receive live event immediately
                data = ws.receive_json()
                assert data["type"] == "live_event"
                assert data["data"] == "fresh"


@pytest.mark.asyncio
async def test_ws_basic_history_replay(app) -> None:
    """Emit 3 messages before connect, client receives all 3 in order."""
    from starlette.testclient import TestClient

    # Pre-populate history
    buffer = get_history_buffer()
    buffer.record("my-session", {"type": "pre1", "data": "first"})
    buffer.record("my-session", {"type": "pre2", "data": "second"})
    buffer.record("my-session", {"type": "pre3", "data": "third"})

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
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events?session_id=my-session") as ws:
                # Receive 3 history events first
                events = []
                for _ in range(3):
                    events.append(ws.receive_json())

                assert events[0]["type"] == "pre1"
                assert events[1]["type"] == "pre2"
                assert events[2]["type"] == "pre3"


@pytest.mark.asyncio
async def test_ws_history_plus_live(app) -> None:
    """Emit 2 messages before connect, connect, emit 1 more → client receives all 3."""
    from starlette.testclient import TestClient

    buffer = get_history_buffer()
    buffer.record("mixed-session", {"type": "pre", "data": "history"})

    event_queue = asyncio.Queue()
    await event_queue.put({"type": "live", "data": "new"})

    with (
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.subscribe",
            return_value=event_queue,
            create=True,
        ),
        patch("code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True),
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
            return_value=[{"type": "global_recent"}],
            create=True,
        ),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events?session_id=mixed-session") as ws:
                # History first
                h1 = ws.receive_json()
                assert h1["type"] == "pre"

                # Then global recent
                r1 = ws.receive_json()
                assert r1["type"] == "global_recent"

                # Then live
                l1 = ws.receive_json()
                assert l1["type"] == "live"


@pytest.mark.asyncio
async def test_ws_maxlen_eviction(app) -> None:
    """Emit 250 messages with maxlen=200 → only last 200 replayed."""
    from starlette.testclient import TestClient

    buffer = SessionHistoryBuffer(maxlen=200)  # Override for test

    with patch(
        "code_puppy.messaging.history_buffer.get_history_buffer",
        return_value=buffer,
    ):
        # Pre-populate with 250 events
        for i in range(250):
            buffer.record("evict-session", {"type": f"event-{i}"})

        event_queue = asyncio.Queue()

        with (
            patch(
                "code_puppy.plugins.frontend_emitter.emitter.subscribe",
                return_value=event_queue,
                create=True,
            ),
            patch(
                "code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True
            ),
            patch(
                "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
                return_value=[],
                create=True,
            ),
        ):
            with TestClient(app) as client:
                with client.websocket_connect(
                    "/ws/events?session_id=evict-session"
                ) as ws:
                    events = []
                    for _ in range(200):
                        events.append(ws.receive_json())

                    # First event should be #50 (250-200)
                    assert events[0]["type"] == "event-50"
                    # Last should be #249
                    assert events[199]["type"] == "event-249"


@pytest.mark.asyncio
async def test_ws_multi_session_isolation(app) -> None:
    """Session A's history is not replayed to session B."""
    from starlette.testclient import TestClient

    buffer = get_history_buffer()
    buffer.record("session-a", {"type": "a-event"})
    buffer.record("session-b", {"type": "b-event"})

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
    ):
        with TestClient(app) as client:
            # Connect as session-a
            with client.websocket_connect("/ws/events?session_id=session-a") as ws:
                data = ws.receive_json()
                assert data["type"] == "a-event"

            # Connect as session-b
            with client.websocket_connect("/ws/events?session_id=session-b") as ws:
                data = ws.receive_json()
                assert data["type"] == "b-event"


@pytest.mark.asyncio
async def test_ws_graceful_no_session_id(app) -> None:
    """Without session_id, works fine without history replay."""
    from starlette.testclient import TestClient

    buffer = get_history_buffer()
    buffer.record("some-session", {"type": "should-not-see"})

    event_queue = asyncio.Queue()
    await event_queue.put({"type": "live"})

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
    ):
        with TestClient(app) as client:
            # No session_id - should just get live events
            with client.websocket_connect("/ws/events") as ws:
                data = ws.receive_json()
                assert data["type"] == "live"


@pytest.mark.asyncio
async def test_ws_records_live_events(app) -> None:
    """Live events are recorded to session history."""
    from starlette.testclient import TestClient

    buffer = get_history_buffer()

    # Setup: emit and queue a live event
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
    ):
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/events?session_id=recorder-session"
            ) as ws:
                # Simulate incoming live event
                await event_queue.put({"type": "live-recorded", "data": "yep"})

                # Receive it
                data = ws.receive_json()
                assert data["type"] == "live-recorded"

    # After disconnect, verify it was recorded
    assert buffer.event_count("recorder-session") == 1
    history = buffer.get_history("recorder-session")
    assert history[0]["type"] == "live-recorded"


@pytest.mark.asyncio
async def test_ws_reconnect_scenario(app) -> None:
    """Main use case: disconnect, emit messages, reconnect → replay."""
    from starlette.testclient import TestClient

    buffer = get_history_buffer()

    # Initial connection (first client)
    event_queue_1 = asyncio.Queue()

    with (
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.subscribe",
            return_value=event_queue_1,
            create=True,
        ),
        patch("code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True),
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
            return_value=[],
            create=True,
        ),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events?session_id=reconnect-test") as ws:
                # Live event while connected
                await event_queue_1.put({"type": "during-first"})
                ws.receive_json()

    # While disconnected, record events directly
    buffer.record("reconnect-test", {"type": "while-disconnected-1"})
    buffer.record("reconnect-test", {"type": "while-disconnected-2"})

    # New connection (reconnect)
    event_queue_2 = asyncio.Queue()

    with (
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.subscribe",
            return_value=event_queue_2,
            create=True,
        ),
        patch("code_puppy.plugins.frontend_emitter.emitter.unsubscribe", create=True),
        patch(
            "code_puppy.plugins.frontend_emitter.emitter.get_recent_events",
            return_value=[],
            create=True,
        ),
    ):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/events?session_id=reconnect-test") as ws:
                # Should receive history (during-first + while-disconnected)
                events = []
                for _ in range(3):
                    events.append(ws.receive_json())

                types = [e["type"] for e in events]
                assert "during-first" in types
                assert "while-disconnected-1" in types
                assert "while-disconnected-2" in types


# =============================================================================
# Global Singleton Tests
# =============================================================================


def test_global_singleton():
    """Global buffer is singleton."""
    reset_history_buffer()

    b1 = get_history_buffer()
    b2 = get_history_buffer()

    assert b1 is b2


def test_reset_creates_new():
    """Reset creates new buffer instance."""
    reset_history_buffer()

    b1 = get_history_buffer()
    b1.record("test", {"type": "old"})

    reset_history_buffer()

    b2 = get_history_buffer()
    assert b1 is not b2
    assert b2.get_history("test") == []  # Fresh buffer


# =============================================================================
# Config Integration
# =============================================================================


def test_default_maxlen_from_config():
    """Buffer uses ws_history_maxlen from config."""
    reset_history_buffer()

    with patch(
        "code_puppy.messaging.history_buffer.get_ws_history_maxlen", return_value=50
    ):
        buf = SessionHistoryBuffer()  # Uses config default

        for i in range(100):
            buf.record("test", {"type": f"e{i}"})

        assert len(buf.get_history("test")) == 50
