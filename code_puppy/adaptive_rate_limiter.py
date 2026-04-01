"""Adaptive rate limiter that dynamically adjusts concurrency per model.

When an HTTP 429 (Too Many Requests) is detected for a specific model,
the concurrency limit for that model is reduced.  A background recovery
task gradually restores the limit once the cooldown period has elapsed.

The module is a **singleton** – all state lives at module level, matching
the pattern used by ``concurrency_limits.py``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Tunable defaults ────────────────────────────────────────────────────────

DEFAULT_MIN_LIMIT: int = 1
DEFAULT_MAX_LIMIT: int = 10
DEFAULT_COOLDOWN_SECONDS: float = 60.0
DEFAULT_RECOVERY_RATE: float = 0.5  # fraction of current limit to add per tick
DEFAULT_INITIAL_LIMIT: int = 10  # starting concurrency for any new model


# ── Per-model state ─────────────────────────────────────────────────────────


@dataclass
class ModelRateLimitState:
    """Tracks rate-limit health for a single model.

    Uses an ``asyncio.Condition`` + counter instead of ``Semaphore``
    because Python 3.14 removed ``Semaphore.acquire_nowait()`` and
    ``Semaphore.locked()``, making it impossible to shrink a semaphore
    without risking deadlock.  The condition-based approach lets us
    dynamically lower ``current_limit`` and have waiters observe the
    change immediately.
    """

    current_limit: float
    active_count: int = 0
    last_429_time: float | None = None
    total_429_count: int = 0
    condition: asyncio.Condition = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.condition is None:
            self.condition = asyncio.Condition()


# ── Singleton state ─────────────────────────────────────────────────────────

_model_states: dict[str, ModelRateLimitState] = {}
_lock: asyncio.Lock | None = None
_recovery_task: asyncio.Task | None = None
_recovery_started: bool = False

# Configurable knobs – may be overridden before first use via configure()
_cfg_min_limit: int = DEFAULT_MIN_LIMIT
_cfg_max_limit: int = DEFAULT_MAX_LIMIT
_cfg_cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
_cfg_recovery_rate: float = DEFAULT_RECOVERY_RATE
_cfg_initial_limit: int = DEFAULT_INITIAL_LIMIT


# ── Internal helpers ────────────────────────────────────────────────────────


def _ensure_lock() -> asyncio.Lock:
    """Return the module-level asyncio.Lock, creating it if needed."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _ensure_state(model_name: str) -> ModelRateLimitState:
    """Get or create state for *model_name* (caller must hold ``_lock``)."""
    if model_name not in _model_states:
        _model_states[model_name] = ModelRateLimitState(
            current_limit=float(_cfg_initial_limit),
        )
        logger.debug(
            "adaptive_rate_limiter: initialised model %r with limit %.0f",
            model_name,
            _cfg_initial_limit,
        )
    return _model_states[model_name]


async def _recovery_loop() -> None:
    """Background coroutine that gradually restores rate limits.

    Runs once per ``_cfg_cooldown_seconds``.  For every model that has
    been throttled, it increases the limit by ``_cfg_recovery_rate`` of
    the current value (or +1, whichever is larger), capped at
    ``_cfg_max_limit``.
    """
    global _recovery_task
    logger.info("adaptive_rate_limiter: recovery loop started")
    try:
        while True:
            await asyncio.sleep(_cfg_cooldown_seconds)
            lock = _ensure_lock()
            async with lock:
                now = time.monotonic()
                for model_name, state in _model_states.items():
                    if state.last_429_time is None:
                        continue
                    elapsed = now - state.last_429_time
                    if elapsed < _cfg_cooldown_seconds:
                        continue  # still in cooldown
                    old_limit = state.current_limit
                    increment = max(1.0, state.current_limit * _cfg_recovery_rate)
                    new_limit = min(
                        state.current_limit + increment,
                        float(_cfg_max_limit),
                    )
                    if abs(new_limit - old_limit) < 0.01:
                        continue  # already at max
                    state.current_limit = new_limit
                    # Wake any waiters that may now be unblocked
                    async with state.condition:
                        state.condition.notify_all()
                    logger.info(
                        "adaptive_rate_limiter: %r limit recovered %.1f → %.0f "
                        "(after %.0fs cooldown)",
                        model_name,
                        old_limit,
                        new_limit,
                        elapsed,
                    )
    except asyncio.CancelledError:
        logger.info("adaptive_rate_limiter: recovery loop cancelled")
    except Exception:
        logger.exception("adaptive_rate_limiter: recovery loop error")


def _ensure_recovery_task() -> None:
    """Start the background recovery task if it isn't running yet.

    Safe to call from sync code; the task is scheduled on the running
    event loop.
    """
    global _recovery_task, _recovery_started
    if _recovery_started:
        return
    _recovery_started = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        _recovery_task = loop.create_task(_recovery_loop())
    else:
        # No running loop yet – will be started on next async call.
        _recovery_started = False


# ── Public API ──────────────────────────────────────────────────────────────


