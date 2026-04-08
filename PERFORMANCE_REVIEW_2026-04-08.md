# Python Performance Review — code_puppy

**Date:** 2026-04-08  
**Reviewer:** planning-agent-019d6e (orchestrated via code-scout + 2× python-reviewer)  
**Scope:** 8 hot-path modules in `code_puppy/` (focused review, not exhaustive sweep)  
**Methodology:** Static code review using the user's 10-point performance rubric; existing review docs deduplicated.

---

## 📑 Executive Summary

This review identified **31 new performance findings** across 8 hot-path modules, ranked as:

| Severity | Count | Definition |
|----------|-------|------------|
| **High** | 4 | Measurable user-visible latency OR on every request/event OR O(n²) algorithms |
| **Medium** | 15 | Meaningful CPU/memory savings on hot paths, not individually user-visible |
| **Low** | 12 | Micro-optimizations, code cleanliness, tiny wins |

**Top 4 highest-leverage fixes:**
1. `callbacks._trigger_callbacks_sync` calls `asyncio.run()` on every async callback dispatched from a sync context — creates+destroys a full event loop per call (~50-100μs vs ~5-10μs with persistent loop). **10× improvement possible.**
2. `callbacks.on_stream_event` runs a ContextVar lookup + dict mutation on every streaming token — compounded with locks from `get_callbacks()` this is the hottest path in the codebase.
3. `claude_cache_client._transform_request_body` does unconditional `json.loads` → mutate → `json.dumps` on every Anthropic request body (often 50KB+), even when no transformation is needed. Short-circuit with byte-level checks.
4. `session_storage.save_session` does double pydantic serialization on the DBOS fallback path (the common path in workflow mode) — `dump_json()` → `json.loads()` round-trip adds ~50% serialization cost per autosave.

**Findings already covered in prior review docs** (deduplicated; see `BUGS_PERF_DESIGN_REVIEW.md` and `PYTHON_QUALITY_REVIEW.md`):
- `async_utils.run_async_sync` thread starvation (PERF-HIGH)
- `request_cache` O(n) LRU eviction scan (PERF-MEDIUM)
- `request_cache` header-only update race condition (SEV-MEDIUM)
- `round_robin_model` sync availability check in async path (PERF-MEDIUM)
- `adaptive_rate_limiter` float epsilon magic number / int() truncation (SEV-MEDIUM)
- `callbacks.py` async/sync callback mixing (SEV-MEDIUM) — *this review adds new perf angles*
- `interactive_loop.py` imports inside functions (SEV-MEDIUM) — *this review adds new perf angles*
- `model_factory.py` Zai builder duplication / deep nesting (not perf)

---

## 🔥 High-Severity Findings

### [Finding H1] `asyncio.run()` creates a full event loop per async callback in sync context
- **Location**: `code_puppy/callbacks.py:189-192` — `_trigger_callbacks_sync()`
- **Issue**: When `_trigger_callbacks_sync` encounters an async callback from a non-async thread, it calls `asyncio.run(result)` which creates a *new event loop*, runs the coroutine, and tears it down. This costs ~50-100μs per call and allocates significant internal objects. Every file permission check and some tool dispatches go through this path.
- **Impact**: **High** — Every file permission check, every tool call in some codepaths goes through `_trigger_callbacks_sync`. If any plugin registers an async callback for `file_permission` or `pre_tool_call`, each invocation pays the full loop-creation tax. Can be 10× slower than necessary.
- **Fix**:
  ```python
  # BEFORE (callbacks.py:189-192)
  except RuntimeError:
      # No running loop - we're in a sync/worker thread context
      result = asyncio.run(result)

  # AFTER — use a dedicated per-thread persistent loop
  import threading

  _worker_loop: asyncio.AbstractEventLoop | None = None
  _worker_loop_lock = threading.Lock()

  def _get_or_create_worker_loop() -> asyncio.AbstractEventLoop:
      """Return a persistent event loop for running async callbacks from sync threads."""
      global _worker_loop
      if _worker_loop is not None and not _worker_loop.is_closed():
          return _worker_loop
      with _worker_loop_lock:
          if _worker_loop is None or _worker_loop.is_closed():
              _worker_loop = asyncio.new_event_loop()
          return _worker_loop

  # In _trigger_callbacks_sync:
  except RuntimeError:
      loop = _get_or_create_worker_loop()
      result = loop.run_until_complete(result)
  ```
- **Why**: `loop.run_until_complete()` on a persistent loop costs ~5-10μs vs ~50-100μs for `asyncio.run()` which creates + destroys a loop each time. For plugins that fire async callbacks on every tool call, this is a 10× improvement on hot paths.

---

### [Finding H2] `stream_event` ContextVar lookup + dict mutation per streaming token
- **Location**: `code_puppy/callbacks.py:574-593` — `on_stream_event()`
- **Issue**: Called per streaming token (100s/sec). Each call does: `get_current_run_context()` (ContextVar lookup), `isinstance(event_data, dict)` check, then `.setdefault()` which internally calls `__getitem__` + `__setitem__` even if key already exists. Combined with `_trigger_callbacks()` overhead (lock + TaskGroup from Findings M1 & M3), this is the hottest path in the codebase.
- **Impact**: **High** — At 100+ tokens/sec during streaming responses, per-call overhead compounds. `get_callbacks()` + `count_callbacks()` both acquire the RLock, and `setdefault()` always executes both `__getitem__` + `__setitem__` internally. Each token pays ~5-10μs of pure infrastructure overhead.
- **Fix**:
  ```python
  # BEFORE
  ctx = get_current_run_context()
  if ctx is not None and isinstance(event_data, dict):
      event_data.setdefault("_run_id", ctx.run_id)
      event_data.setdefault("_component_name", ctx.component_name)

  # AFTER — avoid dict mutation when keys already exist
  ctx = get_current_run_context()
  if ctx is not None and isinstance(event_data, dict):
      # setdefault always calls __setitem__ internally even when key exists.
      # Explicit 'in' check short-circuits for the steady state (keys set on first call).
      if "_run_id" not in event_data:
          event_data["_run_id"] = ctx.run_id
      if "_component_name" not in event_data:
          event_data["_component_name"] = ctx.component_name
  ```
- **Why**: `setdefault()` always executes a `__setitem__` path internally. The explicit `in` + conditional set avoids the mutation entirely for the steady state. Combined with Finding M1 (zero-lock snapshot reads), this reduces per-token overhead from ~5-10μs to <1μs.

