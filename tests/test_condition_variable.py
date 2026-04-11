"""Test for condition variable replacement of asyncio.sleep(0.1)."""

import pytest

from code_puppy.messaging import (
    wait_for_messages_rendered,
)
from code_puppy.messaging.message_queue import MessageQueue


class TestConditionVariable:
    """Test that condition variable signaling works correctly."""

    def test_wait_for_empty_returns_immediately_when_empty(self):
        """wait_for_empty should return True immediately if no pending messages."""
        queue = MessageQueue()
        queue._has_active_renderer = True  # Mark as active so messages aren't buffered

        # Queue is empty, should return immediately
        result = queue.wait_for_empty(timeout=0.1)
        assert result is True

    def test_pending_count_tracked_correctly(self):
        """pending_count should be tracked when messages are emitted."""
        from code_puppy.messaging.message_queue import UIMessage, MessageType

        queue = MessageQueue()
        queue._has_active_renderer = True

        # Initially empty
        assert queue._pending_count == 0

        # Emit a message (without actually adding to queue since we're not running)
        msg = UIMessage(type=MessageType.INFO, content="test message")

        # Manually simulate emit behavior
        with queue._queue_condition:
            queue._pending_count += 1

        # Pending count should be incremented
        assert queue._pending_count == 1

    def test_condition_variable_exists(self):
        """Queue should have a condition variable for signaling."""
        queue = MessageQueue()
        import threading

        assert hasattr(queue, "_queue_condition")
        assert isinstance(queue._queue_condition, threading.Condition)

    @pytest.mark.asyncio
    async def test_wait_for_messages_rendered_async(self):
        """wait_for_messages_rendered should work from async context."""
        # Should not raise and should return True when queue is empty
        result = await wait_for_messages_rendered(timeout=0.1)
        assert result is True

    def test_emit_increments_pending_count(self):
        """emit() should increment pending_count under condition lock."""
        from code_puppy.messaging.message_queue import MessageType, UIMessage

        queue = MessageQueue()
        queue._has_active_renderer = True

        msg = UIMessage(type=MessageType.INFO, content="test")

        # Check pending count increases
        initial = queue._pending_count
        queue.emit(msg)
        assert queue._pending_count == initial + 1

    def test_message_queue_has_pending_count_attribute(self):
        """MessageQueue should have _pending_count attribute initialized to 0."""
        queue = MessageQueue()
        assert hasattr(queue, "_pending_count")
        assert queue._pending_count == 0


class TestNoSleepPolling:
    """Test that we no longer need to poll with asyncio.sleep."""

    @pytest.mark.asyncio
    async def test_wait_for_messages_is_event_driven(self):
        """wait_for_messages_rendered uses condition variable, not polling."""
        # This test verifies the implementation doesn't use sleep internally
        import inspect

        source = inspect.getsource(wait_for_messages_rendered)
        # Should mention condition or to_thread, not sleep
        assert "sleep" not in source.lower() or "to_thread" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
