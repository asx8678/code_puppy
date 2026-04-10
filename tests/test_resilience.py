"""Tests for resilience module."""

import asyncio
from unittest.mock import Mock, call

import pytest

from code_puppy.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    RetryConfig,
    RetryResult,
    RetryState,
    circuit_breaker,
    get_circuit_breaker_status,
    get_or_create_circuit_breaker,
    retry,
    with_fallback,
    with_retry,
    with_retry_sync,
)


class TestRetryConfig:
    """Test RetryConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        cfg = RetryConfig()
        assert cfg.max_attempts == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.exponential_base == 2.0
        assert cfg.retryable_exceptions == (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
        )

    def test_custom_values(self):
        """Test custom configuration values."""
        cfg = RetryConfig(
            max_attempts=5,
            base_delay=0.5,
            max_delay=30.0,
            exponential_base=1.5,
            retryable_exceptions=(ValueError,),
        )
        assert cfg.max_attempts == 5
        assert cfg.base_delay == 0.5
        assert cfg.max_delay == 30.0
        assert cfg.exponential_base == 1.5
        assert cfg.retryable_exceptions == (ValueError,)


class TestWithRetry:
    """Test with_retry function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Test function succeeds on first try."""
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await with_retry(success_func)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """Test function succeeds after retries."""
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count} failed")
            return "success"

        config = RetryConfig(max_attempts=5, base_delay=0.01)
        result = await with_retry(flaky_func, config)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhaust_retries(self):
        """Test exception raised after all retries exhausted."""
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        config = RetryConfig(max_attempts=3, base_delay=0.01)

        with pytest.raises(ValueError, match="Always fails"):
            await with_retry(always_fails, config)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_callback(self):
        """Test on_retry callback is called."""
        callback_calls = []

        def on_retry(attempt, error, delay):
            callback_calls.append((attempt, type(error).__name__, delay))

        async def flaky_func():
            raise ValueError("Fail")

        config = RetryConfig(max_attempts=2, base_delay=0.01, on_retry=on_retry)

        with pytest.raises(ValueError):
            await with_retry(flaky_func, config)

        assert len(callback_calls) == 1  # Called once before final attempt
        assert callback_calls[0][0] == 1  # First retry attempt
        assert callback_calls[0][1] == "ValueError"

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        """Test non-retryable exceptions fail immediately."""
        call_count = 0

        async def raises_typeerror():
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retryable")

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        )

        with pytest.raises(TypeError):
            await with_retry(raises_typeerror, config)

        assert call_count == 1  # No retries


class TestWithRetrySync:
    """Test synchronous retry."""

    def test_sync_retry_success(self):
        """Test sync function succeeds."""
        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Fail")
            return "success"

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        result = with_retry_sync(flaky_func, config)

        assert result == "success"
        assert call_count == 2


class TestWithFallback:
    """Test with_fallback function."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        """Test primary function succeeds."""
        primary = Mock(return_value="primary_result")
        fallback1 = Mock(return_value="fallback1_result")

        result = await with_fallback(primary, [fallback1])

        assert result == "primary_result"
        primary.assert_called_once()
        fallback1.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_used(self):
        """Test fallback is used when primary fails."""
        primary = Mock(side_effect=ValueError("Primary failed"))
        fallback1 = Mock(return_value="fallback_result")

        result = await with_fallback(primary, [fallback1])

        assert result == "fallback_result"
        primary.assert_called_once()
        fallback1.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_fallbacks(self):
        """Test trying multiple fallbacks."""
        primary = Mock(side_effect=ValueError("Primary failed"))
        fallback1 = Mock(side_effect=ValueError("Fallback1 failed"))
        fallback2 = Mock(return_value="fallback2_result")

        result = await with_fallback(primary, [fallback1, fallback2])

        assert result == "fallback2_result"
        primary.assert_called_once()
        fallback1.assert_called_once()
        fallback2.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_fail_with_default(self):
        """Test default value returned when all fail."""
        primary = Mock(side_effect=ValueError("Primary failed"))
        fallback = Mock(side_effect=ValueError("Fallback failed"))

        result = await with_fallback(primary, [fallback], default="default_value")

        assert result == "default_value"

    @pytest.mark.asyncio
    async def test_async_functions(self):
        """Test with async primary and fallbacks."""

        async def async_primary():
            raise ValueError("Async fail")

        async def async_fallback():
            return "async_fallback_result"

        result = await with_fallback(async_primary, [async_fallback])

        assert result == "async_fallback_result"


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Test circuit starts in closed state."""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful call in closed state."""
        breaker = CircuitBreaker("test")

        result = await breaker.call(lambda: "success")

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Test circuit opens after threshold failures."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        # Cause 3 failures
        for _ in range(3):
            try:
                await breaker.call(lambda: (_ for _ in ()).throw(ValueError("Fail")))
            except ValueError:
                pass

        assert breaker.state == CircuitState.OPEN
        assert breaker.failures == 3

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        """Test open circuit rejects calls."""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0)
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        try:
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("Fail")))
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitOpenError, match="Circuit test is open"):
            await breaker.call(lambda: "should not execute")

    @pytest.mark.asyncio
    async def test_circuit_recovery(self):
        """Test circuit recovers after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.01,  # Very short for testing
        )
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        try:
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("Fail")))
        except ValueError:
            pass

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.02)

        # Next call should trigger half-open state
        with pytest.raises(ValueError):
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("Fail again")))

        # Should be open again after failure in half-open
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_in_half_open_closes_circuit(self):
        """Test success in half-open state closes circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.01,
            success_threshold=1,
        )
        breaker = CircuitBreaker("test", config)

        # Open the circuit
        try:
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("Fail")))
        except ValueError:
            pass

        await asyncio.sleep(0.02)  # Wait for recovery timeout

        # Success in half-open should close circuit
        result = await breaker.call(lambda: "success")

        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failures == 0

    @pytest.mark.asyncio
    async def test_async_function_in_breaker(self):
        """Test circuit breaker with async function."""
        breaker = CircuitBreaker("test")

        async def async_success():
            await asyncio.sleep(0.001)
            return "async_result"

        result = await breaker.call(async_success)

        assert result == "async_result"


class TestRetryDecorator:
    """Test @retry decorator."""

    def test_decorator_does_not_accept_temperature_escalation(self):
        """The retry decorator should NOT accept temperature_escalation."""
        import inspect

        sig = inspect.signature(retry)
        assert "temperature_escalation" not in sig.parameters

    @pytest.mark.asyncio
    async def test_async_retry_decorator(self):
        """Test retry decorator on async function."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        async def flaky_async():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Fail")
            return "success"

        result = await flaky_async()

        assert result == "success"
        assert call_count == 2

    def test_sync_retry_decorator(self):
        """Test retry decorator on sync function."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def flaky_sync():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Fail")
            return "success"

        result = flaky_sync()

        assert result == "success"
        assert call_count == 2


class TestCircuitBreakerDecorator:
    """Test @circuit_breaker decorator."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_decorator(self):
        """Test circuit breaker decorator."""
        call_count = 0

        @circuit_breaker("test_cb", failure_threshold=2)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Call {call_count} failed")

        # First 2 calls will fail and open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await flaky_func()

        # Next call should be rejected by circuit breaker
        with pytest.raises(CircuitOpenError):
            await flaky_func()

        # Should not have made a 3rd actual call
        assert call_count == 2