---

### [Finding H3] `claude_cache_client._transform_request_body` unconditional JSON round-trip per request
- **Location**: `code_puppy/claude_cache_client.py:372-422` — `_transform_request_body()`
- **Issue**: Every `/v1/messages` request body is unconditionally parsed via `json.loads(body.decode())`, mutated, then re-encoded via `json.dumps(data).encode()`. For large request bodies (50KB+ with long conversations), this is ~1-2ms of pure CPU work per request, even when no transformation markers are present.
- **Impact**: **High** — This runs on every Anthropic API request. A 50KB JSON body takes ~0.5-1ms to parse + ~0.5-1ms to re-encode. For a model doing 10 req/s, that's 10-20ms/sec of pure JSON overhead. Worse, on retry paths the body is re-parsed even though it was already transformed.
- **Fix**:
  ```python
  # BEFORE
  @staticmethod
  def _transform_request_body(body: bytes) -> tuple[bytes | None, bool, bool]:
      try:
          data = json.loads(body.decode("utf-8"))
      except Exception:
          return None, False, False
      # ... mutations ...
      return json.dumps(data).encode("utf-8"), tools_modified, cache_modified

  # AFTER — short-circuit if no transformation markers found
  @staticmethod
  def _transform_request_body(body: bytes) -> tuple[bytes | None, bool, bool]:
      # Fast byte-level check: only parse JSON if markers that require
      # transformation are present. memchr scan is ~50ns for 50KB vs
      # json.loads at ~500μs for 50KB.
      needs_tool_prefix = b'"tools"' in body and b'"name"' in body
      needs_cache_control = b'"messages"' in body and b'"cache_control"' not in body
      needs_id_sanitization = b'"tool_use"' in body or b'"tool_result"' in body

      if not (needs_tool_prefix or needs_cache_control or needs_id_sanitization):
          return None, False, False

      try:
          data = json.loads(body.decode("utf-8"))
      except Exception:
          return None, False, False
      # ... rest of mutation logic unchanged ...
  ```
- **Why**: `b'"tools"' in body` is a simple memchr scan (~50ns for 50KB) vs `json.loads` (~500μs for 50KB). When tools aren't present and cache_control is already injected, we skip the entire parse+mutate+re-encode cycle. This short-circuits for retry requests where the body was already transformed, and for simple user messages without tool blocks.

---

### [Finding H4] `session_storage.save_session` double pydantic serialization in DBOS fallback
- **Location**: `code_puppy/session_storage.py:334-358` — `save_session()`
- **Issue**: The fast path `dump_python(history, mode="json")` fails frequently in DBOS workflow mode (per code comment). The fallback does: `ModelMessagesTypeAdapter.dump_json(history)` → `json.loads(json_data)`. This is a full pydantic JSON serialization followed by a full JSON deserialization — roughly 2× the work of the fast path. On a 100-message history, pydantic serialization alone takes 10-50ms.
- **Impact**: **High** — On the autosave hot path, which fires after every agent response. In DBOS mode (common) the fast path fails, so every autosave pays this double-serialization tax. For a 100-message history, this adds 20-100ms per save → user-perceptible pauses during save bursts.
- **Fix**:
  ```python
  # BEFORE
  try:
      serializable_history = ModelMessagesTypeAdapter.dump_python(
          history, mode="json"
      )
  except Exception as e:
      logger.warning(f"Fast path failed: {e}. Falling back...")
      try:
          json_data = ModelMessagesTypeAdapter.dump_json(history)
          serializable_history = json.loads(json_data)
      except Exception as e2:
          serializable_history = history

  # AFTER — use mode="python" for fallback instead of json round-trip
  def _sanitize_for_msgpack(messages: list) -> list:
      """Strip non-serializable objects (coroutines, etc.) from message metadata."""
      import types
      sanitized = []
      for msg in messages:
          if isinstance(msg, dict):
              clean = {
                  k: v for k, v in msg.items()
                  if not isinstance(v, (types.CoroutineType, types.GeneratorType))
              }
              if 'metadata' in clean and isinstance(clean['metadata'], dict):
                  clean['metadata'] = {
                      k: v for k, v in clean['metadata'].items()
                      if not isinstance(v, (types.CoroutineType, types.GeneratorType))
                  }
              sanitized.append(clean)
          else:
              sanitized.append(msg)
      return sanitized

  try:
      serializable_history = ModelMessagesTypeAdapter.dump_python(
          history, mode="json"
      )
  except Exception as e:
      logger.warning(f"Fast path failed: {e}. Sanitizing...")
      try:
          serializable_history = _sanitize_for_msgpack(
              ModelMessagesTypeAdapter.dump_python(history, mode="python")
          )
      except Exception as e2:
          logger.warning(f"Sanitization failed: {e2}. Using original.")
          serializable_history = history
  ```
- **Why**: `dump_python(mode="python")` skips JSON-specific coercion rules and returns native Python types directly — msgpack can handle these natively. The sanitization is a single O(n) pass. Eliminates the `dump_json → json.loads` round-trip, saving ~50% of serialization time on the fallback path (~10-50ms per save on a 100-message history).

---

## ⚙️ Medium-Severity Findings

### [Finding M1] `get_callbacks()` acquires RLock on every event dispatch
- **Location**: `code_puppy/callbacks.py:148-153` — `get_callbacks()`
- **Issue**: Every callback dispatch (streaming tokens, tool calls, file ops) acquires a `threading.RLock` just to snapshot a list that almost never changes after startup. Lock acquisition is ~1-2μs uncontended but grows to 10-50μs under contention. Worse, `_trigger_callbacks`/`_trigger_callbacks_sync` call `count_callbacks()` first (another lock), *then* `get_callbacks()` (another lock) — 2-3 lock round-trips per event.
- **Impact**: **Medium** — Lock is uncontended 99% of the time (writes happen at startup), but `get_callbacks` is called per-dispatch. Compounds with Finding H2 on streaming token paths.
- **Fix**:
  ```python
  # BEFORE
  _callbacks_lock = threading.RLock()

  def get_callbacks(phase: PhaseType) -> tuple[CallbackFunc, ...]:
      with _callbacks_lock:
          return tuple(_callbacks.get(phase, ()))

  # AFTER — copy-on-write with a module-level frozen snapshot
  _callbacks_lock = threading.Lock()
  _callbacks: dict[PhaseType, list[CallbackFunc]] = {...}
  # Frozen snapshot rebuilt only on mutation
  _callbacks_snapshot: dict[PhaseType, tuple[CallbackFunc, ...]] = {
      phase: () for phase in _callbacks
  }

  def _rebuild_snapshot() -> None:
      """Rebuild the read-only snapshot. Caller must hold _callbacks_lock."""
      global _callbacks_snapshot
      _callbacks_snapshot = {
          phase: tuple(funcs) for phase, funcs in _callbacks.items()
      }

  def get_callbacks(phase: PhaseType) -> tuple[CallbackFunc, ...]:
      # Zero-lock read: snapshot dict reads are GIL-atomic
      return _callbacks_snapshot.get(phase, ())

  # In register_callback / unregister_callback / clear_callbacks:
  # call _rebuild_snapshot() while holding _callbacks_lock after mutation
  ```
