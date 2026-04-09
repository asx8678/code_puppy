"""Per-session history buffer for WebSocket history replay.

This module provides SessionHistoryBuffer, a thread-safe per-session event
buffer that enables seamless WebSocket client reconnection. When a client
disconnects and reconnects with the same session_id, events emitted while
offline are replayed before live streaming resumes.

Configuration:
    ws_history_maxlen: Maximum events per session (default: 200)

Example:
    >>> from code_puppy.messaging.history_buffer import get_history_buffer
    >>> buffer = get_history_buffer()
    >>> buffer.record("session-123", {"type": "agent_start", "data": {...}})
    >>> # On reconnect:
    >>> history = buffer.get_history("session-123")
    >>> for event in history:
    ...     await websocket.send_json(event)
    >>> buffer.clear_session("session-123")  # Cleanup on disconnect
"""

import threading
from collections import deque
from typing import Any

from code_puppy.config import get_ws_history_maxlen


class SessionHistoryBuffer:
    """Thread-safe per-session event buffer for WebSocket history replay.

        Each session has its own fixed-size deque (maxlen). When full, oldest
    tooth:    events are automatically evicted (O(1)). Thread-safe for concurrent
        record() calls from multiple threads.

        Attributes:
            _maxlen: Maximum events per session deque.
            _history: Dict mapping session_id → deque of events.
            _lock: threading.Lock for thread-safe access.
    """

    __slots__ = ("_maxlen", "_history", "_lock")

    def __init__(self, maxlen: int | None = None) -> None:
        """Initialize the history buffer.

        Args:
            maxlen: Max events per session. If None, uses ws_history_maxlen
                from config (default 200).
        """
        self._maxlen = maxlen if maxlen is not None else get_ws_history_maxlen()
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def record(self, session_id: str, event: dict[str, Any]) -> None:
        """Record an event for a session.

        Thread-safe. Creates the session deque if needed.

        Args:
            session_id: The session identifier.
            event: JSON-serializable event dict. Should have 'type' and
                optionally 'timestamp', 'id' fields.
        """
        with self._lock:
            # Use dict.get() with sentinel pattern for atomic get-or-create
            session_deque = self._history.get(session_id)
            if session_deque is None:
                session_deque = deque(maxlen=self._maxlen)
                self._history[session_id] = session_deque
            session_deque.append(event)

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """Get buffered events for a session (newest first).

        Returns a copy of the deque as a list. The list is ordered from
        oldest to newest (same as deque iteration order).

        Args:
            session_id: The session identifier.

        Returns:
            List of events for the session, or empty list if session unknown.
        """
        with self._lock:
            session_deque = self._history.get(session_id)
            if session_deque is None:
                return []
            return list(session_deque)

    def clear_session(self, session_id: str) -> bool:
        """Clear history for a session and remove it.

        Call this when a WebSocket disconnects to prevent memory leaks.

        Args:
            session_id: The session identifier.

        Returns:
            True if session existed and was cleared, False if unknown.
        """
        with self._lock:
            if session_id in self._history:
                del self._history[session_id]
                return True
            return False

    def clear_all(self) -> int:
        """Clear all session history (useful for testing).

        Returns:
            Number of sessions cleared.
        """
        with self._lock:
            count = len(self._history)
            self._history.clear()
            return count

    def session_count(self) -> int:
        """Get number of active sessions with history.

        Returns:
            Count of sessions with buffered events.
        """
        with self._lock:
            return len(self._history)

    def event_count(self, session_id: str) -> int:
        """Get number of buffered events for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Event count, or 0 if session unknown.
        """
        with self._lock:
            session_deque = self._history.get(session_id)
            return len(session_deque) if session_deque else 0

    def has_session(self, session_id: str) -> bool:
        """Check if a session has history.

        Args:
            session_id: The session identifier.

        Returns:
            True if session exists with history.
        """
        with self._lock:
            return session_id in self._history


# =============================================================================
# Global Singleton
# =============================================================================

_global_buffer: SessionHistoryBuffer | None = None
_buffer_lock = threading.Lock()


def get_history_buffer() -> SessionHistoryBuffer:
    """Get or create the global SessionHistoryBuffer singleton.

    Thread-safe. Creates buffer on first call with config maxlen.

    Returns:
        The global SessionHistoryBuffer instance.
    """
    global _global_buffer

    if _global_buffer is None:
        with _buffer_lock:
            if _global_buffer is None:
                _global_buffer = SessionHistoryBuffer()
    return _global_buffer


def reset_history_buffer() -> None:
    """Reset the global history buffer (for testing).

    Warning: This loses all buffered history!
    """
    global _global_buffer

    with _buffer_lock:
        _global_buffer = None


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "SessionHistoryBuffer",
    "get_history_buffer",
    "reset_history_buffer",
]
