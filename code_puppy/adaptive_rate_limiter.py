"""Adaptive rate limiter that dynamically adjusts concurrency per model.

When an HTTP 429 (Too Many Requests) is detected for a specific model,
the concurrency limit for that model is reduced.  A background recovery
task gradually restores the limit once the cooldown period has elapsed.

**Circuit Breaker Integration:**

On 429, a circuit breaker enters the **OPEN** state, queuing all new
requests instead of sending them.  After a cooldown period it enters
**HALF_OPEN** and allows one test request.  If the test succeeds the
circuit **CLOSES** and queued requests are gradually released; if the
test triggers another 429 the cooldown is doubled and the circuit
stays OPEN.

The module is a **singleton** – all state lives at module level, matching
the pattern used by ``concurrency_limits.py``.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Circuit state ───────────────────────────────────────────────────────────


class CircuitState(enum.Enum):
    """States of the per-model circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ── Tunable defaults ────────────────────────────────────────────────────────

DEFAULT_MIN_LIMIT: int = 1
DEFAULT_MAX_LIMIT: int = 10
DEFAULT_COOLDOWN_SECONDS: float = 60.0
DEFAULT_RECOVERY_RATE: float = 0.5  # fraction of current limit to add per tick
DEFAULT_INITIAL_LIMIT: int = 10  # starting concurrency for any new model

# Circuit breaker defaults
DEFAULT_CIRCUIT_BREAKER_ENABLED: bool = False
DEFAULT_CIRCUIT_COOLDOWN_SECONDS: float = 10.0
DEFAULT_CIRCUIT_HALF_OPEN_REQUESTS: int = 1
DEFAULT_QUEUE_MAX_SIZE: int = 100
DEFAULT_RELEASE_RATE: float = 1.0  # requests per second


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

    # Circuit breaker fields
    circuit_state: CircuitState = CircuitState.CLOSED
    circuit_opened_time: float = 0.0
    cooldown_multiplier: float = 1.0
    half_open_test_count: int = 0
    request_queue: asyncio.Queue | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.condition is None:
            self.condition = asyncio.Condition()
        if self.request_queue is None:
            self.request_queue = asyncio.Queue(maxsize=DEFAULT_QUEUE_MAX_SIZE)


# ── Singleton state ─────────────────────────────────────────────────────────

_model_states: dict[str, ModelRateLimitState] = {}
_lock: asyncio.Lock | None = None
_recovery_task: asyncio.Task | None = None
_recovery_started: bool = False
_circuit_tasks: set[asyncio.Task] = set()  # track per-model cooldown tasks

# Configurable knobs – may be overridden before first use via configure()
_cfg_min_limit: int = DEFAULT_MIN_LIMIT
_cfg_max_limit: int = DEFAULT_MAX_LIMIT
_cfg_cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
_cfg_recovery_rate: float = DEFAULT_RECOVERY_RATE
_cfg_initial_limit: int = DEFAULT_INITIAL_LIMIT

# Circuit breaker config knobs
_cfg_circuit_breaker_enabled: bool = DEFAULT_CIRCUIT_BREAKER_ENABLED
_cfg_circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS
_cfg_circuit_half_open_requests: int = DEFAULT_CIRCUIT_HALF_OPEN_REQUESTS
_cfg_queue_max_size: int = DEFAULT_QUEUE_MAX_SIZE
_cfg_release_rate: float = DEFAULT_RELEASE_RATE


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


def _cleanup_old_states(max_age_seconds: float = 3600) -> int:
    """Remove states that haven't seen 429s in a while.

    Returns the number of states removed.  States that were never
    rate-limited (``last_429_time is None``) are also eligible for
    cleanup once they exceed the age threshold, keeping the state
    dict from growing unboundedly as new models are encountered.
    """
    now = time.monotonic()
    to_remove = [
        k for k, s in _model_states.items()
        if s.last_429_time is None or (now - s.last_429_time) > max_age_seconds
    ]
    for k in to_remove:
        del _model_states[k]
    if to_remove:
        logger.debug(
            "adaptive_rate_limiter: cleaned up %d stale model state(s)",
            len(to_remove),
        )
    return len(to_remove)