- **Why**: Eliminates lock acquisition on the read path entirely. Dict reads are GIL-atomic in CPython. Writes are rare (startup only); reads happen 100s-1000s of times per second during streaming. This is the single highest-leverage change since it benefits every dispatch path.

---

### [Finding M2] `TaskGroup` overhead for zero-or-one callback dispatch
- **Location**: `code_puppy/callbacks.py:247-253` — `_trigger_callbacks()`
- **Issue**: `async with asyncio.TaskGroup()` is unconditionally created even when callbacks has exactly one entry. TaskGroup has non-trivial setup (~10-20μs): exception handler, task set, cleanup callbacks.
- **Impact**: **Medium** — Called per streaming event, per tool call, per agent start/end. For the common case of 0-1 callbacks, a direct await is cheaper.
- **Fix**:
  ```python
  # BEFORE
  async with asyncio.TaskGroup() as tg:
      tasks = [tg.create_task(_run_one(cb)) for cb in callbacks]
  results = [t.result() for t in tasks]

  # AFTER
  if len(callbacks) == 1:
      results = [await _run_one(callbacks[0])]
  else:
      async with asyncio.TaskGroup() as tg:
          tasks = [tg.create_task(_run_one(cb)) for cb in callbacks]
      results = [t.result() for t in tasks]
  ```
- **Why**: Eliminates TaskGroup setup/teardown for the single-callback fast path (the dominant case). Saves ~10-20μs per dispatch on hot paths like `stream_event`.

---

### [Finding M3] `release_model_slot` creates `asyncio.Task` unconditionally
- **Location**: `code_puppy/adaptive_rate_limiter.py:604-626` — `release_model_slot()`
- **Issue**: On every slot release, `loop.create_task(_notify_waiters(state))` is called even when `active_count` was well below the limit (no one waiting). Each `create_task` allocates a Task object (~1-2μs + GC pressure).
- **Impact**: **Medium** — Called once per API request completion. With 10 concurrent models at 10 req/s each, that's 100 wasted tasks/sec.
- **Fix**:
  ```python
  # BEFORE
  def release_model_slot(model_name: str) -> None:
      state = _state.model_states.get(key)
      if state is not None:
          state.active_count = max(0, state.active_count - 1)
          try:
              loop = asyncio.get_running_loop()
              loop.create_task(_notify_waiters(state))
          except RuntimeError:
              pass

  # AFTER — skip task creation when no one can be waiting
  def release_model_slot(model_name: str) -> None:
      key = _normalize_model_name(model_name)
      if key is None:
          return
      state = _state.model_states.get(key)
      if state is None:
          return
      old_count = state.active_count
      state.active_count = max(0, old_count - 1)
      # Only notify if we were at/above limit (someone might be waiting)
      if old_count >= math.ceil(state.current_limit):
          try:
              loop = asyncio.get_running_loop()
              loop.create_task(_notify_waiters(state))
          except RuntimeError:
              pass
  ```
- **Why**: Avoids Task object creation when `active_count` was below `current_limit` — meaning no `acquire_model_slot` caller can be blocked. This is the steady-state case (most requests complete without hitting the limit).

---

### [Finding M4] `acquire_model_slot` takes global lock on every request
- **Location**: `code_puppy/adaptive_rate_limiter.py:484-601` — `acquire_model_slot()`
- **Issue**: The function acquires `_state.lock` (global) to look up the model state, releases it, then acquires `state.condition`. 2 lock acquisitions per request; the global lock is the bottleneck since all models share it.
- **Impact**: **Medium** — Every API request pays 2 lock acquisitions. Global lock under contention becomes a serialization point.
- **Fix**:
  ```python
  # BEFORE
  async with lock:
      state = _state.model_states.get(key)
      if state is None:
          state = _ensure_state(key)
  async with state.condition:
      while state.active_count >= math.ceil(state.current_limit):
          await asyncio.wait_for(state.condition.wait(), timeout=timeout)
      state.active_count += 1

  # AFTER — double-checked locking, skip global lock when state exists
  state = _state.model_states.get(key)
  if state is None:
      async with lock:
          state = _state.model_states.get(key)
          if state is None:
              state = _ensure_state(key)

  async with state.condition:
      while state.active_count >= math.ceil(state.current_limit):
          await asyncio.wait_for(state.condition.wait(), timeout=timeout)
      state.active_count += 1
  ```
- **Why**: After the first request for a model, `state` is cached in `_state.model_states` and rarely removed. The `async with lock` is pure overhead on the hot path. Double-checked locking avoids the global lock on 99%+ of calls.

---

### [Finding M5] `_compute_headers_hash` sorts + double encodes per header
- **Location**: `code_puppy/request_cache.py:136-157` — `_compute_headers_hash()`
- **Issue**: Sorts all headers every call (O(n log n)); for each header, calls `.encode()` twice (key + value), allocating bytes objects. Also has a duplicate `"content-length"` in the exclusion tuple (typo, same check twice). `digest_size=32` is overkill for a cache key.
- **Impact**: **Medium** — Called on every `get_or_build()`. For requests with ~10 headers, that's 20 `.encode()` allocations + a sort per call.
- **Fix**:
  ```python
  # BEFORE
  _EXCLUDED = ("content-length", "content-length")  # duplicate!
  hasher = hashlib.blake2b(digest_size=32)
  normalized = sorted(
      (k.lower(), str(v).lower())
      for k, v in headers.items()
      if k.lower() not in _EXCLUDED
  )
  for key, value in normalized:
      hasher.update(key.encode())
      hasher.update(value.encode())

  # AFTER
  _EXCLUDED_HEADERS = frozenset({"content-length"})

  def _compute_headers_hash(self, headers: dict[str, str]) -> str:
      hasher = hashlib.blake2b(digest_size=16)  # 32 hex chars, plenty for cache key
      for key in sorted(headers):
          lkey = key.lower()
          if lkey in _EXCLUDED_HEADERS:
              continue
          hasher.update(lkey.encode())
          hasher.update(str(headers[key]).lower().encode())
      return hasher.hexdigest()
  ```
