"""Tests for async_utils module."""

import asyncio
import os
import threading
import time
from code_puppy.async_utils import run_async_sync, _get_executor, _shutdown_executor, DebouncedQueue


async def simple_coro(value: int) -> int:
    """Simple coroutine that returns a value."""
    await asyncio.sleep(0.01)  # Small delay to ensure async nature
    return value * 2


async def failing_coro() -> None:
    """Coro that raises an exception."""
    await asyncio.sleep(0.01)
    raise ValueError("test error")


async def thread_identity_coro() -> tuple[int, int]:
    """Coro that returns thread identity and event loop id."""
    loop = asyncio.get_event_loop()
    return threading.current_thread().ident, id(loop)


def test_run_async_sync_returns_correct_result() -> None:
    """Test that run_async_sync correctly executes coroutines and returns results."""
    result = run_async_sync(simple_coro(21))
    assert result == 42


def test_run_async_sync_exception_propagation() -> None:
    """Test that exceptions from coroutines are properly propagated."""
    try:
        run_async_sync(failing_coro())
        assert False, "Expected ValueError to be raised"
    except ValueError as e:
        assert str(e) == "test error"


def test_run_async_sync_concurrent_calls() -> None:
    """Test that concurrent calls from multiple threads complete correctly."""
    results = []
    errors = []

    def worker(value: int) -> None:
        try:
            result = run_async_sync(simple_coro(value))
            results.append(result)
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(errors) == 0, f"Got errors: {errors}"
    assert sorted(results) == [i * 2 for i in range(10)]


def test_run_async_sync_multiple_calls_same_thread() -> None:
    """Test that multiple calls from the same thread work correctly."""
    results = []
    for i in range(5):
        result = run_async_sync(simple_coro(i))
        results.append(result)
    assert results == [0, 2, 4, 6, 8]


def test_run_async_sync_nested_calls() -> None:
    """Test that nested calls within coroutines work correctly."""

    async def outer_coro() -> int:
        inner = run_async_sync(simple_coro(5))
        return inner + 10

    result = run_async_sync(outer_coro())
    assert result == 20  # (5 * 2) + 10


def test_concurrent_workers_execute_correctly() -> None:
    """Test that concurrent workers execute coroutines correctly."""
    results = []

    def worker(value: int) -> None:
        tid, lid = run_async_sync(thread_identity_coro())
        results.append((value, tid, lid))

    threads = []
    for i in range(5):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All 5 calls should have completed with valid results
    assert len(results) == 5
    # Each value should appear exactly once
    values = [v for v, _, _ in results]
    assert sorted(values) == [0, 1, 2, 3, 4]
    # All thread IDs should be valid (non-zero)
    thread_ids = [tid for _, tid, _ in results]
    assert all(tid > 0 for tid in thread_ids)
    # All loop IDs should be valid (non-zero)
    loop_ids = [lid for _, _, lid in results]
    assert all(lid > 0 for lid in loop_ids)


def test_executor_is_singleton():
    """_get_executor() returns the same executor on multiple calls."""
    exec1 = _get_executor()
    exec2 = _get_executor()
    assert exec1 is exec2


def test_executor_is_bounded():
    """Executor is bounded to expected max_workers."""
    executor = _get_executor()
    expected_max = min(32, (os.cpu_count() or 1) + 4)
    assert executor._max_workers == expected_max


def test_executor_recreated_after_shutdown():
    """After _shutdown_executor(), a new executor is created on next use."""
    exec1 = _get_executor()
    _shutdown_executor()
    exec2 = _get_executor()
    assert exec1 is not exec2
    # Cleanup
    _shutdown_executor()


# -----------------------------------------------------------------------------
# DebouncedQueue Tests
# -----------------------------------------------------------------------------


def test_debounced_queue_basic_debounce():
    """Test that items are batched and flushed after debounce interval."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    # Use a short debounce interval for testing
    queue = DebouncedQueue[str](callback=callback, interval_ms=50)

    # Add items
    queue.add("key1", "value1")
    queue.add("key2", "value2")

    # Items should not be flushed immediately
    assert len(flushed_items) == 0
    assert queue.pending_count() == 2

    # Wait for debounce interval + small buffer
    time.sleep(0.1)

    # Now items should be flushed
    assert sorted(flushed_items) == ["value1", "value2"]
    assert queue.pending_count() == 0
    assert queue.is_empty()


def test_debounced_queue_deduplication():
    """Test that same-key entries replace existing entries."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=50)

    # Add items with same key - should replace
    queue.add("key1", "value1")
    queue.add("key1", "value1_updated")
    queue.add("key1", "value1_final")
    queue.add("key2", "value2")

    assert queue.pending_count() == 2  # Only 2 unique keys

    time.sleep(0.1)

    # Should have the final values
    assert sorted(flushed_items) == ["value1_final", "value2"]


