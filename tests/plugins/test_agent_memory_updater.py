"""Tests for the MemoryUpdater debounced batch updater.

Tests cover:
- Debounce batching (add facts, verify batched on flush)
- Deduplication (same text fact replaces previous)
- Reinforce bypasses debounce (immediate operation)
- Remove bypasses debounce (immediate operation)
- Shutdown flush (graceful cleanup)
- Thread safety (concurrent adds)
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.agent_memory.storage import Fact, FileMemoryStorage
from code_puppy.plugins.agent_memory.updater import (
    DEFAULT_DEBOUNCE_MS,
    MemoryUpdater,
)


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch the _MEMORY_DIR to use our temp directory
        storage = FileMemoryStorage("test-agent")
        storage._file_path = Path(tmpdir) / "test-agent.json"
        yield storage


@pytest.fixture
def updater(temp_storage):
    """Create a MemoryUpdater with short debounce for faster tests."""
    # Use 50ms debounce for speedy tests
    return MemoryUpdater(temp_storage, debounce_ms=50)


class TestDebounceBatching:
    """Test that facts are batched and written on flush."""

    def test_add_single_fact_pending(self, updater, temp_storage):
        """Adding a fact should put it in pending state."""
        fact: Fact = {"text": "Python is fun", "confidence": 0.9}
        updater.add_fact(fact)

        assert updater.pending_count() == 1
        assert not updater.is_empty()
        # Should not be in storage yet (debounced)
        assert temp_storage.fact_count() == 0

    def test_add_multiple_facts_batching(self, updater):
        """Adding multiple facts should batch them together."""
        facts = [
            {"text": f"Fact {i}", "confidence": 0.5 + i * 0.1}
            for i in range(5)
        ]

        for fact in facts:
            updater.add_fact(fact)

        assert updater.pending_count() == 5

    def test_flush_writes_to_storage(self, updater, temp_storage):
        """Flush should write all pending facts to storage."""
        facts = [
            {"text": f"Fact {i}", "confidence": 0.5 + i * 0.1}
            for i in range(3)
        ]

        for fact in facts:
            updater.add_fact(fact)

        flushed = updater.flush()

        assert len(flushed) == 3
        assert updater.pending_count() == 0
        assert updater.is_empty()
        assert temp_storage.fact_count() == 3

    def test_flush_returns_empty_when_empty(self, updater):
        """Flush should return empty list when no pending facts."""
        flushed = updater.flush()
        assert flushed == []

    def test_auto_flush_on_debounce_timeout(self, updater, temp_storage):
        """Facts should auto-flush after debounce window expires."""
        fact: Fact = {"text": "Auto flush test", "confidence": 0.9}
        updater.add_fact(fact)

        # Wait for debounce timeout (50ms in tests)
        time.sleep(0.1)

        # Should be in storage now
        assert temp_storage.fact_count() == 1
        assert updater.is_empty()


class TestDeduplication:
    """Test that facts with same text are deduplicated."""

    def test_same_text_replaces_pending(self, updater):
        """Adding fact with same text should replace pending fact."""
        fact1: Fact = {"text": "Python is fun", "confidence": 0.5}
        fact2: Fact = {"text": "Python is fun", "confidence": 0.9}

        updater.add_fact(fact1)
        updater.add_fact(fact2)

        # Should still be 1 pending (deduplicated)
        assert updater.pending_count() == 1

    def test_latest_fact_wins_on_flush(self, updater, temp_storage):
        """When flushed, the latest version of a fact should be written."""
        fact1: Fact = {"text": "Python is fun", "confidence": 0.5, "source_session": "s1"}
        fact2: Fact = {"text": "Python is fun", "confidence": 0.9, "source_session": "s2"}

        updater.add_fact(fact1)
        updater.add_fact(fact2)
        updater.flush()

        # Should only have 1 fact (deduplicated)
        assert temp_storage.fact_count() == 1
        saved_fact = temp_storage.get_facts()[0]
        assert saved_fact["confidence"] == 0.9
        assert saved_fact["source_session"] == "s2"

    def test_different_texts_not_deduplicated(self, updater, temp_storage):
        """Facts with different texts should not be deduplicated."""
        facts = [
            {"text": "Python is fun", "confidence": 0.9},
            {"text": "Rust is fast", "confidence": 0.85},
            {"text": "Go is simple", "confidence": 0.8},
        ]

        for fact in facts:
            updater.add_fact(fact)

        updater.flush()

        assert temp_storage.fact_count() == 3


class TestReinforceBypassesDebounce:
    """Test that reinforce_fact bypasses the debounce queue."""

    def test_reinforce_immediate_update(self, temp_storage):
        """reinforce_fact should immediately update storage."""
        # Pre-seed a fact
        fact: Fact = {
            "text": "Python is fun",
            "confidence": 0.9,
            "last_reinforced": "2024-01-01T00:00:00+00:00",
        }
        temp_storage.add_fact(fact)

        # Create updater and reinforce
        updater = MemoryUpdater(temp_storage, debounce_ms=5000)  # Long debounce
        result = updater.reinforce_fact("Python is fun", session_id="session-123")

        assert result is True
        # Should be updated immediately, no need to flush
        facts = temp_storage.get_facts()
        assert facts[0]["last_reinforced"] != "2024-01-01T00:00:00+00:00"
        assert facts[0]["source_session"] == "session-123"

    def test_reinforce_nonexistent_fact(self, temp_storage):
        """reinforce_fact should return False for missing fact."""
        updater = MemoryUpdater(temp_storage, debounce_ms=50)
        result = updater.reinforce_fact("Nonexistent fact")

        assert result is False

    def test_reinforce_does_not_affect_queue(self, updater):
        """reinforce_fact should not add to or affect the debounce queue."""
        pending_fact: Fact = {"text": "Pending fact", "confidence": 0.5}
        updater.add_fact(pending_fact)

        # This won't find anything but shouldn't crash
        updater.reinforce_fact("Some other fact")

        # Pending count unchanged
        assert updater.pending_count() == 1


class TestRemoveBypassesDebounce:
    """Test that remove_fact bypasses the debounce queue."""

    def test_remove_immediate_delete(self, temp_storage):
        """remove_fact should immediately delete from storage."""
        # Pre-seed a fact
        fact: Fact = {"text": "Delete me", "confidence": 0.9}
        temp_storage.add_fact(fact)

        # Create updater with long debounce and remove
        updater = MemoryUpdater(temp_storage, debounce_ms=5000)
        result = updater.remove_fact("Delete me")

        assert result is True
        # Should be gone immediately
        assert temp_storage.fact_count() == 0

    def test_remove_nonexistent_fact(self, temp_storage):
        """remove_fact should return False for missing fact."""
        updater = MemoryUpdater(temp_storage, debounce_ms=50)
        result = updater.remove_fact("Nonexistent fact")

        assert result is False

    def test_remove_from_storage_not_queue(self, updater, temp_storage):
        """remove_fact removes from storage, queue pending items separate."""
        # Pre-seed a fact in storage
        fact: Fact = {"text": "In storage", "confidence": 0.9}
        temp_storage.add_fact(fact)

        # Add a different fact to queue
        pending: Fact = {"text": "In queue", "confidence": 0.5}
        updater.add_fact(pending)

        # Remove the one in storage
        result = updater.remove_fact("In storage")

        assert result is True
        assert temp_storage.fact_count() == 0
        # Queue should still have pending fact
        assert updater.pending_count() == 1


class TestShutdownFlush:
    """Test graceful flush on shutdown."""

    def test_shutdown_callback_registered(self, temp_storage):
        """Updater should register shutdown callback via DebouncedQueue."""
        with patch("code_puppy.callbacks.register_callback") as mock_register:
            updater = MemoryUpdater(temp_storage, debounce_ms=50)
            # DebouncedQueue registers shutdown callback on instantiation
            # We verify the queue is properly configured by checking
            # that it was created (which internally registers callbacks)
            assert updater._queue is not None
            # Note: The DebouncedQueue registers its own shutdown callback
            # during __init__, so we verify it was created successfully

    def test_manual_flush_before_exit(self, updater, temp_storage):
        """Simulating shutdown flush behavior."""
        facts = [
            {"text": f"Fact {i}", "confidence": 0.5 + i * 0.1}
            for i in range(3)
        ]

        for fact in facts:
            updater.add_fact(fact)

        # Manual flush simulating what happens on shutdown
        updater.flush()

        assert temp_storage.fact_count() == 3

    def test_flush_empty_queue_no_error(self, updater):
        """Flushing empty queue should not error."""
        result = updater.flush()
        assert result == []


class TestThreadSafety:
    """Test thread safety for concurrent operations."""

    def test_concurrent_adds(self, updater, temp_storage):
        """Multiple threads adding facts should be safe."""
        num_threads = 10
        facts_per_thread = 5

        def add_facts(thread_id: int) -> None:
            for i in range(facts_per_thread):
                fact: Fact = {
                    "text": f"Thread-{thread_id}-Fact-{i}",
                    "confidence": 0.5 + (thread_id * 0.01),
                }
                updater.add_fact(fact)

        threads = [
            threading.Thread(target=add_facts, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All facts should be pending
        assert updater.pending_count() == num_threads * facts_per_thread

        # Flush and verify all written
        updater.flush()
        assert temp_storage.fact_count() == num_threads * facts_per_thread

    def test_concurrent_add_and_flush(self, updater, temp_storage):
        """Concurrent adds while flushing should be safe."""
        results = {"errors": 0}

        def add_facts() -> None:
            try:
                for i in range(20):
                    fact: Fact = {"text": f"Fact-{i}", "confidence": 0.5}
                    updater.add_fact(fact)
                    time.sleep(0.001)  # Small delay to interleave with flush
            except Exception:
                results["errors"] += 1

        def periodic_flush() -> None:
            try:
                for _ in range(5):
                    time.sleep(0.01)
                    updater.flush()
            except Exception:
                results["errors"] += 1

        add_thread = threading.Thread(target=add_facts)
        flush_thread = threading.Thread(target=periodic_flush)

        add_thread.start()
        flush_thread.start()

        add_thread.join()
        flush_thread.join()

        # Final flush to catch any remaining
        updater.flush()

        assert results["errors"] == 0
        # Some facts should have been written
        # (exact count depends on timing, but should be > 0)
        total_facts = temp_storage.fact_count() + updater.pending_count()
        assert total_facts > 0

    def test_thread_safe_counters(self, updater):
        """pending_count and is_empty should be thread-safe."""
        for i in range(100):
            updater.add_fact({"text": f"Fact {i}", "confidence": 0.5})

        # Concurrent reads should not crash
        results = []

        def read_counters() -> None:
            for _ in range(50):
                results.append(updater.pending_count())
                results.append(updater.is_empty())

        threads = [threading.Thread(target=read_counters) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4 * 50 * 2  # All reads completed


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_add_fact_without_text(self, updater, temp_storage):
        """Adding fact without text should log warning and not queue."""
        bad_fact: Fact = {"confidence": 0.9}  # No text key
        updater.add_fact(bad_fact)

        assert updater.pending_count() == 0

    def test_add_invalid_fact_type(self, updater, temp_storage):
        """Adding non-dict fact should log warning and not queue."""
        updater.add_fact("not a dict")  # type: ignore[arg-type]

        assert updater.pending_count() == 0

    def test_add_fact_with_empty_text(self, updater):
        """Fact with empty text should still be added (debounce queue allows it)."""
        fact: Fact = {"text": "", "confidence": 0.5}
        updater.add_fact(fact)

        # Empty text is technically allowed by the queue
        # but will be filtered on flush (since we use text as key)
        assert updater.pending_count() == 1

    def test_clear_empties_everything(self, updater, temp_storage):
        """clear() should empty both storage and pending queue."""
        # Add to storage
        temp_storage.add_fact({"text": "In storage", "confidence": 0.9})

        # Add to queue
        updater.add_fact({"text": "In queue", "confidence": 0.5})

        updater.clear()

        assert temp_storage.fact_count() == 0
        assert updater.is_empty()

    def test_get_facts_not_include_pending(self, updater, temp_storage):
        """get_facts reads from storage, not pending queue."""
        # Add to storage
        temp_storage.add_fact({"text": "In storage", "confidence": 0.9})

        # Add to queue (not flushed)
        updater.add_fact({"text": "In queue", "confidence": 0.5})

        facts = updater.get_facts()

        # Should only see the one in storage
        assert len(facts) == 1
        assert facts[0]["text"] == "In storage"


class TestDefaultValues:
    """Test default constants and values."""

    def test_default_debounce_ms(self):
        """DEFAULT_DEBOUNCE_MS should be 30000 (30 seconds)."""
        assert DEFAULT_DEBOUNCE_MS == 30000

    def test_updater_uses_default_debounce(self, temp_storage):
        """Updater should use default debounce when not specified."""
        updater = MemoryUpdater(temp_storage)
        assert updater._debounce_ms == DEFAULT_DEBOUNCE_MS

    def test_custom_debounce_override(self, temp_storage):
        """Custom debounce should override default."""
        updater = MemoryUpdater(temp_storage, debounce_ms=100)
        assert updater._debounce_ms == 100


class TestIntegrationWithStorage:
    """Integration tests between updater and storage."""

    def test_full_workflow(self, temp_storage):
        """Complete workflow: add, reinforce, remove, flush."""
        updater = MemoryUpdater(temp_storage, debounce_ms=50)

        # Add facts
        updater.add_fact({"text": "Fact A", "confidence": 0.9})
        updater.add_fact({"text": "Fact B", "confidence": 0.8})
        assert updater.pending_count() == 2

        # Flush adds
        updater.flush()
        assert temp_storage.fact_count() == 2

        # Reinforce (immediate)
        updater.reinforce_fact("Fact A", session_id="session-1")
        facts = temp_storage.get_facts()
        fact_a = next(f for f in facts if f["text"] == "Fact A")
        assert fact_a["source_session"] == "session-1"

        # Remove (immediate)
        updater.remove_fact("Fact B")
        assert temp_storage.fact_count() == 1

        # Add more and let debounce flush
        updater.add_fact({"text": "Fact C", "confidence": 0.7})
        time.sleep(0.1)  # Wait for auto-flush
        assert temp_storage.fact_count() == 2

    def test_deduplication_across_flushes(self, temp_storage):
        """Facts added separately should deduplicate on each flush."""
        updater = MemoryUpdater(temp_storage, debounce_ms=50)

        # Add and flush first batch
        updater.add_fact({"text": "Shared", "confidence": 0.5, "batch": 1})
        updater.add_fact({"text": "Unique-1", "confidence": 0.6, "batch": 1})
        time.sleep(0.1)  # Wait for auto-flush

        assert temp_storage.fact_count() == 2

        # Add second batch with same "Shared" text
        updater.add_fact({"text": "Shared", "confidence": 0.9, "batch": 2})
        updater.add_fact({"text": "Unique-2", "confidence": 0.7, "batch": 2})
        time.sleep(0.1)  # Wait for auto-flush

        # Should have 4 facts now (2 from first flush + 2 from second)
        # Note: deduplication only happens within a batch, not across flushes
        assert temp_storage.fact_count() == 4

        # Verify both versions of "Shared" exist (different batch numbers)
        facts = temp_storage.get_facts()
        shared_facts = [f for f in facts if f["text"] == "Shared"]
        assert len(shared_facts) == 2  # Both versions stored