- **Why**: `digest_size=16` halves hash computation; fixes the duplicate exclusion typo; uses `frozenset` for O(1) exclusion lookup; sorts just keys (not tuples) which is faster for small dicts.

---

### [Finding M6] `_sanitize_tool_ids_in_payload` triple-nested loop scans all messages
- **Location**: `code_puppy/claude_cache_client.py:71-111` — `_sanitize_tool_ids_in_payload()`
- **Issue**: For every request, scans every message → every content block → every block type. For a 100-message conversation with 5 blocks each, that's 500 iterations + isinstance checks, even when no tool blocks exist.
- **Impact**: **Medium** — Iteration cost scales linearly with conversation length. Combines with H3 (JSON parse) to amplify cost for long conversations.
- **Fix**:
  ```python
  # AFTER — short-circuit via byte check before calling (integrate with H3 fix)
  # In _transform_request_body, gate the sanitization:
  if b'"tool_use"' not in body and b'"tool_result"' not in body:
      ids_modified = False
  else:
      ids_modified = _sanitize_tool_ids_in_payload(data)
  ```
- **Why**: The `b'"tool_use"' not in body` check is ~50ns and eliminates the 500-iteration scan for requests without tool blocks (majority of user messages in a conversation).

---

### [Finding M7] `_get_jwt_age_seconds` has broken prefix-based cache + redundant with existing lru_cache
- **Location**: `code_puppy/claude_cache_client.py:248-289` — `_get_jwt_age_seconds()`
- **Issue**: Instance-level cache uses `token[:64]` as the key, but JWTs commonly share a 64-char prefix (header is deterministic). Also, the module already has an `@lru_cache(maxsize=16)` on `_get_jwt_iat()` that does the correct thing. The instance cache is redundant and potentially incorrect.
- **Impact**: **Medium** — On cache miss, `_jwt.decode()` runs (~20-50μs). Prefix collisions cause stale age calculations which can delay or skip token refresh.
- **Fix**:
  ```python
  # BEFORE
  token_prefix = token[:64]
  if self._cached_jwt_iat is not None:
      cached_prefix, cached_iat = self._cached_jwt_iat
      if cached_prefix == token_prefix:
          return time.time() - cached_iat
  # ... fallback to full validation ...

  # AFTER — use the existing module-level lru_cache
  def _get_jwt_age_seconds(self, token: str | None) -> float | None:
      if not token:
          return None
      iat = _get_jwt_iat(token)  # already @lru_cache(maxsize=16)
      if iat <= 0:
          return None
      return time.time() - iat
  ```
- **Why**: The module-level `_get_jwt_iat()` already caches by full token string. Removes a buggy instance cache and simplifies the code.

---

### [Finding M8] `send()` extracts body bytes multiple times per request
- **Location**: `code_puppy/claude_cache_client.py:488-623` — `send()`
- **Issue**: Calls `self._extract_body_bytes(request)` up to 3 times per request: for token refresh, for Claude Code transformations, and for auth error retry. Each call triggers property access + try/except.
- **Impact**: **Medium** — Body extraction isn't free. For large bodies, repeated access is wasteful.
- **Fix**:
  ```python
  # AFTER — extract once at top of send(), reuse throughout
  async def send(self, request, *args, **kwargs):
      body_bytes = self._extract_body_bytes(request)  # extract ONCE
      # ... pass body_bytes to all downstream helpers ...
  ```
- **Why**: Eliminates 2 redundant `_extract_body_bytes` calls per request. Each call involves try/except + hasattr + getattr.

---

### [Finding M9] `http_utils._resolve_proxy_config` re-reads 8 env vars per client creation
- **Location**: `code_puppy/http_utils.py:39-88` — `_resolve_proxy_config()`
- **Issue**: Every call to `create_async_client()` invokes `_resolve_proxy_config()`, which calls `os.environ.get()` up to 8 times, `get_cert_bundle_path()` (another env lookup + `os.path.exists()`), and `get_http2()`. These values almost never change during a session.
- **Impact**: **Medium** — Called per model-switch via model_factory builders. 8 dict lookups + 1 filesystem stat = ~microseconds. Free to cache.
- **Fix**:
  ```python
  # AFTER — 5s TTL cache
  import time as _time

  _proxy_config_cache: tuple[float, ProxyConfig] | None = None
  _PROXY_CONFIG_TTL = 5.0

  def _resolve_proxy_config(verify: bool | str | None = None) -> ProxyConfig:
      global _proxy_config_cache
      if verify is None and _proxy_config_cache is not None:
          cached_at, cached = _proxy_config_cache
          if _time.monotonic() - cached_at < _PROXY_CONFIG_TTL:
              return cached
      # ... existing logic ...
      result = ProxyConfig(...)
      if verify is None:
          _proxy_config_cache = (_time.monotonic(), result)
      return result
  ```
- **Why**: Eliminates 8 dict lookups + 1 filesystem stat per client creation for the common case. 5s TTL handles mid-session proxy toggling.

---

### [Finding M10] Fire-and-forget asyncio tasks with no reference retention
- **Location**: `code_puppy/http_utils.py:98-114` — `_notify_adaptive_rate_limiter()` (and `_notify_success()`)
- **Issue**: `loop.create_task(record_rate_limit(model_name))` creates a task that's never stored. Python 3.12+ emits `Task was destroyed but it is pending!` warnings when unreferenced tasks are GC'd. Under load, these notifications can be silently dropped.
- **Impact**: **Medium** — Correctness/rate-limiter effectiveness. Lost notifications mean the adaptive limiter can't converge. Also clutters stderr with asyncio warnings.
- **Fix**:
  ```python
  # BEFORE
  loop = asyncio.get_running_loop()
  loop.create_task(record_rate_limit(model_name))

  # AFTER — retain task reference via done callback
  loop = asyncio.get_running_loop()
  task = loop.create_task(record_rate_limit(model_name))
  task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
  ```
- **Why**: `add_done_callback` prevents GC of the task until it completes, and silently consumes any exception (fire-and-forget semantics). Apply the same pattern to `_notify_success()`.

