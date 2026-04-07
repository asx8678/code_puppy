# Phase 3.1 - Holistic Bugs/Performance/Design Review

**Date:** 2026-04-07  
**Scope:** Batch B - Concurrency, Integration, TUI, FFI Surfaces  
**Reviewers:** Husky 🐺

---

## [SEV-HIGH] async_utils.py: Potential Thread Starvation in run_async_sync

**File:** `code_puppy/async_utils.py:21-39`

**Issue:** The `run_async_sync` function creates a dedicated event loop in a background thread but blocks on `future.result()` synchronously. While this prevents blocking the calling thread's event loop, it creates a thread-per-call pattern that can lead to:
1. Thread starvation under high load (unbounded thread creation)
2. Dangling event loops that never get cleaned up (threads are daemon=True but loops stay open)
3. Race condition where `_loop_local.loop` is closed between check and use

**Code:**
```python
def run_async_sync(coro) -> Any:
    if (not hasattr(_loop_local, "loop") or _loop_local.loop is None or _loop_local.loop.is_closed()):
        _loop_local.loop = asyncio.new_event_loop()  # Race here
        _loop_local.thread = threading.Thread(target=_loop_local.loop.run_forever, daemon=True)
        _loop_local.thread.start()
    future = asyncio.run_coroutine_threadsafe(coro, _loop_local.loop)
    return future.result()  # Blocks calling thread
```

**Fix:** 
- Use `concurrent.futures.ThreadPoolExecutor` with a bounded number of threads
- Add proper cleanup logic with `loop.call_soon_threadsafe(loop.stop)` after work completes
- Consider using `anyio` or `asyncio.run_coroutine_threadsafe` with proper shutdown handling

---

## [SEV-HIGH] concurrency_limits.py: Non-Thread-Safe Lazy Initialization

**File:** `code_puppy/concurrency_limits.py:54-56, 68-70, 80-82`

**Issue:** The global semaphores are initialized lazily without any synchronization. Multiple concurrent calls can race:

```python
def _get_file_ops_semaphore() -> asyncio.Semaphore:
    global _file_ops_semaphore
    if _file_ops_semaphore is None:  # Race: multiple threads see None
        config = _read_config()
        _file_ops_semaphore = asyncio.Semaphore(config.file_ops_limit)  # Multiple semaphores created
    return _file_ops_semaphore
```

**Impact:** Under high concurrency, multiple semaphores can be created, breaking the concurrency limit guarantee and potentially causing resource exhaustion.

**Fix:**
- Use `asyncio.Lock()` for async-safe initialization
- Or use `threading.Lock()` for thread-safe initialization
- Consider using `functools.lru_cache` or a proper singleton pattern

---

## [SEV-HIGH] round_robin_model.py: Async/Thread Safety Mismatch

**File:** `code_puppy/round_robin_model.py:105-135`

**Issue:** The `_get_next_model()` method holds a `threading.Lock` while potentially making async calls (via `model_availability_service.select_first_available()`). While the current implementation appears to only read from the service, there's a risk of:
1. Holding a lock across async boundaries (deadlock risk if service becomes async)
2. Threading.Lock doesn't provide async safety - concurrent async tasks can still race

**Code:**
```python
def _get_next_model(self) -> Model:
    with self._lock:  # Threading.Lock held
        n = len(self.models)
        ordered_names = [...]  # Build list
    
    result = model_availability_service.select_first_available(ordered_names)  # Could become async
    
    with self._lock:  # Second lock acquisition - potential race between releases
        ...
```

**Fix:**
- Use `asyncio.Lock` instead of `threading.Lock` for async code
- Consider consolidating into single lock region if ordering matters

---

## [SEV-HIGH] round_robin_model.py: Inconsistent Lock Scope for Index Updates

**File:** `code_puppy/round_robin_model.py:121-135`

**Issue:** The `_current_index` and `_request_count` are updated in a separate `with self._lock` block from where `ordered_names` is computed. This creates a race window where:

1. Thread A computes `ordered_names` starting at index 0
2. Thread B advances `_current_index` to 1
3. Thread A uses `ordered_names` but updates index based on stale `skip_count`

This could lead to double-selecting the same model or skipping models entirely.

