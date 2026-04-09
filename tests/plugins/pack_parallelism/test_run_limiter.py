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
            assert acquired, f"Failed to acquire slot {i + 1} after shrink/grow cycle"

        assert limiter.active_count == 3

    def test_grow_with_unabsorbed_deficit_does_not_over_release(self, limiter):
        """Grow with unabsorbed shrink deficit must not over-release ghost slots.

        Regression test for: Zeroing _shrink_deficit on grow caused over-release.
        When growing after a shrink, any unabsorbed deficit must first be
        consumed before releasing new capacity to the semaphore.
        """
        # Start with limit 3
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Acquire all 3 slots
        for _ in range(3):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 3

        # Shrink to 1 - creates deficit of 2 (3-1=2)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter.effective_limit == 1

        # Grow to 2 - growth is 1, but deficit is 2
        # The growth should absorb 1 from deficit, not release any slots
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2

        # Release one slot - absorbed by remaining deficit (now 1)
        limiter.release()
        assert limiter.active_count == 2

        # Release second slot - absorbed by remaining deficit (now 0)
        limiter.release()
        assert limiter.active_count == 1

        # Release third slot - now creates capacity since deficit is 0
        limiter.release()
        assert limiter.active_count == 0

        # Should be able to acquire exactly 2 slots (the new limit)
        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 3:  # Safety break
                break

        assert acquired_count == 2, (
            f"Expected 2 slots after shrink/grow with deficit, got {acquired_count}. "
            "Ghost slots were likely over-released."
        )

    def test_shrink_deficit_absorbs_releases_to_enforce_lower_cap(self, limiter):
        """Shrink deficit must absorb releases until deficit is cleared.

        Regression test for: Shrink with semaphore slack never enforced new lower cap.
        The deficit counter ensures that releases don't create capacity until
        the deficit is fully absorbed, effectively lowering the cap over time.
        """
        # Start with limit 4, acquire all slots (no slack)
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Acquire all 4 slots
        for _ in range(4):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 4

        # Shrink to 1 - creates deficit of 3 (4-1=3)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter.effective_limit == 1

        # Release first slot - absorbed by deficit (now 2)
        # No capacity is released to semaphore
        limiter.release()
        assert limiter.active_count == 3

        # Try to acquire - should fail because release was absorbed by deficit
        acquired = limiter.acquire_sync(blocking=False)
        assert not acquired, (
            "Should not acquire immediately after release during shrink deficit - "
            "release was absorbed, not converted to capacity"
        )

        # Release second slot - absorbed by deficit (now 1)
        limiter.release()
        assert limiter.active_count == 2
        acquired = limiter.acquire_sync(blocking=False)
        assert not acquired, "Second release also absorbed - still no capacity"

        # Release third slot - absorbed by deficit (now 0)
        limiter.release()
        assert limiter.active_count == 1
        acquired = limiter.acquire_sync(blocking=False)
        assert not acquired, "Third release also absorbed - still no capacity"

        # Release fourth slot - now capacity is released (deficit is 0)
        limiter.release()
        assert limiter.active_count == 0

        # NOW we can acquire up to the limit (1)
        acquired = limiter.acquire_sync(blocking=False)
        assert acquired, "After deficit cleared, should acquire the slot"

        # Can't acquire second because limit is 1
        second_acquire = limiter.acquire_sync(blocking=False)
        assert not second_acquire, "Should not exceed new limit of 1"

        # This release creates capacity for next acquire
        limiter.release()
        acquired = limiter.acquire_sync(blocking=False)
        assert acquired, "Release after deficit=0 creates capacity"
        limiter.release()

    def test_shrink_with_slack_enforces_new_cap_immediately(self, limiter):
        """Shrink with free capacity (slack) must enforce new lower cap immediately.

        Regression test for: shrink-with-slack allowed acquires past the new cap
        because free semaphore slots were not drained immediately.
        When shrinking from 4 to 2 with only 1 active run (3 slots free),
        the new cap of 2 must be enforced immediately - only 1 more acquire
        should be allowed, not 3.
        """
        # Start with limit 4, but only acquire 1 slot (leaving 3 slots slack)
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 1

        # Shrink to 2 - should immediately drain the 2 excess free slots
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2

        # Should only be able to acquire 1 more slot (2 - 1 active = 1 available)
        second_acquire = limiter.acquire_sync(blocking=False)
        assert second_acquire, "Should acquire second slot up to new limit"

        # Third acquire should fail - new cap is 2
        third_acquire = limiter.acquire_sync(blocking=False)
        assert not third_acquire, (
            "Should NOT acquire third slot - new limit is 2 and "
            "shrink should have drained excess free capacity immediately"
        )

        assert limiter.active_count == 2, (
            f"Expected 2 active, got {limiter.active_count}"
        )

        # Clean up
        limiter.release()
        limiter.release()

    def test_shrink_then_grow_does_not_over_release_ghost_slots(self, limiter):
        """Shrink-then-grow must not over-release ghost slots.

        Regression test for: shrink-then-grow could over-release slots if
        deficit tracking and slot draining were inconsistent.
        When we shrink (draining free slots + tracking deficit), then grow,
        the growth should only restore net-new capacity after absorbing deficit.
        """
        # Start with limit 5, acquire 2 slots (leaving 3 slots slack)
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2

        # Shrink to 3 - should drain 2 free slots (3 excess - 1 kept = 2 drained)
        # Deficit = 2 (5-3=2)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3

        # Can only acquire 1 more (3 limit - 2 active = 1 available)
        third_acquire = limiter.acquire_sync(blocking=False)
        assert third_acquire, "Should acquire third slot up to new limit"

        fourth_acquire = limiter.acquire_sync(blocking=False)
        assert not fourth_acquire, "Should NOT acquire fourth - limit is 3"

        assert limiter.active_count == 3

        # Grow to 4 - growth is 1, deficit is 2
        # Growth absorbs 1 from deficit (deficit now 1), no slots released
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=4))
        assert limiter.effective_limit == 4

        # Release one slot - absorbed by deficit (deficit now 0)
        limiter.release()
        assert limiter.active_count == 2

        # Now we should be able to acquire up to 4 total
        # Current: 2 active, can acquire 2 more
        acquired_count = limiter.active_count
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety break
                break

        assert acquired_count == 4, (
            f"Expected 4 slots after shrink-then-grow, got {acquired_count}. "
            "Ghost slots were likely over-released or deficit tracking failed."
        )

        # Clean up
        while limiter.active_count > 0:
            limiter.release()


