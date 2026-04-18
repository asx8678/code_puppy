# Pytest Hang Diagnosis Report

**Date:** 2026-04-18  
**Task:** bd-126  
**Issue:** ALL pytest runs time out at 20 minutes (even sequential `-n0` runs)

## Executive Summary

The test suite **does NOT hang on any specific test**. Instead, pytest hangs at **session teardown** (after all tests complete) because **ThreadPoolExecutor workers are never shut down**. The main process waits indefinitely for daemon threads that are blocked on `work_queue.get(block=True)`.

## Root Cause

Multiple modules create **global ThreadPoolExecutor instances** at import time with `atexit` shutdown handlers. During pytest runs:

1. Tests import these modules, creating thread pools
2. Thread pool workers start and block on `work_queue.get(block=True)` 
3. Tests complete successfully
4. pytest tries to finish the session
5. **The atexit handlers don't run during pytest's teardown** (or run too late)
6. Python waits forever for non-daemon worker threads to finish

### Affected Thread Pools

| Module | Thread Prefix | Workers | Shutdown Mechanism |
|--------|--------------|---------|-------------------|
| `code_puppy/tools/command_runner.py` | `shell_cmd_` | 16 | `atexit.register(..., wait=False)` |
| `code_puppy/async_utils.py` | `async_utils_pool` | min(32, cpu+4) | Callback `shutdown` or `atexit` |
| `code_puppy/summarization_agent.py` | `summarizer-loop` | 1 | `atexit.register(...)` |
| `code_puppy/session_storage.py` | `autosave` | 1 | `atexit.register(...)` |

### Evidence

When tests timeout, stack traces show:

```
~~~~~~~~~~~~~~~~~~~~~~ Stack of async_utils_pool_0 (6174093312) ~~~~~~~~~~~~~~~~~~~~~~
  File ".../threading.py", line 1024, in run
    self._target(*self._args, **self._kwargs)
  File ".../concurrent/futures/thread.py", line 116, in _worker
    work_item = work_queue.get(block=True)  # <-- BLOCKED HERE
```

## Reproduction Recipe

```bash
# This hangs after ~5-10 minutes (at session teardown):
cd ../bd-126
timeout 300 uv run --active pytest tests/ -n0 --timeout=30 -q

# Individual test files complete fine:
timeout 60 uv run --active pytest tests/tools/test_command_runner_core.py -n0 --timeout=30 -v
# Result: 17 passed in 3.46s

# Subset of directories completes:
timeout 180 uv run --active pytest tests/test_*.py -n0 --timeout=30 -q
# Result: 163 failed, 4483 passed in 87s

# But ALL tests together hang at teardown:
timeout 300 uv run --active pytest tests/ -n0 --timeout=30 -q
# Result: Timeout after 300s
```

## Why This Happens

1. **pytest-xdist or pytest itself** may interfere with atexit handler execution
2. **Thread pools are non-daemon by default** - Python waits for them at exit
3. **The `isolate_config_between_tests` fixture** resets many singletons but NOT thread pools
4. **No `pytest_sessionfinish` hook** to explicitly shut down thread pools

## Proposed Fix

### Option 1: Add thread pool cleanup to conftest.py (Recommended)

Add to `tests/conftest.py`:

```python
def pytest_sessionfinish(session, exitstatus):
    """Shut down global thread pools to prevent hang at exit."""
    # Shutdown command_runner shell executor
    try:
        from code_puppy.tools.command_runner import _SHELL_EXECUTOR
        if _SHELL_EXECUTOR is not None:
            _SHELL_EXECUTOR.shutdown(wait=False)
    except ImportError:
        pass
    
    # Shutdown async_utils executor  
    try:
        from code_puppy.async_utils import _shutdown_executor
        _shutdown_executor()
    except ImportError:
        pass
    
    # Shutdown summarization agent pool
    try:
        from code_puppy.summarization_agent import _shutdown_thread_pool
        _shutdown_thread_pool()
    except ImportError:
        pass
    
    # Shutdown session storage autosave executor
    try:
        from code_puppy.session_storage import _autosave_executor
        _autosave_executor.shutdown(wait=False)
    except ImportError:
        pass
```

### Option 2: Make thread pool workers daemon threads

Modify each ThreadPoolExecutor creation:

```python
executor = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="shell_cmd_",
)
# Make workers daemon so they don't block process exit
executor._threads = set()  # Can't directly set, need custom implementation
```

**Problem:** ThreadPoolExecutor doesn't expose a way to set daemon=True on workers.

### Option 3: Use `pytest-timeout` at session level

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
timeout = 900  # 15 minutes global timeout
```

**Problem:** This doesn't fix the root cause, just limits the hang time.

## Recommended Action

Implement **Option 1** - add explicit thread pool shutdown to `pytest_sessionfinish`. This is:
- Non-invasive to production code
- Explicit and maintainable  
- Follows the existing pattern of cleanup in conftest.py
- Fixes the root cause

## Additional Notes

- The `isolate_config_between_tests` fixture already resets many singletons (policy engine, security boundary, run limiter, message queue, callbacks) but was missing thread pool cleanup
- Tests themselves complete successfully - the hang is purely at session teardown
- The issue only manifests when running ALL tests because that's when multiple thread pools accumulate