**Fix:**
- Use a single lock acquisition for the entire method
- Or use atomic operations for index increment

---

## [SEV-MEDIUM] resilience.py: Circuit Breaker Race on State Transitions

**File:** `code_puppy/resilience.py:101-115`

**Issue:** The CircuitBreaker captures state under lock but releases it before the actual function execution:

```python
async with self._lock:
    if self.state == CircuitState.OPEN:
        # ... check timeout
    was_half_open = self.state == CircuitState.HALF_OPEN  # Captured under lock

try:
    result = func()  # Executed OUTSIDE lock
    if inspect.isawaitable(result):
        result = await result
    await self._on_success(was_half_open)  # State may have changed!
```

Between capturing `was_half_open` and calling `_on_success()`, another concurrent call could change the circuit state, causing incorrect success/failure accounting.

**Fix:**
- Re-check state inside `_on_success()` and `_on_failure()` under lock
- Or pass the actual state transition logic, not just the boolean flag

---

## [SEV-MEDIUM] resilience.py: Non-Reentrant Lock Risk in Circuit Breaker

**File:** `code_puppy/resilience.py:68-134`

**Issue:** The circuit breaker uses `asyncio.Lock()` which is non-reentrant by default. If a function wrapped by the circuit breaker calls another function wrapped by the same circuit breaker, it will deadlock.

**Fix:**
- Document this limitation clearly
- Consider using `asyncio.Semaphore(1)` if reentrancy is needed
- Or use a reentrant lock pattern with owner tracking

---

## [SEV-MEDIUM] request_cache.py: Race Condition in Header-Only Update Path

**File:** `code_puppy/request_cache.py:231-254`

**Issue:** The `get_or_build` method modifies the cache entry in-place during header-only updates:

```python
if entry.headers_hash == headers_hash:
    entry.access_count += 1
    entry.last_accessed = time.time()
    return entry.request  # Cache hit
else:
    # Content matches but headers differ
    new_request = self._copy_request_with_headers(entry.request, headers, client)
    entry.request = new_request  # Modified in-place!
    entry.headers_hash = headers_hash
    entry.created_at = time.time()  # Reset TTL
```

Two concurrent calls with the same content but different headers can:
1. Both see the same entry with matching content_hash
2. Both compute different `new_request` objects
3. Second write overwrites first's `new_request`
4. First caller gets a request object that's no longer in the cache

**Fix:**
- Create new `CachedRequest` entry instead of modifying in-place
- Or use a lock per content_hash

---

## [SEV-MEDIUM] staged_changes.py: Missing Atomicity in apply/reject Operations

**File:** `code_puppy/staged_changes.py` (apply methods not shown in review)

**Issue:** The `StagedChange` dataclass tracks `applied` and `rejected` as separate boolean fields. This allows invalid state combinations (both True, both False after apply). There's no state machine enforcement.

Additionally, the `save_to_disk()` and `load_from_disk()` methods don't use atomic file operations, risking corrupt state files on crash.

**Fix:**
- Use a proper state enum instead of booleans
- Use `code_puppy.persistence.atomic_write_json()` instead of direct `json.dump()`

---

## [SEV-MEDIUM] gemini_model.py: HTTP Client Leak on Connection Errors

**File:** `code_puppy/gemini_model.py:161-175`

**Issue:** The `_get_client()` creates an `httpx.AsyncClient` with 180s timeout, but if the client fails to connect (DNS error, network unreachable), the exception propagates without cleanup. The client object may be left in a half-initialized state.

**Code:**
```python
async def _get_client(self) -> httpx.AsyncClient:
    if self._http_client is None:
        self._http_client = httpx.AsyncClient(timeout=180)  # Could raise
    return self._http_client
```

**Fix:**
- Wrap initialization in try/except and clean up on failure
- Consider using connection pooling limits to prevent resource exhaustion

---

## [SEV-MEDIUM] gemini_model.py: UUID Generation for Tool Calls Not Crypto-Secure

**File:** `code_puppy/gemini_model.py:43-45`

**Issue:** Tool call IDs are generated using `uuid.uuid4()` which is random but not guaranteed unique across time/restarts. For critical path tracking, consider using a counter+entropy approach or ensuring uniqueness at the protocol level.

