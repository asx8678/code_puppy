"""Tests for RunLimiter - job-level concurrency throttling.

These tests verify the RunLimiter class functionality including:
- Sync and async acquire/release
- Blocking and non-blocking modes
- Timeout handling
- Context managers
- Config reload
- Mixed sync/async callers
"""

import asyncio
import threading
import time

import pytest

from code_puppy.plugins.pack_parallelism.run_limiter import (
    RunConcurrencyLimitError,
    RunLimiter,
    RunLimiterConfig,
    get_run_limiter,
    reset_run_limiter_for_tests,
    update_run_limiter_config,
)


# Fixtures
@pytest.fixture
def reset_limiter():
    """Reset the singleton before and after each test."""
    reset_run_limiter_for_tests()
    yield
    reset_run_limiter_for_tests()


@pytest.fixture
def limiter():
    """Create a fresh RunLimiter with default config."""
    return RunLimiter(RunLimiterConfig(max_concurrent_runs=2))


@pytest.fixture
def limiter_no_parallel():
    """Create a RunLimiter with parallel disabled."""
    return RunLimiter(RunLimiterConfig(max_concurrent_runs=5, allow_parallel=False))


# ============================================================================
# Basic sync acquisition tests
# ============================================================================


class TestSyncAcquire:
    """Test sync acquire operations."""

    def test_acquire_when_empty_succeeds_immediately(self, limiter):
        """Sync acquire when empty: succeeds immediately."""
        result = limiter.acquire_sync(blocking=False)
        assert result is True
        assert limiter.active_count == 1

    def test_acquire_when_full_non_blocking_returns_false(self, limiter):
        """Sync acquire when full (non-blocking): returns False without waiting."""
        # Fill the limiter
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)

        # Third acquire should fail (non-blocking)
        result = limiter.acquire_sync(blocking=False)
        assert result is False
        assert limiter.active_count == 2

    def test_acquire_blocking_vs_nonblocking(self, limiter):
        """Sync acquire: non-blocking returns immediately, blocking would wait."""
        # Fill the limiter
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)

        # Non-blocking should return False immediately
        start = time.monotonic()
        result = limiter.acquire_sync(blocking=False)
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 0.01  # Should be immediate

        # Release and verify blocking can succeed
        limiter.release()
        result = limiter.acquire_sync(blocking=True)
        assert result is True


# ============================================================================
# Async acquisition tests
# ============================================================================