@pytest.mark.asyncio
class TestReentrancyDepthResetRegression:
    """Regression tests for reentrancy depth reset leak in sync-fallback paths.

    Issue: The async branch already resets _reentrancy_depth to 0 when depth == 1,
    but the sync-fallback branches did not. This could leave depth stuck at 1 after
    a sync-fallback release, causing subsequent acquire calls to incorrectly bypass
    the limiter.
    """

    async def test_depth_reset_to_zero_after_sync_fallback_no_slot(self):
        """Direct test: _get_reentrancy_depth() == 0 after forced sync-fallback release.

        This test directly asserts the fix by:
        1. Acquire async slot (depth becomes 1)
        2. Force _async_active = 0 to simulate sync-fallback path with no active slot
        3. Call release() - the finally block MUST reset depth to 0
        4. Immediately assert _get_reentrancy_depth() == 0

        Before the fix, depth would remain at 1, causing the assertion to fail.
        """
        from code_puppy.plugins.pack_parallelism.run_limiter import (
            _get_reentrancy_depth,
        )

        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Step 1: Acquire a slot (sets depth to 1)
        await limiter.acquire_async()
        assert limiter.active_count == 1
        assert _get_reentrancy_depth() == 1, "Depth should be 1 after acquire"

        # Step 2: Force the sync-fallback path by clearing async active count
        # This simulates the edge case where release() is called from async context
        # but _async_active is 0, forcing it to try sync fallback (which also has 0)
        with limiter._state_lock:
            limiter._async_active = 0

        # Step 3: Call release() - no slot will be found, but finally block must reset depth
        limiter.release()

        # Step 4: CRITICAL ASSERTION - depth must be reset to 0
        # Before the fix, this would fail with depth == 1
        current_depth = _get_reentrancy_depth()
        assert current_depth == 0, (
            f"BUG: reentrancy depth not reset after sync-fallback release "
            f"with no active slot. Expected 0, got {current_depth}"
        )

        # Step 5: Verify the next acquire is a real acquire, not a bypass
        # If depth was stuck at 1, the next acquire would bypass (depth > 0 path)
        # and active_count would stay at 0 (since we cleared _async_active above).
        # With depth=0, it will try to acquire a real slot, fail because limit=1
        # and there's already an active slot (from step 1), and raise timeout.
        with pytest.raises(RunConcurrencyLimitError):
            await limiter.acquire_async(timeout=0.01)

        # Clean up: restore the active count and release properly
        with limiter._state_lock:
            limiter._async_active = 1
        limiter.release()
        assert limiter.active_count == 0

    async def test_next_acquire_is_real_after_depth_reset(self):
        """Behavioral test: after depth reset, next acquire is real (not bypass).

        This complements the direct depth test by verifying the behavioral consequence:
        - After the depth reset fix, the next acquire() call will be a real acquire
          (go through the semaphore) rather than a bypass (due to depth > 0).
        - A real acquire respects the concurrency limit and increments active_count.
        - A bypass would skip the semaphore and incorrectly keep active_count at 0.
        """
        from code_puppy.plugins.pack_parallelism.run_limiter import (
            _get_reentrancy_depth,
        )

        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=1))

        # Step 1: Acquire a slot (depth becomes 1)
        await limiter.acquire_async()
        assert limiter.active_count == 1
        assert _get_reentrancy_depth() == 1

        # Step 2: Force the sync-fallback path by clearing async active count
        with limiter._state_lock:
            limiter._async_active = 0

        # Step 3: Release - depth will be reset even though no slot found
        limiter.release()
        assert _get_reentrancy_depth() == 0, "Depth must be reset to 0"

        # Step 4: Verify the next acquire is a real acquire, not a bypass
        # Restore state first so we can verify real acquire behavior
        with limiter._state_lock:
            limiter._async_active = 1

        # Release the actual slot properly
        limiter.release()
        assert limiter.active_count == 0

        # Now acquire again - with depth=0, this should be a REAL acquire
        # (not a bypass). We verify this by checking active_count increments.
        await limiter.acquire_async()
        assert limiter.active_count == 1, (
            "Next acquire after depth reset should be a real acquire "
            "(active_count should increment). If depth was stuck at 1, "
            "this would bypass and active_count would stay at 0."
        )

        # Clean up
        limiter.release()
        assert limiter.active_count == 0


