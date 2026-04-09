"""RunLimiter - thread-safe + asyncio-safe concurrency gate for agent invocations.

Based on Orion's backend/jobs.py pattern but adapted for code_puppy's mixed sync/async world.
Uses Condition variables for fair FIFO queueing and supports both sync and async callers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RunConcurrencyLimitError(Exception):
    """Raised when concurrent run limit is exceeded and caller opted out of waiting."""
    
    def __init__(self, message: str, active: int, limit: int, waited: float | None = None):
        super().__init__(message)
        self.active = active
        self.limit = limit
        self.waited = waited  # Seconds waited before giving up (None if non-blocking)


@dataclass(frozen=True)
class RunLimiterConfig:
    """Configuration for RunLimiter.
    
    Matches Orion's pattern:
    - max_concurrent_runs: hard cap (when allow_parallel=True)
    - allow_parallel=False: forces max=1 regardless of max_concurrent_runs
    - wait_timeout: None=forever, float=seconds before raising
    """
    max_concurrent_runs: int = 2
    allow_parallel: bool = True
    wait_timeout: float | None = None  # None = wait forever


class RunLimiter:
    """Thread + async-safe limiter for concurrent agent runs.
    
    Uses threading.Condition for sync side and asyncio.Condition for async side.
    Both share the same underlying counter protected by independent locks.
    
    Fairness: FIFO queueing via condition variable notify/wait pattern.
    
    Graceful degradation: if initialized with invalid config, falls back to
    sensible defaults and logs a warning rather than crashing.
    """
    
    def __init__(self, config: RunLimiterConfig | None = None):
        self._config = config or RunLimiterConfig()
        
        # Validate config with fallback
        if self._config.max_concurrent_runs < 1:
            logger.warning(
                "Invalid max_concurrent_runs=%d, using default=2",
                self._config.max_concurrent_runs,
            )
            self._config = RunLimiterConfig(
                max_concurrent_runs=2,
                allow_parallel=self._config.allow_parallel,
                wait_timeout=self._config.wait_timeout,
            )
        
        # Shared state (synchronized via _lock)
        self._active_count: int = 0
        self._waiters_count: int = 0  # Waiting threads/coroutines
        
        # Sync primitives
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        
        # Async primitives (separate since they can't be shared)
        self._async_lock = asyncio.Lock()
        # Note: asyncio.Condition needs a lock, we'll use our _async_lock
        self._async_condition = asyncio.Condition(self._async_lock)
    
    @property
    def effective_limit(self) -> int:
        """Actual cap enforced (respects allow_parallel)."""
        if not self._config.allow_parallel:
            return 1
        return max(1, self._config.max_concurrent_runs)
    
    @property
    def active_count(self) -> int:
        """Current number of active runs (thread-safe read)."""
        with self._lock:
            return self._active_count
    
    @property
    def waiters_count(self) -> int:
        """Number of callers currently waiting for a slot."""
        with self._lock:
            return self._waiters_count
    
    def _can_acquire(self) -> bool:
        """Check if slot available (must hold _lock)."""
        return self._active_count < self.effective_limit
    
    def acquire_sync(self, *, blocking: bool = True, timeout: float | None = None) -> bool:
        """Try to acquire a slot (sync). 
        
        Args:
            blocking: If False, return immediately with True/False
            timeout: Max seconds to wait (None = use config default, 0 = no wait)
        
        Returns:
            True if slot acquired, False if non-blocking and full
        
        Raises:
            RunConcurrencyLimitError: If timeout expires while waiting
        """
        effective_timeout = timeout if timeout is not None else self._config.wait_timeout
        
        with self._lock:
            if self._can_acquire():
                self._active_count += 1
                return True
            
            if not blocking:
                return False
            
            # Need to wait
            self._waiters_count += 1
            
        # Wait outside the lock using condition variable
        import time
        start_time = time.monotonic()
        
        try:
            with self._condition:
                while True:
                    with self._lock:
                        if self._can_acquire():
                            self._active_count += 1
                            self._waiters_count -= 1
                            return True
                    
                    # Check timeout
                    if effective_timeout is not None:
                        elapsed = time.monotonic() - start_time
                        remaining = effective_timeout - elapsed
                        if remaining <= 0:
                            with self._lock:
                                self._waiters_count -= 1
                            raise RunConcurrencyLimitError(
                                f"Timeout waiting for run slot (limit={self.effective_limit})",
                                active=self.active_count,
                                limit=self.effective_limit,
                                waited=effective_timeout,
                            )
                        # Wait with timeout
                        if not self._condition.wait(timeout=remaining):
                            # Timeout expired
                            with self._lock:
                                self._waiters_count -= 1
                            raise RunConcurrencyLimitError(
                                f"Timeout waiting for run slot (limit={self.effective_limit})",
                                active=self.active_count,
                                limit=self.effective_limit,
                                waited=effective_timeout,
                            )
                    else:
                        # Wait forever
                        self._condition.wait()
        except RunConcurrencyLimitError:
            raise
        except Exception as e:
            # Ensure waiter count is decremented on unexpected error
            with self._lock:
                self._waiters_count = max(0, self._waiters_count - 1)
            raise
    
    async def acquire_async(self, timeout: float | None = None) -> None:
        """Async acquire with optional wait timeout.
        
        Args:
            timeout: Max seconds to wait (None = use config default = infinite)
        
        Raises:
            RunConcurrencyLimitError: On timeout
        """
        effective_timeout = timeout if timeout is not None else self._config.wait_timeout
        
        # Fast path: no contention
        async with self._async_lock:
            if self._active_count < self.effective_limit:
                self._active_count += 1
                return
            self._waiters_count += 1
        
        # Slow path: need to wait
        import asyncio
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with self._async_condition:
                while True:
                    async with self._async_lock:
                        if self._active_count < self.effective_limit:
                            self._active_count += 1
                            self._waiters_count -= 1
                            return
                    
                    # Check timeout
                    if effective_timeout is not None:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        remaining = effective_timeout - elapsed
                        if remaining <= 0:
                            async with self._async_lock:
                                self._waiters_count -= 1
                            raise RunConcurrencyLimitError(
                                f"Timeout waiting for run slot (limit={self.effective_limit})",
                                active=self._active_count,
                                limit=self.effective_limit,
                                waited=effective_timeout,
                            )
                        # Wait with timeout
                        try:
                            await asyncio.wait_for(
                                self._async_condition.wait(),
                                timeout=remaining,
                            )
                        except asyncio.TimeoutError:
                            async with self._async_lock:
                                self._waiters_count -= 1
                            raise RunConcurrencyLimitError(
                                f"Timeout waiting for run slot (limit={self.effective_limit})",
                                active=self._active_count,
                                limit=self.effective_limit,
                                waited=effective_timeout,
                            )
                    else:
                        # Wait forever
                        await self._async_condition.wait()
        except RunConcurrencyLimitError:
            raise
        except Exception:
            # Ensure waiter count is decremented on unexpected error
            async with self._async_lock:
                self._waiters_count = max(0, self._waiters_count - 1)
            raise
    
    def release(self) -> None:
        """Release a slot. Notifies one waiter (FIFO via condition variable)."""
        with self._lock:
            if self._active_count > 0:
                self._active_count -= 1
            else:
                logger.warning("RunLimiter.release() called with no active runs")
        
        # Notify sync waiters
        with self._condition:
            self._condition.notify()
        
        # Notify async waiters (fire and forget - can't hold both locks)
        try:
            # Try to notify without blocking
            loop = asyncio.get_running_loop()
            # Schedule the notification on the event loop
            loop.call_soon_threadsafe(self._notify_async)
        except RuntimeError:
            # No running loop - ignore (async callers not active)
            pass
    
    def _notify_async(self) -> None:
        """Notify async waiters (must be called from event loop thread)."""
        try:
            # Create a task to notify
            asyncio.create_task(self._do_async_notify())
        except RuntimeError:
            pass

    async def _do_async_notify(self) -> None:
        """Actually perform the async notification."""
        async with self._async_condition:
            self._async_condition.notify()

    @contextmanager
    def slot_sync(self, *, blocking: bool = True, timeout: float | None = None):
        """Context manager for sync callers.

        Usage:
            with limiter.slot_sync():
                run_agent()

        Raises:
            RunConcurrencyLimitError: If timeout expires
        """
        acquired = self.acquire_sync(blocking=blocking, timeout=timeout)
        if not acquired:
            raise RunConcurrencyLimitError(
                f"Run slot not available (limit={self.effective_limit})",
                active=self.active_count,
                limit=self.effective_limit,
                waited=None,
            )
        try:
            yield self
        finally:
            self.release()
    
    @asynccontextmanager
    async def slot_async(self, timeout: float | None = None):
        """Async context manager.
        
        Usage:
            async with limiter.slot_async():
                await run_agent()
        
        Raises:
            RunConcurrencyLimitError: If timeout expires
        """
        await self.acquire_async(timeout=timeout)
        try:
            yield self
        finally:
            self.release()
    
    def update_config(self, new_config: RunLimiterConfig) -> None:
        """Atomically swap config and re-check bounds.
        
        If the new limit is higher than before, notifies waiters.
        If lower, active runs are not affected (only new acquisitions).
        """
        old_limit = self.effective_limit
        
        # Validate before applying
        if new_config.max_concurrent_runs < 1:
            logger.warning(
                "Invalid max_concurrent_runs=%d, rejecting config update",
                new_config.max_concurrent_runs,
            )
            return
        
        self._config = new_config
        new_limit = self.effective_limit
        
        logger.info(
            "RunLimiter config updated: limit %d -> %d",
            old_limit,
            new_limit,
        )
        
        # If limit increased, wake up waiters
        if new_limit > old_limit:
            # Notify sync waiters
            with self._condition:
                # Notify multiple times in case multiple slots opened
                for _ in range(new_limit - old_limit):
                    self._condition.notify()
            
            # Notify async waiters
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._notify_multiple_async, new_limit - old_limit)
            except RuntimeError:
                pass
    
    def _notify_multiple_async(self, count: int) -> None:
        """Notify multiple async waiters."""
        try:
            asyncio.create_task(self._do_multiple_async_notify(count))
        except RuntimeError:
            pass
    
    async def _do_multiple_async_notify(self, count: int) -> None:
        """Actually perform multiple async notifications."""
        async with self._async_condition:
            for _ in range(count):
                self._async_condition.notify()


# Singleton instance management
_limiter_instance: RunLimiter | None = None
_limiter_lock = threading.Lock()


def _build_from_config() -> RunLimiter:
    """Build a RunLimiter from config file or defaults."""
    # Read from pack_parallelism.toml if available
    from pathlib import Path
    
    config_path = Path.home() / ".code_puppy" / "pack_parallelism.toml"
    
    max_runs = 2  # Default from MAX_PARALLEL_AGENTS convention
    allow_parallel = True
    wait_timeout = None
    
    if config_path.exists():
        try:
            import tomllib  # Python 3.11+
            
            with open(config_path, "rb") as fh:
                data = tomllib.load(fh)
            
            pack_leader = data.get("pack_leader", {})
            # pack_parallelism uses 'max_parallelism', we map it
            max_runs = pack_leader.get("max_parallelism", max_runs)
            allow_parallel = pack_leader.get("allow_parallel", allow_parallel)
            # Optional: timeout configuration
            timeout_val = pack_leader.get("run_wait_timeout")
            if timeout_val is not None:
                wait_timeout = float(timeout_val)
                
        except ImportError:
            # Python < 3.11 - try tomli
            try:
                import tomli
                
                with open(config_path, "rb") as fh:
                    data = tomli.load(fh)
                
                pack_leader = data.get("pack_leader", {})
                max_runs = pack_leader.get("max_parallelism", max_runs)
                allow_parallel = pack_leader.get("allow_parallel", allow_parallel)
                timeout_val = pack_leader.get("run_wait_timeout")
                if timeout_val is not None:
                    wait_timeout = float(timeout_val)
                    
            except ImportError:
                logger.debug("No TOML library available for config parsing")
            except Exception as e:
                logger.warning("Failed to parse pack_parallelism.toml: %s", e)
        except Exception as e:
            logger.warning("Failed to parse pack_parallelism.toml: %s", e)
    
    config = RunLimiterConfig(
        max_concurrent_runs=max_runs,
        allow_parallel=allow_parallel,
        wait_timeout=wait_timeout,
    )
    
    return RunLimiter(config)


def get_run_limiter() -> RunLimiter:
    """Get the singleton RunLimiter instance (lazily initialized).
    
    Thread-safe. First caller triggers initialization from config.
    Subsequent callers get the same instance.
    """
    global _limiter_instance
    
    if _limiter_instance is None:
        with _limiter_lock:
            if _limiter_instance is None:
                try:
                    _limiter_instance = _build_from_config()
                    logger.info(
                        "RunLimiter initialized: limit=%d, allow_parallel=%s",
                        _limiter_instance.effective_limit,
                        _limiter_instance._config.allow_parallel,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to initialize RunLimiter from config, using defaults: %s",
                        e,
                    )
                    _limiter_instance = RunLimiter()  # Fallback to defaults
    
    return _limiter_instance


def reset_run_limiter_for_tests() -> None:
    """Reset the singleton for testing.
    
    Clears the instance so the next get_run_limiter() call re-initializes.
    """
    global _limiter_instance
    with _limiter_lock:
        _limiter_instance = None
        logger.debug("RunLimiter singleton reset for tests")


def update_run_limiter_config(max_concurrent_runs: int | None = None, 
                               allow_parallel: bool | None = None,
                               wait_timeout: float | None = None) -> None:
    """Update the singleton's config at runtime.
    
    Convenience function that reads current config, updates specified fields,
    and applies the new config atomically.
    
    Used by /pack-parallel command to adjust limit on the fly.
    """
    limiter = get_run_limiter()
    
    current = limiter._config
    new_config = RunLimiterConfig(
        max_concurrent_runs=max_concurrent_runs if max_concurrent_runs is not None else current.max_concurrent_runs,
        allow_parallel=allow_parallel if allow_parallel is not None else current.allow_parallel,
        wait_timeout=wait_timeout if wait_timeout is not None else current.wait_timeout,
    )
    
    limiter.update_config(new_config)