@pytest.mark.asyncio
class TestAsyncAcquire:
    """Test async acquire operations with reliable asyncio.Event patterns."""

    async def test_acquire_when_empty_succeeds_immediately(self, limiter):
        """Async acquire when empty: succeeds immediately."""
        await limiter.acquire_async()
        assert limiter.active_count == 1
        limiter.release()

    async def test_acquire_waits_when_full(self, limiter):
        """Async acquire when full: waits until slot released."""
        # Fill the limiter
        await limiter.acquire_async()
        await limiter.acquire_async()
        assert limiter.active_count == 2

        # Signal to release slot
        slot_released = asyncio.Event()
        acquired_second = asyncio.Event()

        async def holder():
            await asyncio.wait_for(slot_released.wait(), timeout=1.0)
            limiter.release()

        async def waiter():
            await limiter.acquire_async()
            acquired_second.set()
            limiter.release()

        holder_task = asyncio.create_task(holder())
        await asyncio.sleep(0.01)

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 2
        assert limiter.waiters_count == 1

        slot_released.set()
        await asyncio.wait_for(acquired_second.wait(), timeout=1.0)

        await holder_task
        await waiter_task

    async def test_acquire_timeout_raises(self, limiter):
        """Async acquire with timeout: raises RunConcurrencyLimitError on expiry."""
        await limiter.acquire_async()
        await limiter.acquire_async()

        with pytest.raises(RunConcurrencyLimitError) as exc_info:
            await limiter.acquire_async(timeout=0.01)

        assert exc_info.value.limit == 2
        assert exc_info.value.active == 2
        limiter.release()
        limiter.release()

    async def test_acquire_timeout_zero_fast_fail(self, limiter):
        """Async acquire with timeout=0: immediately fails if full."""
        await limiter.acquire_async()
        await limiter.acquire_async()

        with pytest.raises(RunConcurrencyLimitError):
            await limiter.acquire_async(timeout=0)

        limiter.release()
        limiter.release()

    async def test_acquire_timeout_zero_succeeds_when_empty(self, limiter):
        """Async acquire with timeout=0: succeeds when slot available."""
        await limiter.acquire_async()
        await limiter.acquire_async(timeout=0)
        assert limiter.active_count == 2
        limiter.release()
        limiter.release()

    async def test_only_n_async_run_concurrently_with_n_equals_2(self, limiter):
        """Only 2 async workers run concurrently with limit=2."""
        max_observed = 0
        concurrent = 0
        lock = asyncio.Lock()

        async def worker(idx: int):
            nonlocal max_observed, concurrent
            await limiter.acquire_async()
            async with lock:
                concurrent += 1
                max_observed = max(max_observed, concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1
            limiter.release()

        await asyncio.gather(*[worker(i) for i in range(6)])
        assert max_observed == 2

    async def test_only_n_async_run_concurrently_with_n_equals_3(self):
        """Only 3 async workers run concurrently with limit=3."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))
        max_observed = 0
        concurrent = 0
        lock = asyncio.Lock()

        async def worker(idx: int):
            nonlocal max_observed, concurrent
            await limiter.acquire_async()
            async with lock:
                concurrent += 1
                max_observed = max(max_observed, concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1
            limiter.release()

        await asyncio.gather(*[worker(i) for i in range(9)])
        assert max_observed == 3


@pytest.mark.asyncio
class TestAsyncSlotContextManager:
    """Test slot_async context manager."""

    async def test_slot_async_releases_on_success(self, limiter):
        """Async context manager releases slot on successful exit."""
        async with limiter.slot_async():
            assert limiter.active_count == 1
        assert limiter.active_count == 0

    async def test_slot_async_releases_on_exception(self, limiter):
        """Async context manager releases slot on exception."""
        try:
            async with limiter.slot_async():
                assert limiter.active_count == 1
                raise RuntimeError("Test error")
        except RuntimeError:
            pass
        assert limiter.active_count == 0

    async def test_slot_async_raises_when_full_non_blocking(self, limiter):
        """slot_async with timeout=0 raises when limiter is full."""
        await limiter.acquire_async()
        await limiter.acquire_async()

        with pytest.raises(RunConcurrencyLimitError):
            async with limiter.slot_async(timeout=0):
                pass

        limiter.release()
        limiter.release()


# ============================================================================
# allow_parallel=False tests
# ============================================================================


class TestAllowParallelFalse:
    """Test allow_parallel=False behavior."""

    def test_allow_parallel_false_effective_limit_is_one(self, limiter_no_parallel):
        """allow_parallel=False: effective_limit is 1 regardless of max_concurrent_runs."""
        assert limiter_no_parallel.effective_limit == 1
        assert limiter_no_parallel._config.max_concurrent_runs == 5

    def test_allow_parallel_false_only_one_can_acquire(self, limiter_no_parallel):
        """allow_parallel=False: only one slot available."""
        result = limiter_no_parallel.acquire_sync(blocking=False)
        assert result is True

        result = limiter_no_parallel.acquire_sync(blocking=False)
        assert result is False


# ============================================================================
# Sync context manager tests
# ============================================================================


class TestSyncContextManagers:
    """Test slot_sync context manager."""

    def test_slot_sync_releases_on_success(self, limiter):
        """Context manager releases on success."""
        with limiter.slot_sync():
            assert limiter.active_count == 1
        assert limiter.active_count == 0

    def test_slot_sync_releases_on_exception(self, limiter):
        """Context manager releases on exception."""
        try:
            with limiter.slot_sync():
                assert limiter.active_count == 1
                raise RuntimeError("Test error")
        except RuntimeError:
            pass
        assert limiter.active_count == 0


# ============================================================================
# Config reload tests
# ============================================================================


class TestConfigReload:
    """Test update_config behavior."""

    def test_update_config_changes_effective_limit(self, limiter):
        """Config reload: update_config() changes the effective limit."""
        assert limiter.effective_limit == 2

        new_config = RunLimiterConfig(max_concurrent_runs=5)
        limiter.update_config(new_config)

        assert limiter.effective_limit == 5

        for _ in range(5):
            limiter.acquire_sync(blocking=False)

    def test_update_config_invalid_config_rejected(self, limiter):
        """Config reload: invalid max_concurrent_runs rejected."""
        original_limit = limiter.effective_limit

        invalid_config = RunLimiterConfig(max_concurrent_runs=0)
        limiter.update_config(invalid_config)

        assert limiter.effective_limit == original_limit


@pytest.mark.asyncio
class TestAsyncConfigUpdates:
    """Test update_config with async waiters."""

    async def test_update_config_higher_limit_unblocks_waiters(self, limiter):
        """Increasing limit unblocks queued async waiters."""
        await limiter.acquire_async()
        await limiter.acquire_async()

        acquired_flags = [asyncio.Event() for _ in range(2)]

        async def waiter(flag: asyncio.Event):
            await limiter.acquire_async()
            flag.set()

        tasks = []
        for flag in acquired_flags:
            task = asyncio.create_task(waiter(flag))
            tasks.append(task)
            await asyncio.sleep(0.01)

        assert limiter.waiters_count == 2

        new_config = RunLimiterConfig(max_concurrent_runs=4)
        limiter.update_config(new_config)

        for flag in acquired_flags:
            await asyncio.wait_for(flag.wait(), timeout=1.0)

        assert limiter.active_count == 4

        for _ in range(4):
            limiter.release()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_update_config_lower_limit_respects_in_flight(self):
        """Lowering limit keeps existing acquisitions active."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        await limiter.acquire_async()
        await limiter.acquire_async()
        assert limiter.active_count == 2

        new_config = RunLimiterConfig(max_concurrent_runs=1)
        limiter.update_config(new_config)

        assert limiter.active_count == 2
        assert limiter.effective_limit == 1

        new_acquired = asyncio.Event()

        async def new_waiter():
            await limiter.acquire_async()
            new_acquired.set()

        task = asyncio.create_task(new_waiter())
        await asyncio.sleep(0.05)
        assert not new_acquired.is_set()

        # Must release BOTH slots since limit is now 1
        limiter.release()  # active=1
        await asyncio.sleep(0.05)
        # Still blocked because active==limit
        assert not new_acquired.is_set()

        limiter.release()  # active=0, waiter can acquire
        await asyncio.wait_for(new_acquired.wait(), timeout=1.0)

        limiter.release()
        await task


# ============================================================================
# Mixed sync/async tests
# ============================================================================


@pytest.mark.asyncio
class TestMixedSyncAsync:
    """Test mixed sync/async callers sharing the same limiter."""

    async def test_mixed_sync_async_share_limiter(self, limiter):
        """Sync and async callers share the same limit and queue."""
        # Fill the limiter completely first
        limiter.acquire_sync()
        limiter.acquire_sync()
        assert limiter.active_count == 2

        release_sync = threading.Event()

        def sync_holder():
            release_sync.wait(timeout=2.0)
            limiter.release()

        loop = asyncio.get_running_loop()
        sync_task = loop.run_in_executor(None, sync_holder)

        async_acquired = asyncio.Event()

        async def async_waiter():
            await limiter.acquire_async()
            async_acquired.set()

        async_task = asyncio.create_task(async_waiter())
        await asyncio.sleep(0.05)
        assert not async_acquired.is_set()
        assert limiter.waiters_count == 1

        release_sync.set()
        await asyncio.wait_for(async_acquired.wait(), timeout=1.0)

        await sync_task
        limiter.release()
        limiter.release()
        await async_task

    async def test_release_notifies_sync_waiters(self, limiter):
        """Release notifies sync waiters in background thread."""
        limiter.acquire_sync()
        limiter.acquire_sync()

        sync_acquired = threading.Event()

        def sync_waiter():
            limiter.acquire_sync()
            sync_acquired.set()

        loop = asyncio.get_running_loop()
        sync_task = loop.run_in_executor(None, sync_waiter)

        await asyncio.sleep(0.05)
        assert limiter.waiters_count == 1

        await asyncio.sleep(0)
        limiter.release()

        await asyncio.wait_for(
            loop.run_in_executor(None, sync_acquired.wait, 1.0), timeout=1.5
        )

        limiter.release()
        limiter.release()
        await sync_task


# ============================================================================
# FIFO fairness tests
# ============================================================================


@pytest.mark.asyncio
class TestAsyncFairness:
    """Test FIFO fairness for async waiters."""

    async def test_async_fifo_fairness(self):
        """Waiters acquire slots in order they started waiting."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        await limiter.acquire_async()

        acquisition_order = []
        order_lock = asyncio.Lock()

        async def waiter(name: str, ready: asyncio.Event, go: asyncio.Event):
            ready.set()
            await go.wait()
            await limiter.acquire_async()
            async with order_lock:
                acquisition_order.append(name)

        ready_events = [asyncio.Event() for _ in range(3)]
        go_events = [asyncio.Event() for _ in range(3)]

        tasks = [
            asyncio.create_task(waiter(f"w{i}", ready_events[i], go_events[i]))
            for i in range(3)
        ]

        for e in ready_events:
            await asyncio.wait_for(e.wait(), timeout=1.0)

        for e in go_events:
            e.set()
            await asyncio.sleep(0.01)

        for expected in ["w0", "w1", "w2"]:
            await asyncio.sleep(0.05)
            limiter.release()
            await asyncio.sleep(0.05)

        await asyncio.gather(*[asyncio.wait_for(t, timeout=2.0) for t in tasks])

        assert acquisition_order == ["w0", "w1", "w2"]

        while limiter.active_count > 0:
            limiter.release()


# ============================================================================
# Singleton tests
# ============================================================================


class TestSingleton:
    """Test get_run_limiter singleton behavior."""

    def test_get_run_limiter_returns_same_instance(self, reset_limiter):
        """Singleton: get_run_limiter() returns the same instance across calls."""
        limiter1 = get_run_limiter()
        limiter2 = get_run_limiter()
        assert limiter1 is limiter2

    def test_reset_run_limiter_for_tests_clears_singleton(self, reset_limiter):
        """Singleton: reset_run_limiter_for_tests clears the singleton."""
        limiter1 = get_run_limiter()
        reset_run_limiter_for_tests()
        limiter2 = get_run_limiter()
        assert limiter1 is not limiter2

    def test_update_run_limiter_config_updates_singleton(self, reset_limiter):
        """update_run_limiter_config updates the singleton's config."""
        limiter = get_run_limiter()

        update_run_limiter_config(max_concurrent_runs=5)

        assert limiter.effective_limit == 5
        assert limiter is get_run_limiter()


# ============================================================================
# Observability tests
# ============================================================================


class TestObservability:
    """Test active_count, effective_limit, waiters_count properties."""

    def test_active_count_reflects_current_state(self, limiter):
        """active_count property reflects current state."""
        assert limiter.active_count == 0

        limiter.acquire_sync()
        assert limiter.active_count == 1

        limiter.acquire_sync()
        assert limiter.active_count == 2

        limiter.release()
        assert limiter.active_count == 1

    def test_effective_limit_respects_allow_parallel(self):
        """effective_limit property respects allow_parallel flag."""
        limiter_parallel = RunLimiter(
            RunLimiterConfig(max_concurrent_runs=5, allow_parallel=True)
        )
        assert limiter_parallel.effective_limit == 5

        limiter_serial = RunLimiter(
            RunLimiterConfig(max_concurrent_runs=5, allow_parallel=False)
        )
        assert limiter_serial.effective_limit == 1

    def test_waiters_count_initially_zero(self, limiter):
        """waiters_count property is initially zero."""
        assert limiter.waiters_count == 0

        limiter.acquire_sync(blocking=False)
        assert limiter.waiters_count == 0

        limiter.release()
        assert limiter.waiters_count == 0


# ============================================================================
# Error handling tests
# ============================================================================


class TestErrorHandling:
    """Test error conditions and edge cases."""

    def test_release_with_no_active_runs_logs_warning(self, limiter, caplog):
        """release() called with no active runs logs warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            limiter.release()

        assert "no active runs" in caplog.text

    def test_invalid_config_defaults_to_sensible_values(self):
        """Invalid config defaults to sensible values."""
        invalid_config = RunLimiterConfig(max_concurrent_runs=-5)
        limiter = RunLimiter(invalid_config)
        assert limiter.effective_limit == 2

    @pytest.mark.asyncio
    async def test_slot_sync_with_full_limiter_raises(self, limiter):
        """slot_sync with full limiter raises RunConcurrencyLimitError."""
        limiter.acquire_sync()
        limiter.acquire_sync()

        with pytest.raises(RunConcurrencyLimitError):
            with limiter.slot_sync(blocking=False):
                pass


# ============================================================================
# Integration test
# ============================================================================


class TestIntegration:
    """Integration-level tests."""

    def test_basic_lifecycle(self):
        """Basic acquire/release lifecycle."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        assert limiter.acquire_sync(blocking=False) is True
        assert limiter.active_count == 1

        assert limiter.acquire_sync(blocking=False) is True
        assert limiter.active_count == 2

        assert limiter.acquire_sync(blocking=False) is False
        assert limiter.active_count == 2

        limiter.release()
        limiter.release()
        assert limiter.active_count == 0
