"""
Tests for code_puppy.utils.parallel — worker pool and semaphore.

Inspired by oh-my-pi's parallel.ts.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from code_puppy.utils.parallel import Semaphore, map_with_concurrency, ParallelResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _identity(item: int, idx: int) -> int:
    """Return the item unchanged after yielding control."""
    await asyncio.sleep(0)
    return item


async def _double(item: int, idx: int) -> int:
    await asyncio.sleep(0)
    return item * 2


# ---------------------------------------------------------------------------
# map_with_concurrency — basic behaviour
# ---------------------------------------------------------------------------


class TestMapWithConcurrency:
    @pytest.mark.asyncio
    async def test_basic_concurrency_2(self):
        """Basic map with concurrency=2 over 6 items returns correct results."""
        result = await map_with_concurrency(list(range(6)), 2, _double)

        assert isinstance(result, ParallelResult)
        assert result.aborted is False
        assert result.results == [0, 2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    async def test_concurrency_1_is_sequential(self):
        """concurrency=1 processes items one at a time, in order."""
        order: list[int] = []

        async def record(item: int, idx: int) -> int:
            order.append(item)
            await asyncio.sleep(0)
            return item

        result = await map_with_concurrency(list(range(5)), 1, record)

        assert result.results == list(range(5))
        assert order == list(range(5))  # strict ordering guaranteed

    @pytest.mark.asyncio
    async def test_concurrency_greater_than_items(self):
        """concurrency > len(items) is clamped — all items still processed."""
        result = await map_with_concurrency([10, 20, 30], concurrency=100, fn=_identity)

        assert result.results == [10, 20, 30]
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_empty_items_list(self):
        """Empty input returns an empty result immediately."""
        result = await map_with_concurrency([], concurrency=4, fn=_double)

        assert result.results == []
        assert result.aborted is False

    @pytest.mark.asyncio
    async def test_result_ordering_matches_input(self):
        """Results must be in the same order as the input regardless of completion order."""

        # Give earlier-indexed items *longer* sleeps so they finish last.
        async def slow_first(item: int, idx: int) -> str:
            await asyncio.sleep(0.01 * (5 - idx))  # idx 0 is slowest
            return f"item-{item}"

        result = await map_with_concurrency(
            list(range(6)), concurrency=6, fn=slow_first
        )

        assert result.results == [f"item-{i}" for i in range(6)]

    @pytest.mark.asyncio
    async def test_single_item(self):
        """Single-item list works correctly."""
        result = await map_with_concurrency([42], concurrency=1, fn=_identity)
        assert result.results == [42]


# ---------------------------------------------------------------------------
# map_with_concurrency — abort signal
# ---------------------------------------------------------------------------


class TestAbortSignal:
    @pytest.mark.asyncio
    async def test_abort_mid_execution_returns_partial(self):
        """Setting the signal stops scheduling new work; partial results are preserved."""
        signal = asyncio.Event()

        async def fn(item: int, idx: int) -> int:
            if idx == 0:
                # Trigger abort after the very first item is processed.
                signal.set()
            await asyncio.sleep(0)
            return item

        result = await map_with_concurrency(
            list(range(6)), concurrency=1, fn=fn, signal=signal
        )

        assert result.aborted is True
        # First item must have been processed.
        assert result.results[0] == 0
        # Items after the abort point should be None (skipped).
        assert all(r is None for r in result.results[1:])

    @pytest.mark.asyncio
    async def test_signal_already_set_skips_all(self):
        """If the signal is already set before the call, no items are processed."""
        signal = asyncio.Event()
        signal.set()

        called: list[int] = []

        async def fn(item: int, idx: int) -> int:
            called.append(item)
            return item

        result = await map_with_concurrency(
            list(range(5)), concurrency=2, fn=fn, signal=signal
        )

        assert result.aborted is True
        assert all(r is None for r in result.results)
        assert called == []  # no item was ever processed

    @pytest.mark.asyncio
    async def test_no_signal_no_abort(self):
        """Without a signal the operation never marks itself as aborted."""
        result = await map_with_concurrency(list(range(4)), concurrency=2, fn=_identity)
        assert result.aborted is False


# ---------------------------------------------------------------------------
# map_with_concurrency — error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_error_propagates(self):
        """An exception from fn is re-raised to the caller."""

        async def fn(item: int, idx: int) -> int:
            if item == 3:
                raise ValueError("bad item 3")
            return item

        with pytest.raises(ValueError, match="bad item 3"):
            await map_with_concurrency(list(range(6)), concurrency=1, fn=fn)

    @pytest.mark.asyncio
    async def test_error_cancels_other_workers(self):
        """A failing task causes still-running workers to be cancelled."""
        started: list[int] = []
        completed: list[int] = []

        async def fn(item: int, idx: int) -> int:
            started.append(item)
            if item == 0:
                raise RuntimeError("boom")
            # Long sleep — should be cancelled before finishing.
            await asyncio.sleep(10)
            completed.append(item)
            return item

        with pytest.raises(RuntimeError, match="boom"):
            await map_with_concurrency(list(range(4)), concurrency=4, fn=fn)

        # Item 0 started (and raised), others may have started but never completed.
        assert 0 in started
        assert completed == []  # no item finished the long sleep


# ---------------------------------------------------------------------------
# Semaphore — acquire / release
# ---------------------------------------------------------------------------


class TestSemaphore:
    @pytest.mark.asyncio
    async def test_basic_acquire_release(self):
        """A semaphore with max=2 allows two simultaneous acquires."""
        sem = Semaphore(2)
        await sem.acquire()
        await sem.acquire()
        # Both slots occupied; a third acquire should block.
        # We assert available slots is now 0 by checking internal state.
        assert sem._available == 0
        sem.release()
        assert sem._available == 1
        sem.release()
        assert sem._available == 2

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_full(self):
        """acquire() waits when no slots are free, then proceeds after release()."""
        sem = Semaphore(1)
        await sem.acquire()  # occupies the single slot

        released = asyncio.Event()

        async def holder() -> None:
            await asyncio.sleep(0.02)
            sem.release()
            released.set()

        asyncio.create_task(holder())
        # This should block until the holder releases.
        await sem.acquire()
        assert released.is_set()
        sem.release()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Semaphore works correctly as an async context manager."""
        sem = Semaphore(1)
        inside = False

        async with sem:
            inside = True
            assert sem._available == 0  # slot is held

        assert inside
        assert sem._available == 1  # slot released on exit

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_exception(self):
        """Slot is released even when the body raises."""
        sem = Semaphore(1)

        with pytest.raises(ZeroDivisionError):
            async with sem:
                raise ZeroDivisionError("oops")

        assert sem._available == 1  # must be restored

    @pytest.mark.asyncio
    async def test_max_concurrent_respected(self):
        """Never more than max_concurrent tasks run simultaneously."""
        max_c = 3
        sem = Semaphore(max_c)
        active = 0
        peak = 0

        async def task(_: int) -> None:
            nonlocal active, peak
            async with sem:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*[task(i) for i in range(10)])
        assert peak <= max_c

    def test_invalid_max_raises(self):
        """Semaphore(0) should raise ValueError."""
        with pytest.raises(ValueError):
            Semaphore(0)

    @pytest.mark.asyncio
    async def test_multiple_waiters_served_in_order(self):
        """Waiters are unblocked in FIFO order."""
        sem = Semaphore(1)
        await sem.acquire()  # hold the single slot

        order: list[int] = []

        async def waiter(n: int) -> None:
            await sem.acquire()
            order.append(n)
            sem.release()

        # Schedule 3 waiters — they should queue up in creation order.
        tasks = [asyncio.create_task(waiter(i)) for i in range(3)]
        await asyncio.sleep(0)  # let tasks park on the semaphore

        sem.release()  # release the slot we're holding; triggers FIFO unblocking
        await asyncio.gather(*tasks)

        assert order == [0, 1, 2]
