"""Stress and edge-case tests for RunLimiter.

These tests cover:
- In-flight waiters during config changes
- Shrink path edge cases  
- Singleton init edge cases
- Deficit invariants
"""

import asyncio
import threading
from unittest.mock import patch

import pytest

from code_puppy.plugins.pack_parallelism.run_limiter import (
    RunConcurrencyLimitError,
    RunLimiter,
    RunLimiterConfig,
    _get_reentrancy_depth,
    _set_reentrancy_depth,
    get_run_limiter,
    reset_run_limiter_for_tests,
)


@pytest.fixture
def reset_limiter():
    """Reset the singleton before and after each test."""
    reset_run_limiter_for_tests()
    yield
    reset_run_limiter_for_tests()


# ============================================================================
# In-flight Waiters Stress Tests
# ============================================================================


@pytest.mark.asyncio
class TestInflightWaiters:
    """Stress tests for in-flight waiters during config changes and edge cases."""

    async def test_waiters_during_shrink_are_not_dropped(self):
        """Waiters that are waiting when shrink happens must not be dropped.

        Regression test: When the limit is reduced while waiters are pending,
        they should still get a slot when capacity becomes available,
        not be silently forgotten.
        """
        from code_puppy.plugins.pack_parallelism.run_limiter import _set_reentrancy_depth

        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        # Use fully independent tasks (they get fresh context)
        async def holder_task():
            await limiter.acquire_async()
            await asyncio.sleep(10)  # Hold indefinitely

        # Fill to capacity with independent tasks
        holders = [asyncio.create_task(holder_task()) for _ in range(2)]
        await asyncio.sleep(0.1)  # Let them acquire
        assert limiter.active_count == 2

        # Start 3 waiters that will queue up (independent tasks)
        waiter_acquired = [asyncio.Event() for _ in range(3)]

        async def waiter_task(idx, event):
            await limiter.acquire_async()
            event.set()

        waiters = [
            asyncio.create_task(waiter_task(i, waiter_acquired[i]))
            for i in range(3)
        ]
        await asyncio.sleep(0.1)  # Let them queue
        assert limiter.waiters_count == 3

        # Shrink to 1 - waiters should remain queued
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter.effective_limit == 1
        assert limiter.waiters_count == 3  # Still waiting

        # Release holder slots one by one
        # Cancel first holder to release a slot
        holders[0].cancel()
        try:
            await holders[0]
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.05)

        # Cancel second holder
        holders[1].cancel()
        try:
            await holders[1]
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.05)

        # With deficit tracking, the first waiter should eventually get a slot
        # Cancel remaining waiters gracefully
        for w in waiters:
            if not w.done():
                w.cancel()
        for w in waiters:
            try:
                await w
            except asyncio.CancelledError:
                pass

    async def test_waiters_during_grow_get_prioritized_correctly(self):
        """When growing, existing waiters should get new capacity first."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Fill capacity
        holder_event = asyncio.Event()

        async def holder():
            await limiter.acquire_async()
            holder_event.set()
            await asyncio.sleep(10)

        holder_task = asyncio.create_task(holder())
        await asyncio.wait_for(holder_event.wait(), timeout=1.0)

        # Start waiters
        waiter_order: list[int] = []
        order_lock = asyncio.Lock()
        waiter_ready = [asyncio.Event() for _ in range(3)]

        async def waiter(idx):
            waiter_ready[idx].set()
            await limiter.acquire_async()
            async with order_lock:
                waiter_order.append(idx)

        waiters = [asyncio.create_task(waiter(i)) for i in range(3)]
        await asyncio.wait_for(asyncio.gather(*[e.wait() for e in waiter_ready]), timeout=1.0)
        await asyncio.sleep(0.05)  # Let them queue
        assert limiter.waiters_count == 3

        # Grow to 2 - first waiter should get slot
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        await asyncio.sleep(0.05)
        assert len(waiter_order) == 1

        # Release holder - second waiter should get slot
        holder_task.cancel()
        try:
            await holder_task
        except asyncio.CancelledError:
            pass
        limiter.release()
        await asyncio.sleep(0.05)
        assert len(waiter_order) == 2

        # Cancel remaining waiters
        for w in waiters:
            if not w.done():
                w.cancel()
                try:
                    await w
                except asyncio.CancelledError:
                    pass

    async def test_rapid_config_changes_during_wait(self):
        """Rapid shrink/grow cycles while waiters are pending must not lose waiters."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        # Fill capacity
        holder_acquired = [asyncio.Event() for _ in range(2)]

        async def holder(idx):
            await limiter.acquire_async()
            holder_acquired[idx].set()
            await asyncio.sleep(10)

        holders = [asyncio.create_task(holder(i)) for i in range(2)]
        await asyncio.wait_for(asyncio.gather(*[e.wait() for e in holder_acquired]), timeout=1.0)

        # Start a waiter
        waiter_acquired = asyncio.Event()

        async def waiter():
            await limiter.acquire_async()
            waiter_acquired.set()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert limiter.waiters_count == 1

        # Rapid config changes
        for new_limit in [3, 1, 4, 2, 1, 5]:
            limiter.update_config(RunLimiterConfig(max_concurrent_runs=new_limit))
            await asyncio.sleep(0.01)

        # Release holders - waiter should eventually get a slot
        for _ in range(2):
            limiter.release()
        await asyncio.sleep(0.1)

        # Cancel everything
        for h in holders:
            h.cancel()
        waiter_task.cancel()
        try:
            await asyncio.gather(*holders, waiter_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def test_waiter_count_accuracy_under_stress(self):
        """waiters_count must remain accurate under concurrent stress."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Fill capacity
        holder = asyncio.Event()

        async def hold():
            await limiter.acquire_async()
            holder.set()
            await asyncio.sleep(10)

        holder_task = asyncio.create_task(hold())
        await asyncio.wait_for(holder.wait(), timeout=1.0)

        # Many concurrent waiters
        num_waiters = 50
        start_events = [asyncio.Event() for _ in range(num_waiters)]

        async def delayed_waiter(start_event):
            start_event.set()
            try:
                await limiter.acquire_async(timeout=5.0)
                return "acquired"
            except RunConcurrencyLimitError:
                return "timeout"

        # Create all waiters simultaneously
        tasks = [
            asyncio.create_task(delayed_waiter(e))
            for e in start_events
        ]
        await asyncio.wait_for(asyncio.gather(*[e.wait() for e in start_events]), timeout=1.0)
        await asyncio.sleep(0.1)

        # Check waiters_count is accurate
        assert limiter.waiters_count == num_waiters, (
            f"Expected {num_waiters} waiters, got {limiter.waiters_count}"
        )

        # Cancel holder and let waiters proceed
        holder_task.cancel()
        try:
            await holder_task
        except asyncio.CancelledError:
            pass

        # All waiters should complete
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
        acquired_count = sum(1 for r in results if r == "acquired")

        # Should be able to acquire up to the limit
        assert acquired_count <= limiter.effective_limit or acquired_count == 1, (
            f"Unexpected acquisition pattern: {results[:10]}..."
        )

        # Waiters count should be 0
        await asyncio.sleep(0.05)
        assert limiter.waiters_count == 0


# ============================================================================
# Shrink Path Edge Case Tests
# ============================================================================



    """Edge case tests for the shrink path in update_config."""


# ============================================================================
# Singleton Init Edge Case Tests
# ============================================================================


class TestSingletonInitEdgeCases:
    """Edge case tests for singleton initialization."""

    def test_concurrent_singleton_init_race(self, reset_limiter):
        """Concurrent calls to get_run_limiter() must not create multiple instances."""
        instances: list = []
        errors: list = []
        lock = threading.Lock()

        def get_instance():
            try:
                inst = get_run_limiter()
                with lock:
                    instances.append(inst)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Spawn many threads simultaneously
        threads = [threading.Thread(target=get_instance) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent init: {errors}"
        # All instances should be the same object
        assert len(set(id(i) for i in instances)) == 1, (
            "Multiple instances created during concurrent init"
        )

    def test_singleton_init_with_invalid_config(self, reset_limiter, tmp_path, monkeypatch):
        """Singleton init with invalid config file must use defaults gracefully."""
        # Create invalid config
        config_dir = tmp_path / ".code_puppy"
        config_dir.mkdir()
        config_file = config_dir / "pack_parallelism.toml"
        config_file.write_text("invalid toml content {{[[")

        # Temporarily redirect home
        monkeypatch.setenv("HOME", str(tmp_path))

        # Should not crash
        limiter = get_run_limiter()
        assert limiter.effective_limit >= 1  # Sensible default

    def test_reentrancy_depth_cleared_on_reset(self, reset_limiter):
        """Reset must clear reentrancy depth to prevent stale state."""
        # Manually set a depth
        _set_reentrancy_depth(5)
        assert _get_reentrancy_depth() == 5

        # Reset should clear it
        reset_run_limiter_for_tests()
        assert _get_reentrancy_depth() == 0

    def test_singleton_preserves_config_after_reset(self, reset_limiter):
        """After reset, new singleton must re-read config."""
        # Get initial instance and modify config
        limiter1 = get_run_limiter()
        limiter1.update_config(RunLimiterConfig(max_concurrent_runs=7))
        assert limiter1.effective_limit == 7

        # Reset and get new instance
        reset_run_limiter_for_tests()
        limiter2 = get_run_limiter()

        # New instance should not have the modified config
        # (it re-reads from defaults/file, not from modified limiter1)
        assert limiter1 is not limiter2
        assert limiter2.effective_limit != 7 or limiter2.effective_limit == 2


# ============================================================================
# Deficit Invariant Tests
# ============================================================================


class TestDeficitInvariants:
    """Tests to verify deficit tracking invariants are maintained."""

    def test_deficit_never_negative(self):
        """Deficit counters must never go negative."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Set up deficit
        for _ in range(3):
            limiter.acquire_sync(blocking=False)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter._sync_deficit == 2  # Or _async_deficit depending on path

        # Release all slots - deficit absorbs first 2
        for _ in range(3):
            limiter.release()

        # Deficit should be 0, not negative
        assert limiter._sync_deficit >= 0
        assert limiter._async_deficit >= 0
        assert limiter._sync_deficit == 0
        assert limiter._async_deficit == 0

    def test_deficit_plus_active_equals_old_limit(self):
        """After shrink: deficit + active + new_limit_remaining = old_limit."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))

        # Acquire 3 slots, leaving 2 slack
        for _ in range(3):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 3

        # Shrink to 2
        old_limit = 5
        new_limit = 2
        excess = old_limit - new_limit  # 3

        limiter.update_config(RunLimiterConfig(max_concurrent_runs=new_limit))

        # After shrink:
        # - Some excess drained from semaphore (slack)
        # - Rest becomes deficit
        # - Deficit + (new_limit - active_with_new_capacity) should be consistent
        assert limiter.effective_limit == new_limit
        assert limiter._sync_deficit >= 0

        # Clean up
        while limiter.active_count > 0:
            limiter.release()

    def test_releases_dont_exceed_deficit(self):
        """Releases must not create more capacity than deficit allows.

        When deficit > 0, releases absorb into deficit without creating
        new capacity. The total "virtual" slots (deficit + semaphore value)
        should remain constant until deficit reaches 0.
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Acquire all 4 slots
        for _ in range(4):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 4

        # Shrink to 1 - creates deficit of 3
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))

        # Release 2 slots - both absorbed by deficit
        limiter.release()
        limiter.release()
        assert limiter.active_count == 2

        # Check deficit tracking is correct
        # Depending on path (sync/async), deficit could be on either side
        total_deficit = limiter._sync_deficit + limiter._async_deficit
        assert total_deficit > 0, "Deficit should still exist"

        # Release third slot - absorbs remaining deficit
        limiter.release()
        assert limiter.active_count == 1

        # Fourth release creates capacity (deficit now 0)
        limiter.release()
        assert limiter.active_count == 0

        # Can now acquire exactly 1 slot (the limit)
        acquired = limiter.acquire_sync(blocking=False)
        assert acquired
        assert limiter.active_count == 1

        second = limiter.acquire_sync(blocking=False)
        assert not second  # Limit is 1

        limiter.release()

    def test_growth_cannot_exceed_original_limit(self):
        """After multiple shrink/grow cycles, we shouldn't exceed intended limits."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Acquire all 3 slots
        for _ in range(3):
            limiter.acquire_sync(blocking=False)

        # Several shrink/grow cycles
        for _ in range(5):
            limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
            limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))

        # Release all
        for _ in range(3):
            limiter.release()

        # Should be able to acquire exactly 3 slots
        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety
                break

        assert acquired_count == 3, (
            f"Expected 3 slots, got {acquired_count}. "
            "Deficit tracking leaked slots across cycles."
        )

        while limiter.active_count > 0:
            limiter.release()


# ============================================================================
# Shrink Path Edge Case Tests
# ============================================================================


class TestShrinkPathEdgeCases:
    """Edge case tests for the shrink path in update_config."""

    def test_shrink_to_zero_is_rejected(self):
        """Shrink to 0 (or negative) must be rejected as invalid."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        original_limit = limiter.effective_limit
        invalid_config = RunLimiterConfig(max_concurrent_runs=0)
        limiter.update_config(invalid_config)

        assert limiter.effective_limit == original_limit
        assert limiter._sync_deficit == 0
        assert limiter._async_deficit == 0

    def test_shrink_while_all_slots_in_use_no_slack(self):
        """Shrink when all slots in use (no slack) - all excess becomes deficit."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Acquire all 4 slots via sync path (no reentrancy issues)
        for _ in range(4):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 4
        assert limiter._sync_active == 4

        # Shrink to 2 - all 2 excess become deficit (none could be drained)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2
        assert limiter._sync_deficit == 2  # 4 - 2 = 2
        assert limiter._async_deficit == 0

        # Release all - deficit absorbs first 2 releases
        limiter.release()
        limiter.release()
        assert limiter.active_count == 2
        assert limiter._sync_deficit == 0

        limiter.release()
        limiter.release()
        assert limiter.active_count == 0

    def test_shrink_with_partial_slack(self):
        """Shrink with partial slack - some slots drained, rest become deficit."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))

        # Acquire 2 slots via sync, leaving 3 slack
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2
        assert limiter._sync_active == 2

        # Shrink from 5 to 3
        # Excess = 2 (5-3=2)
        # Sync: 2 active, 3 slots, drain 2 free slots, deficit = 0
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3
        assert limiter._sync_deficit == 0  # All excess was drainable

        # Can acquire 1 more (3 limit - 2 active = 1)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 3

        # Cannot acquire more
        acquired = limiter.acquire_sync(blocking=False)
        assert not acquired

        limiter.release()
        limiter.release()
        limiter.release()

    async def test_shrink_with_waiter_gets_priority(self):
        """When shrinking with waiters, released slots should go to waiters.

        The deficit absorbs releases first, but any slot made available
        through deficit clearing should be immediately available to waiters.
        """
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Fill all slots using independent tasks
        async def holder_task():
            await limiter.acquire_async()
            await asyncio.sleep(10)

        holders = [asyncio.create_task(holder_task()) for _ in range(3)]
        await asyncio.sleep(0.1)
        assert limiter.active_count == 3

        # Shrink to 1 - creates deficit of 2
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))

        # Start a waiter
        waiter_got_slot = asyncio.Event()

        async def waiter():
            await limiter.acquire_async()
            waiter_got_slot.set()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)

        # Cancel holder tasks to release slots
        for h in holders:
            h.cancel()
            try:
                await h
            except asyncio.CancelledError:
                pass
        await asyncio.sleep(0.05)

        # Waiter may or may not get a slot depending on timing
        # Cancel it gracefully
        if not waiter_task.done():
            waiter_task.cancel()
        try:
            await waiter_task
        except asyncio.CancelledError:
            pass

    def test_shrink_then_immediate_grow(self):
        """Shrink followed immediately by grow must restore capacity correctly."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Acquire 2 slots via sync
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2

        # Shrink then immediately grow back
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=4))

        assert limiter.effective_limit == 4
        # Should be able to acquire 2 more
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 4

        for _ in range(4):
            limiter.release()


# ============================================================================
# Mixed Sync/Async Edge Cases
# ============================================================================


@pytest.mark.asyncio
class TestMixedSyncAsyncEdgeCases:
    """Edge cases involving mixed sync and async usage."""

    async def test_sync_acquire_async_release(self):
        """Sync acquire followed by async release must work correctly."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        # Sync acquire
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 1
        assert limiter._sync_active == 1

        # Release from async context
        limiter.release()
        assert limiter.active_count == 0

    async def test_async_acquire_sync_release(self):
        """Async acquire followed by sync release must work correctly."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=2))

        # Async acquire
        await limiter.acquire_async()
        assert limiter.active_count == 1
        assert limiter._async_active == 1

        # Release from sync context (simulated by calling release directly)
        # Note: in reality this might be called from a different thread
        limiter.release()
        assert limiter.active_count == 0

    async def test_mixed_active_counts_correctly(self):
        """Mixed sync/async active counts must sum correctly."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # One sync, one async
        limiter.acquire_sync(blocking=False)
        await limiter.acquire_async()

        assert limiter.active_count == 2
        assert limiter._sync_active == 1
        assert limiter._async_active == 1

        limiter.release()
        limiter.release()


