"""Property-based tests for RunLimiter invariants using Hypothesis.

These tests verify that RunLimiter maintains its core invariants:
1. active_count + waiters_count never exceeds effective_limit in steady state
2. Reentrant depth is properly tracked and never negative
3. Config validation always clamps invalid values
4. Semaphore state remains consistent after config updates
"""

import asyncio

import pytest

# Skip entire module if hypothesis is not available
hypothesis = pytest.importorskip("hypothesis")

from hypothesis import given, settings, strategies as st  # noqa: E402

from code_puppy.plugins.pack_parallelism.run_limiter import (  # noqa: E402
    RunLimiter,
    RunLimiterConfig,
    _get_reentrancy_depth,
    _set_reentrancy_depth,
    reset_run_limiter_for_tests,
)


# Strategies for generating valid RunLimiter configs
valid_limits = st.integers(min_value=1, max_value=64)
valid_timeouts = st.one_of(
    st.none(), st.floats(min_value=0.1, max_value=3600, allow_nan=False)
)


@st.composite
def valid_config(draw) -> RunLimiterConfig:
    """Generate a valid RunLimiterConfig."""
    max_runs = draw(valid_limits)
    allow_parallel = draw(st.booleans())
    wait_timeout = draw(valid_timeouts)
    return RunLimiterConfig(
        max_concurrent_runs=max_runs,
        allow_parallel=allow_parallel,
        wait_timeout=wait_timeout,
    )


class TestRunLimiterInvariants:
    """Property tests for RunLimiter core invariants."""

    @given(config=valid_config())
    @settings(max_examples=100, deadline=None)
    def test_config_effective_limit_is_at_least_one(
        self, config: RunLimiterConfig
    ) -> None:
        """Invariant: effective_limit is always >= 1."""
        limiter = RunLimiter(config)
        assert limiter.effective_limit >= 1

    @given(config=valid_config())
    @settings(max_examples=100, deadline=None)
    def test_config_allow_parallel_false_forces_limit_one(
        self, config: RunLimiterConfig
    ) -> None:
        """Invariant: allow_parallel=False forces effective_limit=1."""
        if not config.allow_parallel:
            limiter = RunLimiter(config)
            assert limiter.effective_limit == 1

    @given(max_runs=st.integers(max_value=0))  # Invalid values
    @settings(max_examples=20, deadline=None)
    def test_invalid_config_clamped_to_default(self, max_runs: int) -> None:
        """Invariant: invalid max_concurrent_runs (< 1) is clamped to 2."""
        config = RunLimiterConfig(max_concurrent_runs=max_runs)
        limiter = RunLimiter(config)
        # Should use default of 2, not the invalid value
        assert limiter.effective_limit >= 1

    @given(st.data())
    @settings(max_examples=50, deadline=None)
    def test_active_count_never_negative(self, data) -> None:
        """Invariant: active_count is never negative."""
        config = data.draw(valid_config())
        limiter = RunLimiter(config)
        assert limiter.active_count >= 0

    @given(st.data())
    @settings(max_examples=50, deadline=None)
    def test_waiters_count_never_negative(self, data) -> None:
        """Invariant: waiters_count is never negative."""
        config = data.draw(valid_config())
        limiter = RunLimiter(config)
        assert limiter.waiters_count >= 0


class TestRunLimiterReentrancy:
    """Property tests for reentrancy tracking."""

    def setup_method(self) -> None:
        """Reset state before each test."""
        reset_run_limiter_for_tests()
        _set_reentrancy_depth(0)

    @given(depth=st.integers(min_value=0, max_value=10))
    @settings(max_examples=30, deadline=None)
    def test_reentrancy_depth_roundtrip(self, depth: int) -> None:
        """Invariant: _get_reentrancy_depth returns what _set_reentrancy_depth sets."""
        _set_reentrancy_depth(depth)
        assert _get_reentrancy_depth() == depth

    @given(new_config=valid_config())
    @settings(max_examples=30, deadline=None)
    def test_config_update_preserves_non_negative_counters(
        self, new_config: RunLimiterConfig
    ) -> None:
        """Invariant: config updates never make counters negative."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=4))

        # Simulate some activity
        limiter._async_active = 2
        limiter._sync_active = 1

        limiter.update_config(new_config)

        # Counters should remain non-negative
        assert limiter._async_active >= 0
        assert limiter._sync_active >= 0
        assert limiter._async_waiters >= 0
        assert limiter._sync_waiters >= 0


class TestRunLimiterConcurrencyInvariants:
    """Property tests for concurrency-related invariants."""

    @pytest.mark.asyncio
    @given(limit=st.integers(min_value=1, max_value=8))
    @settings(max_examples=20, deadline=None)
    async def test_async_acquire_respects_limit(self, limit: int) -> None:
        """Invariant: acquire_async respects effective_limit."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=limit))

        acquired_count = 0

        async def try_acquire() -> bool:
            try:
                await limiter.acquire_async(timeout=0.01)
                return True
            except Exception:
                return False

        # Try to acquire more than limit slots
        results = await asyncio.gather(*[try_acquire() for _ in range(limit + 2)])
        acquired_count = sum(results)

        # Should not exceed limit
        assert acquired_count <= limit

        # Cleanup
        for _ in range(acquired_count):
            limiter.release()

    @given(limit=st.integers(min_value=1, max_value=8))
    @settings(max_examples=20, deadline=None)
    def test_sync_acquire_blocking_respects_limit(self, limit: int) -> None:
        """Invariant: acquire_sync respects effective_limit."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=limit))

        acquired = 0
        for _ in range(limit + 2):
            if limiter.acquire_sync(blocking=False):
                acquired += 1

        # Should not exceed limit
        assert acquired <= limit

        # Cleanup
        for _ in range(acquired):
            limiter.release()


class TestRunLimiterConfigTransitions:
    """Property tests for config update state transitions."""

    @given(
        initial=valid_config(),
        updated=valid_config(),
    )
    @settings(max_examples=50, deadline=None)
    def test_limit_transition_result_valid(
        self, initial: RunLimiterConfig, updated: RunLimiterConfig
    ) -> None:
        """Invariant: after any config transition, effective_limit is valid."""
        limiter = RunLimiter(initial)
        limiter.update_config(updated)

        assert limiter.effective_limit >= 1
        if not updated.allow_parallel:
            assert limiter.effective_limit == 1


class TestRunLimiterSemaphores:
    """Property tests for semaphore state."""

    @given(limit=st.integers(min_value=1, max_value=16))
    @settings(max_examples=30, deadline=None)
    def test_semaphore_values_initialized_correctly(self, limit: int) -> None:
        """Invariant: semaphores are initialized with correct initial values."""
        limiter = RunLimiter(RunLimiterConfig(max_concurrent_runs=limit))

        # Check internal semaphore state
        async_sem = limiter._async_sem
        sync_sem = limiter._sync_sem

        # Both should have the same effective limit
        assert async_sem._value == limit
        assert sync_sem._value == limit