---

### [Finding M11] Retry backoff lacks jitter — thundering herd on shared rate limits
- **Location**: `code_puppy/http_utils.py:209-215` — `RetryingAsyncClient.send()`
- **Issue**: Wait times are deterministic: Cerebras path is `3.0 * 2**attempt`, default path is `2**attempt`. No jitter. If multiple Code Puppy instances hit the same provider simultaneously, all retry at the exact same moment, amplifying the 429 cycle.
- **Impact**: **Medium** — Single-user: fine. Multi-instance / team sharing a rate-limited API key: all instances retry in lockstep, defeating the backoff. Adding jitter is essentially free.
- **Fix**:
  ```python
  # AFTER — AWS-style full jitter
  import random
  _jitter = random.random

  if self._ignore_retry_headers:
      wait_time = 3.0 * (2**attempt) * (0.5 + _jitter())
  else:
      wait_time = 2**attempt * (0.5 + _jitter())
  ```
- **Why**: Full jitter (0.5× to 1.5× base) is the AWS-recommended strategy for distributed retry. Zero-cost change for single-user, significant win for multi-instance deployments.

---

### [Finding M12] `_deserialize_messages` runs full pydantic validation on load
- **Location**: `code_puppy/session_storage.py:99-112` — `_deserialize_messages()`
- **Issue**: `ModelMessagesTypeAdapter.validate_python(raw_messages)` does full pydantic model construction for every message. On a 100-message history, ~50-200ms. The data was already validated on save AND integrity-checked via HMAC.
- **Impact**: **Medium** — Once per session load. Noticeable pause on `/autosave_load` for large histories (200+ messages).
- **Fix**:
  ```python
  # AFTER — trust the HMAC-verified data, let pydantic-ai lazy-validate
  # (verify that Agent.set_message_history accepts raw dicts first)
  return raw_messages  # Already validated on save; HMAC verifies integrity
  ```
- **Why**: If the data was serialized by pydantic and integrity-checked via HMAC, re-validating on load is redundant work. Reduces 100-message load from ~100ms to ~5ms. *Caveat: verify pydantic-ai's `Agent.set_message_history()` accepts raw dicts before applying.*

---

### [Finding M13] `load_config` runs 6 `stat()` syscalls even when cached
- **Location**: `code_puppy/model_factory.py:395-430` — `ModelFactory.load_config()`
- **Issue**: The mtime-based cache invalidation calls `p.stat().st_mtime` on 6 source files on *every* call to `load_config()`, even when the cache is valid. That's 6 syscalls (~1-5μs each on macOS/APFS) per model lookup.
- **Impact**: **Medium** — A single model switch triggers both `get_model()` and `make_model_settings()`, each calling `load_config()`. That's 12 syscalls per model switch.
- **Fix**:
  ```python
  # AFTER — 1s TTL on mtime check, config files change rarely
  import time as _time

  _config_cache_timestamp: float = 0.0
  _CONFIG_CACHE_TTL = 1.0

  def load_config() -> dict[str, Any]:
      global _model_config_cache, _model_config_mtimes, _config_cache_timestamp

      # Fast path: skip stat() calls if cache was validated < 1s ago
      if _model_config_cache is not None and _time.monotonic() - _config_cache_timestamp < _CONFIG_CACHE_TTL:
          return MappingProxyType(_model_config_cache)

      # ... existing stat() logic ...
      _config_cache_timestamp = _time.monotonic()
      return MappingProxyType(_model_config_cache)
  ```
- **Why**: Reduces stat() calls from 6 per `load_config()` to 0 for 1 second after first validation. Config files change rarely (user edits). The 1s TTL catches manual edits.

---

### [Finding M14] `make_model_settings()` not memoized despite deterministic output
- **Location**: `code_puppy/model_factory.py:145-270` — `make_model_settings()`
- **Issue**: For a given `(model_name, max_tokens)`, `make_model_settings()` returns a deterministic result. It's called per model creation with no caching. Internal calls to `load_config()` are expensive (see M13).
- **Impact**: **Medium** — Combined with M13, every model switch pays unnecessary config-loading overhead.
- **Fix**:
  ```python
  from functools import lru_cache

  @lru_cache(maxsize=32)
  def _cached_make_model_settings(model_name: str, max_tokens: int | None) -> ModelSettings:
      # ... existing make_model_settings body ...
      return model_settings

  def make_model_settings(model_name: str, max_tokens: int | None = None) -> ModelSettings:
      return _cached_make_model_settings(model_name, max_tokens)
  ```
- **Why**: `lru_cache(maxsize=32)` covers all models. Cache hits return in ~100ns. Cache invalidates on process restart (which is when config changes in practice).

---

### [Finding M15] Wiggum loop does full autosave finalize per reloop
- **Location**: `code_puppy/interactive_loop.py:487-491` — wiggum loop inside `interactive_mode()`
- **Issue**: Each wiggum iteration calls `finalize_autosave_session()` (file I/O: msgpack + HMAC + file write + JSON metadata) and `current_agent.clear_message_history()`. At ~10ms per save × 100 loops = 1 second of wasted I/O, since the data is immediately cleared.
- **Impact**: **Medium** — Depends on wiggum usage. When enabled, each iteration wastes serialization work on data about to be discarded.
- **Fix**:
  ```python
  # AFTER — skip autosave since we're about to clear anyway
  while is_wiggum_active():
      ...
      # Don't autosave — the history is immediately discarded
      from code_puppy.config import set_current_autosave_session_name, generate_autosave_session_name
      new_session_id = set_current_autosave_session_name(generate_autosave_session_name())
      current_agent.clear_message_history()
      ...
      await asyncio.sleep(0.2)  # Reduced from 0.5s
  ```
- **Why**: Eliminates full serialization + file write + HMAC per wiggum iteration when the data is immediately discarded. Saves ~10ms per iteration on I/O.

---

## 🔹 Low-Severity Findings

### [Finding L1] `register_callback` uses O(n) list membership for dedup
- **Location**: `code_puppy/callbacks.py:101` — `register_callback()`
- **Issue**: `func in _callbacks[phase]` is O(n) list scan.
- **Impact**: **Low** — Registration happens at startup, not hot path.
- **Fix**: Track registrations in a companion `set[int]` keyed by `id(func)`.
- **Why**: O(1) vs O(n). Correctness by principle.

