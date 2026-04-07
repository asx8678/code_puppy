"""Tests for async_utils module."""

import asyncio
import threading
from code_puppy.async_utils import run_async_sync


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