**Fix:**
- Document that IDs are for correlation only, not security
- Consider using `uuid.uuid1()` with node ID for better uniqueness guarantees

---

## [SEV-MEDIUM] tui/app.py: CancelledError Handling Loses Stack Trace

**File:** `code_puppy/tui/app.py:338-341`

**Issue:** The `_handle_agent_prompt` catches `asyncio.CancelledError` but doesn't preserve or log the cancellation context:

```python
try:
    result, agent_task = await run_prompt_with_attachments(...)
    ...
except asyncio.CancelledError:
    chat.write("[yellow]Task cancelled.[/yellow]")
    return  # Silent swallow - where did cancellation come from?
```

This makes debugging cancellation sources impossible.

**Fix:**
- Log cancellation with stack trace for debugging
- Re-raise `CancelledError` after handling UI update unless truly consumed

---

## [SEV-MEDIUM] tui/message_bridge.py: Potential Message Loss on Bridge Stop

**File:** `code_puppy/tui/message_bridge.py:74-77`

**Issue:** The `stop()` method sets `_running = False` and cancels the task, but there may be messages in flight between the MessageQueue and the TUI that get dropped:

```python
def stop(self) -> None:
    self._running = False
    if self._stop_event:
        self._stop_event.set()
    if self._task:
        self._task.cancel()  # Immediate cancel, messages may be pending
        self._task = None
```

**Fix:**
- Drain the queue before stopping
- Use graceful shutdown with timeout before forced cancel

---

## [SEV-LOW] _core_bridge.py: Potential for Mutable State Bugs in Serialization

**File:** `code_puppy/_core_bridge.py:100-156`

**Issue:** The `serialize_message_for_rust` function modifies message parts in-place during serialization. While the current implementation creates new dicts for each part, the recursive nature and attribute access could potentially modify the original pydantic-ai message objects if they have mutable defaults.

**Fix:**
- Add `copy.deepcopy()` around the message before processing
- Document that the function doesn't mutate inputs

---

## [SEV-LOW] turbo_parse_bridge.py: ImportError Masked as Feature Flag

**File:** `code_puppy/turbo_parse_bridge.py:9-120`

**Issue:** The import failure of `turbo_parse` is silently caught and results in stub implementations. This makes it impossible to distinguish between:
1. Turbo parse not installed (expected fallback)
2. Turbo parse installed but corrupted/failing to import (bug)

**Fix:**
- Log the actual ImportError at debug/warning level
- Expose the error details in `get_turbo_parse_status()` for debugging

---

## [SEV-LOW] persistence.py: TOCTOU in safe_resolve_path

**File:** `code_puppy/persistence.py:24-42`

**Issue:** The `safe_resolve_path` function resolves a path and then checks if it's within `allowed_parent`. However, between the `resolve()` call and the check, a symlink could be modified (Time-of-Check-Time-of-Use race):

```python
resolved = path.resolve(strict=False)  # Follows symlinks
if allowed_parent is not None:
    resolved.relative_to(allowed_parent.resolve())  # Check
```

**Impact:** Low - requires attacker control of filesystem during operation

**Fix:**
- Use `path.absolute()` instead of `resolve()` to avoid symlink following
- Or use `os.path.realpath()` and check atomicity at OS level

---

## [SEV-LOW] workflow_state.py: ContextVar Scope Leak

**File:** `code_puppy/workflow_state.py:133-137`

**Issue:** The `get_workflow_state()` creates a new `WorkflowState` if none exists and sets it in the ContextVar. However, if called from a callback or signal handler, it may inadvertently set state in an unexpected context scope.

**Fix:**
- Require explicit initialization before use
- Log warning when auto-creating state

---

## [SEV-LOW] reopenable_async_client.py: Double Lock Acquisition

**File:** `code_puppy/reopenable_async_client.py:65-71, 82-89`

**Issue:** The class uses both `asyncio.Lock` AND `threading.Lock`:

```python
self._lock = asyncio.Lock()        # For async operations
self._sync_lock = threading.Lock()  # For sync operations
```

This creates a potential for deadlock if a thread holds `_sync_lock` and tries to acquire `_lock` while an async task holds `_lock` and tries to acquire `_sync_lock` (though current code appears safe).