### [Finding L2] `_normalize_model_name` lru_cache is counterproductive
- **Location**: `code_puppy/adaptive_rate_limiter.py:189-199`
- **Issue**: `@lru_cache(maxsize=128)` wraps a function doing just `.lower().strip()`. The cache lookup (~100-300ns) costs more than the operation itself (~50ns) for the typical case of 3-10 unique model names.
- **Impact**: **Low** — ~0.2μs/call loss.
- **Fix**: Remove the `@lru_cache` decorator.
- **Why**: `str.lower().strip()` is already fast; caching adds overhead without meaningful benefit.

### [Finding L3] `_recovery_loop` scans all model states every 60s unconditionally
- **Location**: `code_puppy/adaptive_rate_limiter.py:231-300`
- **Issue**: Wakes every 60s and iterates ALL `model_states`, even if none have been rate-limited. Holds `_state.lock` during iteration.
- **Impact**: **Low** — Runs every 60s. Small absolute cost but blocks `acquire_model_slot` during iteration.
- **Fix**: Track throttled models in a dedicated `set[str]`; iterate only that set.
- **Why**: Reduces lock-hold iteration from O(all models) to O(throttled models).

### [Finding L4] `_recovery_loop` mutates current_limit outside lock (TOCTOU)
- **Location**: `code_puppy/adaptive_rate_limiter.py:276-284`
- **Issue**: Recovery items collected under `_state.lock`, but `st.current_limit = new_limit` applied outside the lock. Concurrent `record_rate_limit` can lower the limit between snapshot and apply.
- **Impact**: **Low** — Correctness concern. Recovery can overwrite a just-lowered limit.
- **Fix**: Apply under `state.condition` lock with monotonic-increase guard (`if new_limit > st.current_limit`).
- **Why**: Prevents recovery from negating fresh rate-limit responses.

### [Finding L5] `request_cache` probabilistic eviction allocates bytes per call
- **Location**: `code_puppy/request_cache.py:200-202`
- **Issue**: `hash(content_hash.encode()) % 100 == 0` allocates bytes unnecessarily, and Python string `hash()` has non-uniform distribution on hex strings.
- **Impact**: **Low** — Per cache miss only.
- **Fix**: Replace with a deterministic counter (`self._call_counter += 1; if self._call_counter % 100 == 0: ...`).
- **Why**: Zero-allocation, uniform distribution, simpler.

### [Finding L6] `CachedRequest` dataclass missing `__slots__`
- **Location**: `code_puppy/request_cache.py:60-75`
- **Issue**: No `__slots__` — each instance carries a `__dict__` (~200 bytes overhead).
- **Impact**: **Low** — ~25KB total overhead at max cache size.
- **Fix**: Add `@dataclass(slots=True)`.
- **Why**: Standard practice for frequently-instantiated dataclasses; ~2× faster attribute access.

### [Finding L7] Cerebras backoff off-by-one / intent unclear
- **Location**: `code_puppy/http_utils.py:210`
- **Issue**: `3.0 * (2**attempt)` with `attempt` starting at 0 gives 3, 6, 12, 24, 48, 96 — the final value hits the 60s cap. Not a perf bug, just unclear intent.
- **Impact**: **Low** — Documentation issue.
- **Fix**: No code change needed; add a comment documenting the sequence.
- **Why**: Clarity.

### [Finding L8] `save_session` O(n) token recount when caller forgets `precomputed_total`
- **Location**: `code_puppy/session_storage.py:379-383`
- **Issue**: `sum(token_estimator(message) for message in history)` is O(n) when `precomputed_total` is None. Main autosave path passes it; defensive callers may not.
- **Impact**: **Low** — Only affects non-main callers.
- **Fix**: Make the argument required or log a warning when computed on-the-fly.
- **Why**: Defensive design making the cost visible.

### [Finding L9] Imports inside `interactive_mode` main loop
- **Location**: `code_puppy/interactive_loop.py:283-520`
- **Issue**: ~15-20 `from code_puppy.X import Y` statements inside the while loop body. Each costs ~100ns (sys.modules lookup + attribute access) — ~1.5-2μs per iteration.
- **Impact**: **Low** — Negligible vs. network I/O. Real issue is import-lock contention potential.
- **Fix**: Hoist unconditional imports to the top of `interactive_mode()`; keep circular-import-guarded imports where they are.
- **Why**: Free code hygiene; eliminates ~15 dict lookups per iteration.

### [Finding L10] `is_quota_exception` linear keyword scan
- **Location**: `code_puppy/model_factory.py:589-648`
- **Issue**: `any(kw in msg for kw in _TERMINAL_KEYWORDS)` runs 8 separate substring searches over `str(exc).lower()`. For large exception messages, this adds up.
- **Impact**: **Low** — Only on exception paths.
- **Fix**: Pre-compile as a single regex: `_TERMINAL_PATTERN = re.compile("|".join(re.escape(kw) for kw in _TERMINAL_KEYWORDS))`.
- **Why**: Single-pass regex vs 8-pass substring check; free optimization.

### [Finding L11] Plugin model type handler iteration on every `get_model()`
- **Location**: `code_puppy/model_factory.py:1042-1063`
- **Issue**: After builder registry miss, iterates `callbacks.on_register_model_types()` for plugin handlers. For types like `chatgpt_oauth`, `claude_code`, this runs on every model creation.
- **Impact**: **Low** — ~10-50μs for plugin-resolved types.
- **Fix**: Merge plugin handlers into `_MODEL_BUILDERS` on first plugin load; single dict lookup thereafter.
- **Why**: O(1) vs O(n) iteration; more maintainable.

### [Finding L12] `_load_plugin_model_providers` lazy init has no lock
- **Location**: `code_puppy/model_factory.py:73-86`
- **Issue**: `_providers_loaded` flag check + set is not atomic. In multi-threaded contexts (e.g., via `run_async_sync`), double-init is possible.
- **Impact**: **Low** — Unlikely in current CLI usage. Double-init would just call callbacks twice, not corrupt state.
- **Fix**: Add `threading.Lock()` with double-checked locking pattern.
- **Why**: Correctness under future multi-threaded usage.

---

## 🌐 Cross-Module Patterns

