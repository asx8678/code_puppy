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
    force_reset_limiter_state,
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
        # Fill the limiter using separate tasks (same task would use reentrancy bypass)
        holder_task = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.01)  # Let first acquire complete
        waiter_task = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.01)  # Let second acquire start waiting
        assert limiter.active_count == 2
        assert limiter.waiters_count == 0  # No additional waiters yet

        # Signal to release slot
        slot_released = asyncio.Event()
        acquired_third = asyncio.Event()

        async def holder():
            await asyncio.wait_for(slot_released.wait(), timeout=1.0)
            limiter.release()  # Release one slot

        async def third_waiter():
            await limiter.acquire_async()
            acquired_third.set()
            limiter.release()

        # Start the holder that will release a slot
        holder_task2 = asyncio.create_task(holder())
        await asyncio.sleep(0.01)

        # Now a third task tries to acquire (should wait until slot released)
        third_task = asyncio.create_task(third_waiter())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 2
        assert limiter.waiters_count == 1  # Third is waiting

        slot_released.set()
        await asyncio.wait_for(acquired_third.wait(), timeout=1.0)

        await holder_task
        await waiter_task
        await holder_task2
        await third_task

    async def test_acquire_timeout_raises(self, limiter):
        """Async acquire with timeout: raises RunConcurrencyLimitError on expiry."""
        # Fill limiter using separate tasks
        task1 = asyncio.create_task(limiter.acquire_async())
        task2 = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 2

        # Use a new task for the timeout test (current task has no slot, depth=0)
        async def try_acquire():
            await limiter.acquire_async(timeout=0.01)

        with pytest.raises(RunConcurrencyLimitError) as exc_info:
            await try_acquire()

        assert exc_info.value.limit == 2
        assert exc_info.value.active == 2
        await task1
        await task2

    async def test_acquire_timeout_zero_fast_fail(self, limiter):
        """Async acquire with timeout=0: immediately fails if full."""
        # Fill limiter using separate tasks
        task1 = asyncio.create_task(limiter.acquire_async())
        task2 = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 2

        async def try_acquire():
            await limiter.acquire_async(timeout=0)

        with pytest.raises(RunConcurrencyLimitError):
            await try_acquire()

        await task1
        await task2

    async def test_acquire_timeout_zero_succeeds_when_empty(self, limiter):
        """Async acquire with timeout=0: succeeds when slot available."""
        # First acquire from a separate task so this task stays clean
        task1 = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.01)
        # Current task has no slot, second slot is available
        await limiter.acquire_async(timeout=0)
        assert limiter.active_count == 2
        limiter.release()
        await task1

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
        # Fill limiter using separate tasks
        task1 = asyncio.create_task(limiter.acquire_async())
        task2 = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 2

        async def try_slot():
            async with limiter.slot_async(timeout=0):
                pass

        with pytest.raises(RunConcurrencyLimitError):
            await try_slot()

        await task1
        await task2


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

    def test_update_config_from_sync_context_no_crash(self, limiter):
        """update_config() called from sync context must not crash.

        Regression test for: asyncio.create_task() called with no running loop.
        The shrink path in update_config() must work from sync contexts.
        """
        # Start with a higher limit
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))

        # Fill up with some active runs (but not all)
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2

        # Shrink from sync context - this must NOT crash
        shrink_config = RunLimiterConfig(max_concurrent_runs=2)
        limiter.update_config(shrink_config)  # Should not raise RuntimeError

        assert limiter.effective_limit == 2

    def test_shrink_then_grow_no_slot_leak(self, limiter):
        """Shrink followed by grow must not leak slots.

        Regression test for: _drain_slot over-draining causing permanent slot loss.
        After shrinking and growing back, the full capacity should be available.
        """
        # Start with limit 3
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Acquire 2 slots
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2

        # Shrink to 1 - active runs continue, deficit = 1
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter.effective_limit == 1

        # Release one slot - deficit absorbs it, no semaphore release
        limiter.release()
        assert limiter.active_count == 1

        # Release second slot - now active == 0
        limiter.release()
        assert limiter.active_count == 0

        # Grow back to 3
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3

        # Should be able to acquire all 3 slots
        for i in range(3):
            acquired = limiter.acquire_sync(blocking=False)
            assert acquired, f"Failed to acquire slot {i+1} after shrink/grow cycle"

        assert limiter.active_count == 3


