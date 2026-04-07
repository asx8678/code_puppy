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

# Thread-local storage for event loops within pool worker threads
_loop_local = threading.local()

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


def _ensure_thread_loop() -> asyncio.AbstractEventLoop:
    """Ensure the current thread has a running event loop."""
    if (
        not hasattr(_loop_local, "loop")
        or _loop_local.loop is None
        or _loop_local.loop.is_closed()
    ):
        _loop_local.loop = asyncio.new_event_loop()
        # Store loop reference for use in the thread function
        loop_ref = _loop_local.loop

        # Start the loop running forever in this thread
        def run_loop():
            try:
                loop_ref.run_forever()
            finally:
                loop_ref.close()

        _loop_local.thread = threading.Thread(target=run_loop, daemon=True)
        _loop_local.thread.start()
    return _loop_local.loop


def _run_coro_in_thread(coro) -> Any:
    """Run a coroutine in the current thread's event loop."""
    loop = _ensure_thread_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def run_async_sync(coro) -> Any:
    """Run a coroutine in a background thread pool's event loop.

    Uses a bounded ThreadPoolExecutor to prevent thread explosion under load.
    Each worker thread maintains its own dedicated event loop.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine
    """
    # Submit to the bounded thread pool - limits concurrent threads
    executor = _get_executor()
    return executor.submit(_run_coro_in_thread, coro).result()
