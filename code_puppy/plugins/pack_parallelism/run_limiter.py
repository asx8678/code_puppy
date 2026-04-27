"""RunLimiter - concurrency gate for agent invocations.

When the Elixir control plane is connected, delegates all counter state
management to `CodePuppyControl.Plugins.PackParallelism` GenServer, which
serializes all mutations through a single BEAM process mailbox. This
eleminates the `_async_active` race condition (HACK(pack-parallelism))
where concurrent Python threads could read stale counter values under
`threading.Lock`.

When the Elixir control plane is NOT connected, falls back to local
asyncio.Semaphore / threading.Semaphore with reentrancy tracking via
contextvars.

Design:
- Elixir GenServer: authoritative state when connected (no race possible)
- asyncio.Semaphore: local fallback for async path (cancellation-safe)
- threading.Semaphore: local fallback for sync path (tests only)
- contextvars.ContextVar: reentrancy depth tracking (always in Python)
- Default wait_timeout = 600s (fail loud, not silent hang)
"""

import asyncio
import contextvars
import logging
import threading
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Task-local reentrancy depth counter.
# ContextVar is the correct primitive: asyncio.create_task() snapshots the
# current context, so child tasks INHERIT the parent's depth. This is exactly
# what we need for nested invoke_agent deadlock prevention — when a parent
# agent holds a slot and spawns a child agent (via create_task), the child
# inherits depth=1 and its own acquire_async() call bypasses the limiter.
_reentrancy_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "run_limiter_reentrancy_depth", default=0
)


def _get_reentrancy_depth() -> int:
    """Get reentrancy depth for the current async context."""
    return _reentrancy_depth.get()


def _set_reentrancy_depth(depth: int) -> None:
    """Set reentrancy depth for the current async context."""
    _reentrancy_depth.set(max(0, depth))


class RunConcurrencyLimitError(Exception):
    """Raised when concurrent run limit is exceeded and caller opted out of waiting."""

    def __init__(
        self, message: str, active: int, limit: int, waited: float | None = None
    ):
        super().__init__(message)
        self.active = active
        self.limit = limit
        self.waited = waited # Seconds waited before giving up (None if non-blocking)


@dataclass(frozen=True)
class RunLimiterConfig:
    """Configuration for RunLimiter.

    - max_concurrent_runs: hard cap (when allow_parallel=True)
    - allow_parallel=False: forces max=1 regardless of max_concurrent_runs
    - wait_timeout: None=forever, float=seconds before raising (default: 600)
    """

    max_concurrent_runs: int = 2
    allow_parallel: bool = True
    wait_timeout: float | None = 600.0 # CHANGED: was None, now 10 minutes default