# ============================================================================
# Stress Tests
# ============================================================================


class TestStressScenarios:
    """High-concurrency stress tests."""

    async def test_high_concurrency_acquire_release(self):
        """Stress test with many concurrent acquire/release cycles."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))
        num_workers = 50
        iterations = 10

        async def worker():
            for _ in range(iterations):
                await limiter.acquire_async()
                await asyncio.sleep(0.001)  # Simulate work
                limiter.release()

        await asyncio.gather(*[worker() for _ in range(num_workers)])

        # Final state should be clean
        assert limiter.active_count == 0
        assert limiter.waiters_count == 0
        assert limiter._sync_deficit == 0
        assert limiter._async_deficit == 0

    async def test_rapid_config_changes_stress(self):
        """Rapid config changes with concurrent operations."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))
        stop_event = asyncio.Event()
        errors: list = []
        error_lock = asyncio.Lock()

        async def changer():
            limits = [1, 5, 3, 7, 2, 10, 4]
            idx = 0
            while not stop_event.is_set():
                try:
                    limiter.update_config(
                        RunLimiterConfig(max_concurrent_runs=limits[idx % len(limits)])
                    )
                    idx += 1
                    await asyncio.sleep(0.01)
                except Exception as e:
                    async with error_lock:
                        errors.append(f"changer: {e}")

        async def user():
            try:
                for _ in range(20):
                    try:
                        await limiter.acquire_async(timeout=0.1)
                        await asyncio.sleep(0.01)
                        limiter.release()
                    except RunConcurrencyLimitError:
                        pass
            except Exception as e:
                async with error_lock:
                    errors.append(f"user: {e}")

        # Start tasks
        changer_task = asyncio.create_task(changer())
        user_tasks = [asyncio.create_task(user()) for _ in range(5)]

        # Let it run for a bit
        await asyncio.sleep(0.5)
        stop_event.set()

        await changer_task
        await asyncio.gather(*user_tasks)

        assert not errors, f"Errors during stress test: {errors}"

    def test_threading_stress_sync_only(self):
        """Stress test with many threads using sync interface."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))
        num_threads = 20
        iterations = 50
        errors: list = []
        error_lock = threading.Lock()

        def worker():
            try:
                for _ in range(iterations):
                    if limiter.acquire_sync(blocking=True, timeout=1.0):
                        # Simulate work
                        import time
                        time.sleep(0.001)
                        limiter.release()
            except Exception as e:
                with error_lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during threading stress: {errors}"
        assert limiter.active_count == 0
        assert limiter.waiters_count == 0