async def _recovery_loop() -> None:
    """Background coroutine that gradually restores rate limits.

    Runs once per ``_cfg_cooldown_seconds``.  For every model that has
    been throttled, it increases the limit by ``_cfg_recovery_rate`` of
    the current value (or +1, whichever is larger), capped at
    ``_cfg_max_limit``.

    Also periodically prunes stale model states to prevent unbounded
    memory growth.
    """
    global _recovery_task
    logger.info("adaptive_rate_limiter: recovery loop started")
    try:
        while True:
            await asyncio.sleep(_cfg_cooldown_seconds)
            lock = _ensure_lock()
            async with lock:
                # Periodically clean up stale model states
                if len(_model_states) > 100:
                    removed = _cleanup_old_states(max_age_seconds=3600)
                    if removed:
                        logger.info(
                            "adaptive_rate_limiter: pruned %d stale state(s), "
                            "%d remaining",
                            removed,
                            len(_model_states),
                        )
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


# ── Circuit breaker internals ───────────────────────────────────────────────


async def _circuit_cooldown_loop(model_name: str, state: ModelRateLimitState) -> None:
    """Background task: wait for cooldown then transition to HALF_OPEN.

    Runs per-model when the circuit opens.  After the cooldown period
    elapses, the circuit transitions to HALF_OPEN which allows test
    requests through.
    """
    effective_cooldown = _cfg_circuit_cooldown_seconds * state.cooldown_multiplier
    logger.info(
        "Circuit OPEN for %r: holding requests for %.1fs "
        "(cooldown ×%.0f)",
        model_name,
        effective_cooldown,
        state.cooldown_multiplier,
    )
    try:
        await asyncio.sleep(effective_cooldown)
        lock = _ensure_lock()
        async with lock:
            # Only transition if still OPEN (might have been force-closed)
            if state.circuit_state == CircuitState.OPEN:
                state.circuit_state = CircuitState.HALF_OPEN
                state.half_open_test_count = 0
                logger.info(
                    "Circuit HALF_OPEN for %r: testing with %d request(s)",
                    model_name,
                    _cfg_circuit_half_open_requests,
                )
                # Wake any waiters that might want to test the circuit
                async with state.condition:
                    state.condition.notify_all()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception(
            "adaptive_rate_limiter: circuit cooldown loop error for %r",
            model_name,
        )


async def _process_queue(model_name: str, state: ModelRateLimitState) -> None:
    """Background task: gradually release queued requests.

    Called when the circuit transitions from HALF_OPEN → CLOSED.
    Releases one request per second (configurable via ``_cfg_release_rate``).
    """
    queue = state.request_queue
    if queue is None:
        return
    released = 0
    total = queue.qsize()
    logger.info(
        "Releasing queued requests (%d pending) for %r at %.1f/s",
        total,
        model_name,
        _cfg_release_rate,
    )
    interval = (1.0 / _cfg_release_rate) if _cfg_release_rate > 0 else 0
    try:
        if total > 0:
            # Batch-notify all waiters so they wake immediately,
            # then rate-limit the actual processing pace.
            async with state.condition:
                for _ in range(total):
                    state.condition.notify_one()
            for i in range(total):
                if interval > 0:
                    await asyncio.sleep(interval)
                logger.info(
                    "Released queued request %d/%d for %r",
                    i + 1,
                    total,
                    model_name,
                )
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception(
            "adaptive_rate_limiter: queue processing error for %r",
            model_name,
        )


async def _notify_waiters(state: ModelRateLimitState) -> None:
    """Wake up waiters that may now be able to acquire a slot."""
    async with state.condition:
        state.condition.notify_all()


# ── Circuit breaker public API ──────────────────────────────────────────────


async def open_circuit(model_name: str) -> None:
    """Transition the circuit breaker for *model_name* to OPEN.

    Queues all new ``acquire_model_slot`` calls until the cooldown
    elapses and the circuit enters HALF_OPEN.
    """
    key = model_name.lower().strip()
    if not key:
        return

    _ensure_recovery_task()
    lock = _ensure_lock()
    async with lock:
        state = _ensure_state(key)
        if state.circuit_state == CircuitState.OPEN:
            # Already open – just increase the cooldown multiplier
            state.cooldown_multiplier = min(state.cooldown_multiplier * 2.0, 64.0)
            logger.warning(
                "Circuit already OPEN for %r, extending cooldown (×%.0f)",
                key,
                state.cooldown_multiplier,
            )
            return

        # 429 during HALF_OPEN → extend cooldown
        if state.circuit_state == CircuitState.HALF_OPEN:
            state.cooldown_multiplier = min(state.cooldown_multiplier * 2.0, 64.0)
            logger.warning(
                "429 during HALF_OPEN for %r, extending cooldown (×%.0f)",
                key,
                state.cooldown_multiplier,
            )
        else:
            state.cooldown_multiplier = 1.0

        state.circuit_state = CircuitState.OPEN
        state.circuit_opened_time = time.monotonic()
        state.half_open_test_count = 0

    # Start the cooldown loop outside the lock
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_circuit_cooldown_loop(key, state))
        _circuit_tasks.add(task)
        task.add_done_callback(_circuit_tasks.discard)
    except RuntimeError:
        pass


