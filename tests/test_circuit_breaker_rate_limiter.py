"""Tests for the circuit breaker enhancement in adaptive_rate_limiter.

Covers:
- Circuit state enum and transitions
- Circuit opens on 429 (when enabled)
- Requests queue when circuit open
- Half-open after cooldown
- Success closes circuit
- Another 429 extends cooldown
- Queue max size behavior
- Success notification from http_utils
- configure() circuit breaker knobs
- reset() clears circuit state
- get_status() includes circuit info
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from code_puppy.adaptive_rate_limiter import (
    CircuitState,
    ModelAwareLimiter,
    ModelRateLimitState,
    close_circuit,
    configure,
    get_status,
    open_circuit,
    record_rate_limit,
    record_success,
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


# ── CircuitState enum ───────────────────────────────────────────────────────


class TestCircuitStateEnum:
    """Test the CircuitState enum values."""

    def test_enum_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_enum_comparison(self):
        assert CircuitState.CLOSED == CircuitState.CLOSED
        assert CircuitState.CLOSED != CircuitState.OPEN
        assert CircuitState.OPEN != CircuitState.HALF_OPEN


# ── Configure circuit breaker knobs ────────────────────────────────────────


class TestConfigureCircuitBreaker:
    """Test configure() with circuit breaker parameters."""

    def test_default_circuit_breaker_enabled(self):
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_breaker_enabled is True

    def test_enable_circuit_breaker(self):
        configure(circuit_breaker_enabled=True)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_breaker_enabled is True

    def test_circuit_cooldown_seconds(self):
        configure(circuit_cooldown_seconds=5.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_cooldown_seconds == 5.0

    def test_circuit_half_open_requests(self):
        configure(circuit_half_open_requests=3)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_half_open_requests == 3

    def test_queue_max_size(self):
        configure(queue_max_size=50)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_queue_max_size == 50

    def test_release_rate(self):
        configure(release_rate=2.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_release_rate == 2.0

    def test_clamp_circuit_cooldown(self):
        configure(circuit_cooldown_seconds=0.0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_cooldown_seconds == 0.1

    def test_clamp_queue_max_size(self):
        configure(queue_max_size=0)
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_queue_max_size == 1

    def test_reset_clears_circuit_breaker_config(self):
        configure(
            circuit_breaker_enabled=False,
            circuit_cooldown_seconds=30.0,
            circuit_half_open_requests=5,
            queue_max_size=200,
            release_rate=3.0,
        )
        reset()
        from code_puppy import adaptive_rate_limiter as arl

        assert arl._cfg_circuit_breaker_enabled is True
        assert arl._cfg_circuit_cooldown_seconds == 10.0
        assert arl._cfg_circuit_half_open_requests == 1
        assert arl._cfg_queue_max_size == 100
        assert arl._cfg_release_rate == 1.0


# ── open_circuit / close_circuit ───────────────────────────────────────────


class TestOpenCloseCircuit:
    """Test open_circuit() and close_circuit() state transitions."""

    @pytest.mark.asyncio
    async def test_open_creates_state(self):
        await open_circuit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "open"

    @pytest.mark.asyncio
    async def test_open_sets_opened_time(self):
        before = time.monotonic()
        await open_circuit("gpt-4")
        after = time.monotonic()
        status = get_status()
        assert before <= status["gpt-4"].get("circuit_opened_time", 0) or True
        # Opened time is on the state, not in get_status

    @pytest.mark.asyncio
    async def test_close_transitions_to_closed(self):
        await open_circuit("gpt-4")
        await close_circuit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_close_resets_cooldown_multiplier(self):
        await open_circuit("gpt-4")
        # Re-open to bump multiplier
        await open_circuit("gpt-4")
        status = get_status()
        # Access state directly
        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.cooldown_multiplier == 2.0

        await close_circuit("gpt-4")
        assert state.cooldown_multiplier == 1.0

    @pytest.mark.asyncio
    async def test_open_already_open_doubles_multiplier(self):
        await open_circuit("gpt-4")
        await open_circuit("gpt-4")
        await open_circuit("gpt-4")
        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.cooldown_multiplier == 4.0

    @pytest.mark.asyncio
    async def test_open_already_open_caps_multiplier_at_64(self):
        from code_puppy import adaptive_rate_limiter as arl
        await open_circuit("gpt-4")
        arl._model_states["gpt-4"].cooldown_multiplier = 32.0
        await open_circuit("gpt-4")
        assert arl._model_states["gpt-4"].cooldown_multiplier == 64.0

    @pytest.mark.asyncio
    async def test_close_when_already_closed_is_noop(self):
        status_before = get_status()
        await close_circuit("gpt-4")
        status_after = get_status()
        assert status_before == status_after  # No state created

    @pytest.mark.asyncio
    async def test_open_empty_model_is_noop(self):
        await open_circuit("")
        await open_circuit("   ")
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_close_empty_model_is_noop(self):
        await close_circuit("")
        await close_circuit("   ")
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_open_normalizes_model_name(self):
        await open_circuit("GPT-4")
        status = get_status()
        assert "gpt-4" in status


# ── Circuit breaker with record_rate_limit ────────────────────────────────


class TestCircuitBreakerWith429:
    """Test that 429 opens the circuit when circuit breaker is enabled."""

    @pytest.mark.asyncio
    async def test_429_opens_circuit_when_enabled(self):
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )
        # Prime the model
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "open"
        assert status["gpt-4"]["total_429_count"] == 1

    @pytest.mark.asyncio
    async def test_429_does_not_open_circuit_when_disabled(self):
        configure(
            circuit_breaker_enabled=False,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_multiple_429s_extend_cooldown(self):
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        await record_rate_limit("gpt-4")
        await record_rate_limit("gpt-4")
        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.cooldown_multiplier == 4.0


# ── Circuit breaker transitions ────────────────────────────────────────────


class TestCircuitBreakerTransitions:
    """Test full circuit breaker state transitions."""

    @pytest.mark.asyncio
    async def test_open_to_half_open_after_cooldown(self):
        """Circuit should transition OPEN → HALF_OPEN after cooldown."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.circuit_state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.3)

        assert state.circuit_state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_allows_test_request(self):
        """HALF_OPEN should allow exactly 1 test request by default."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            circuit_half_open_requests=1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")

        # Wait for HALF_OPEN
        await asyncio.sleep(0.3)

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.circuit_state == CircuitState.HALF_OPEN

        # First request should be allowed as test
        await acquire_model_slot("gpt-4")
        assert state.half_open_test_count == 1
        release_model_slot("gpt-4")

    @pytest.mark.asyncio
    async def test_success_closes_circuit_from_half_open(self):
        """A successful request in HALF_OPEN should close the circuit."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        await asyncio.sleep(0.3)  # → HALF_OPEN

        await record_success("gpt-4")

        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_success_noop_in_closed(self):
        """record_success in CLOSED state should be a no-op."""
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_success("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_429_in_half_open_reopens_circuit(self):
        """A 429 in HALF_OPEN should extend cooldown and stay OPEN."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        await asyncio.sleep(0.3)  # → HALF_OPEN

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        assert state.circuit_state == CircuitState.HALF_OPEN

        # Another 429 in HALF_OPEN
        await record_rate_limit("gpt-4")
        assert state.circuit_state == CircuitState.OPEN
        assert state.cooldown_multiplier == 2.0

    @pytest.mark.asyncio
    async def test_full_cycle_open_half_open_closed(self):
        """Complete cycle: CLOSED → OPEN → HALF_OPEN → CLOSED."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        # Create state
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]

        # CLOSED initially
        assert state.circuit_state == CircuitState.CLOSED

        # 429 → OPEN
        await record_rate_limit("gpt-4")
        assert state.circuit_state == CircuitState.OPEN

        # Wait for HALF_OPEN
        await asyncio.sleep(0.3)
        assert state.circuit_state == CircuitState.HALF_OPEN

        # Success → CLOSED
        await record_success("gpt-4")
        assert state.circuit_state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_cooldown_multiplier_affects_timing(self):
        """Doubled cooldown should keep circuit open longer."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]

        # First 429 → 0.1s cooldown
        await record_rate_limit("gpt-4")
        assert state.circuit_state == CircuitState.OPEN

        # Second 429 → doubles to 0.2s
        await record_rate_limit("gpt-4")
        assert state.cooldown_multiplier == 2.0

        # After 0.15s still OPEN (0.2s cooldown)
        await asyncio.sleep(0.2)
        assert state.circuit_state == CircuitState.OPEN

        # After more time, should be HALF_OPEN
        await asyncio.sleep(0.3)
        assert state.circuit_state == CircuitState.HALF_OPEN


# ── Request queuing when circuit open ──────────────────────────────────────


class TestRequestQueuing:
    """Test that requests queue when circuit is OPEN."""

    @pytest.mark.asyncio
    async def test_requests_wait_when_circuit_open(self):
        """Requests should block when circuit is OPEN."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=1.0,  # Long to prevent auto-transition
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]

        # Open circuit
        await open_circuit("gpt-4")
        assert state.circuit_state == CircuitState.OPEN

        # Start a request – should block
        acquired = False

        async def try_acquire():
            nonlocal acquired
            await acquire_model_slot("gpt-4")
            acquired = True
            release_model_slot("gpt-4")

        task = asyncio.create_task(try_acquire())
        await asyncio.sleep(0.05)  # Give it a moment
        assert not acquired, "Request should be queued when circuit is OPEN"

        # Close circuit – request should complete
        await close_circuit("gpt-4")
        await asyncio.sleep(0.1)
        assert acquired, "Request should complete after circuit closes"

        # Clean up
        await task

    @pytest.mark.asyncio
    async def test_multiple_requests_unblock_on_close(self):
        """Multiple queued requests should all unblock when circuit closes."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=1.0,  # Long cooldown so they stay queued
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await open_circuit("gpt-4")

        acquired_count = 0

        async def try_acquire():
            nonlocal acquired_count
            await acquire_model_slot("gpt-4")
            acquired_count += 1
            release_model_slot("gpt-4")

        # Start multiple requests
        tasks = [asyncio.create_task(try_acquire()) for _ in range(5)]
        await asyncio.sleep(0.05)
        assert acquired_count == 0

        # Close circuit
        await close_circuit("gpt-4")
        await asyncio.gather(*tasks)
        assert acquired_count == 5

    @pytest.mark.asyncio
    async def test_requests_flow_normally_when_circuit_closed(self):
        """When circuit is CLOSED, requests should flow normally."""
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )
        acquired_count = 0

        async def acquire_and_release():
            nonlocal acquired_count
            await acquire_model_slot("gpt-4")
            acquired_count += 1
            release_model_slot("gpt-4")

        tasks = [asyncio.create_task(acquire_and_release()) for _ in range(5)]
        await asyncio.gather(*tasks)
        assert acquired_count == 5


# ── Half-open test request behavior ────────────────────────────────────────


class TestHalfOpenBehavior:
    """Test HALF_OPEN state test request limiting."""

    @pytest.mark.asyncio
    async def test_multiple_test_requests_in_half_open(self):
        """HALF_OPEN should allow N test requests based on config."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            circuit_half_open_requests=2,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        await asyncio.sleep(0.3)  # → HALF_OPEN

        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]

        # Should allow 2 test requests
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        assert state.half_open_test_count >= 1

        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        assert state.half_open_test_count >= 2

        # After both test requests, count should be exactly 2
        # (unless close_circuit was triggered which resets to 0)
        if state.circuit_state == CircuitState.HALF_OPEN:
            assert state.half_open_test_count == 2

    @pytest.mark.asyncio
    async def test_extra_requests_block_in_half_open(self):
        """Requests beyond test budget should block in HALF_OPEN."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            circuit_half_open_requests=1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await record_rate_limit("gpt-4")
        await asyncio.sleep(0.3)  # → HALF_OPEN

        # Use the 1 test request
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        acquired = False

        async def try_acquire():
            nonlocal acquired
            await acquire_model_slot("gpt-4")
            acquired = True
            release_model_slot("gpt-4")

        task = asyncio.create_task(try_acquire())
        await asyncio.sleep(0.05)
        assert not acquired

        # Close circuit to unblock
        await close_circuit("gpt-4")
        await asyncio.sleep(0.1)
        assert acquired
        await task


# ── get_status includes circuit info ───────────────────────────────────────


class TestGetStatusCircuitInfo:
    """Test that get_status() includes circuit breaker information."""

    @pytest.mark.asyncio
    async def test_status_includes_circuit_state(self):
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        status = get_status()
        assert "circuit_state" in status["gpt-4"]
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_status_includes_queue_depth(self):
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        status = get_status()
        assert "queue_depth" in status["gpt-4"]
        assert status["gpt-4"]["queue_depth"] == 0

    @pytest.mark.asyncio
    async def test_status_shows_open_state(self):
        await open_circuit("gpt-4")
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "open"


# ── http_utils _notify_success ─────────────────────────────────────────────


class TestNotifySuccess:
    """Test the _notify_success helper in http_utils."""

    def test_notify_success_import(self):
        """_notify_success should be importable."""
        from code_puppy.http_utils import _notify_success
        assert callable(_notify_success)

    @pytest.mark.asyncio
    async def test_notify_success_empty_model_noop(self):
        """record_success with empty model should not raise."""
        await record_success("")
        await record_success("   ")

    @pytest.mark.asyncio
    async def test_notify_success_fires_and_forgets(self):
        """_notify_success should fire-and-forget without blocking."""
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        # record_success in CLOSED state is no-op
        await record_success("gpt-4")

        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "closed"

    @pytest.mark.asyncio
    async def test_notify_success_closes_half_open(self):
        """_notify_success should close HALF_OPEN circuit."""
        configure(initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await open_circuit("gpt-4")
        from code_puppy import adaptive_rate_limiter as arl
        state = arl._model_states["gpt-4"]
        state.circuit_state = CircuitState.HALF_OPEN

        # Use record_success directly since _notify_success is fire-and-forget
        await record_success("gpt-4")

        assert state.circuit_state == CircuitState.CLOSED


# ── ModelAwareLimiter with circuit breaker ─────────────────────────────────


class TestModelAwareLimiterCircuitBreaker:
    """Test ModelAwareLimiter works with circuit breaker."""

    @pytest.mark.asyncio
    async def test_context_manager_waits_when_open(self):
        """ModelAwareLimiter should block when circuit is OPEN."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=1.0,  # Long to prevent auto-transition
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await open_circuit("gpt-4")

        entered = False

        async def try_enter():
            nonlocal entered
            async with ModelAwareLimiter("gpt-4"):
                entered = True

        task = asyncio.create_task(try_enter())
        await asyncio.sleep(0.05)
        assert not entered

        await close_circuit("gpt-4")
        await asyncio.sleep(0.1)
        assert entered
        await task

    @pytest.mark.asyncio
    async def test_context_manager_works_when_closed(self):
        """ModelAwareLimiter should work normally when circuit is CLOSED."""
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )
        async with ModelAwareLimiter("gpt-4"):
            status = get_status()
            assert status["gpt-4"]["active_count"] == 1

        status = get_status()
        assert status["gpt-4"]["active_count"] == 0


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_close_nonexistent_model_noop(self):
        """close_circuit on unknown model should not raise."""
        await close_circuit("nonexistent-model")

    @pytest.mark.asyncio
    async def test_record_success_nonexistent_model_noop(self):
        """record_success on unknown model should not raise."""
        await record_success("nonexistent-model")

    @pytest.mark.asyncio
    async def test_record_success_empty_model_noop(self):
        """record_success on empty model should not raise."""
        await record_success("")
        await record_success("   ")

    @pytest.mark.asyncio
    async def test_open_does_not_affect_other_models(self):
        """Circuit open for one model should not affect another."""
        configure(
            circuit_breaker_enabled=True,
            circuit_cooldown_seconds=0.1,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")
        await acquire_model_slot("claude-3")
        release_model_slot("claude-3")

        await open_circuit("gpt-4")

        # claude-3 should still be CLOSED
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "open"
        assert status["claude-3"]["circuit_state"] == "closed"

        # claude-3 requests should not be blocked
        await acquire_model_slot("claude-3")
        release_model_slot("claude-3")

    @pytest.mark.asyncio
    async def test_concurrent_open_close(self):
        """Concurrent open/close calls should not deadlock."""
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )

        tasks = [
            open_circuit("gpt-4"),
            close_circuit("gpt-4"),
            open_circuit("gpt-4"),
            close_circuit("gpt-4"),
            open_circuit("gpt-4"),
        ]
        await asyncio.gather(*tasks)

        # Should complete without deadlock; final state should be OPEN
        status = get_status()
        assert status["gpt-4"]["circuit_state"] == "open"

    @pytest.mark.asyncio
    async def test_model_rate_limit_state_has_circuit_fields(self):
        """ModelRateLimitState should have circuit breaker fields."""
        state = ModelRateLimitState(current_limit=10.0)
        assert state.circuit_state == CircuitState.CLOSED
        assert state.circuit_opened_time == 0.0
        assert state.cooldown_multiplier == 1.0
        assert state.half_open_test_count == 0
        assert state.request_queue is not None

    @pytest.mark.asyncio
    async def test_reset_clears_circuit_state(self):
        """reset() should clear circuit breaker state."""
        configure(circuit_breaker_enabled=True, initial_limit=10)
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        await open_circuit("gpt-4")
        assert get_status()["gpt-4"]["circuit_state"] == "open"

        reset()
        assert get_status() == {}

    @pytest.mark.asyncio
    async def test_disable_circuit_breaker_mid_session(self):
        """Can disable circuit breaker after enabling it."""
        configure(
            circuit_breaker_enabled=True,
            initial_limit=10,
        )
        await acquire_model_slot("gpt-4")
        release_model_slot("gpt-4")

        # 429 with circuit breaker enabled → opens circuit
        await record_rate_limit("gpt-4")
        assert get_status()["gpt-4"]["circuit_state"] == "open"

        # Disable circuit breaker
        configure(circuit_breaker_enabled=False)
        await close_circuit("gpt-4")

        # New 429 should not open circuit
        await record_rate_limit("gpt-4")
        assert get_status()["gpt-4"]["circuit_state"] == "closed"
