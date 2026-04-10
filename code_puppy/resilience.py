"""Shared retry and fallback helpers for resilient operations.

This module provides decorators and utilities for adding retry logic,
fallback chains, and circuit breakers to operations. Used by both
the agent pack system and general tool execution.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import time
import warnings
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Generic, ParamSpec, TypeVar

from code_puppy.async_utils import run_async_sync

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def walk_causes(
    exc: BaseException,
    max_depth: int = 5,
) -> list[BaseException]:
    """Walk an exception's ``__cause__``/``__context__`` chain up to ``max_depth``.

    Returns a list starting with ``exc`` itself, followed by each nested cause
    (preferring ``__cause__`` over ``__context__``). Cycle-safe via identity tracking.

    Args: exc - The top-level exception. max_depth - Maximum chain depth (default 5).
    Returns: List of exceptions in chain order (shallowest first).
    """
    chain: list[BaseException] = [exc]
    seen: set[int] = {id(exc)}
    current: BaseException = exc
    for _ in range(max_depth):
        nxt = current.__cause__ or current.__context__
        if nxt is None or id(nxt) in seen:
            break
        chain.append(nxt)
        seen.add(id(nxt))
        current = nxt
    return chain


def _is_coro_func(func: Callable) -> bool:
    """Cached check if a function is a coroutine function.

    inspect.iscoroutinefunction is moderately expensive and called
    repeatedly during decorator application. This cache speeds up
    retry/circuit breaker decorator application on hot paths.
    """
    return inspect.iscoroutinefunction(func)


def _is_terminal_quota_error(exc: BaseException) -> bool:
    """Classify whether an exception represents a *terminal* (not transient) quota.

    Returns True if the exception chain contains ``httpx.HTTPStatusError`` with
    status 429 AND Retry-After > 300 seconds, or message indicating daily/monthly
    quota exhaustion. Otherwise returns False (error is transient).
    """
    # Walk the cause chain
    for err in walk_causes(exc):
        # Check for httpx status errors with long retry-after
        status_err = None
        # Try to find httpx.HTTPStatusError without hard-importing httpx at module load
        try:
            import httpx

            if isinstance(err, httpx.HTTPStatusError):
                status_err = err
        except ImportError:
            pass

        if status_err is not None and status_err.response.status_code == 429:
            retry_after = status_err.response.headers.get("retry-after")
            if retry_after:
                try:
                    # Retry-After can be seconds (int) or HTTP-date (skip the latter)
                    retry_after_secs = float(retry_after)
                    if retry_after_secs > 300:
                        return True
                except ValueError:
                    pass

        # Check for daily/monthly quota exhaustion markers
        msg = str(err).lower()
        terminal_markers = (
            "daily",
            "per day",
            "monthly",
            "per month",
            "quota_exhausted",
            "quota exceeded for quota metric",
        )
        if any(marker in msg for marker in terminal_markers):
            return True

    return False


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = auto()  # Normal operation
    OPEN = auto()  # Failing, reject calls
    HALF_OPEN = auto()  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts (int): Maximum retry attempts (default: 3)
        base_delay (float): Initial delay in seconds (default: 1.0)
        max_delay (float): Maximum delay in seconds (default: 60.0)
        exponential_base (float): Base for exponential backoff (default: 2.0)
        retryable_exceptions (tuple): Exception types to retry
        on_retry: Optional callback with (attempt, error, delay)
        temperature_escalation: Optional temperature values per attempt
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,  # Network issues
        TimeoutError,  # Timeouts
        OSError,  # File/network OS errors
        ValueError,  # Parse errors
    )
    on_retry: Callable[[int, Exception, float], None] | None = None
    temperature_escalation: list[float] | None = None


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker.

    Attributes:
        failure_threshold (int): Failures before opening circuit
        recovery_timeout (float): Seconds before recovery attempt
        half_open_max_calls (int): Max calls in half-open state
        success_threshold (int): Consecutive successes to close circuit
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    success_threshold: int = 2


@dataclass
class FallbackConfig(Generic[T]):
    """Configuration for fallback chain.

    Attributes:
        fallbacks: List of fallback functions to try in order
        default_value: Default value if all fallbacks fail
    """

    fallbacks: list[Callable[P, T]] = field(default_factory=list)
    default_value: T | None = None


class CircuitBreaker:
    """Circuit breaker for preventing cascade failures.

    Tracks failures and opens circuit when threshold is reached,
    preventing further calls until service recovers.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.last_failure_time: float = 0.0
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[[], T]) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute

        Returns:
            Result from function

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Any exception from the function
        """
        # State snapshot captured under single lock acquisition
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.config.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info(f"Circuit {self.name} entering half-open state")
                else:
                    raise CircuitOpenError(f"Circuit {self.name} is open")

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitOpenError(
                        f"Circuit {self.name} half-open limit reached"
                    )
                self.half_open_calls += 1

            # Capture state for post-execution updates (still under lock)
            # was_half_open is captured under lock, and _on_success/_on_failure
            # re-acquire the same lock before reading it, so there's no race.
            was_half_open = self.state == CircuitState.HALF_OPEN
            failure_threshold = self.config.failure_threshold

        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result
            await self._on_success(was_half_open)
            return result
        except Exception:
            await self._on_failure(was_half_open, failure_threshold)
            raise

    async def _on_success(self, was_half_open: bool) -> None:
        """Record successful call."""
        async with self._lock:
            if was_half_open:
                self.successes += 1
                if self.successes >= self.config.success_threshold:
                    logger.info(f"Circuit {self.name} closing (recovered)")
                    self._reset()
            else:
                self.failures = max(0, self.failures - 1)

    async def _on_failure(self, was_half_open: bool, failure_threshold: int) -> None:
        """Record failed call."""
        async with self._lock:
            self.failures += 1
            self.last_failure_time = time.time()

            if was_half_open:
                logger.warning(f"Circuit {self.name} opening (failure in half-open)")
                self.state = CircuitState.OPEN
            elif self.failures >= failure_threshold:
                logger.warning(
                    f"Circuit {self.name} opening ({self.failures} failures)"
                )
                self.state = CircuitState.OPEN

    def _reset(self) -> None:
        """Reset circuit to closed state."""
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.half_open_calls = 0


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


@dataclass
class RetryState:
    """Mutable state for the current retry loop.

    Allows the retried function to observe the current attempt number
    and any per-attempt parameters (e.g., temperature escalation).

    Inspired by Agentless ``localize.py:250-300`` which escalates LLM
    temperature on validation-failure retries (0→0.2→0.4→0.8→1.0).

    Example:
        >>> state = RetryState()
        >>> config = RetryConfig(
        ...     max_attempts=5,
        ...     base_delay=0.1,
        ...     temperature_escalation=[0.0, 0.2, 0.4, 0.8, 1.0],
        ... )
        >>> async def call_llm():
        ...     temp = state.temperature or 0.0
        ...     return await some_llm_api(temperature=temp)
        >>> # state.attempt and state.temperature are updated each iteration
    """

    attempt: int = 0
    _temperature: float | None = field(default=None, repr=False)

    @property
    def temperature(self) -> float | None:
        """Current temperature from escalation config, or None if not set."""
        return self._temperature


async def with_retry(
    func: Callable[[], T],
    config: RetryConfig | None = None,
    on_terminal_quota: Callable[[Exception], Any] | None = None,
    *,
    state: RetryState | None = None,
) -> T:
    """Execute function with retry logic.

    Args: func - Function to execute (sync or async). config - Retry configuration.
        on_terminal_quota - Optional callback for terminal quota errors.
        state - Optional RetryState to track attempt and temperature.
    Returns: Result from successful execution.

    Raises:
        Exception: The last exception after all retries exhausted
    """
    cfg = config or RetryConfig()
    if state is None:
        state = RetryState()
    last_error: Exception | None = None

    for attempt in range(cfg.max_attempts):
        state.attempt = attempt
        if cfg.temperature_escalation is not None:
            idx = min(attempt, len(cfg.temperature_escalation) - 1)
            state._temperature = cfg.temperature_escalation[idx]
        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as e:
            last_error = e

            # Check for terminal quota errors before deciding to retry
            if _is_terminal_quota_error(e):
                if on_terminal_quota is not None:
                    callback_result = on_terminal_quota(e)
                    # Handle both sync and async callbacks
                    if inspect.isawaitable(callback_result):
                        callback_result = await callback_result  # type: ignore
                    if callback_result:
                        # Callback wants us to reset and retry (e.g., new model)
                        logger.info(
                            "Terminal quota detected; on_terminal_quota returned "
                            "truthy — resetting retry attempt counter"
                        )
                        attempt = 0  # Reset attempt counter
                        continue
                    # Callback returned falsy - treat as terminal, don't retry
                    raise
                # No callback - terminal errors don't retry
                raise

            # Check if any exception in the cause chain is retryable
            exc_chain = walk_causes(e)
            if not any(isinstance(err, cfg.retryable_exceptions) for err in exc_chain):
                # Not a retryable exception - re-raise immediately
                raise

            # Retryable exception - proceed with retry logic
            if attempt < cfg.max_attempts - 1:
                delay = min(
                    cfg.base_delay * (cfg.exponential_base**attempt),
                    cfg.max_delay,
                )
                # Add jitter to prevent thundering herd
                delay = delay + random.uniform(0, delay * 0.1)
                if cfg.on_retry:
                    cfg.on_retry(attempt + 1, e, delay)
                logger.warning(
                    f"Retry {attempt + 1}/{cfg.max_attempts} after error: {e}"
                )
                await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error


def with_retry_sync(
    func: Callable[[], T],
    config: RetryConfig | None = None,
    on_terminal_quota: Callable[[Exception], Any] | None = None,
    *,
    state: RetryState | None = None,
) -> T:
    """Synchronous version of with_retry. Wraps async with_retry using background thread event loop."""
    try:
        asyncio.get_running_loop()
        warnings.warn(
            "with_retry_sync called from async context - this will block the event loop",
            stacklevel=2,
        )
    except RuntimeError:
        pass  # No running loop, safe to use
    return run_async_sync(with_retry(func, config, on_terminal_quota, state=state))


async def with_fallback(
    primary: Callable[[], T],
    fallbacks: list[Callable[[], T]],
    default: T | None = None,
) -> T | None:
    """Try primary function, fall back to alternatives on failure.

    Args:
        primary: Primary function to try
        fallbacks: List of fallback functions to try in order
        default: Default value if all fail

    Returns:
        Result from first successful function, or default
    """
    functions = [primary] + fallbacks

    for i, func in enumerate(functions):
        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result
            if i > 0:
                logger.info(f"Fallback {i} succeeded after primary failed")
            return result
        except Exception as e:
            func_name = getattr(func, "__name__", repr(func))
            logger.warning(
                f"{'Primary' if i == 0 else f'Fallback {i}'} {func_name} failed: {e}"
            )
            continue

    return default


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,  # Network issues
        TimeoutError,  # Timeouts
        OSError,  # File/network OS errors
        ValueError,  # Parse errors
    ),
    on_terminal_quota: Callable[[Exception], Any] | None = None,
    temperature_escalation: list[float] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to add retry logic to a function.

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exception types to retry
        on_terminal_quota: Optional callback for terminal quota errors
        temperature_escalation: Optional list of temperature values for each attempt
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        retryable_exceptions=retryable_exceptions,
        temperature_escalation=temperature_escalation,
    )

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await with_retry(
                lambda: func(*args, **kwargs), config, on_terminal_quota
            )

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return with_retry_sync(
                lambda: func(*args, **kwargs), config, on_terminal_quota
            )

        # Return async wrapper if function is async, sync otherwise
        if _is_coro_func(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to add circuit breaker to a function."""
    breaker = CircuitBreaker(
        name,
        CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        ),
    )

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await breaker.call(lambda: func(*args, **kwargs))

        # Store breaker reference on function for monitoring
        async_wrapper._circuit_breaker = breaker  # type: ignore

        return async_wrapper  # type: ignore

    return decorator


# Global registry for circuit breakers (for monitoring)
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_or_create_circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    """Get existing circuit breaker or create new one.

    Args:
        name: Unique name for the circuit breaker
        config: Optional configuration

    Returns:
        CircuitBreaker instance
    """
    breaker = _circuit_breakers.get(name)
    if breaker is None:
        breaker = CircuitBreaker(name, config)
        breaker = _circuit_breakers.setdefault(name, breaker)
    return breaker


def get_circuit_breaker_status() -> dict[str, dict[str, Any]]:
    """Get status of all circuit breakers.

    Returns:
        Dict mapping breaker names to their status
    """
    return {
        name: {
            "state": breaker.state.name,
            "failures": breaker.failures,
            "successes": breaker.successes,
        }
        for name, breaker in _circuit_breakers.items()
    }