@pytest.mark.asyncio
class TestAsyncConfigUpdates:
    """Test update_config with async waiters."""

    async def test_update_config_higher_limit_adds_slots(self, limiter):
        """Increasing limit adds new slots for future acquires."""
        # Fill using separate tasks created BEFORE any acquire (independent contexts)
        async def acquire_slot():
            await limiter.acquire_async()

        task1 = asyncio.create_task(acquire_slot())
        task2 = asyncio.create_task(acquire_slot())
        await asyncio.sleep(0.05)

        assert limiter.active_count == 2

        new_config = RunLimiterConfig(max_concurrent_runs=4)
        limiter.update_config(new_config)

        # Should be able to acquire 2 more slots via new tasks
        task3 = asyncio.create_task(acquire_slot())
        task4 = asyncio.create_task(acquire_slot())
        await asyncio.sleep(0.05)

        assert limiter.active_count == 4

        # Release all slots
        limiter.release()
        limiter.release()
        await task1
        await task2
        for t in [task3, task4]:
            limiter.release()
            await t

    async def test_update_config_lower_limit_respects_in_flight(self):
        """Lowering limit keeps existing acquisitions active.

        With deficit-based shrinking, the deficit counter ensures that
        releases don't restore capacity until the deficit is cleared.
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Use separate tasks created BEFORE any acquire (independent contexts)
        async def acquire_slot():
            await limiter.acquire_async()

        # Fill the limiter completely first (3 slots)
        task1 = asyncio.create_task(acquire_slot())
        task2 = asyncio.create_task(acquire_slot())
        task3 = asyncio.create_task(acquire_slot())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 3

        # Shrink to 1 - this sets deficit=2 while 3 are still active
        new_config = RunLimiterConfig(max_concurrent_runs=1)
        limiter.update_config(new_config)

        # Note: active_count stays 3 because we haven't released anything yet
        # After shrink, releases will absorb the deficit first
        assert limiter.effective_limit == 1

        # New waiter should block because semaphore is empty (3 slots in use)
        new_acquired = asyncio.Event()

        async def new_waiter():
            await limiter.acquire_async()
            new_acquired.set()

        task4 = asyncio.create_task(new_waiter())
        await asyncio.sleep(0.05)
        assert not new_acquired.is_set()

        # Release first slot - deficit absorbs it, no capacity restored
        # active goes to 2, deficit goes to 1, semaphore stays at 0
        limiter.release()
        await asyncio.sleep(0.05)
        assert not new_acquired.is_set()

        # Release second slot - deficit absorbs it, still no capacity
        # active goes to 1, deficit goes to 0, semaphore stays at 0
        limiter.release()
        await asyncio.sleep(0.05)
        assert not new_acquired.is_set()

        # Release third slot - now capacity is restored
        # active goes to 0, deficit stays at 0, semaphore releases 1 slot
        limiter.release()
        await asyncio.wait_for(new_acquired.wait(), timeout=1.0)

        # Clean up: release remaining slots
        limiter.release()  # from task4
        await task4
        limiter.release()  # from task1
        limiter.release()  # from task2
        limiter.release()  # from task3
        await task1
        await task2
        await task3


# ============================================================================
# Cancellation tests (Bug #1 fix)
# ============================================================================


@pytest.mark.asyncio
class TestCancellation:
    """Test cancellation-safety of the new asyncio.Semaphore implementation."""

    async def test_cancelled_acquire_decrements_waiters(self):
        """When an async acquire is cancelled while waiting, waiters_count is properly decremented."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Create holder task first (independent context)
        holder_task = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 1

        # Now create waiter that will block (also independent context)
        ready_to_wait = asyncio.Event()
        should_acquire = asyncio.Event()

        async def waiter():
            ready_to_wait.set()
            await should_acquire.wait()  # Wait for signal
            await limiter.acquire_async()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.wait_for(ready_to_wait.wait(), timeout=1.0)
        
        # Signal waiter to start acquiring (will block since holder has slot)
        should_acquire.set()
        await asyncio.sleep(0.05)

        assert limiter.waiters_count == 1  # Waiter is waiting

        # Cancel the waiter
        waiter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_task

        # Waiter count should be 0 after cancellation
        await asyncio.sleep(0.05)  # Let cleanup finish
        assert limiter.waiters_count == 0
        assert limiter.active_count == 1  # Still holding original

        limiter.release()
        await holder_task
        assert limiter.active_count == 0

    async def test_cancelled_acquire_does_not_leak_slot(self):
        """After a cancelled acquire, a new caller can still acquire the released slot."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Create holder task first (independent context)
        holder_task = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 1

        # Create waiter that will block
        ready_to_wait = asyncio.Event()
        should_acquire = asyncio.Event()

        async def waiter():
            ready_to_wait.set()
            await should_acquire.wait()
            await limiter.acquire_async()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.wait_for(ready_to_wait.wait(), timeout=1.0)
        should_acquire.set()
        await asyncio.sleep(0.05)

        # Cancel the waiter
        waiter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_task

        # Release the original slot
        limiter.release()
        await holder_task

        # A new caller MUST be able to acquire immediately — no zombie slot stealing
        await asyncio.wait_for(limiter.acquire_async(), timeout=0.5)
        assert limiter.active_count == 1
        limiter.release()

    async def test_many_cancellations_no_drift(self):
        """Stress test: many cancelled acquires should not drift active/waiter counts."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        # Create all waiter tasks BEFORE any acquires (so they're independent)
        ready_events = [asyncio.Event() for _ in range(22)]

        async def waiter(ready: asyncio.Event):
            ready.set()
            await limiter.acquire_async()

        # Start 2 holders first
        holder1 = asyncio.create_task(limiter.acquire_async())
        holder2 = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)

        # Now start 20 waiters
        waiters = [asyncio.create_task(waiter(ready_events[i])) for i in range(20)]
        await asyncio.sleep(0.1)

        # Cancel all waiters
        for w in waiters:
            w.cancel()

        results = await asyncio.gather(*waiters, return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)

        # Counts should be clean
        await asyncio.sleep(0.05)
        assert limiter.waiters_count == 0
        assert limiter.active_count == 2  # Only holders

        # Release holder slots
        limiter.release()
        limiter.release()
        await holder1
        await holder2
        assert limiter.active_count == 0

    async def test_timeout_then_success_for_next_caller(self):
        """After a timeout, subsequent callers can still acquire when slots free up."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Create holder task independently
        holder_task = asyncio.create_task(limiter.acquire_async())
        await asyncio.sleep(0.05)
        assert limiter.active_count == 1

        # Now this task tries to acquire and times out
        with pytest.raises(RunConcurrencyLimitError):
            await limiter.acquire_async(timeout=0.05)

        assert limiter.waiters_count == 0

        # Release from the holder task
        limiter.release()
        await holder_task
        # New caller should succeed
        await asyncio.wait_for(limiter.acquire_async(), timeout=0.5)
        limiter.release()


# ============================================================================
# Reentrancy tests (Bug #2 fix)
# ============================================================================


@pytest.mark.asyncio
class TestReentrancy:
    """Test reentrancy bypass to prevent nested agent deadlocks."""

    async def test_nested_acquire_bypasses_limit(self):
        """A task that already holds a slot can 'acquire' nested without waiting."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        await limiter.acquire_async()
        assert limiter.active_count == 1

        # Nested acquire should be a no-op (bypass)
        await limiter.acquire_async()
        assert limiter.active_count == 1  # Still 1 — nested call did not take a slot

        # Nested release should also be a no-op
        limiter.release()
        assert limiter.active_count == 1

        # Top-level release
        limiter.release()
        assert limiter.active_count == 0

    async def test_nested_acquire_survives_deep_nesting(self):
        """Three levels of nesting work correctly."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        await limiter.acquire_async()  # depth 1
        await limiter.acquire_async()  # depth 2
        await limiter.acquire_async()  # depth 3

        assert limiter.active_count == 1

        limiter.release()  # depth 2
        limiter.release()  # depth 1
        assert limiter.active_count == 1

        limiter.release()  # depth 0
        assert limiter.active_count == 0

    async def test_child_task_inherits_reentrancy_bypass(self):
        """Child tasks created via asyncio.create_task() inherit the parent's slot.

        This is the CRITICAL fix for nested invoke_agent deadlocks: when an agent
        holds a slot and spawns a sub-agent via create_task, the sub-agent's own
        acquire_async() must be a no-op bypass (because the parent is already
        counting the slot). Otherwise we get deadlock when nested depth > limit.

        Mechanism: contextvars.ContextVar is snapshotted by asyncio.create_task().
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        child_done = asyncio.Event()
        child_observed_active = None
        child_observed_limit_reached = None

        async def child_work():
            nonlocal child_observed_active, child_observed_limit_reached
            # Child inherits parent's context with depth=1
            # So this acquire should be a NO-OP bypass
            await limiter.acquire_async()
            # The active count should still be 1 (parent's slot)
            child_observed_active = limiter.active_count
            # Try a DEEPER nested acquire — should also bypass
            await limiter.acquire_async()
            child_observed_limit_reached = limiter.active_count
            # Release both bypasses
            limiter.release()
            limiter.release()
            child_done.set()

        # Parent acquires slot
        await limiter.acquire_async()
        assert limiter.active_count == 1

        # Spawn child — it inherits context with depth=1
        child_task = asyncio.create_task(child_work())
        await asyncio.wait_for(child_done.wait(), timeout=1.0)
        await child_task

        # Child should have observed active_count=1 throughout (no new slots taken)
        assert child_observed_active == 1, (
            f"Child's nested acquire did not bypass! observed active={child_observed_active}"
        )
        assert child_observed_limit_reached == 1, (
            "Deeper nesting did not bypass!"
        )

        # Parent still holds its slot
        assert limiter.active_count == 1
        limiter.release()
        assert limiter.active_count == 0

    async def test_sibling_tasks_do_not_share_reentrancy(self):
        """Sibling tasks (created before any acquire) don't share reentrancy state.

        This verifies that contextvar scoping is per-task: two independent tasks
        can each acquire their own slot without interference.
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        t1_acquired = asyncio.Event()
        t2_acquired = asyncio.Event()
        t1_release = asyncio.Event()
        t2_release = asyncio.Event()

        async def worker(acquired_ev, release_ev):
            await limiter.acquire_async()
            acquired_ev.set()
            await release_ev.wait()
            limiter.release()

        task1 = asyncio.create_task(worker(t1_acquired, t1_release))
        task2 = asyncio.create_task(worker(t2_acquired, t2_release))

        # Both should acquire independently
        await asyncio.wait_for(t1_acquired.wait(), timeout=1.0)
        await asyncio.wait_for(t2_acquired.wait(), timeout=1.0)
        assert limiter.active_count == 2  # Both hold real slots

        t1_release.set()
        t2_release.set()
        await asyncio.gather(task1, task2)
        assert limiter.active_count == 0

    async def test_deeply_nested_create_task_chain(self):
        """Simulate agent_tools.py pattern: chain of create_task -> create_task -> ...

        Only the OUTERMOST task takes a real slot; all nested create_task children
        inherit the bypass. This prevents deadlock when nested depth > limit.
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))
        depth_reached = 0

        async def recurse(levels_remaining: int):
            nonlocal depth_reached
            await limiter.acquire_async()  # Only the FIRST call takes a slot
            depth_reached = max(depth_reached, 5 - levels_remaining)
            if levels_remaining > 0:
                child = asyncio.create_task(recurse(levels_remaining - 1))
                await child
            limiter.release()

        await recurse(5)
        assert depth_reached == 5, f"Expected depth 5, got {depth_reached}"
        assert limiter.active_count == 0  # All cleaned up