### CM1: Exception-based `asyncio.get_running_loop()` appears in 4+ locations
- **Locations**: `callbacks.py:185-192`, `adaptive_rate_limiter.py:442-444`, `adaptive_rate_limiter.py:618-619`, `http_utils.py:98-114`
- **Issue**: The pattern `try: loop = asyncio.get_running_loop(); ... except RuntimeError: ...` uses exceptions for control flow. Each exception raise/catch is ~200ns.
- **Recommendation**: Add a shared helper in `async_utils.py`:
  ```python
  def try_get_running_loop() -> asyncio.AbstractEventLoop | None:
      """Fast loop lookup without exception overhead."""
      try:
          return asyncio.get_running_loop()
      except RuntimeError:
          return None
  ```
  Or better, use `asyncio._get_running_loop()` (private C function, ~20ns, returns None if no loop).

### CM2: `time.time()` vs `time.monotonic()` inconsistency
- **Locations**: `request_cache.py` uses `time.time()` (wall-clock), `adaptive_rate_limiter.py` uses `time.monotonic()`.
- **Issue**: Wall-clock is subject to NTP jumps. A backwards jump could make cache entries immortal or instantly expire.
- **Recommendation**: Standardize on `time.monotonic()` for all TTL/elapsed-time logic.

### CM3: Env var re-reading across modules
- **Locations**: `http_utils._resolve_proxy_config()` (Finding M9), `model_factory.get_api_key()` (various).
- **Issue**: Both modules read `os.environ.get()` on every call despite env vars rarely changing mid-session.
- **Recommendation**: Centralized `EnvSnapshot` class with short TTL, or watch `os.environ` for mutation.

### CM4: No httpx client pooling across model switches
- **Location**: `model_factory.py` builders
- **Issue**: `create_async_client()` called per model builder invocation. Users switching between e.g. `custom_openai` and `cerebras` pay TCP handshake + TLS negotiation each time.
- **Recommendation**: Pool `httpx.AsyncClient` instances keyed by `(proxy_url, verify, headers_hash)`.

### CM5: Lock type mixing (threading.RLock + asyncio.Lock) in same codebase
- **Locations**: `callbacks.py` uses `threading.RLock`, `adaptive_rate_limiter.py` uses `asyncio.Lock`
- **Issue**: If a callback registered for `stream_event` calls into the rate limiter, cross-lock ordering is undefined.
- **Recommendation**: Document lock hierarchy (asyncio locks strictly before threading locks) or pick one consistent type.

---

## 🔬 Profiling Recipe Appendix

Run these commands against a live code_puppy session to validate findings before optimizing.

### 1. py-spy top (zero-instrumentation, live sampling)
```bash
# Attach to a running code_puppy process — shows top functions by CPU
py-spy top --pid $(pgrep -f "code-puppy\|code_puppy") --rate 100

# Look for:
#   - callbacks._trigger_callbacks_sync  (Finding H1)
#   - callbacks.on_stream_event          (Finding H2)
#   - claude_cache_client._transform_request_body  (Finding H3)
#   - session_storage.save_session       (Finding H4)
```

### 2. py-spy record (flamegraph for full visual)
```bash
# Record 30s of an active streaming session
py-spy record --pid $(pgrep -f "code-puppy\|code_puppy") --rate 100 --duration 30 -o profile.svg

# Open profile.svg in a browser; look for wide bars in:
#   - callbacks._trigger_callbacks*
#   - claude_cache_client.send
#   - ModelMessagesTypeAdapter.dump_*
```

### 3. cProfile targeted (offline, deterministic)
```bash
# Profile a synthetic workload
python -m cProfile -o profile.prof -m code_puppy -p "write a hello world python script"
python -c "
import pstats
p = pstats.Stats('profile.prof')
p.sort_stats('cumulative').print_stats(30)
p.sort_stats('tottime').print_stats(30)
"
```

### 4. Validate Finding H1 (asyncio.run overhead) microbenchmark
```bash
python -c "
import asyncio, time
async def noop(): pass

# asyncio.run() per call
start = time.perf_counter()
for _ in range(1000):
    asyncio.run(noop())
print(f'asyncio.run x1000: {(time.perf_counter()-start)*1000:.1f}ms')

# persistent loop
loop = asyncio.new_event_loop()
start = time.perf_counter()
for _ in range(1000):
    loop.run_until_complete(noop())
print(f'persistent loop x1000: {(time.perf_counter()-start)*1000:.1f}ms')
loop.close()
"
# Expected: asyncio.run is ~10x slower
```

### 5. Validate Finding H3 (JSON round-trip) microbenchmark
```bash
python -c "
import json, time
body = json.dumps({'messages': [{'content': 'x' * 50000}]}).encode()

# Current: unconditional parse + re-encode
start = time.perf_counter()
for _ in range(100):
    data = json.loads(body.decode())
    json.dumps(data).encode()
print(f'JSON round-trip 50KB x100: {(time.perf_counter()-start)*1000:.1f}ms')

# Proposed: byte-level check
start = time.perf_counter()
for _ in range(100):
    b'\"tools\"' in body
print(f'byte check x100: {(time.perf_counter()-start)*1000:.3f}ms')
"
# Expected: byte check is ~10000x faster than round-trip for cache-hit case
```

### 6. Validate Finding H4 (session_storage double serialization)
```bash
python -c "
import time, json
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart

# Synthetic 100-message history
history = [
    ModelRequest(parts=[UserPromptPart(content=f'msg {i}')])
    for i in range(100)
]

# Fast path
t0 = time.perf_counter()
for _ in range(10):
    ModelMessagesTypeAdapter.dump_python(history, mode='json')
print(f'dump_python mode=json x10: {(time.perf_counter()-t0)*100:.1f}ms')

# Current fallback (double serialization)
t0 = time.perf_counter()
for _ in range(10):
    data = ModelMessagesTypeAdapter.dump_json(history)
    json.loads(data)
print(f'dump_json+json.loads x10: {(time.perf_counter()-t0)*100:.1f}ms')

# Proposed fix (mode=python + sanitize)
t0 = time.perf_counter()
for _ in range(10):
    ModelMessagesTypeAdapter.dump_python(history, mode='python')
print(f'dump_python mode=python x10: {(time.perf_counter()-t0)*100:.1f}ms')
"
```

### 7. Validate Finding M13 (load_config stat() overhead)
```bash
python -c "
import cProfile, pstats
from code_puppy.model_factory import ModelFactory

cProfile.runctx(
    'for _ in range(1000): ModelFactory.load_config()',
    globals(), locals(), 'load_config.prof'
)
p = pstats.Stats('load_config.prof')
p.sort_stats('cumulative').print_stats(20)
# Look for pathlib.Path.stat in the top-10
"
```