async def close_circuit(model_name: str) -> None:
    """Transition the circuit breaker for *model_name* to CLOSED.

    Resets cooldown multiplier and starts releasing queued requests.
    """
    key = model_name.lower().strip()
    if not key:
        return

    lock = _ensure_lock()
    state: ModelRateLimitState | None = None
    was_open: bool = False

    async with lock:
        state = _model_states.get(key)
        if state is None or state.circuit_state == CircuitState.CLOSED:
            return

        was_open = (
            state.circuit_state == CircuitState.HALF_OPEN
            or state.circuit_state == CircuitState.OPEN
        )
        state.circuit_state = CircuitState.CLOSED
        state.circuit_opened_time = 0.0
        state.cooldown_multiplier = 1.0
        state.half_open_test_count = 0
        logger.info("Circuit CLOSED for %r", key)

        # Wake any waiters that were blocked in acquire_model_slot
        async with state.condition:
            state.condition.notify_all()

    # Start queue processing outside the lock
    if was_open and state is not None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_process_queue(key, state))
            _circuit_tasks.add(task)
            task.add_done_callback(_circuit_tasks.discard)
        except RuntimeError:
            pass


async def record_success(model_name: str) -> None:
    """Signal that a successful (non-429) request completed for *model_name*.

    If the circuit is in HALF_OPEN state and the test request succeeded,
    this transitions the circuit to CLOSED and begins releasing queued
    requests.

    In CLOSED state this is a no-op.
    """
    key = model_name.lower().strip()
    if not key:
        return

    lock = _ensure_lock()
    should_close = False
    async with lock:
        state = _model_states.get(key)
        if state is not None and state.circuit_state == CircuitState.HALF_OPEN:
            should_close = True

    if should_close:
        await close_circuit(key)


# ── Public API ──────────────────────────────────────────────────────────────


def configure(
    *,
    min_limit: int | None = None,
    max_limit: int | None = None,
    cooldown_seconds: float | None = None,
    recovery_rate: float | None = None,
    initial_limit: int | None = None,
    # Circuit breaker config
    circuit_breaker_enabled: bool | None = None,
    circuit_cooldown_seconds: float | None = None,
    circuit_half_open_requests: int | None = None,
    queue_max_size: int | None = None,
    release_rate: float | None = None,
) -> None:
    """Override default configuration knobs.

    Must be called *before* any model state is created (i.e. before the
    first ``record_rate_limit`` / ``acquire_model_slot`` call).
    """
    global _cfg_min_limit, _cfg_max_limit, _cfg_cooldown_seconds
    global _cfg_recovery_rate, _cfg_initial_limit
    global _cfg_circuit_breaker_enabled, _cfg_circuit_cooldown_seconds
    global _cfg_circuit_half_open_requests, _cfg_queue_max_size
    global _cfg_release_rate

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

    if circuit_breaker_enabled is not None:
        _cfg_circuit_breaker_enabled = circuit_breaker_enabled
    if circuit_cooldown_seconds is not None:
        _cfg_circuit_cooldown_seconds = max(0.1, circuit_cooldown_seconds)
    if circuit_half_open_requests is not None:
        _cfg_circuit_half_open_requests = max(1, circuit_half_open_requests)
    if queue_max_size is not None:
        _cfg_queue_max_size = max(1, queue_max_size)
    if release_rate is not None:
        _cfg_release_rate = max(0.0, release_rate)


