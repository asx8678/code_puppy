"""Event emitter for frontend integration.

Provides a global event queue that WebSocket handlers can subscribe to.
Events are JSON-serializable dicts with type, timestamp, and data.

Also records events to the session history buffer for replay on reconnect.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from code_puppy.config import (
    get_frontend_emitter_enabled,
    get_frontend_emitter_max_recent_events,
    get_frontend_emitter_queue_size,
)
from code_puppy.messaging.history_buffer import get_history_buffer

logger = logging.getLogger(__name__)

# Global state for event distribution
# Each subscriber is a tuple of (queue, session_id) where session_id may be None
_subscribers: set[tuple[asyncio.Queue[dict[str, Any]], str | None]] = set()
_recent_events: list[dict[str, Any]] = []  # Keep last N events for new subscribers


def emit_event(
    event_type: str, data: Any = None, session_id: str | None = None
) -> None:
    """Emit an event to subscribers.

    Creates a structured event dict with unique ID, type, timestamp, and data,
    then broadcasts it to active subscriber queues. Events are filtered by session_id:
    subscribers with no session_id receive all events, while subscribers with a
    session_id only receive events matching their session.

    Args:
        event_type: Type of event (e.g., "tool_call_start", "stream_token")
        data: Event data payload - should be JSON-serializable
        session_id: Optional session ID to filter which subscribers receive this event.
                   Events with a session_id are only sent to subscribers that either
                   have no session filter (global subscribers) or match this session_id.
    """
    # Early return if emitter is disabled
    if not get_frontend_emitter_enabled():
        return

    event: dict[str, Any] = {
        "id": str(uuid4()),
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "data": data or {},
    }

    # Store in recent events for replay to new subscribers
    max_recent = get_frontend_emitter_max_recent_events()
    _recent_events.append(event)
    if len(_recent_events) > max_recent:
        _recent_events.pop(0)

    # Broadcast to matching subscribers:
    # - Subscribers with no session_id filter get all events (global subscribers)
    # - Subscribers with a session_id only get events matching their session
    for subscriber_queue, subscriber_session_id in _subscribers.copy():
        # Filter: if event has session_id and subscriber has a different session_id, skip
        if session_id is not None and subscriber_session_id is not None:
            if session_id != subscriber_session_id:
                continue

        try:
            subscriber_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Subscriber queue full, dropping event: {event_type}")
        except Exception as e:
            logger.error(f"Failed to emit event to subscriber: {e}")


def subscribe(session_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
    """Subscribe to events.

    Creates and returns a new async queue that will receive future events.
    The queue has a configurable max size (via frontend_emitter_queue_size)
    to prevent unbounded memory growth if the subscriber is slow to process events.

    Args:
        session_id: Optional session ID to filter events. If provided, the
                   subscriber will only receive events for this session.
                   If None, the subscriber receives all events (global subscriber).

    Returns:
        An asyncio.Queue that will receive event dictionaries.
    """
    queue_size = get_frontend_emitter_queue_size()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
    _subscribers.add((queue, session_id))
    logger.debug(
        f"New subscriber added (session_id={session_id}), total subscribers: {len(_subscribers)}"
    )
    return queue


def unsubscribe(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Unsubscribe from events.

    Removes the queue from the subscriber set. Safe to call even if the queue
    was never subscribed or already unsubscribed.

    Args:
        queue: The queue returned from subscribe()
    """
    # Find and remove the tuple containing this queue
    for subscriber in list(_subscribers):
        if subscriber[0] is queue:
            _subscribers.discard(subscriber)
            break
    logger.debug(f"Subscriber removed, remaining subscribers: {len(_subscribers)}")


def get_recent_events() -> list[dict[str, Any]]:
    """Get recent events for new subscribers.

    Returns a copy of the most recent events (up to frontend_emitter_max_recent_events).
    Useful for allowing new WebSocket connections to "catch up" on
    recent activity.

    Returns:
        A list of recent event dictionaries.
    """
    return _recent_events.copy()


def get_subscriber_count() -> int:
    """Get the current number of active subscribers.

    Returns:
        Number of active subscriber queues.
    """
    return len(_subscribers)


def clear_recent_events() -> None:
    """Clear the recent events buffer.

    Useful for testing or resetting state.
    """
    _recent_events.clear()
    logger.debug("Recent events cleared")


def record_event(session_id: str, event: dict[str, Any]) -> None:
    """Record an event to the session history buffer for replay.

    Thread-safe. Can be called from any thread.

    Args:
        session_id: The session identifier.
        event: The event dict to record (must be JSON-serializable).
    """
    buffer = get_history_buffer()
    buffer.record(session_id, event)


def get_session_history(session_id: str) -> list[dict[str, Any]]:
    """Get buffered history for a specific session.

    Args:
        session_id: The session identifier.

    Returns:
        List of events for the session, or empty list if unknown.
    """
    buffer = get_history_buffer()
    return buffer.get_history(session_id)
