"""Tests for code_puppy.utils.parallel — Semaphore, map_with_concurrency, Bulkhead."""

import asyncio
import pytest

from code_puppy.utils.parallel import (
    Bulkhead,
    BulkheadFullError,
    BulkheadStats,
    BulkheadTimeoutError,
    ParallelResult,
    Semaphore,
    map_with_concurrency,
)


# ── Semaphore ────────────────────────────────────────────────────────────────


class TestSemaphore:
    def test_invalid_max(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            Semaphore(0)

    async def test_basic_acquire_release(self):
        sem = Semaphore(2)
        await sem.acquire()
        await sem.acquire()
        sem.release()
        sem.release()

    async def test_double_release_raises(self):
        sem = Semaphore(1)
        with pytest.raises(RuntimeError, match="called too many times"):
            sem.release()

    async def test_context_manager(self):
        sem = Semaphore(1)
        async with sem:
            pass  # Should not raise


# ── map_with_concurrency ─────────────────────────────────────────────────────


class TestMapWithConcurrency:
    async def test_empty_input(self):
        result = await map_with_concurrency([], 4, lambda item, idx: item)
        assert result == ParallelResult(results=[], aborted=False)

    async def test_preserves_order(self):
        items = [10, 20, 30, 40]

        async def double(item: int, idx: int) -> int:
            await asyncio.sleep(0.01)
            return item * 2

        result = await map_with_concurrency(items, 2, double)
        assert result.results == [20, 40, 60, 80]
        assert not result.aborted

    async def test_abort_signal(self):
        signal = asyncio.Event()
        call_count = 0

        async def slow(item: int, idx: int) -> int:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                signal.set()
            await asyncio.sleep(0.01)
            return item

        result = await map_with_concurrency([1, 2, 3, 4, 5], 1, slow, signal)
        assert result.aborted
        # At least 2 processed before abort
        non_none = [r for r in result.results if r is not None]
        assert len(non_none) >= 2

    async def test_fail_fast(self):
        async def failing(item: int, idx: int) -> int:
            if idx == 1:
                raise ValueError("boom")
            await asyncio.sleep(0.05)
            return item

        with pytest.raises(ValueError, match="boom"):
            await map_with_concurrency([1, 2, 3, 4], 2, failing)


# ── Bulkhead ─────────────────────────────────────────────────────────────────


class TestBulkhead:
    async def test_basic_execute(self):
        bh = Bulkhead("test", max_concurrent=2, max_queue=5)

        async def work():
            return 42

        result = await bh.execute(work)
        assert result == 42

    async def test_stats_after_execution(self):
        bh = Bulkhead("test", max_concurrent=2, max_queue=5)

        async def work():
            return "ok"

        await bh.execute(work)
        await bh.execute(work)

        stats = bh.get_stats()
        assert stats.completed == 2
        assert stats.active == 0
        assert stats.rejected == 0
        assert stats.timed_out == 0
        assert stats.max_concurrent == 2
        assert stats.max_queue == 5

    async def test_concurrent_limit_enforced(self):
        """Verify that no more than max_concurrent tasks run simultaneously."""
        bh = Bulkhead("test", max_concurrent=2, max_queue=10)
        max_seen = 0
        current = 0
        lock = asyncio.Lock()

        async def tracked_work():
            nonlocal max_seen, current
            async with lock:
                current += 1
                if current > max_seen:
                    max_seen = current
            await asyncio.sleep(0.05)
            async with lock:
                current -= 1
            return True

        tasks = [asyncio.create_task(bh.execute(tracked_work)) for _ in range(6)]
        await asyncio.gather(*tasks)

        assert max_seen <= 2
        assert bh.get_stats().completed == 6

    async def test_queue_full_raises(self):
        bh = Bulkhead("test", max_concurrent=1, max_queue=1, queue_timeout=5.0)
        gate = asyncio.Event()

        async def blocking_work():
            await gate.wait()
            return True

        # Fill the one concurrent slot
        t1 = asyncio.create_task(bh.execute(blocking_work))
        await asyncio.sleep(0.02)  # Let it acquire

        # Fill the one queue slot
        t2 = asyncio.create_task(bh.execute(blocking_work))
        await asyncio.sleep(0.02)

        # Third request should be rejected
        with pytest.raises(BulkheadFullError, match="is full"):
            await bh.execute(blocking_work)

        stats = bh.get_stats()
        assert stats.rejected == 1

        gate.set()
        await asyncio.gather(t1, t2)

    async def test_queue_timeout(self):
        bh = Bulkhead("test", max_concurrent=1, max_queue=5, queue_timeout=0.1)
        gate = asyncio.Event()

        async def blocking_work():
            await gate.wait()
            return True

        # Fill the concurrent slot
        t1 = asyncio.create_task(bh.execute(blocking_work))
        await asyncio.sleep(0.02)

        # Queue a task that will time out
        with pytest.raises(BulkheadTimeoutError, match="queue timeout"):
            await bh.execute(blocking_work)

        assert bh.get_stats().timed_out == 1

        gate.set()
        await t1

    async def test_has_capacity(self):
        bh = Bulkhead("test", max_concurrent=1, max_queue=0)
        assert bh.has_capacity()

        gate = asyncio.Event()

        async def blocking():
            await gate.wait()

        t = asyncio.create_task(bh.execute(blocking))
        await asyncio.sleep(0.02)

        assert not bh.has_capacity()

        gate.set()
        await t

    async def test_available_capacity(self):
        bh = Bulkhead("test", max_concurrent=3, max_queue=10)
        assert bh.available_capacity() == 13  # 3 + 10

    async def test_reset_stats(self):
        bh = Bulkhead("test", max_concurrent=2, max_queue=5)

        async def work():
            return True

        await bh.execute(work)
        assert bh.get_stats().completed == 1

        bh.reset_stats()
        stats = bh.get_stats()
        assert stats.completed == 0
        assert stats.rejected == 0
        assert stats.timed_out == 0

    async def test_exception_in_fn_still_releases_slot(self):
        bh = Bulkhead("test", max_concurrent=1, max_queue=5)

        async def failing():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await bh.execute(failing)

        # Slot should be released — next task should work
        async def ok():
            return "recovered"

        result = await bh.execute(ok)
        assert result == "recovered"
        # Both tasks count as completed (the bulkhead tracks all finished executions)
        assert bh.get_stats().completed == 2

    def test_invalid_max_concurrent(self):
        with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
            Bulkhead("test", max_concurrent=0)

    def test_invalid_max_queue(self):
        with pytest.raises(ValueError, match="max_queue must be >= 0"):
            Bulkhead("test", max_queue=-1)

    async def test_stats_dataclass(self):
        stats = BulkheadStats(
            active=1, queued=2, max_concurrent=5,
            max_queue=10, completed=3, rejected=0, timed_out=1,
        )
        assert stats.active == 1
        assert stats.queued == 2
