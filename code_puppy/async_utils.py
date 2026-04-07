"""Shared async utilities for running coroutines from sync code.

This module provides a bridge between async and sync code,
used by tools and resilience utilities that need to execute
async code from synchronous contexts.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

# Thread-local storage for dedicated event loops (used by run_async_sync)
_loop_local = threading.local()


def run_async_sync(coro) -> Any:
    """Run a coroutine in a dedicated background thread's event loop.

    This is more reliable than asyncio.run() for nested calls and cases
    where an event loop may already exist in the current thread.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine
    """
    # Check if we have a dedicated loop in this thread
    if (
        not hasattr(_loop_local, "loop")
        or _loop_local.loop is None
        or _loop_local.loop.is_closed()
    ):
        _loop_local.loop = asyncio.new_event_loop()
        _loop_local.thread = threading.Thread(
            target=_loop_local.loop.run_forever, daemon=True
        )
        _loop_local.thread.start()

    # Submit the coroutine to the dedicated loop
    future = asyncio.run_coroutine_threadsafe(coro, _loop_local.loop)
    return future.result()