async def record_rate_limit(model_name: str) -> None:
    """Signal that *model_name* just received an HTTP 429 response.

    The concurrency limit for this model is immediately reduced by 50 %
    (but never below ``min_limit``).  The circuit breaker also opens,
    queuing all new requests until the cooldown elapses.
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

    # Open the circuit breaker if enabled (outside the lock)
    if _cfg_circuit_breaker_enabled:
        await open_circuit(key)


async def acquire_model_slot(model_name: str) -> None:
    """Acquire an adaptive concurrency slot for *model_name*.

    Blocks until a slot is available.  The first call for any model
    auto-starts the background recovery task.

    **Circuit breaker behaviour:**

    * **CLOSED** – normal slot acquisition.
    * **OPEN** – the call blocks and is queued until the cooldown
      elapses (circuit → HALF_OPEN → test request → CLOSED).
    * **HALF_OPEN** – the call is allowed only if the test-request
      budget has not been exhausted.
    """
    key = model_name.lower().strip()
    if not key:
        return

    _ensure_recovery_task()
    lock = _ensure_lock()

    # ── Check circuit state (only when circuit breaker enabled) ──────
    if _cfg_circuit_breaker_enabled:
        need_wait_open = False
        need_wait_half_open = False

        async with lock:
            state = _ensure_state(key)

            if state.circuit_state == CircuitState.OPEN:
                queue = state.request_queue
                if queue is not None and queue.full():
                    logger.warning(
                        "Circuit queue full for %r – request will still wait",
                        key,
                    )
                need_wait_open = True

            elif state.circuit_state == CircuitState.HALF_OPEN:
                if state.half_open_test_count >= _cfg_circuit_half_open_requests:
                    need_wait_half_open = True
                else:
                    state.half_open_test_count += 1
                    logger.info(
                        "Circuit HALF_OPEN test request %d/%d for %r",
                        state.half_open_test_count,
                        _cfg_circuit_half_open_requests,
                        key,
                    )

        # Wait OUTSIDE the lock to avoid deadlock with close_circuit()
        if need_wait_open:
            async with state.condition:
                while state.circuit_state == CircuitState.OPEN:
                    await state.condition.wait()

        elif need_wait_half_open:
            async with state.condition:
                while state.circuit_state == CircuitState.HALF_OPEN:
                    await state.condition.wait()

    # ── Normal slot acquisition ─────────────────────────────────────────
    async with lock:
        state = _model_states.get(key)
        if state is None:
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
                "circuit_state": "open",
                "queue_depth": 3,
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
        queue_depth = (
            state.request_queue.qsize() if state.request_queue is not None else 0
        )
        result[model_name] = {
            "current_limit": state.current_limit,
            "active_count": state.active_count,
            "total_429_count": state.total_429_count,
            "last_429_time": state.last_429_time,
            "in_cooldown": in_cooldown,
            "circuit_state": state.circuit_state.value,
            "queue_depth": queue_depth,
        }
    return result


def reset() -> None:
    """Clear **all** per-model state and cancel the recovery task.

    Intended for use in tests and interactive sessions.
    """
    global _model_states, _recovery_task, _recovery_started
    global _cfg_min_limit, _cfg_max_limit, _cfg_cooldown_seconds
    global _cfg_recovery_rate, _cfg_initial_limit
    global _cfg_circuit_breaker_enabled, _cfg_circuit_cooldown_seconds
    global _cfg_circuit_half_open_requests, _cfg_queue_max_size
    global _cfg_release_rate, _circuit_tasks

    if _recovery_task is not None:
        _recovery_task.cancel()
        _recovery_task = None
    for task in _circuit_tasks:
        task.cancel()
    _circuit_tasks.clear()
    _model_states.clear()
    _recovery_started = False

    # Restore defaults
    _cfg_min_limit = DEFAULT_MIN_LIMIT
    _cfg_max_limit = DEFAULT_MAX_LIMIT
    _cfg_cooldown_seconds = DEFAULT_COOLDOWN_SECONDS
    _cfg_recovery_rate = DEFAULT_RECOVERY_RATE
    _cfg_initial_limit = DEFAULT_INITIAL_LIMIT
    _cfg_circuit_breaker_enabled = DEFAULT_CIRCUIT_BREAKER_ENABLED
    _cfg_circuit_cooldown_seconds = DEFAULT_CIRCUIT_COOLDOWN_SECONDS
    _cfg_circuit_half_open_requests = DEFAULT_CIRCUIT_HALF_OPEN_REQUESTS
    _cfg_queue_max_size = DEFAULT_QUEUE_MAX_SIZE
    _cfg_release_rate = DEFAULT_RELEASE_RATE


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
