"""
Parallel worker pool utilities for Code Puppy.

Provides a bounded-concurrency async map and a from-scratch counting semaphore.

Inspired by oh-my-pi's parallel.ts.
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class ParallelResult(Generic[R]):
    """Result of a parallel map operation.

    Attributes:
        results: Ordered results matching the input list.  Entries for tasks
            that were skipped due to an abort signal are ``None``.
        aborted: ``True`` when the operation was cut short by the abort signal.
    """

    results: list[R | None]
    aborted: bool = False


class Semaphore:
    """Async counting semaphore for controlling concurrency.

    Written from scratch using an explicit ``asyncio.Future`` queue rather than
    delegating to ``asyncio.Semaphore``.  This mirrors the low-level slot/waiter
    pattern used in oh-my-pi's parallel.ts.

    Usage::

        sem = Semaphore(3)

        async with sem:
            await do_work()

        # or manually:
        await sem.acquire()
        try:
            await do_work()
        finally:
            sem.release()
    """

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError(
                f"max_concurrent must be >= 1, got {max_concurrent}"
            )
        self._max = max_concurrent
        # Available slots (0 means fully occupied).
        self._available: int = max_concurrent
        # Queue of futures waiting for a slot; each future resolves to None
        # when a slot is granted.
        self._waiters: collections.deque[asyncio.Future[None]] = (
            collections.deque()
        )

    async def acquire(self) -> None:
        """Wait until a concurrency slot is available, then occupy it."""
        if self._available > 0:
            self._available -= 1
            return
        # No slots free — park a Future on the waiter queue.
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._waiters.append(future)
        await future  # blocks until release() resolves us

    def release(self) -> None:
        """Free the held slot, granting it directly to the next waiter if any."""
        if self._waiters:
            # Hand the slot directly to the oldest waiter — don't increment
            # _available since the slot stays occupied by the new holder.
            future = self._waiters.popleft()
            if not future.done():
                future.set_result(None)
        else:
            self._available += 1

    async def __aenter__(self) -> "Semaphore":
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()


async def map_with_concurrency(
    items: list[T],
    concurrency: int,
    fn: Callable[[T, int], Awaitable[R]],
    signal: asyncio.Event | None = None,
) -> ParallelResult[R]:
    """Apply *fn* to every item in *items* with at most *concurrency* tasks running
    simultaneously.

    The worker-pool pattern mirrors oh-my-pi's parallel.ts: a fixed number of
    worker coroutines race to claim the next unprocessed index, keeping the
    concurrency cap constant without spawning one task per item.

    Args:
        items:       Items to process.
        concurrency: Maximum simultaneous operations.  Clamped to ``[1, len(items)]``.
        fn:          Async function called as ``fn(item, index) -> R``.
        signal:      Optional :class:`asyncio.Event`.  When set, workers stop
                     picking up new items and the result is marked as aborted.
                     Tasks that are already running are allowed to complete.

    Returns:
        :class:`ParallelResult` whose ``results`` list preserves input ordering.
        Skipped entries (due to abort) are ``None``.

    Raises:
        Any exception raised by *fn* — the remaining workers are cancelled and
        the first error is re-raised immediately (fail-fast semantics).
    """
    if not items:
        return ParallelResult(results=[], aborted=False)

    n = len(items)
    # Clamp concurrency to a sensible range.
    concurrency = max(1, min(concurrency, n))

    results: list[R | None] = [None] * n
    _next_index: int = 0
    _index_lock = asyncio.Lock()
    _was_aborted: bool = False

    async def _worker() -> None:
        nonlocal _next_index, _was_aborted

        while True:
            # Claim the next index under the lock.
            async with _index_lock:
                if _next_index >= n:
                    # No more work.
                    return
                if signal is not None and signal.is_set():
                    _was_aborted = True
                    return
                idx = _next_index
                _next_index += 1

            # Process the item outside the lock so other workers can proceed.
            results[idx] = await fn(items[idx], idx)

    # Spawn exactly `concurrency` worker tasks.
    tasks = [asyncio.create_task(_worker()) for _ in range(concurrency)]

    try:
        # gather with default return_exceptions=False: the first exception
        # raised by a worker is re-raised here immediately.
        await asyncio.gather(*tasks)
    except Exception:
        # Fail-fast: cancel every still-running worker, then re-raise.
        for task in tasks:
            if not task.done():
                task.cancel()
        # Await cancellation (swallow CancelledError / other exceptions from
        # already-failed tasks so they don't interfere).
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    return ParallelResult(results=results, aborted=_was_aborted)