**Fix:**
- Document the lock hierarchy clearly
- Consider using a single lock type (asyncio.Lock can be used from sync code with `asyncio.run_coroutine_threadsafe()`)

---

## Performance Issues

### [PERF-HIGH] async_utils.py: run_async_sync Creates Thread Per Module

**File:** `code_puppy/async_utils.py:27`

**Issue:** Each Python module that calls `run_async_sync` gets its own thread and event loop via thread-local storage. This doesn't scale - with 100+ modules you could have 100+ threads.

**Fix:**
- Use a shared thread pool (e.g., `concurrent.futures.ThreadPoolExecutor(max_workers=4)`)
- Cache and reuse event loops across threads

### [PERF-MEDIUM] request_cache.py: Cache Eviction Uses Linear Scan

**File:** `code_puppy/request_cache.py:167-175`

**Issue:** The LRU eviction scans all entries to find the least recently used:

```python
lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].last_accessed)
```

This is O(n) and becomes expensive as cache grows.

**Fix:**
- Use `collections.OrderedDict` or `functools.lru_cache` for O(1) eviction
- Or maintain a separate heap/priority queue

### [PERF-MEDIUM] round_robin_model.py: Synchronous Availability Check in Async Path

**File:** `code_puppy/round_robin_model.py:114`

**Issue:** `model_availability_service.select_first_available()` appears to be synchronous but is called from async methods. If this becomes slow (e.g., with many models or network-based health checks), it blocks the event loop.

**Fix:**
- Use `await asyncio.to_thread()` to offload if potentially slow
- Or make the service async-native

### [PERF-LOW] gemini_model.py: Schema Sanitization Called Per-Request

**File:** `code_puppy/gemini_model.py:254-257`

**Issue:** The `_sanitize_schema_for_gemini()` function is called for every tool on every request. Schemas are typically static per tool.

**Fix:**
- Cache sanitized schemas in a LRU cache or pre-sanitize at tool registration time

---

## Design Issues

### [DESIGN-MEDIUM] concurrency_limits.py: Mix of Sync and Async APIs

**Issue:** The module exposes both sync (`release_file_ops_slot()`) and async (`acquire_file_ops_slot()`) methods for the same semaphores. This makes it easy to accidentally:
1. Call async `acquire` and sync `release` (won't match)
2. Use sync release from async code (may block)

**Fix:**
- Consolidate on async API only
- Or provide explicit `AsyncLimiter` / `SyncLimiter` classes

### [DESIGN-MEDIUM] staged_changes.py: Global State Without Namespace Isolation

**Issue:** The `_sandbox` global is a single instance. Multiple concurrent sessions (e.g., in API server context) would share the same sandbox, causing changes from one session to leak to another.

**Fix:**
- Add session ID-based isolation
- Or require explicit sandbox instance creation (remove global singleton)

### [DESIGN-MEDIUM] workflow_state.py: No Cleanup of Old States

**Issue:** ContextVars are never explicitly cleaned up. In a long-running process, this could lead to memory growth as each context (per request/task) leaves a WorkflowState behind.

**Fix:**
- Add expiration/TTL for states
- Or explicitly reset state at end of processing

---

## Summary

| Severity | Count | Categories |
|----------|-------|------------|
| SEV-HIGH | 4 | Race conditions, thread safety |
| SEV-MEDIUM | 8 | Resource leaks, state consistency |
| SEV-LOW | 5 | TOCTOU, logging, design |
| PERF-HIGH | 1 | Thread pool exhaustion |
| PERF-MEDIUM | 2 | Cache efficiency, blocking |
| PERF-LOW | 1 | Repeated computation |
| DESIGN-MEDIUM | 3 | API consistency, isolation |

**Most Critical:**
1. `async_utils.py` thread starvation - can deadlock under load
2. `concurrency_limits.py` non-thread-safe init - breaks limits under load
3. `round_robin_model.py` lock scope issues - causes incorrect routing

**Recommended Priority Order:**
1. Fix SEV-HIGH race conditions
2. Add monitoring/metrics to detect cache thrashing
3. Review all async/thread boundaries for consistency
4. Implement resource cleanup for long-running processes
