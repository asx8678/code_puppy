"""poll() helper for eventually-consistent test assertions.

Inspired by gemini-cli/packages/test-utils/src/test-rig.ts:31-55.

Usage:
    # Async
    result = await poll(lambda: my_async_check(), timeout=5.0)
    assert result == expected

    # Sync
    result = poll_sync(lambda: my_sync_check(), timeout=5.0)
    assert result == expected
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


async def poll(
    fn: Callable[[], Awaitable[T] | T],
    timeout: float = 60.0,
    interval: float = 0.1,
    *,
    message: str | None = None,
) -> T:
    """Repeatedly call fn until it returns a truthy value or timeout expires.

    Supports both sync and async fn. Returns the truthy value, or raises
    TimeoutError if no truthy value seen before deadline.

    Args:
        fn: Callable returning a value (sync or async). Truthy = success.
        timeout: Total time budget in seconds. Default 60s.
        interval: Sleep between attempts in seconds. Default 100ms.
        message: Optional context for the TimeoutError.

    Raises:
        TimeoutError: If fn never returned truthy within timeout.
    """
    deadline = time.monotonic() + timeout
    last_value: T | None = None
    while True:
        result = fn()
        if inspect.isawaitable(result):
            result = await result  # type: ignore[assignment]
        last_value = result  # type: ignore[assignment]
        if result:
            return result  # type: ignore[return-value]
        if time.monotonic() >= deadline:
            raise TimeoutError(
                message
                or f"poll() timed out after {timeout}s; last value: {last_value!r}"
            )
        await asyncio.sleep(interval)


def poll_sync(
    fn: Callable[[], T],
    timeout: float = 60.0,
    interval: float = 0.1,
    *,
    message: str | None = None,
) -> T:
    """Sync variant of poll() — for tests that aren't async.

    Args:
        fn: Sync callable. Truthy return = success.
        timeout: Total time budget in seconds. Default 60s.
        interval: Sleep between attempts in seconds. Default 100ms.
        message: Optional context for the TimeoutError.

    Raises:
        TimeoutError: If fn never returned truthy within timeout.
    """
    deadline = time.monotonic() + timeout
    last_value: T | None = None
    while True:
        result = fn()
        last_value = result
        if result:
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError(
                message
                or f"poll_sync() timed out after {timeout}s; last value: {last_value!r}"
            )
        time.sleep(interval)


__all__ = ["poll", "poll_sync"]