# ============================================================================
# Note: Mixed sync/async tests removed
# ============================================================================
# Sync and async are now independent by design — they use separate semaphores.
# Production only uses the async path. Tests should use either all-sync or all-async.


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
# Force reset tests
# ============================================================================


class TestForceReset:
    """Test force_reset_limiter_state emergency recovery."""

    def test_force_reset_with_no_instance(self, reset_limiter):
        """Reset when no instance exists returns appropriate status."""
        # Ensure no instance exists
        reset_run_limiter_for_tests()
        result = force_reset_limiter_state()
        assert result["status"] == "no_instance"

    def test_force_reset_clears_active_and_waiters(self, reset_limiter):
        """Reset clears all counters and recreates semaphores."""
        limiter = get_run_limiter()

        # Artificially mess up state
        limiter._async_active = 5
        limiter._async_waiters = 3
        limiter._sync_active = 2
        limiter._sync_waiters = 1

        result = force_reset_limiter_state()

        assert result["status"] == "reset"
        assert result["previous"]["async_active"] == 5
        assert result["previous"]["async_waiters"] == 3
        assert result["previous"]["sync_active"] == 2
        assert result["previous"]["sync_waiters"] == 1

        # After reset
        assert limiter.active_count == 0
        assert limiter.waiters_count == 0

    @pytest.mark.asyncio
    async def test_force_reset_makes_slots_available(self, reset_limiter):
        """After reset, new acquires can succeed even if old state was stuck."""
        limiter = get_run_limiter()

        # Artificially "leak" slots by corrupting active count
        limiter._async_active = 100  # Pretend 100 slots are "taken"
        # Replace with empty semaphore - force a stuck state
        limiter._async_sem = asyncio.Semaphore(0)  # Empty semaphore
        limiter._sync_sem = threading.Semaphore(0)  # Empty sync semaphore too

        # Try to acquire sync — should fail with current state (no slots)
        # Note: we need a short timeout because blocking=False still waits
        # in threading.Semaphore if there's a lock contention
        acquired = limiter._sync_sem.acquire(blocking=False)
        assert not acquired

        # Force reset
        force_reset_limiter_state()

        # Now we can acquire normally via sync path
        acquired = limiter.acquire_sync(blocking=False)
        assert acquired
        assert limiter.active_count == 1
        limiter.release()


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