def configure(
    *,
    min_limit: int | None = None,
    max_limit: int | None = None,
    cooldown_seconds: float | None = None,
    recovery_rate: float | None = None,
    initial_limit: int | None = None,
) -> None:
    """Override default configuration knobs.

    Must be called *before* any model state is created (i.e. before the
    first ``record_rate_limit`` / ``acquire_model_slot`` call).
    """
    global _cfg_min_limit, _cfg_max_limit, _cfg_cooldown_seconds
    global _cfg_recovery_rate, _cfg_initial_limit

    if min_limit is not None:
        _cfg_min_limit = max(1, min_limit)
    if max_limit is not None:
        _cfg_max_limit = max(_cfg_min_limit, max_limit)
    if cooldown_seconds is not None:
        _cfg_cooldown_seconds = max(1.0, cooldown_seconds)
    if recovery_rate is not None:
        _cfg_recovery_rate = max(0.0, min(1.0, recovery_rate))
    if initial_limit is not None:
        _cfg_initial_limit = max(
            _cfg_min_limit, min(initial_limit, _cfg_max_limit)
        )


async def record_rate_limit(model_name: str) -> None:
    """Signal that *model_name* just received an HTTP 429 response.

    The concurrency limit for this model is immediately reduced by 50 %
    (but never below ``min_limit``).
    """
    key = model_name.lower().strip()
    if not key:
        return

    _ensure_recovery_task()
    lock = _ensure_lock()
    async with lock:
        state = _ensure_state(key)
        state.last_429_time = time.monotonic()
        state.total_429_count += 1
        old_limit = state.current_limit
        new_limit = max(float(_cfg_min_limit), state.current_limit * 0.5)
        state.current_limit = new_limit
        logger.warning(
            "adaptive_rate_limiter: %r rate-limited (429 #%d), "
            "limit reduced %.1f → %.1f",
            key,
            state.total_429_count,
            old_limit,
            new_limit,
        )


async def acquire_model_slot(model_name: str) -> None:
    """Acquire an adaptive concurrency slot for *model_name*.

    Blocks until a slot is available.  The first call for any model
    auto-starts the background recovery task.
    """
    key = model_name.lower().strip()
    if not key:
        return

    _ensure_recovery_task()
    lock = _ensure_lock()
    async with lock:
        state = _ensure_state(key)

    async with state.condition:
        while state.active_count >= int(state.current_limit):
            await state.condition.wait()
        state.active_count += 1


def release_model_slot(model_name: str) -> None:
    """Release an adaptive concurrency slot for *model_name*.

    This is synchronous because it only decrements a counter and
    notifies waiters.  It must be called exactly once for every
    successful ``acquire_model_slot`` call.
    """
    key = model_name.lower().strip()
    if not key:
        return

    state = _model_states.get(key)
    if state is not None:
        # We need to notify waiters from an async context, but release()
        # is sync.  We schedule the notification on the running loop.
        state.active_count = max(0, state.active_count - 1)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify_waiters(state))
        except RuntimeError:
            pass


async def _notify_waiters(state: ModelRateLimitState) -> None:
    """Wake up waiters that may now be able to acquire a slot."""
    async with state.condition:
        state.condition.notify_all()


def get_model_semaphore(model_name: str) -> ModelRateLimitState | None:
    """Return the per-model state, or ``None`` if the model is not tracked.

    .. deprecated::
        Use :func:`get_status` for a clean snapshot, or access
        ``_model_states`` directly in tests.
    """
    key = model_name.lower().strip()
    return _model_states.get(key)


def get_status() -> dict[str, dict[str, Any]]:
    """Return a snapshot of all tracked models and their current limits.

    Example::

        {
            "gpt-4": {
                "current_limit": 5.0,
                "active_count": 2,
                "total_429_count": 2,
                "last_429_time": 1719999999.123,
                "in_cooldown": True,
            },
        }
    """
    now = time.monotonic()
    result: dict[str, dict[str, Any]] = {}
    for model_name, state in _model_states.items():
        in_cooldown = (
            state.last_429_time is not None
            and (now - state.last_429_time) < _cfg_cooldown_seconds
        )
        result[model_name] = {
            "current_limit": state.current_limit,
            "active_count": state.active_count,
            "total_429_count": state.total_429_count,
            "last_429_time": state.last_429_time,
            "in_cooldown": in_cooldown,
        }
    return result


def reset() -> None:
    """Clear **all** per-model state and cancel the recovery task.

    Intended for use in tests and interactive sessions.
    """
    global _model_states, _recovery_task, _recovery_started
    global _cfg_min_limit, _cfg_max_limit, _cfg_cooldown_seconds
    global _cfg_recovery_rate, _cfg_initial_limit

    if _recovery_task is not None:
        _recovery_task.cancel()
        _recovery_task = None
    _model_states.clear()
    _recovery_started = False

    # Restore defaults
    _cfg_min_limit = DEFAULT_MIN_LIMIT
    _cfg_max_limit = DEFAULT_MAX_LIMIT
    _cfg_cooldown_seconds = DEFAULT_COOLDOWN_SECONDS
    _cfg_recovery_rate = DEFAULT_RECOVERY_RATE
    _cfg_initial_limit = DEFAULT_INITIAL_LIMIT


# ── Context manager ─────────────────────────────────────────────────────────


class ModelAwareLimiter:
    """Async context manager that acquires/releases an adaptive slot.

    Usage::

        async with ModelAwareLimiter("gpt-4"):
            await make_api_call(...)
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._state: ModelRateLimitState | None = None

    async def __aenter__(self) -> ModelAwareLimiter:
        await acquire_model_slot(self._model_name)
        key = self._model_name.lower().strip()
        self._state = _model_states.get(key)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if self._state is not None:
            self._state.active_count = max(0, self._state.active_count - 1)
            async with self._state.condition:
                self._state.condition.notify_all()
        return False
