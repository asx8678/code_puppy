"""Shared retry and fallback helpers for resilient operations.

This module provides decorators and utilities for adding retry logic,
fallback chains, and circuit breakers to operations. Used by both
the agent pack system and general tool execution.
"""

from __future__ import annotations

import asyncio
import inspect
import functools
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Generic, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, reject calls
    HALF_OPEN = auto()   # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior.
    
    Attributes:
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 60.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry
            (default: (ConnectionError, TimeoutError, OSError, ValueError))
        on_retry: Optional callback called on each retry with (attempt, error, delay)
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,  # Network issues
        TimeoutError,     # Timeouts
        OSError,          # File/network OS errors
        ValueError,       # Parse errors
    )
    on_retry: Callable[[int, Exception, float], None] | None = None


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker.
    
    Attributes:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before attempting recovery
        half_open_max_calls: Max calls allowed in half-open state
        success_threshold: Consecutive successes needed to close circuit
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
                    raise CircuitOpenError(f"Circuit {self.name} half-open limit reached")
                self.half_open_calls += 1
            
            # Capture state for post-execution updates (still under lock)
            was_half_open = self.state == CircuitState.HALF_OPEN
            failure_threshold = self.config.failure_threshold
        
        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result
            await self._on_success(was_half_open)
            return result
        except Exception as e:
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
                logger.warning(f"Circuit {self.name} opening ({self.failures} failures)")
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


async def with_retry(
    func: Callable[[], T],
    config: RetryConfig | None = None,
) -> T:
    """Execute function with retry logic.
    
    Args:
        func: Function to execute (sync or async)
        config: Retry configuration
        
    Returns:
        Result from successful execution
        
    Raises:
        Exception: The last exception after all retries exhausted
    """
    cfg = config or RetryConfig()
    last_error: Exception | None = None
    
    for attempt in range(cfg.max_attempts):
        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result
            return result
        except cfg.retryable_exceptions as e:
            last_error = e
            if attempt < cfg.max_attempts - 1:
                delay = min(
                    cfg.base_delay * (cfg.exponential_base ** attempt),
                    cfg.max_delay,
                )
                if cfg.on_retry:
                    cfg.on_retry(attempt + 1, e, delay)
                logger.warning(f"Retry {attempt + 1}/{cfg.max_attempts} after error: {e}")
                await asyncio.sleep(delay)
    
    assert last_error is not None
    raise last_error


def with_retry_sync(
    func: Callable[[], T],
    config: RetryConfig | None = None,
) -> T:
    """Synchronous version of with_retry.
    
    Args:
        func: Synchronous function to execute
        config: Retry configuration
        
    Returns:
        Result from successful execution
    """
    cfg = config or RetryConfig()
    last_error: Exception | None = None
    
    for attempt in range(cfg.max_attempts):
        try:
            return func()
        except cfg.retryable_exceptions as e:
            last_error = e
            if attempt < cfg.max_attempts - 1:
                delay = min(
                    cfg.base_delay * (cfg.exponential_base ** attempt),
                    cfg.max_delay,
                )
                if cfg.on_retry:
                    cfg.on_retry(attempt + 1, e, delay)
                logger.warning(f"Retry {attempt + 1}/{cfg.max_attempts} after error: {e}")
                time.sleep(delay)
    
    assert last_error is not None
    raise last_error


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
            func_name = getattr(func, '__name__', repr(func))
            logger.warning(f"{'Primary' if i == 0 else f'Fallback {i}'} {func_name} failed: {e}")
            continue
    
    return default


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,  # Network issues
        TimeoutError,     # Timeouts
        OSError,          # File/network OS errors
        ValueError,       # Parse errors
    ),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to add retry logic to a function.
    
    Example:
        @retry(max_attempts=3)
        async def fetch_data():
            ...
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        retryable_exceptions=retryable_exceptions,
    )
    
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await with_retry(lambda: func(*args, **kwargs), config)
        
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return with_retry_sync(lambda: func(*args, **kwargs), config)
        
        # Return async wrapper if function is async, sync otherwise
        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore
    
    return decorator


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to add circuit breaker to a function.
    
    Example:
        @circuit_breaker("api_calls")
        async def call_api():
            ...
    """
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
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, config)
    return _circuit_breakers[name]


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