def test_debounced_queue_timer_reset():
    """Test that timer resets on each add(), delaying the flush."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=100)

    # Add first item
    queue.add("key1", "value1")
    time.sleep(0.05)  # Wait less than debounce interval

    # Add second item - should reset timer
    queue.add("key2", "value2")

    # Wait a bit more (should not flush yet since timer was reset)
    time.sleep(0.06)  # Total ~110ms from first add, but only ~60ms from second

    # Should still not be flushed (need to wait for new timer)
    assert len(flushed_items) == 0

    # Wait for the new timer
    time.sleep(0.1)

    # Now it should be flushed
    assert sorted(flushed_items) == ["value1", "value2"]


def test_debounced_queue_concurrent_adds():
    """Test thread-safety under concurrent adds from multiple threads."""
    flushed_items = []
    errors = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=50)

    def worker(thread_id: int) -> None:
        try:
            for i in range(5):
                key = f"thread{thread_id}_item{i}"
                value = f"value_{thread_id}_{i}"
                queue.add(key, value)
                time.sleep(0.005)  # Small delay between adds
        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    for i in range(4):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Wait for debounce to flush
    time.sleep(0.1)

    # Should have no errors
    assert len(errors) == 0, f"Got errors: {errors}"

    # Should have exactly 20 items (4 threads * 5 items each)
    assert len(flushed_items) == 20

    # Verify we got values from all threads
    thread_ids = set()
    for item in flushed_items:
        # Parse "value_{thread_id}_{item_num}"
        parts = item.split("_")
        thread_ids.add(int(parts[1]))
    assert thread_ids == {0, 1, 2, 3}


def test_debounced_queue_graceful_shutdown():
    """Test that shutdown callback flushes pending items."""
    flushed_items = []

    def callback(items: list[int]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[int](callback=callback, interval_ms=5000)  # Long interval

    # Add items but don't wait for debounce
    queue.add("a", 1)
    queue.add("b", 2)
    queue.add("c", 3)

    assert queue.pending_count() == 3
    assert len(flushed_items) == 0

    # Simulate shutdown - call the internal flush method directly
    # (the _on_shutdown would be called by the callbacks system)
    flushed = queue.flush()
    assert sorted(flushed) == [1, 2, 3]


def test_debounced_queue_manual_flush():
    """Test manual flush returns pending items."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=1000)

    queue.add("x", "item1")
    queue.add("y", "item2")
    queue.add("z", "item3")

    # Manual flush
    result = queue.flush()

    assert sorted(result) == ["item1", "item2", "item3"]
    assert queue.is_empty()
    assert queue.pending_count() == 0
    # Callback should not have been called for manual flush
    assert len(flushed_items) == 0


def test_debounced_queue_is_empty():
    """Test is_empty method."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=50)

    assert queue.is_empty()

    queue.add("key", "value")
    assert not queue.is_empty()

    time.sleep(0.1)
    assert queue.is_empty()


def test_debounced_queue_pending_count():
    """Test pending_count method."""
    flushed_items = []

    def callback(items: list[str]) -> None:
        flushed_items.extend(items)

    queue = DebouncedQueue[str](callback=callback, interval_ms=50)

    assert queue.pending_count() == 0

    queue.add("k1", "v1")
    assert queue.pending_count() == 1

    queue.add("k2", "v2")
    assert queue.pending_count() == 2

    queue.add("k1", "v1_updated")  # Same key, should replace
    assert queue.pending_count() == 2

    time.sleep(0.1)
    assert queue.pending_count() == 0


def test_debounced_queue_generic_typing():
    """Test that DebouncedQueue works with different types."""
    # Test with integers
    int_results = []
    int_queue = DebouncedQueue[int](callback=lambda x: int_results.extend(x), interval_ms=50)
    int_queue.add("a", 42)
    int_queue.add("b", 99)
    time.sleep(0.1)
    assert sorted(int_results) == [42, 99]

    # Test with dicts
    dict_results = []
    dict_queue = DebouncedQueue[dict](callback=lambda x: dict_results.extend(x), interval_ms=50)
    dict_queue.add("a", {"foo": "bar"})
    dict_queue.add("b", {"baz": 123})
    time.sleep(0.1)
    assert len(dict_results) == 2
    assert any(d.get("foo") == "bar" for d in dict_results)


def test_debounced_queue_daemon_timer():
    """Test that timer is created as a daemon thread by default."""
    queue = DebouncedQueue[str](callback=lambda x: None, interval_ms=100)
    queue.add("key", "value")

    # The timer should be a daemon
    assert queue._timer is not None
    assert queue._timer.daemon is True

    # Clean up
    queue.flush()


def test_debounced_queue_non_daemon_timer():
    """Test that timer respects daemon_timer=False setting."""
    queue = DebouncedQueue[str](callback=lambda x: None, interval_ms=100, daemon_timer=False)
    queue.add("key", "value")

    # The timer should NOT be a daemon
    assert queue._timer is not None
    assert queue._timer.daemon is False

    # Clean up
    queue.flush()