# ============================================================================
# Regression tests for per-side growth (no shared growth counter)
# ============================================================================


class TestPerSideGrowthRegression:
    """Regression tests for per-side independent growth calculation.

    These tests verify that the fix for the shared growth counter bug is working:
    - Growth must be computed independently per side (async vs sync)
    - Deficit on one side must NOT steal capacity from the other side
    - Each semaphore receives only its net-new capacity after absorbing its own deficit
    """

    def test_sync_only_deficit_does_not_shortchange_async_on_grow(self):
        """Sync-only deficit must NOT steal growth budget from async side.

        Regression test for: The old shared-growth model would subtract sync deficit
        from the shared growth counter, leaving less (or nothing) for async.
        With per-side growth calculation, each side starts with full growth amount.

        The KEY VERIFICATION: After grow, we can acquire up to the new limit.
        With the old bug, async would get 0 growth (stolen by sync deficit),
        limiting total capacity to 1 instead of 3.
        """
        # Start with limit 3
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Acquire all 3 slots via sync (creates sync-only deficit on shrink)
        for _ in range(3):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 3
        assert limiter._sync_active == 3
        assert limiter._async_active == 0

        # Shrink to 1 - creates sync_deficit of 2 (3-1=2), async_deficit = 0
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
        assert limiter.effective_limit == 1
        assert limiter._sync_deficit == 2
        assert limiter._async_deficit == 0

        # Grow back to 3 - total_growth = 2
        # Old (buggy) behavior: growth=2, sync_absorbs=min(2,2)=2, growth=0, async gets 0
        #   - Result: async_sem stays at 3, sync_sem goes to 0+2=2? No wait...
        #   - With old code, remaining growth (0) released to BOTH, so async gets 0
        # New (fixed) behavior:
        #   - async_growth=2, async_deficit=0, releases 2 to async_sem (3+2=5? No, max is 3)
        #   - sync_growth=2, sync_absorbs=min(2,2)=2, sync_growth=0, sync gets 0
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3
        assert limiter._sync_deficit == 0  # Fully absorbed
        assert limiter._async_deficit == 0  # No deficit to absorb

        # With per-side growth, async semaphore should have gained 2 slots
        # (but capped at 3 max since that's the limit)
        async_value_after = limiter._async_sem._value
        sync_value_after = limiter._sync_sem._value

        # Async should have full capacity (3) - it was never depleted
        assert async_value_after == 3, (
            f"Expected async_sem._value=3 (full capacity), got {async_value_after}"
        )

        # Sync should have 0 (all 3 slots in use, no free slots)
        assert sync_value_after == 0, (
            f"Expected sync_sem._value=0 (all slots in use), got {sync_value_after}"
        )

        # The key test: Release all slots and verify we can acquire up to limit 3
        for _ in range(3):
            limiter.release()
        assert limiter.active_count == 0

        # After releases and grow, we should be able to acquire exactly 3 slots
        # With the bug, we'd only be able to acquire 1 (async's growth stolen)
        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety break
                break

        assert acquired_count == 3, (
            f"Expected 3 slots after grow with sync-only deficit, got {acquired_count}. "
            "Async side was shortchanged by sync deficit absorbing shared growth."
        )

        # Clean up
        while limiter.active_count > 0:
            limiter.release()

    def test_async_only_deficit_does_not_shortchange_sync_on_grow(self):
        """Async-only deficit must NOT steal growth budget from sync side.

        Regression test for: The old shared-growth model would subtract async deficit
        from the shared growth counter, leaving less (or nothing) for sync.
        With per-side growth calculation, each side starts with full growth amount.

        We simulate async deficit by using actual async acquires then shrinking.
        """
        # Start with limit 3
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=3))

        # Use an async function to fill the limiter via async path
        async def fill_async():
            await limiter.acquire_async()

        # Run 3 async acquires concurrently to fill the limiter
        async def fill_all():
            tasks = [asyncio.create_task(fill_async()) for _ in range(3)]
            await asyncio.sleep(0.05)  # Let tasks acquire slots
            return tasks

        # Run in new event loop to avoid test isolation issues
        loop = asyncio.new_event_loop()
        try:
            tasks = loop.run_until_complete(fill_all())
            assert limiter._async_active == 3
            assert limiter._sync_active == 0

            # Shrink to 1 - creates async_deficit of 2 (3-1=2), sync_deficit = 0
            # Note: the drain will try to drain from async_sem but all 3 slots are "in use"
            # Actually with threading.Semaphore for sync drain, it drains independently
            # So sync_sem can drain 2 slots (none in use), async_sem can't drain (all in use)
            limiter.update_config(RunLimiterConfig(max_concurrent_runs=1))
            assert limiter.effective_limit == 1
            # After shrink, async has deficit 2 (couldn't drain), sync has deficit 0 (drained 2)
            assert limiter._async_deficit == 2
            assert limiter._sync_deficit == 0

            # Record sync semaphore value before grow (should have 1 slot, limit 1 - active 0)
            sync_value_before = limiter._sync_sem._value

            # Grow back to 3 - total_growth = 2
            # Old (buggy) behavior: growth=2, async_absorbs=min(2,2)=2, growth=0, sync gets 0
            # New (fixed) behavior:
            #   - sync_growth=2, sync_deficit=0, releases 2 to sync_sem
            #   - async_growth=2, async_absorbs=min(2,2)=2, async_growth=0, async gets 0
            limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
            assert limiter.effective_limit == 3
            assert limiter._async_deficit == 0  # Fully absorbed
            assert limiter._sync_deficit == 0  # No deficit to absorb

            # Sync semaphore should have gained 2 slots from growth
            sync_value_after = limiter._sync_sem._value
            expected_sync_increase = 2
            actual_sync_increase = sync_value_after - sync_value_before

            assert actual_sync_increase == expected_sync_increase, (
                f"Expected sync_sem to gain {expected_sync_increase} slots from growth, "
                f"got {actual_sync_increase}. Async-only deficit stole sync's growth budget!"
            )

            # Release all async slots
            for _ in range(3):
                limiter.release()
            assert limiter.active_count == 0

            # We should be able to acquire up to 3 slots via sync (full capacity restored)
            acquired_count = 0
            while limiter.acquire_sync(blocking=False):
                acquired_count += 1
                if acquired_count > 10:  # Safety break
                    break

            assert acquired_count == 3, (
                f"Expected 3 slots after grow with async-only deficit, got {acquired_count}. "
                "Sync side was shortchanged by async deficit absorbing shared growth."
            )

            # Clean up tasks
            for t in tasks:
                if not t.done():
                    t.cancel()
                    try:
                        loop.run_until_complete(t)
                    except asyncio.CancelledError:
                        pass

        finally:
            loop.close()

        # Final cleanup
        while limiter.active_count > 0:
            limiter.release()

    def test_both_sides_deficit_and_grow_restores_both_correctly(self):
        """Both-sides deficit must absorb growth independently, then restore both.

        Verifies that when both async and sync have deficits, each side absorbs
        its own deficit from its own growth budget, then releases net-new capacity.

        This test manually sets up deficits to verify the growth calculation is independent.
        """
        # Start with limit 4
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Manually set up both sides having deficits
        # This simulates a scenario where both sides were shrunk while fully active
        limiter._sync_deficit = 2
        limiter._async_deficit = 2

        # Verify initial state: both semaphores have full capacity (4 slots each)
        # since we haven't actually acquired anything
        assert limiter._sync_sem._value == 4
        assert limiter._async_sem._value == 4

        # Grow to 6 - total_growth = 2 for each side
        # Sync: growth=2, absorbs 2 deficit, releases 0 net-new to sync_sem (stays at 4)
        # Async: growth=2, absorbs 2 deficit, releases 0 net-new to async_sem (stays at 4)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=6))
        assert limiter.effective_limit == 6
        assert limiter._sync_deficit == 0  # Fully absorbed
        assert limiter._async_deficit == 0  # Fully absorbed

        # Both semaphores should still have 4 slots (no net-new released since
        # growth was fully absorbed by deficits on both sides)
        assert limiter._sync_sem._value == 4, (
            f"Expected sync_sem._value=4 (no net-new released), got {limiter._sync_sem._value}"
        )
        assert limiter._async_sem._value == 4, (
            f"Expected async_sem._value=4 (no net-new released), got {limiter._async_sem._value}"
        )

        # Now grow again to 8 - total_growth = 2 for each side
        # This time no deficits, so each side gets 2 net-new slots
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=8))
        assert limiter.effective_limit == 8
        assert limiter._sync_deficit == 0
        assert limiter._async_deficit == 0

        # Now both semaphores should have 6 slots each (4 + 2 net-new)
        assert limiter._sync_sem._value == 6, (
            f"Expected sync_sem._value=6 (4+2 net-new), got {limiter._sync_sem._value}"
        )
        assert limiter._async_sem._value == 6, (
            f"Expected async_sem._value=6 (4+2 net-new), got {limiter._async_sem._value}"
        )

        # Should be able to acquire 6 sync slots (limited by effective_limit=8 but
        # sync_sem only has 6 slots - this is expected with independent semaphores)
        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety break
                break

        # We should get 6 slots (the sync semaphore capacity)
        assert acquired_count == 6, (
            f"Expected 6 sync slots after growth, got {acquired_count}. "
            "Per-side growth restoration failed."
        )

        # Clean up
        while limiter.active_count > 0:
            limiter.release()

    def test_growth_independence_with_different_deficits(self):
        """Different deficits per side must not interfere with each other's growth.

        Verifies that when async has large deficit and sync has small deficit,
        each side gets its full growth budget independently.
        """
        # Start with limit 5
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))

        # Create scenario: sync uses 5 slots, async uses 0
        # After shrink 5->3, sync_deficit=2, async_deficit=0
        for _ in range(5):
            limiter.acquire_sync(blocking=False)
        assert limiter._sync_active == 5
        assert limiter._async_active == 0

        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3
        assert limiter._sync_deficit == 2
        assert limiter._async_deficit == 0

        # Now simulate async usage and deficit by manually setting state
        # This represents async having been shrunk from 5->4 while active
        limiter._async_deficit = 3  # Async had 3 deficit from separate shrink

        # Grow to 6 - total_growth = 3 for each side
        # Sync: growth=3, absorbs 2 deficit, releases 1 to sync_sem
        # Async: growth=3, absorbs 3 deficit, releases 0 to async_sem
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=6))
        assert limiter.effective_limit == 6
        assert limiter._sync_deficit == 0  # 2 - 3? No, min(3,2)=2 absorbed, remaining 0
        assert limiter._async_deficit == 0  # 3 - 3 = 0 absorbed

        # Verify sync deficit was fully absorbed (got 1 net-new, but all used)
        # Actually: sync had deficit 2, growth 3, absorbed 2, net-new 1
        # But we have 5 sync active, so the 1 net-new is already "used" by existing
        # The key point is both deficits were reduced correctly

        # Release all 5 sync slots
        for _ in range(5):
            limiter.release()
        assert limiter.active_count == 0

        # After grow to 6, we should be able to acquire 6 slots
        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety break
                break

        assert acquired_count == 6, (
            f"Expected 6 slots after grow with different deficits, got {acquired_count}. "
            "Growth budget was incorrectly shared between sides."
        )

        # Clean up
        while limiter.active_count > 0:
            limiter.release()


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
        assert child_observed_limit_reached == 1, "Deeper nesting did not bypass!"

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

    @pytest.mark.asyncio
    async def test_force_reset_cancels_waiters_no_over_credit(
        self, reset_limiter
    ):
        """REGRESSION TEST: force_reset cancels waiters (no hang) AND prevents over-crediting.

        This test verifies TWO critical properties:
        1. Pending async waiters do NOT hang forever after force_reset (they get cancelled)
        2. Post-reset concurrency is NOT over-credited (only limit tasks run concurrently)

        Before the fix, waking waiters caused them to acquire on old semaphore
        but release on new semaphore, allowing >limit concurrent tasks.

        After the fix, waiters are cancelled, preventing both hanging and over-crediting.
        """
        limiter = get_run_limiter()
        limit = limiter.effective_limit  # Should be 2 by default

        # Fill the limiter to capacity with holder tasks
        holder1_acquired = asyncio.Event()
        holder2_acquired = asyncio.Event()

        async def holder(acquired_event):
            await limiter.acquire_async()
            acquired_event.set()
            # Hold the slot until cancelled
            await asyncio.sleep(10)

        # Start holder tasks to fill the limiter
        holder1 = asyncio.create_task(holder(holder1_acquired))
        holder2 = asyncio.create_task(holder(holder2_acquired))

        # Wait for holders to acquire with bounded poll
        for _ in range(50):  # Max 1 second total
            if holder1_acquired.is_set() and holder2_acquired.is_set():
                break
            await asyncio.sleep(0.02)
        assert limiter.active_count == limit, f"Expected {limit} active tasks"

        # Start waiters that will block on the full semaphore
        # These waiters should be CANCELLED by force_reset, not woken to succeed
        waiter_results = []

        async def waiter():
            try:
                await limiter.acquire_async()
                # If we get here, we acquired (old bug behavior)
                waiter_results.append("acquired")
                await asyncio.sleep(0.01)
                limiter.release()
            except asyncio.CancelledError:
                # Expected: we were cancelled by force_reset
                waiter_results.append("cancelled")
                raise  # Re-raise to propagate cancellation

        # Start waiters
        task1 = asyncio.create_task(waiter())
        task2 = asyncio.create_task(waiter())

        # Bounded poll: wait for waiters to register with the semaphore
        for _ in range(50):  # Max 1 second total
            if limiter.waiters_count >= 2:
                break
            await asyncio.sleep(0.02)
        assert limiter.waiters_count >= 2, "Waiters should be registered"

        # Force reset while waiters are pending
        # This should CANCEL the waiters, not wake them
        result = force_reset_limiter_state()
        assert result["status"] == "reset"

        # Cancel the holder tasks
        holder1.cancel()
        holder2.cancel()

        # Wait for all tasks with timeout (proves waiters don't hang)
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    holder1, holder2, task1, task2, return_exceptions=True
                ),
                timeout=2.0,  # Should complete quickly if not stranded
            )
        except asyncio.TimeoutError:
            pytest.fail("Tasks did not complete after force_reset - possible hang!")

        # Verify waiters were cancelled (not acquired)
        assert "cancelled" in waiter_results, "Waiters should have been cancelled"
        assert "acquired" not in waiter_results, (
            "Waiters should NOT have acquired (would cause over-crediting)"
        )

        # Verify counters are clean
        assert limiter.active_count == 0
        assert limiter.waiters_count == 0

        # CRITICAL: Verify NO over-crediting - probe with >limit concurrent tasks
        # We use a simple approach: spawn many tasks and track max concurrent
        active_count_log = []
        count_lock = asyncio.Lock()

        async def probe_task():
            await limiter.acquire_async()
            try:
                async with count_lock:
                    active_count_log.append(limiter.active_count)
                # Small delay to let other tasks start
                await asyncio.sleep(0.05)
                async with count_lock:
                    active_count_log.append(limiter.active_count)
            finally:
                limiter.release()

        # Run probe_limit tasks concurrently
        probe_limit = limit + 2  # Try to run more than limit
        probe_tasks = [asyncio.create_task(probe_task()) for _ in range(probe_limit)]
        await asyncio.gather(*probe_tasks)

        # Verify: at no point did more than 'limit' tasks run concurrently
        max_concurrent_observed = max(active_count_log) if active_count_log else 0
        assert max_concurrent_observed <= limit, (
            f"Over-crediting detected! Max concurrent was {max_concurrent_observed}, "
            f"but limit is {limit}. Waiters may have released on wrong semaphore."
        )

        # Verify final state is clean
        assert limiter.active_count == 0
        assert limiter.waiters_count == 0


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


