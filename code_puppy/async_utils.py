"""Shared async utilities for running coroutines from sync code.

This module provides a bridge between async and sync code,
used by tools and resilience utilities that need to execute
async code from synchronous contexts.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# Bounded thread pool for running async code - prevents thread explosion under load.
# max_workers matches Python's ThreadPoolExecutor default: min(32, cpu_count + 4)
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the module-level ThreadPoolExecutor."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                max_workers = min(32, (os.cpu_count() or 1) + 4)
                _executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="async_utils_pool",
                )
    return _executor


def _shutdown_executor() -> None:
    """Gracefully shutdown the thread pool executor."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


# Register cleanup at exit to ensure proper executor shutdown
atexit.register(_shutdown_executor)


def _run_coro_in_thread(coro) -> Any:
    """Run a coroutine in a new event loop within the current thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def run_async_sync(coro) -> Any:
    """Run a coroutine in a background thread pool's event loop.

    Uses a bounded ThreadPoolExecutor to prevent thread explosion under load.
    Each worker thread creates, uses, and closes its own dedicated event loop.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine
    """
    executor = _get_executor()
    future = executor.submit(_run_coro_in_thread, coro)
    return future.result()
