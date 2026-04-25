"""Event emitter for frontend integration.

Provides a global event queue that WebSocket handlers can subscribe to.
Events are JSON-serializable dicts with type, timestamp, and data.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Set
from uuid import uuid4

from code_puppy.config import (
    get_frontend_emitter_enabled,
    get_frontend_emitter_max_recent_events,
    get_frontend_emitter_queue_size,
)

logger = logging.getLogger(__name__)

# Global state for event distribution.  Events can be emitted from worker
# threads while subscribers live on the FastAPI event loop, so all shared state
# is protected by a lock and queue writes are scheduled with call_soon_threadsafe
# when possible.
_lock = threading.RLock()
_subscribers: Set[asyncio.Queue[Dict[str, Any]]] = set()
_subscriber_loops: Dict[asyncio.Queue[Dict[str, Any]], asyncio.AbstractEventLoop] = {}
_recent_events: List[Dict[str, Any]] = []  # Keep last N events for new subscribers


def _put_event(queue: asyncio.Queue[Dict[str, Any]], event: Dict[str, Any]) -> None:
    """Put an event into a subscriber queue, dropping if the queue is full."""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning(f"Subscriber queue full, dropping event: {event.get('type')}")
    except Exception as e:
        logger.error(f"Failed to emit event to subscriber: {e}")


def emit_event(event_type: str, data: Any = None) -> None:
    """Emit an event to all subscribers.

    Creates a structured event dict with unique ID, type, timestamp, and data,
    then broadcasts it to all active subscriber queues.

    Args:
        event_type: Type of event (e.g., "tool_call_start", "stream_token")
        data: Event data payload - should be JSON-serializable
    """
    # Early return if emitter is disabled
    if not get_frontend_emitter_enabled():
        return

    event: Dict[str, Any] = {
        "id": str(uuid4()),
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }

    with _lock:
        # Store in recent events for replay to new subscribers
        max_recent = get_frontend_emitter_max_recent_events()
        _recent_events.append(event)
        if len(_recent_events) > max_recent:
            del _recent_events[: len(_recent_events) - max_recent]

        subscribers = list(_subscribers)
        loops = {queue: _subscriber_loops.get(queue) for queue in subscribers}

    # Broadcast outside the lock so slow queues don't block other emitters.
    for subscriber_queue in subscribers:
        loop = loops.get(subscriber_queue)
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(_put_event, subscriber_queue, event)
            else:
                _put_event(subscriber_queue, event)
        except RuntimeError:
            _put_event(subscriber_queue, event)


def subscribe() -> asyncio.Queue[Dict[str, Any]]:
    """Subscribe to events.

    Creates and returns a new async queue that will receive all future events.
    The queue has a configurable max size (via frontend_emitter_queue_size)
    to prevent unbounded memory growth if the subscriber is slow to process events.

    Returns:
        An asyncio.Queue that will receive event dictionaries.
    """
    queue_size = get_frontend_emitter_queue_size()
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    with _lock:
        _subscribers.add(queue)
        if loop is not None:
            _subscriber_loops[queue] = loop
        count = len(_subscribers)

    logger.debug(f"New subscriber added, total subscribers: {count}")
    return queue


def unsubscribe(queue: asyncio.Queue[Dict[str, Any]]) -> None:
    """Unsubscribe from events.

    Removes the queue from the subscriber set. Safe to call even if the queue
    was never subscribed or already unsubscribed.

    Args:
        queue: The queue returned from subscribe()
    """
    with _lock:
        _subscribers.discard(queue)
        _subscriber_loops.pop(queue, None)
        count = len(_subscribers)
    logger.debug(f"Subscriber removed, remaining subscribers: {count}")


def get_recent_events() -> List[Dict[str, Any]]:
    """Get recent events for new subscribers.

    Returns a copy of the most recent events (up to frontend_emitter_max_recent_events).
    Useful for allowing new WebSocket connections to "catch up" on
    recent activity.

    Returns:
        A list of recent event dictionaries.
    """
    with _lock:
        return _recent_events.copy()


def get_subscriber_count() -> int:
    """Get the current number of active subscribers.

    Returns:
        Number of active subscriber queues.
    """
    with _lock:
        return len(_subscribers)


def clear_recent_events() -> None:
    """Clear the recent events buffer.

    Useful for testing or resetting state.
    """
    with _lock:
        _recent_events.clear()
    logger.debug("Recent events cleared")