# ============================================================================
# Regression tests for per-semaphore deficit tracking
# ============================================================================


class TestSuccessiveShrinksRegression:
    """Regression tests for successive shrinks and per-semaphore deficit tracking.

    These tests verify the fix for two critical bugs identified in review:
    1. Successive shrinks overwriting drained counters and leaking half capacity
    2. Releasing on one side restoring the idle semaphore above the new cap
    """

    def test_successive_shrinks_then_grow_restores_full_capacity(self):
        """Successive shrinks followed by grow must restore full capacity.

        Regression test for: The old shared-deficit model would double-count
        drained slots when shrinking multiple times. With per-semaphore deficit
        tracking, each shrink correctly drains from each semaphore and tracks
        the undrainable remainder as that semaphore's deficit.
        """
        # Start with limit 5
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=5))

        # Acquire 2 slots (leaving 3 slack)
        limiter.acquire_sync(blocking=False)
        limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 2

        # First shrink: 5 -> 3 (excess = 2)
        # Should drain 2 free slots from sync semaphore
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=3))
        assert limiter.effective_limit == 3

        # Should only be able to acquire 1 more (3 - 2 active = 1)
        third = limiter.acquire_sync(blocking=False)
        assert third, "Should acquire third slot up to new limit"
        assert limiter.active_count == 3

        # Fourth should fail
        fourth = limiter.acquire_sync(blocking=False)
        assert not fourth, "Should NOT acquire fourth after first shrink"

        # Second shrink: 3 -> 2 (excess = 1)
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2

        # Current state: 3 active, but limit is 2
        # We can't drain any slots (all in use), so sync_deficit becomes 1
        assert limiter.active_count == 3

        # Release all 3 slots (each absorbed by deficit until it reaches 0)
        limiter.release()  # active=2, deficit absorbed
        limiter.release()  # active=1, deficit absorbed (now 0)
        limiter.release()  # active=0
        assert limiter.active_count == 0

        # Grow back to 5
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=5))
        assert limiter.effective_limit == 5

        # Should be able to acquire all 5 slots
        for i in range(5):
            acquired = limiter.acquire_sync(blocking=False)
            assert acquired, (
                f"Failed to acquire slot {i + 1} after successive shrinks/grow"
            )

        assert limiter.active_count == 5

        # Clean up
        while limiter.active_count > 0:
            limiter.release()

    def test_shrink_does_not_over_release_idle_semaphore(self):
        """Shrink must not over-release the idle semaphore.

        Regression test for: The old model with shared deficit + restore would
        sometimes release slots back to an idle semaphore, temporarily inflating
        its capacity above the new cap. With per-semaphore deficit tracking,
        each semaphore's deficit is independent and releases only affect that
        semaphore's deficit counter, not the semaphore itself.
        """
        # Start with limit 4
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Acquire 1 slot on sync side, 1 on async side (simulated via state)
        # This leaves 2 slots "in use" across both semaphores
        limiter.acquire_sync(blocking=False)  # sync active = 1
        # Manually set async active to simulate mixed usage
        limiter._async_active = 1  # async active = 1
        assert limiter.active_count == 2

        # Shrink: 4 -> 2 (excess = 2)
        # Should drain 2 free slots from each semaphore
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2

        # Verify per-semaphore state:
        # - Sync: started with 4, drained 2 free slots, deficit = 0 (1 active < 2 new limit)
        # - Async: started with 4, drained 2 free slots, deficit = 0 (1 active < 2 new limit)
        assert limiter._sync_deficit == 0, (
            "Sync semaphore should have no deficit (1 active < 2 limit)"
        )
        assert limiter._async_deficit == 0, (
            "Async semaphore should have no deficit (1 active < 2 limit)"
        )

        # Release sync slot - should go directly to semaphore (no deficit)
        limiter.release()  # sync active goes 1 -> 0
        # Verify we can re-acquire it
        reacquired = limiter.acquire_sync(blocking=False)
        assert reacquired, "Should re-acquire sync slot immediately (no deficit)"

        # Clean up
        limiter.release()
        limiter._async_active = 0  # Clear the simulated async active

    def test_successive_shrinks_accumulate_deficit_correctly(self):
        """Successive shrinks must accumulate deficit correctly per semaphore.

        Regression test for: The old model's shared deficit would be overwritten
        on successive shrinks, losing track of the total capacity reduction needed.
        """
        # Start with limit 6
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=6))

        # Acquire all 6 slots
        for _ in range(6):
            limiter.acquire_sync(blocking=False)
        assert limiter.active_count == 6

        # First shrink: 6 -> 4 (excess = 2)
        # Can't drain any (all in use), so sync_deficit = 2
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=4))
        assert limiter.effective_limit == 4
        assert limiter._sync_deficit == 2

        # Second shrink: 4 -> 2 (excess = 2)
        # Still can't drain, so sync_deficit = 2 + 2 = 4
        limiter.update_config(RunLimiterConfig(max_concurrent_runs=2))
        assert limiter.effective_limit == 2
        assert limiter._sync_deficit == 4, (
            f"Expected sync_deficit=4 after successive shrinks (2+2), got {limiter._sync_deficit}"
        )

        # Release all 6 slots
        for _ in range(6):
            limiter.release()
        assert limiter.active_count == 0

        # After all releases, deficit should be 0 (4 absorbed by releases, 2 actually released)
        # Actually: we released 6, but deficit was 4, so 4 absorbed, 2 released to semaphore
        # New limit is 2, so we should be able to acquire exactly 2 slots
        assert limiter._sync_deficit == 0, (
            f"Deficit should be 0 after all releases, got {limiter._sync_deficit}"
        )

        acquired_count = 0
        while limiter.acquire_sync(blocking=False):
            acquired_count += 1
            if acquired_count > 10:  # Safety break
                break

        assert acquired_count == 2, (
            f"Expected 2 slots (new limit), got {acquired_count}. "
            "Deficit tracking failed across successive shrinks."
        )

        # Clean up
        while limiter.active_count > 0:
            limiter.release()