class RunLimiter:
    """Semaphore-based concurrency limiter for agent invocations.

    Uses independent asyncio.Semaphore (primary async path, cancellation-safe)
    and threading.Semaphore (sync path for tests). They do NOT share state —
    this is a deliberate simplification. Production only uses the async path.

    Features:
    - Native cancellation handling via asyncio.Semaphore
    - Reentrancy bypass via contextvars (nested invoke_agent calls don't deadlock)
    - Configurable wait timeout (default 600s) fails loud instead of hanging forever
    """

    def __init__(self, config: RunLimiterConfig | None = None):
        self._config = config or RunLimiterConfig()
        self._validate_and_fix_config()

        limit = self.effective_limit

        # Observability counters — shared across sync and async for reporting
        self._state_lock = threading.Lock()
        self._async_active = 0
        self._async_waiters = 0
        self._sync_active = 0
        self._sync_waiters = 0

        # Independent gates — each with its own slot count
        self._async_sem = asyncio.Semaphore(limit)
        self._sync_sem = threading.Semaphore(limit)

        # Per-semaphore shrink deficit tracking.
        # When limit is lowered, we drain free slots from semaphores.
        # Slots that couldn't be drained (because they were in use) become
        # "deficit" for that specific semaphore. Each release for that semaphore
        # type absorbs one deficit until it reaches 0, then releases resume.
        self._async_deficit = 0
        self._sync_deficit = 0

    def _validate_and_fix_config(self) -> None:
        """Validate config and replace invalid values with defaults."""
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

    @property
    def effective_limit(self) -> int:
        """Actual cap enforced (respects allow_parallel)."""
        if not self._config.allow_parallel:
            return 1
        return max(1, self._config.max_concurrent_runs)

    @property
    def active_count(self) -> int:
        """Current number of active runs (thread-safe read).

        When Elixir GenServer is connected, queries the authoritative
        GenServer state via `run_limiter.status` for a race-free count.
        Falls back to local counters when disconnected.
        """
        try:
            from code_puppy.plugins.elixir_bridge import is_connected

            if is_connected():
                # Import call_method lazily to avoid import cycles at module load
                from code_puppy.plugins.elixir_bridge import call_method

                try:
                    result = call_method("run_limiter.status", {}, timeout=5.0)
                    return result.get("active", 0)
                except Exception:
                    pass  # Fall through to local count
        except ImportError:
            pass

        with self._state_lock:
            return self._async_active + self._sync_active

    @property
    def waiters_count(self) -> int:
        """Number of callers currently waiting for a slot.

        When Elixir GenServer is connected, queries the authoritative
        GenServer state via `run_limiter.status` for a race-free count.
        Falls back to local counters when disconnected.
        """
        try:
            from code_puppy.plugins.elixir_bridge import is_connected

            if is_connected():
                from code_puppy.plugins.elixir_bridge import call_method

                try:
                    result = call_method("run_limiter.status", {}, timeout=5.0)
                    return result.get("waiters", 0)
                except Exception:
                    pass
        except ImportError:
            pass

        with self._state_lock:
            return self._async_waiters + self._sync_waiters

    async def acquire_async(self, timeout: float | None = None) -> None:
        """Async acquire. Cancellation-safe via native asyncio.Semaphore.

        Reentrant: if the current task already holds a slot,
        this is a no-op bypass (just increments the depth counter).

        When the Elixir control plane is connected, delegates entirely to
        `CodePuppyControl.Plugins.PackParallelism` GenServer, which
        serializes all mutations through a single BEAM process mailbox.
        This eliminates the `_async_active` race condition where concurrent
        Python threads could read stale counter values.

        Falls back to local asyncio.Semaphore when disconnected.
        Reentrancy handling stays in Python regardless of bridge state.

        Args:
            timeout: Max seconds to wait (None = use config default = 600s)

        Raises:
            RunConcurrencyLimitError: On timeout
        """
        # Reentrancy check — bypass if current task already holds a slot
        # Keep reentrancy handling in Python regardless of bridge state
        depth = _get_reentrancy_depth()
        if depth > 0:
            _set_reentrancy_depth(depth + 1)
            logger.debug(
                "RunLimiter: reentrant acquire bypassed (depth now %d)", depth + 1
            )
            return

        # Try Elixir bridge first for authoritative state coordination.
        # The GenServer serializes all mutations, eliminating the
        # HACK(pack-parallelism) race on _async_active.
        try:
            from code_puppy.plugins.elixir_bridge import (
                is_connected,
                call_elixir_run_limiter,
            )

            if is_connected():
                params = {}
                if timeout is not None:
                    params["timeout"] = timeout
                result = await call_elixir_run_limiter(
                    "run_limiter.acquire",
                    params,
                    timeout=timeout if timeout is not None else 30.0,
                )
                if result.get("status") == "ok":
                    _set_reentrancy_depth(1)
                    logger.debug("RunLimiter: slot acquired via Elixir GenServer")
                    return
                if result.get("status") == "timeout":
                    raise RunConcurrencyLimitError(
                        f"Timeout waiting for run slot via Elixir GenServer "
                        f"(limit={self.effective_limit})",
                        active=self.active_count,
                        limit=self.effective_limit,
                        waited=timeout,
                    )
                # Fallback for unexpected bridge responses
                logger.debug(
                    "RunLimiter: unexpected bridge response %s, falling back to local",
                    result,
                )
        except ImportError:
            pass
        except RunConcurrencyLimitError:
            raise
        except Exception as e:
            logger.debug(
                "RunLimiter: bridge acquire failed, falling back to local: %s", e
            )

        # Local fallback: asyncio.Semaphore path (disconnected mode)
        # NOTE(code_puppy-154.3): This local path still has the _async_active
        # counter race (HACK(pack-parallelism)). It is only used when the
        # Elixir control plane is disconnected. When connected, the
        # GenServer path above is authoritative and race-free.
        effective_timeout = (
            timeout if timeout is not None else self._config.wait_timeout
        )

        # For timeout=0, fail immediately if limit reached or semaphore locked
        if effective_timeout == 0:
            if self.active_count >= self.effective_limit or self._async_sem.locked():
                raise RunConcurrencyLimitError(
                    f"Run slot not available (limit={self.effective_limit})",
                    active=self.active_count,
                    limit=self.effective_limit,
                    waited=None,
                )
            # Try quick acquire
            try:
                await asyncio.wait_for(self._async_sem.acquire(), timeout=0.001)
                with self._state_lock:
                    self._async_active += 1
                _set_reentrancy_depth(1)
                return
            except asyncio.TimeoutError:
                raise RunConcurrencyLimitError(
                    f"Run slot not available (limit={self.effective_limit})",
                    active=self.active_count,
                    limit=self.effective_limit,
                    waited=None,
                )

        # Increment waiters counter
        with self._state_lock:
            self._async_waiters += 1

        try:
            if effective_timeout is None:
                await self._async_sem.acquire()
            else:
                try:
                    await asyncio.wait_for(
                        self._async_sem.acquire(),
                        timeout=effective_timeout,
                    )
                except asyncio.TimeoutError:
                    raise RunConcurrencyLimitError(
                        f"Timeout waiting for run slot after {effective_timeout}s "
                        f"(limit={self.effective_limit})",
                        active=self.active_count,
                        limit=self.effective_limit,
                        waited=effective_timeout,
                    ) from None

            # Successfully acquired
            with self._state_lock:
                # Use max(0, ...) to prevent underflow if force_reset zeroed counters
                self._async_waiters = max(0, self._async_waiters - 1)
                self._async_active += 1
            _set_reentrancy_depth(1)
            logger.debug("RunLimiter: slot acquired (depth set to 1)")

        except BaseException:
            # Cancellation, timeout, or any error — clean up waiter counter
            with self._state_lock:
                self._async_waiters = max(0, self._async_waiters - 1)
            raise

    def acquire_sync(
        self, *, blocking: bool = True, timeout: float | None = None
    ) -> bool:
        """Sync acquire using threading.Semaphore.

        NOTE: Sync path does NOT participate in reentrancy bypass.
        Sync is only used from tests; production uses acquire_async.

        Args:
            blocking: If False, return immediately with True/False
            timeout: Max seconds to wait (None = use config default, 0 = no wait)

        Returns:
            True if slot acquired, False if non-blocking and full

        Raises:
            RunConcurrencyLimitError: If timeout expires while waiting
        """
        if not blocking:
            acquired = self._sync_sem.acquire(blocking=False)
            if acquired:
                with self._state_lock:
                    self._sync_active += 1
                return True
            return False

        effective_timeout = (
            timeout if timeout is not None else self._config.wait_timeout
        )

        with self._state_lock:
            self._sync_waiters += 1

        try:
            # threading.Semaphore.acquire returns True on success, False on timeout
            acquired = self._sync_sem.acquire(
                blocking=True,
                timeout=effective_timeout,
            )

            if acquired:
                with self._state_lock:
                    # Use max(0, ...) to prevent underflow if force_reset zeroed counters
                    self._sync_waiters = max(0, self._sync_waiters - 1)
                    self._sync_active += 1
                return True
            else:
                # Timeout
                with self._state_lock:
                    self._sync_waiters = max(0, self._sync_waiters - 1)
                raise RunConcurrencyLimitError(
                    f"Timeout waiting for run slot after {effective_timeout}s "
                    f"(limit={self.effective_limit})",
                    active=self.active_count,
                    limit=self.effective_limit,
                    waited=effective_timeout,
                )
        except BaseException:
            with self._state_lock:
                # Only decrement if we haven't already
                if self._sync_waiters > 0:
                    self._sync_waiters -= 1
            raise

    def _release_slot(
        self,
        active_attr: str,
        deficit_attr: str,
        semaphore: asyncio.Semaphore | threading.Semaphore,
        side: str,
    ) -> bool:
        """Release a slot from the specified side (async or sync).

        Returns True if a slot was released, False if no active runs on this side.
        Must be called with _state_lock held.

        Args:
            active_attr: Attribute name for active count ("_async_active" or "_sync_active")
            deficit_attr: Attribute name for deficit ("_async_deficit" or "_sync_deficit")
            semaphore: The semaphore to release to
            side: "async" or "sync" for logging

        Returns:
            True if slot was found and released, False otherwise
        """
        active_count = getattr(self, active_attr)
        if active_count > 0:
            setattr(self, active_attr, active_count - 1)
            deficit = getattr(self, deficit_attr)
            if deficit > 0:
                # Absorb release into deficit (enforcing lower cap)
                setattr(self, deficit_attr, deficit - 1)
                logger.debug(
                    "RunLimiter: %s release absorbed by deficit (now %d)",
                    side,
                    deficit - 1,
                )
            else:
                # Normal release to semaphore
                semaphore.release()
                logger.debug("RunLimiter: released %s slot to semaphore", side)
            return True
        return False

    def release(self) -> None:
        """Release a slot. Auto-detects async vs sync context.

        Reentrancy-aware: if called from a context where depth > 1,
        only decrements the depth counter without releasing the actual slot.

        When the Elixir control plane is connected, delegates the release
        to the GenServer via `run_limiter.release`, which serializes the
        counter decrement. This eliminates the race where local
        `_async_active` could go stale. Fire-and-forget semantics.

        Falls back to local semaphore release when disconnected.
        Reentrancy handling stays in Python regardless of bridge state.

        CRITICAL FIX: The depth reset to 0 when depth == 1 is hoisted into a
        finally block to ensure it always happens, even in sync-fallback paths
        where no active slot was found on either side (prevents depth leak).
        """
        # Check async reentrancy first
        # Keep reentrancy handling in Python regardless of bridge state
        depth = _get_reentrancy_depth()
        if depth > 1:
            _set_reentrancy_depth(depth - 1)
            logger.debug("RunLimiter: reentrant release (depth now %d)", depth - 1)
            return

        # When Elixir GenServer is connected, delegate release there.
        # The GenServer serializes the decrement, eliminating the
        # HACK(pack-parallelism) race on _async_active.
        try:
            from code_puppy.plugins.elixir_bridge import (
                is_connected,
                call_elixir_run_limiter,
            )

            if is_connected():
                # Fire-and-forget: don't wait for response, ignore errors
                try:
                    asyncio.create_task(
                        call_elixir_run_limiter("run_limiter.release", {}, timeout=1.0)
                    )
                    logger.debug(
                        "RunLimiter: release delegated to Elixir GenServer"
                    )
                except Exception:
                    pass # Ignore errors for fire-and-forget
                # Always reset depth when depth == 1
                _set_reentrancy_depth(0)
                return
        except ImportError:
            pass

        # Local fallback: detect async vs sync context
        in_async = False
        try:
            asyncio.get_running_loop()
            in_async = True
        except RuntimeError:
            in_async = False

        try:
            with self._state_lock:
                if in_async:
                    # Try to release from async side first
                    if self._release_slot(
                        "_async_active", "_async_deficit", self._async_sem, "async"
                    ):
                        return
                    # Fallback: async context but no async active, try sync
                    logger.debug(
                        "RunLimiter.release() from async context, trying sync slot"
                    )
                    if self._release_slot(
                        "_sync_active", "_sync_deficit", self._sync_sem, "sync"
                    ):
                        return
                else:
                    # Try to release from sync side first
                    if self._release_slot(
                        "_sync_active", "_sync_deficit", self._sync_sem, "sync"
                    ):
                        return
                    # Fallback: sync context but no sync active, try async
                    logger.debug(
                        "RunLimiter.release() from sync context, trying async slot"
                    )
                    if self._release_slot(
                        "_async_active", "_async_deficit", self._async_sem, "async"
                    ):
                        return

                # No active runs found on either side
                logger.warning("RunLimiter.release() called with no active runs")
        finally:
            # CRITICAL FIX: Always reset depth to 0 when depth == 1, even if
            # no slot was released (e.g., sync-fallback paths with no active runs).
            # This prevents the depth from getting stuck at 1 and causing bypass
            # on subsequent acquire calls.
            if depth == 1:
                _set_reentrancy_depth(0)
                logger.debug("RunLimiter: depth reset to 0 in finally block")

    @contextmanager
    def slot_sync(self, *, blocking: bool = True, timeout: float | None = None):
        """Context manager for sync callers.

        Usage:
            with limiter.slot_sync():
                run_agent()

        Raises:
            RunConcurrencyLimitError: If timeout expires or non-blocking and full
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

    def _drain_slots(
        self,
        semaphore: threading.Semaphore | asyncio.Semaphore,
        deficit_attr: str,
        excess: int,
        is_async: bool,
    ) -> None:
        """Drain free slots from a semaphore up to the excess amount.

        Returns immediately with slots_drained < excess if not enough free slots.
        The undrainable remainder becomes the semaphore's deficit.

        Must be called with _state_lock held.

        Args:
            semaphore: The semaphore to drain from
            deficit_attr: Attribute name for deficit ("_async_deficit" or "_sync_deficit")
            excess: Maximum number of slots to drain
            is_async: True for asyncio.Semaphore, False for threading.Semaphore
        """
        slots_drained = 0

        if is_async:
            # For asyncio.Semaphore, check _value directly using hasattr
            if hasattr(semaphore, "_value"):
                while slots_drained < excess and semaphore._value > 0:
                    semaphore._value -= 1
                    slots_drained += 1
            # If no _value attribute, we can't drain - all excess becomes deficit
        else:
            # For threading.Semaphore, use acquire(blocking=False)
            while slots_drained < excess:
                if semaphore.acquire(blocking=False):
                    slots_drained += 1
                else:
                    break

        # Undrainable remainder becomes this semaphore's deficit
        remaining_deficit = excess - slots_drained
        if remaining_deficit > 0:
            current_deficit = getattr(self, deficit_attr)
            setattr(self, deficit_attr, current_deficit + remaining_deficit)

        logger.debug(
            "RunLimiter: drained %d %s slots (requested %d, deficit now %d)",
            slots_drained,
            "async" if is_async else "sync",
            excess,
            getattr(self, deficit_attr),
        )

    def _release_net_new_slots_to_async(self, count: int) -> None:
        """Release net-new capacity to async semaphore only.

        Must be called with _state_lock held.

        Args:
            count: Number of slots to release to async semaphore
        """
        for _ in range(count):
            self._async_sem.release()
        logger.debug("RunLimiter: released %d net-new slots to async semaphore", count)

    def _release_net_new_slots_to_sync(self, count: int) -> None:
        """Release net-new capacity to sync semaphore only.

        Must be called with _state_lock held.

        Args:
            count: Number of slots to release to sync semaphore
        """
        for _ in range(count):
            self._sync_sem.release()
        logger.debug("RunLimiter: released %d net-new slots to sync semaphore", count)

    def update_config(self, new_config: RunLimiterConfig) -> None:
        """Atomically swap config with coherent state-machine transitions.

        Per-semaphore deficit tracking ensures correctness across shrink/grow cycles.

        Grow (new > old):
            - For each semaphore: absorb growth into existing deficit first
            - Only release net-new slots (growth - deficit_absorbed)

        Shrink (new < old):
            - For each semaphore: drain free slots up to excess amount
            - Undrainable remainder becomes that semaphore's deficit
            - Deficit absorbs next N releases for that semaphore, enforcing lower cap

        Config mutation happens inside the state lock to prevent races.
        """
        # Validate before applying
        if new_config.max_concurrent_runs < 1:
            logger.warning(
                "Invalid max_concurrent_runs=%d, rejecting config update",
                new_config.max_concurrent_runs,
            )
            return

        with self._state_lock:
            old_limit = self.effective_limit
            self._config = new_config
            new_limit = self.effective_limit

            if new_limit == old_limit:
                return

            logger.info(
                "RunLimiter config updated: limit %d -> %d", old_limit, new_limit
            )

            if new_limit > old_limit:
                # Growing: compute growth PER SIDE independently
                # Each side starts with total growth and absorbs its own deficit only
                total_growth = new_limit - old_limit

                # Async side: absorb only async_deficit, release remainder to async_sem only
                async_growth = total_growth
                if self._async_deficit > 0:
                    async_absorbed = min(async_growth, self._async_deficit)
                    self._async_deficit -= async_absorbed
                    async_growth -= async_absorbed
                    logger.debug(
                        "RunLimiter: async growth absorbed %d into async deficit (now %d)",
                        async_absorbed,
                        self._async_deficit,
                    )
                # Release net-new async capacity (only to async semaphore)
                if async_growth > 0:
                    self._release_net_new_slots_to_async(async_growth)

                # Sync side: absorb only sync_deficit, release remainder to sync_sem only
                sync_growth = total_growth
                if self._sync_deficit > 0:
                    sync_absorbed = min(sync_growth, self._sync_deficit)
                    self._sync_deficit -= sync_absorbed
                    sync_growth -= sync_absorbed
                    logger.debug(
                        "RunLimiter: sync growth absorbed %d into sync deficit (now %d)",
                        sync_absorbed,
                        self._sync_deficit,
                    )
                # Release net-new sync capacity (only to sync semaphore)
                if sync_growth > 0:
                    self._release_net_new_slots_to_sync(sync_growth)

            elif new_limit < old_limit:
                # Shrinking: drain free slots from each semaphore
                excess = old_limit - new_limit

                # Drain from sync semaphore, undrainable becomes sync deficit
                self._drain_slots(
                    self._sync_sem, "_sync_deficit", excess, is_async=False
                )

                # Drain from async semaphore, undrainable becomes async deficit
                self._drain_slots(
                    self._async_sem, "_async_deficit", excess, is_async=True
                )


# ============================================================================
# Singleton management
# ============================================================================

_limiter_instance: RunLimiter | None = None
_limiter_lock = threading.Lock()


def _build_from_config() -> RunLimiter:
    """Build a RunLimiter from <active-home>/pack_parallelism.toml."""

    from code_puppy.config_paths import resolve_path

    config_path = resolve_path("pack_parallelism.toml")

    max_runs = 2
    allow_parallel = True
    wait_timeout: float | None = 600.0 # New default: 10 minutes

    if config_path.exists():
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib # type: ignore[no-redef]

            with open(config_path, "rb") as fh:
                data = tomllib.load(fh)

            pack_leader = data.get("pack_leader", {})
            max_runs = pack_leader.get("max_parallelism", max_runs)
            allow_parallel = pack_leader.get("allow_parallel", allow_parallel)
            timeout_val = pack_leader.get("run_wait_timeout")
            if timeout_val is not None:
                wait_timeout = float(timeout_val)
            elif "run_wait_timeout" in pack_leader:
                wait_timeout = None # Explicitly set to None = forever (advanced users)

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
                        "RunLimiter initialized: limit=%d, allow_parallel=%s, wait_timeout=%s",
                        _limiter_instance.effective_limit,
                        _limiter_instance._config.allow_parallel,
                        _limiter_instance._config.wait_timeout,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to initialize RunLimiter from config, using defaults: %s",
                        e,
                    )
                    _limiter_instance = RunLimiter() # Fallback to defaults

    return _limiter_instance


def reset_run_limiter_for_tests() -> None:
    """Reset the singleton for testing.

    Clears the instance so the next get_run_limiter() call re-initializes.
    Also clears reentrancy depth for the current task.
    """
    global _limiter_instance
    with _limiter_lock:
        _limiter_instance = None
        # Clear current task's reentrancy depth if any
        _set_reentrancy_depth(0)
        logger.debug("RunLimiter singleton reset for tests")


def update_run_limiter_config(
    max_concurrent_runs: int | None = None,
    allow_parallel: bool | None = None,
    wait_timeout: float | None = None,
) -> None:
    """Update the singleton's config at runtime.

    Convenience function that reads current config, updates specified fields,
    and applies the new config atomically.

    Used by /pack-parallel command to adjust limit on the fly.
    """
    limiter = get_run_limiter()

    current = limiter._config
    new_config = RunLimiterConfig(
        max_concurrent_runs=max_concurrent_runs
        if max_concurrent_runs is not None
        else current.max_concurrent_runs,
        allow_parallel=allow_parallel
        if allow_parallel is not None
        else current.allow_parallel,
        wait_timeout=wait_timeout if wait_timeout is not None else current.wait_timeout,
    )

    limiter.update_config(new_config)


def force_reset_limiter_state() -> dict:
    """EMERGENCY: force-reset all counters and recreate semaphores.

    Used by `/pack-parallel reset` to recover from stuck states.

    SAFETY NOTE: This function cancels pending async waiters by cancelling
    their futures in the old semaphore's waiter queue. This prevents the
    over-crediting bug where woken waiters would release against the NEW
    semaphore after acquiring on the OLD one.

    Cancelled waiters will:
    1. Have their acquire() future cancelled (raises CancelledError)
    2. Hit the BaseException handler in acquire_async/acquire_sync
    3. Decrement waiters counter (with max(0, ...) protection)
    4. NOT proceed to release (preventing over-crediting)

    Returns a dict with the pre-reset state for logging.
    """
    global _limiter_instance
    if _limiter_instance is None:
        return {"status": "no_instance"}

    limiter = _limiter_instance
    old_state = {
        "async_active": limiter._async_active,
        "async_waiters": limiter._async_waiters,
        "sync_active": limiter._sync_active,
        "sync_waiters": limiter._sync_waiters,
        "limit": limiter.effective_limit,
        "async_deficit": limiter._async_deficit,
        "sync_deficit": limiter._sync_deficit,
    }

    limit = limiter.effective_limit
    with limiter._state_lock:
        # CRITICAL FIX: Cancel pending async waiters instead of waking them.
        # Waking waiters causes over-crediting because they acquire on the
        # old semaphore but release on the new one after the swap.
        # Cancellation prevents them from ever acquiring, so they never release.
        if hasattr(limiter._async_sem, "_waiters") and limiter._async_sem._waiters:
            for waiter in list(limiter._async_sem._waiters):
                if hasattr(waiter, "cancel") and not waiter.done():
                    waiter.cancel()

        # Reset all counters to 0.
        # The max(0, ...) guards in acquire paths prevent underflow if a
        # waiter is in the middle of decrementing when we zero the counters.
        limiter._async_active = 0
        limiter._sync_active = 0
        limiter._async_waiters = 0
        limiter._sync_waiters = 0
        limiter._async_deficit = 0
        limiter._sync_deficit = 0

        # Recreate semaphores from scratch - old semaphores are discarded.
        # Any waiters still blocked on old semaphores will remain there
        # but won't affect the new semaphore state.
        limiter._async_sem = asyncio.Semaphore(limit)
        limiter._sync_sem = threading.Semaphore(limit)

    logger.warning("RunLimiter force-reset. Previous state: %s", old_state)
    return {"status": "reset", "previous": old_state}