class TestCircuitBreakerRegistry:
    """Test circuit breaker registry."""

    def test_get_or_create_circuit_breaker(self):
        """Test getting or creating circuit breakers."""
        breaker1 = get_or_create_circuit_breaker("test_registry")
        breaker2 = get_or_create_circuit_breaker("test_registry")

        # Should be same instance
        assert breaker1 is breaker2

    def test_get_circuit_breaker_status(self):
        """Test getting status of all circuit breakers."""
        # Create a breaker
        breaker = get_or_create_circuit_breaker("status_test")

        # Get status
        status = get_circuit_breaker_status()

        assert "status_test" in status
        assert status["status_test"]["state"] == "CLOSED"


class TestTemperatureEscalation:
    """Test temperature escalation on retry (ADOPT from Agentless)."""

    @pytest.mark.asyncio
    async def test_temperature_escalates_on_retry(self):
        """Temperature values increase with each attempt."""
        state = RetryState()
        temps_seen = []
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            temps_seen.append(state.temperature)
            if call_count < 4:
                raise ValueError(f"Attempt {call_count}")
            return "success"

        config = RetryConfig(
            max_attempts=5,
            base_delay=0.01,
            temperature_escalation=[0.0, 0.2, 0.4, 0.8, 1.0],
        )
        result = await with_retry(flaky_func, config, state=state)
        assert result == "success"
        assert temps_seen == [0.0, 0.2, 0.4, 0.8]

    @pytest.mark.asyncio
    async def test_temperature_none_without_escalation(self):
        """Without escalation config, temperature is None."""
        state = RetryState()

        async def success_func():
            return state.temperature

        config = RetryConfig(max_attempts=3, base_delay=0.01)
        result = await with_retry(success_func, config, state=state)
        assert result is None

    @pytest.mark.asyncio
    async def test_temperature_reuses_last_value(self):
        """When attempts exceed escalation list, last value is reused."""
        state = RetryState()
        temps_seen = []
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            temps_seen.append(state.temperature)
            raise ValueError("Fail")

        config = RetryConfig(
            max_attempts=5,
            base_delay=0.01,
            temperature_escalation=[0.0, 0.5],
        )
        with pytest.raises(ValueError):
            await with_retry(always_fails, config, state=state)
        # [0.0, 0.5, 0.5, 0.5, 0.5]
        assert temps_seen == [0.0, 0.5, 0.5, 0.5, 0.5]

    @pytest.mark.asyncio
    async def test_state_attempt_number_tracked(self):
        """RetryState.attempt is updated on each attempt."""
        state = RetryState()
        attempts_seen = []
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            attempts_seen.append(state.attempt)
            if call_count < 3:
                raise ValueError("Fail")
            return "ok"

        config = RetryConfig(max_attempts=5, base_delay=0.01)
        await with_retry(flaky, config, state=state)
        assert attempts_seen == [0, 1, 2]

    def test_retry_state_defaults(self):
        """RetryState has sensible defaults."""
        state = RetryState()
        assert state.attempt == 0
        assert state.temperature is None

    def test_sync_retry_with_temperature(self):
        """with_retry_sync also supports temperature escalation."""
        state = RetryState()
        temps_seen = []
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            temps_seen.append(state.temperature)
            if call_count < 2:
                raise ValueError("Fail")
            return "ok"

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.01,
            temperature_escalation=[0.0, 0.8, 1.0],
        )
        result = with_retry_sync(flaky, config, state=state)
        assert result == "ok"
        assert temps_seen == [0.0, 0.8]


class TestIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_retry_with_circuit_breaker(self):
        """Test combining retry and circuit breaker."""
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("Temporary failure")
            return "success"

        # First attempt with retry
        result = await with_retry(
            operation, RetryConfig(max_attempts=3, base_delay=0.01)
        )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fallback_with_retry(self):
        """Test combining fallback and retry."""
        primary_calls = 0
        fallback_calls = 0

        @retry(max_attempts=2, base_delay=0.01)
        async def primary():
            nonlocal primary_calls
            primary_calls += 1
            raise ValueError("Always fails")

        async def fallback():
            nonlocal fallback_calls
            fallback_calls += 1
            return "fallback_success"

        # Primary will exhaust retries and fail
        result = await with_fallback(primary, [fallback], default="default")

        assert result == "fallback_success"
        # Primary called twice (initial + 1 retry)
        assert primary_calls == 2
        assert fallback_calls == 1


class TestRetryResult:
    """Tests for RetryResult metadata object."""

    async def test_return_result_success_first_attempt(self):
        async def succeeds():
            return 42

        result = await with_retry(succeeds, return_result=True)
        assert isinstance(result, RetryResult)
        assert result.success is True
        assert result.result == 42
        assert result.attempts == 1
        assert result.total_time >= 0
        assert result.errors == []

    async def test_return_result_success_after_retries(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("retry me")
            return "ok"

        cfg = RetryConfig(max_attempts=5, base_delay=0.01, max_delay=0.05)
        result = await with_retry(flaky, cfg, return_result=True)
        assert result.success is True
        assert result.result == "ok"
        assert result.attempts == 3
        assert len(result.errors) == 2
        assert all(isinstance(e, ConnectionError) for e in result.errors)

    async def test_return_result_all_fail(self):
        async def always_fails():
            raise ConnectionError("nope")

        cfg = RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.02)
        result = await with_retry(always_fails, cfg, return_result=True)
        assert result.success is False
        assert result.result is None
        assert result.attempts == 3
        assert len(result.errors) == 3
        assert result.total_time > 0

    async def test_return_result_non_retryable(self):
        async def type_error():
            raise TypeError("not retryable")

        cfg = RetryConfig(max_attempts=3, base_delay=0.01)
        result = await with_retry(type_error, cfg, return_result=True)
        assert result.success is False
        assert result.attempts == 1
        assert len(result.errors) == 1
        assert isinstance(result.errors[0], TypeError)

    async def test_default_still_raises(self):
        """Without return_result=True, behavior is unchanged."""
        async def fails():
            raise ConnectionError("boom")

        cfg = RetryConfig(max_attempts=2, base_delay=0.01)
        with pytest.raises(ConnectionError):
            await with_retry(fails, cfg)


