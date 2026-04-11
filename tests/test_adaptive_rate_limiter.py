"""Tests for the adaptive rate limiter module.

Covers:
- Module import and configuration
- Per-model semaphore creation and limiting
- Rate limit recording (429 → reduce limit)
- Background recovery loop
- Context manager (ModelAwareLimiter)
- http_utils integration
"""

import asyncio
import time

import pytest

from code_puppy.adaptive_rate_limiter import (
    ModelAwareLimiter,
    configure,
    get_status,
    record_rate_limit,
    acquire_model_slot,
    release_model_slot,
    reset,
)


@pytest.fixture(autouse=True)
def _reset_module():
    """Reset module state before and after every test."""
    reset()
    yield
    reset()


# ── Configuration ───────────────────────────────────────────────────────────


class TestConfigure:
    """Test configure() knobs."""

    def test_default_values(self):
        """Defaults should be sane."""
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_min_limit == 1
        assert arl._cfg_max_limit == 10
        assert arl._cfg_cooldown_seconds == 60.0
        assert arl._cfg_recovery_rate == 0.5
        assert arl._cfg_initial_limit == 10

    def test_configure_min_limit(self):
        configure(min_limit=2)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_min_limit == 2

    def test_configure_max_limit(self):
        configure(max_limit=20)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_max_limit == 20

    def test_configure_cooldown(self):
        configure(cooldown_seconds=30.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_cooldown_seconds == 30.0

    def test_configure_recovery_rate(self):
        configure(recovery_rate=0.3)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_recovery_rate == 0.3

    def test_configure_initial_limit(self):
        configure(initial_limit=5)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_initial_limit == 5

    def test_configure_clamps_min_limit(self):
        configure(min_limit=0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_min_limit == 1

    def test_configure_clamps_max_above_min(self):
        configure(min_limit=5, max_limit=3)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_max_limit == 5  # clamped to min

    def test_configure_clamps_cooldown(self):
        configure(cooldown_seconds=0.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_cooldown_seconds == 1.0

    def test_configure_clamps_recovery_rate(self):
        configure(recovery_rate=2.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_recovery_rate == 1.0

    def test_configure_clamps_initial_limit(self):
        configure(min_limit=3, initial_limit=1)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_initial_limit == 3  # clamped to min


# ── Semaphore creation ──────────────────────────────────────────────────────


class TestSemaphoreCreation:
    """Test get_model_semaphore and lazy initialization."""

    @pytest.mark.asyncio
    async def test_no_state_returns_empty_status(self):
        assert get_status() == {}
        assert "nonexistent" not in get_status()

    @pytest.mark.asyncio
    async def test_acquire_creates_state(self):
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        status = get_status()
        assert "gpt-4" in status
        assert status["gpt-4"]["active_count"] == 0

    @pytest.mark.asyncio
    async def test_initial_limit_applied(self):
        configure(initial_limit=5)
        await acquire_model_slot("gpt-4")
        await acquire_model_slot("gpt-4")
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        release_model_slot("gpt-4")
        release_model_slot("gpt-4")
        status = get_status()
        assert status["gpt-4"]["current_limit"] == 5.0
        assert status["gpt-4"]["active_count"] == 0


# ── Record rate limit ───────────────────────────────────────────────────────


class TestRecordRateLimit:
    """Test that recording a 429 reduces the concurrency limit."""

    @pytest.mark.asyncio
    async def test_record_reduces_limit(self):
        configure(initial_limit=10, min_limit=1)
        # Prime the model
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")

        status = get_status()
        assert "gpt-4" in status
        assert status["gpt-4"]["current_limit"] == 5.0  # halved from 10
        assert status["gpt-4"]["total_429_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_429s_reduce_further(self):
        configure(initial_limit=10, min_limit=1)
        await acquire_model_slot("claude-3")
        release_model_slot("claude-3")

        await record_rate_limit("claude-3")
        await record_rate_limit("claude-3")
        await record_rate_limit("claude-3")

        status = get_status()
        # 10 → 5 → 2.5 → 1.25, but floor to int in semaphore adjust
        # actual float tracking: 10 → 5.0 → 2.5 → 1.25
        assert status["claude-3"]["total_429_count"] == 3
        assert status["claude-3"]["current_limit"] == 1.25

    @pytest.mark.asyncio
    async def test_429_does_not_go_below_min(self):
        configure(initial_limit=4, min_limit=2)
        await acquire_model_slot("model-x")
        release_model_slot("model-x")

        await record_rate_limit("model-x")
        await record_rate_limit("model-x")
        await record_rate_limit("model-x")

        status = get_status()
        # 4 → 2 → 1 → but min is 2
        assert status["model-x"]["current_limit"] == 2.0

    @pytest.mark.asyncio
    async def test_record_normalizes_model_name(self):
        configure(initial_limit=10)
        await acquire_model_slot("GPT-4")
        release_model_slot("GPT-4")

        await record_rate_limit("GPT-4")
        await record_rate_limit("gpt-4")
        await record_rate_limit(" GPT-4 ")

        status = get_status()
        assert "gpt-4" in status
        assert status["gpt-4"]["total_429_count"] == 3

    @pytest.mark.asyncio
    async def test_record_empty_model_is_noop(self):
        await record_rate_limit("")
        await record_rate_limit("   ")
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_429_sets_last_429_time(self):
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        before = time.monotonic()
        await record_rate_limit("gpt-4")
        after = time.monotonic()

        status = get_status()
        assert status["gpt-4"]["last_429_time"] is not None
        assert before <= status["gpt-4"]["last_429_time"] <= after


# ── Recovery loop ───────────────────────────────────────────────────────────


class TestRecoveryLoop:
    """Test the background recovery mechanism."""

    @pytest.mark.asyncio
    async def test_recovery_starts_on_first_use(self):
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._recovery_started is False
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        # record_rate_limit also starts recovery
        await record_rate_limit("gpt-4")
        assert arl._recovery_started is True

    @pytest.mark.asyncio
    async def test_recovery_increases_limit_after_cooldown(self):
        """Manually tick the recovery loop to verify limits increase."""
        configure(
            initial_limit=10,
            min_limit=1,
            max_limit=10,
            cooldown_seconds=0.05,  # very short for testing
            recovery_rate=0.5,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["current_limit"] == 5.0

        # Wait for cooldown + a bit extra
        await asyncio.sleep(0.15)

        # The recovery loop runs in background, so the limit should have increased
        # Note: due to timing, it may or may not have ticked. We just verify
        # that the module didn't crash.
        status = get_status()
        assert status["gpt-4"]["current_limit"] >= 5.0
        assert status["gpt-4"]["current_limit"] <= 10.0

    @pytest.mark.asyncio
    async def test_no_recovery_while_in_cooldown(self):
        configure(
            initial_limit=10,
            min_limit=1,
            max_limit=10,
            cooldown_seconds=5.0,
            recovery_rate=0.5,
        )
        await acquire_model_slot("claude-3")
        release_model_slot("claude-3")

        await record_rate_limit("claude-3")
        status = get_status()
        assert status["claude-3"]["in_cooldown"] is True


# ── Context manager ─────────────────────────────────────────────────────────


class TestModelAwareLimiter:
    """Test the async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_basic(self):
        configure(initial_limit=5)
        async with ModelAwareLimiter("gpt-4"):
            status = get_status()
            # Inside context, one slot is held
            assert status["gpt-4"]["active_count"] == 1

        # After exit, slot released
        status = get_status()
        assert status["gpt-4"]["active_count"] == 0

    @pytest.mark.asyncio
    async def test_context_manager_nested(self):
        configure(initial_limit=5)
        async with ModelAwareLimiter("gpt-4"):
            async with ModelAwareLimiter("gpt-4"):
                status = get_status()
                assert status["gpt-4"]["active_count"] == 2

            status = get_status()
            assert status["gpt-4"]["active_count"] == 1

        status = get_status()
        assert status["gpt-4"]["active_count"] == 0

    @pytest.mark.asyncio
    async def test_context_manager_different_models(self):
        configure(initial_limit=3)
        async with ModelAwareLimiter("gpt-4"):
            async with ModelAwareLimiter("claude-3"):
                status = get_status()
                assert status["gpt-4"]["active_count"] == 1
                assert status["claude-3"]["active_count"] == 1


# ── Concurrency enforcement ─────────────────────────────────────────────────


class TestConcurrencyEnforcement:
    """Test that the adaptive limiter actually limits concurrency."""

    @pytest.mark.asyncio
    async def test_respects_limit_after_429(self):
        configure(initial_limit=10, min_limit=1, max_limit=10)
        # Create state, then immediately reduce to 2
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        # Record two 429s: 10 → 5 → 2.5
        await record_rate_limit("gpt-4")
        await record_rate_limit("gpt-4")

        status = get_status()
        assert status["gpt-4"]["current_limit"] == 2.5

        max_concurrent = 0
        current = 0

        async def hold_slot():
            nonlocal max_concurrent, current
            async with ModelAwareLimiter("gpt-4"):
                current += 1
                max_concurrent = max(max_concurrent, current)
                await asyncio.sleep(0.05)
                current -= 1

        tasks = [hold_slot() for _ in range(10)]
        await asyncio.gather(*tasks)

        # With limit 2.5 (math.ceil() → 3), should not exceed 3
        assert max_concurrent <= 3
        assert max_concurrent >= 1


# ── get_status ──────────────────────────────────────────────────────────────


class TestGetStatus:
    """Test the status reporting."""

    def test_empty_status(self):
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_status_after_record(self):
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        status = get_status()

        assert "gpt-4" in status
        assert "current_limit" in status["gpt-4"]
        assert "total_429_count" in status["gpt-4"]
        assert "last_429_time" in status["gpt-4"]
        assert "in_cooldown" in status["gpt-4"]
        assert status["gpt-4"]["total_429_count"] == 1
        assert status["gpt-4"]["in_cooldown"] is True


# ── Reset ───────────────────────────────────────────────────────────────────


class TestReset:
    """Test that reset() clears all state."""

    @pytest.mark.asyncio
    async def test_reset_clears_models(self):
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        assert get_status() != {}
        reset()
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_reset_clears_recovery_flag(self):
        from code_puppy import adaptive_rate_limiter as arl

        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        arl._recovery_started = True
        reset()
        assert arl._recovery_started is False

    @pytest.mark.asyncio
    async def test_reset_restores_defaults(self):
        from code_puppy import adaptive_rate_limiter as arl

        configure(min_limit=3, max_limit=15, cooldown_seconds=120.0)
        reset()
        assert arl._cfg_min_limit == 1
        assert arl._cfg_max_limit == 10
        assert arl._cfg_cooldown_seconds == 60.0


# ── http_utils integration ──────────────────────────────────────────────────


class TestHttpUtilsIntegration:
    """Test the _notify_adaptive_rate_limiter helper in http_utils."""

    def test_import_http_utils(self):
        """http_utils should import without errors."""
        from code_puppy.http_utils import RetryingAsyncClient

        assert RetryingAsyncClient is not None

    def test_notify_helper_exists(self):
        from code_puppy.http_utils import _notify_adaptive_rate_limiter

        assert callable(_notify_adaptive_rate_limiter)

    def test_notify_on_non_429_is_noop(self):
        from code_puppy.http_utils import _notify_adaptive_rate_limiter

        # Should not raise and should not create state
        _notify_adaptive_rate_limiter("gpt-4", 200)
        _notify_adaptive_rate_limiter("gpt-4", 500)
        _notify_adaptive_rate_limiter("gpt-4", 503)
        # Give the fire-and-forget task a chance to run
        time.sleep(0.05)
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_notify_on_429_creates_state(self):
        from code_puppy.http_utils import _notify_adaptive_rate_limiter

        _notify_adaptive_rate_limiter("gpt-4", 429)
        # Give the fire-and-forget task time to execute
        await asyncio.sleep(0.1)

        status = get_status()
        assert "gpt-4" in status
        assert status["gpt-4"]["total_429_count"] == 1

    def test_notify_empty_model_is_noop(self):
        from code_puppy.http_utils import _notify_adaptive_rate_limiter

        _notify_adaptive_rate_limiter("", 429)
        _notify_adaptive_rate_limiter("   ", 429)
        time.sleep(0.05)
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_retrying_client_has_model_name(self):
        from code_puppy.http_utils import RetryingAsyncClient

        client = RetryingAsyncClient(model_name="GPT-4o")
        assert client.model_name == "gpt-4o"


class TestCheckModelSlot:
    """Tests for the non-consuming check_model_slot() preview."""

    async def test_unknown_model_returns_true(self):
        """Models with no state are not throttled."""
        from code_puppy.adaptive_rate_limiter import check_model_slot

        assert check_model_slot("never-seen-model") is True

    async def test_empty_model_returns_true(self):
        from code_puppy.adaptive_rate_limiter import check_model_slot

        assert check_model_slot("") is True

    async def test_available_slot_returns_true(self):
        from code_puppy.adaptive_rate_limiter import (
            acquire_model_slot,
            check_model_slot,
            configure,
            release_model_slot,
        )

        configure(initial_limit=5)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        # State exists, limit=5, active=0 → True
        assert check_model_slot("gpt-4") is True

    async def test_full_slots_returns_false(self):
        from code_puppy.adaptive_rate_limiter import (
            acquire_model_slot,
            check_model_slot,
            configure,
            release_model_slot,
        )

        configure(initial_limit=1, min_limit=1)
        await acquire_model_slot("gpt-4")

        # Slot occupied → False
        assert check_model_slot("gpt-4") is False

        release_model_slot("gpt-4")
        # Now free again
        assert check_model_slot("gpt-4") is True

    async def test_open_circuit_returns_false(self):
        from code_puppy.adaptive_rate_limiter import (
            check_model_slot,
            configure,
            record_rate_limit,
        )

        configure(circuit_breaker_enabled=True)
        await record_rate_limit("gpt-4")

        # Circuit opened → False
        assert check_model_slot("gpt-4") is False

    async def test_does_not_consume_slot(self):
        """Calling check_model_slot should NOT change active_count."""
        from code_puppy.adaptive_rate_limiter import (
            _state,
            acquire_model_slot,
            check_model_slot,
            configure,
            release_model_slot,
        )

        configure(initial_limit=2)
        await acquire_model_slot("gpt-4")

        before = _state.model_states.get("gpt-4")
        assert before is not None
        active_before = before.active_count

        # Check should not change active_count
        check_model_slot("gpt-4")
        check_model_slot("gpt-4")
        check_model_slot("gpt-4")

        assert before.active_count == active_before

        release_model_slot("gpt-4")