### 8. memory_profiler for request_cache growth over time
```bash
# Install: pip install memory_profiler
python -m memory_profiler -m code_puppy
# Or line-by-line on the cache:
mprof run -m code_puppy -p "long running task"
mprof plot
```

### 9. Custom instrumentation for in-production validation
```python
# Add to callbacks.py temporarily — logs p99 latency per phase
import time as _time
_perf_counters: dict[str, list[float]] = {}

def _perf_time(phase: str, start: float) -> None:
    elapsed_us = (_time.perf_counter() - start) * 1_000_000
    _perf_counters.setdefault(phase, []).append(elapsed_us)
    if len(_perf_counters[phase]) % 1000 == 0:
        times = _perf_counters[phase][-1000:]
        avg = sum(times) / len(times)
        p99 = sorted(times)[990]
        logger.warning(f"PERF {phase}: avg={avg:.0f}μs p99={p99:.0f}μs (last 1000)")

# Usage in _trigger_callbacks_sync:
_start = _time.perf_counter()
# ... existing logic ...
_perf_time("trigger_callbacks_sync", _start)
```

---

## 📊 Prioritized Impact Summary Table

**Ranked by (impact × call frequency × estimated savings).**

| Rank | ID | Location | Finding | Impact | Est. Savings |
|------|----|----|---|---|---|
| 1 | H1 | `callbacks.py:189` | `asyncio.run()` in sync callback dispatch | **High** | ~45-90μs per async-from-sync call |
| 2 | H2 | `callbacks.py:574-593` | Streaming token: ContextVar + dict mutation | **High** | ~5-10μs per streamed token (×100s/sec) |
| 3 | H3 | `claude_cache_client.py:372-422` | Unconditional JSON round-trip per request | **High** | ~1-2ms per 50KB request |
| 4 | H4 | `session_storage.py:334-358` | Double pydantic serialization (DBOS path) | **High** | ~10-50ms per autosave |
| 5 | M1 | `callbacks.py:148` | RLock on every `get_callbacks()` read | Medium | ~1-5μs per event dispatch |
| 6 | M3 | `adaptive_rate_limiter.py:604` | Unconditional task creation on release | Medium | ~1-2μs per request + GC pressure |
| 7 | M4 | `adaptive_rate_limiter.py:484` | Global lock on every `acquire_model_slot` | Medium | ~1-3μs per request |
| 8 | M13 | `model_factory.py:395` | 6 stat() syscalls per cached `load_config()` | Medium | ~6-30μs per model switch |
| 9 | M14 | `model_factory.py:145` | `make_model_settings()` not memoized | Medium | ~10-50μs per model switch |
| 10 | M5 | `request_cache.py:136` | Header hash: sort + double encode + dup typo | Medium | ~1-5μs per cache lookup |
| 11 | M6 | `claude_cache_client.py:71` | Triple-nested loop for tool ID sanitization | Medium | ~500 iters per request (long convo) |
| 12 | H3/M6 combo | `claude_cache_client.py` | Combined byte-check short-circuit | Medium | ~2-5ms per request (compounds H3+M6) |
| 13 | M7 | `claude_cache_client.py:248` | Broken JWT prefix cache | Medium | ~20-50μs per token check |
| 14 | M8 | `claude_cache_client.py:488` | Multiple body extractions per request | Medium | ~2× `_extract_body_bytes` calls saved |
| 15 | M9 | `http_utils.py:39` | 8 env lookups per client creation | Medium | ~5-10μs per client creation |
| 16 | M11 | `http_utils.py:209` | Retry backoff without jitter | Medium | Correctness: thundering herd |
| 17 | M12 | `session_storage.py:99` | Pydantic validation on session load | Medium | ~95ms on 100-msg load |
| 18 | M15 | `interactive_loop.py:487` | Wiggum loop unnecessary finalize | Medium | ~10ms per wiggum iteration |
| 19 | M10 | `http_utils.py:98` | Fire-and-forget tasks no retention | Medium | Correctness: lost notifications |
| 20 | M2 | `callbacks.py:247` | TaskGroup for 0-1 callback dispatch | Medium | ~10-20μs per dispatch |
| 21 | L1-L12 | Various | Micro-optimizations & code hygiene | Low | <1μs each; adopt opportunistically |

### Recommended Implementation Order

**Tier 1 (ship ASAP — measurable user-visible wins):**
1. **H4** — session_storage double-serialization (autosave latency)
2. **H3** — claude_cache_client JSON round-trip (per-request latency)
3. **H1** — callbacks asyncio.run (plugin dispatch latency)

**Tier 2 (ship in the same PR as Tier 1 — cheap compound wins):**
4. **H2** — stream_event optimization (depends on M1 for full effect)
5. **M1** — callbacks copy-on-write snapshot (enables H2)
6. **M6** — tool ID short-circuit (compounds with H3)
7. **M13 + M14** — load_config TTL + make_model_settings memoization (paired fix)

**Tier 3 (separate PR — rate limiter cluster):**
8. **M3** — release_model_slot conditional task
9. **M4** — acquire_model_slot double-checked locking
10. **M10 + M11** — http_utils task retention + retry jitter

**Tier 4 (backlog — code hygiene):**
- All L1-L12 findings. Good first issues for contributors.

---

## 🎯 Methodology Notes

- **Scope**: Static code review only. No runtime profiling was performed — the Profiling Appendix is a recipe for the user to validate findings.
- **Tools used**: `code-scout` (for evidence gathering with line numbers + snippets), two `python-reviewer` agents in parallel (for perf-focused fix generation).
- **Prior art consulted**: `BUGS_PERF_DESIGN_REVIEW.md`, `PYTHON_QUALITY_REVIEW.md`, `PYTHON_REVIEW.md`. Findings already covered in those docs were explicitly deduplicated and referenced.
- **What this review did NOT cover**: 50 of 58 modules in `code_puppy/` (by design — focused hot-path review). Dynamic perf under load. Rust FFI boundary (`_core_bridge.py`, `turbo_parse_bridge.py`). TUI rendering pipeline (`tui/`). Database query patterns in `session_storage.py` were noted but `persistence.py` SQLite layer was not examined.
- **False positive mitigation**: Every High-severity finding includes a concrete profiling command in the appendix to validate before optimizing.

---

**Report generated by:** planning-agent-019d6e  
**Agent coordination:** code-scout → python-reviewer × 2 (parallel) → planning-agent (synthesis)  
**Next suggested step:** Run the Profiling Recipe #4 and #5 microbenchmarks to validate H1 and H3 on this machine before implementing fixes.