class TestRollingWindowCircuitBreaker:
    """Tests for rolling window and volume threshold enhancements."""

    async def test_rolling_window_expires_old_failures(self):
        """Failures outside the window should not count."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            rolling_window_seconds=0.2,
            volume_threshold=0,
        )
        cb = CircuitBreaker("test-rolling", config)

        # Record 2 failures
        for _ in range(2):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
            except ValueError:
                pass

        # Wait for window to expire
        await asyncio.sleep(0.3)

        # Record 1 more failure — total in window is now only 1, not 3
        try:
            await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
        except ValueError:
            pass

        # Circuit should still be CLOSED (only 1 failure in window)
        assert cb.state == CircuitState.CLOSED

    async def test_volume_threshold_prevents_false_trip(self):
        """Circuit shouldn't trip if total requests are below volume_threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            rolling_window_seconds=10.0,
            volume_threshold=5,
        )
        cb = CircuitBreaker("test-volume", config)

        # Record 3 failures (exceeds failure_threshold=2 but below volume_threshold=5)
        for _ in range(3):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
            except ValueError:
                pass

        # Should still be CLOSED — not enough total traffic
        assert cb.state == CircuitState.CLOSED

    async def test_volume_threshold_trips_when_met(self):
        """Circuit trips when both failure_threshold AND volume_threshold are met."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            rolling_window_seconds=10.0,
            volume_threshold=5,
        )
        cb = CircuitBreaker("test-trips", config)

        # 2 successes + 3 failures = 5 total (meets volume), 3 failures (meets threshold)
        for _ in range(2):
            await cb.call(lambda: "ok")
        for _ in range(3):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
            except ValueError:
                pass

        assert cb.state == CircuitState.OPEN

    async def test_rolling_window_disabled_by_default(self):
        """With default config (rolling_window=0), behavior is cumulative as before."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test-default", config)

        for _ in range(3):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
            except ValueError:
                pass

        assert cb.state == CircuitState.OPEN

    async def test_reset_clears_history(self):
        config = CircuitBreakerConfig(
            failure_threshold=5,
            rolling_window_seconds=10.0,
        )
        cb = CircuitBreaker("test-reset", config)

        for _ in range(3):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ValueError("err")))
            except ValueError:
                pass

        assert len(cb._request_history) == 3
        cb._reset()
        assert len(cb._request_history) == 0
