"""Utility functions for benchmarking."""

from __future__ import annotations

import signal
import time
from typing import Any, Callable

from .models import LatencyStats


def time_function(
    func: Callable[[], Any],
    iterations: int,
    warmup: int = 0,
    timeout_sec: float = 30.0,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Time a function over multiple iterations with warmup and timeout.

    Args:
        func: Function to time (should be callable with no args)
        iterations: Number of benchmark iterations
        warmup: Number of warmup iterations
        timeout_sec: Maximum seconds per iteration

    Returns:
        Tuple of (successful_times_ms, failures) where failures is a list
        of dicts containing iteration number and error info.
    """
    failures: list[dict[str, Any]] = []
    times_ms: list[float] = []

    # Warmup (not timed, failures don't count)
    for _ in range(warmup):
        try:
            # Apply timeout to warmup too
            if timeout_sec > 0:
                signal.alarm(int(timeout_sec))
            func()
            if timeout_sec > 0:
                signal.alarm(0)
        except Exception:
            pass  # Warmup failures are OK
        finally:
            if timeout_sec > 0:
                signal.alarm(0)

    # Benchmark with timeout enforcement
    for i in range(iterations):
        start = time.perf_counter()
        try:
            if timeout_sec > 0:
                signal.alarm(int(timeout_sec))
            func()
            if timeout_sec > 0:
                signal.alarm(0)
            end = time.perf_counter()
            times_ms.append((end - start) * 1000)
        except TimeoutError:
            failures.append(
                {"iteration": i, "error": "timeout", "type": "TimeoutError"}
            )
        except Exception as e:
            failures.append({"iteration": i, "error": str(e), "type": type(e).__name__})
        finally:
            if timeout_sec > 0:
                signal.alarm(0)

    return times_ms, failures


def format_stats(stats: LatencyStats) -> str:
    """Format latency stats for display."""
    return (
        f"mean={stats.mean_ms:.3f}ms, median={stats.median_ms:.3f}ms, "
        f"p95={stats.p95_ms:.3f}ms, p99={stats.p99_ms:.3f}ms"
    )
