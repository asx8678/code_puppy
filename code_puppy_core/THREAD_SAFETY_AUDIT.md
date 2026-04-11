# Thread Safety Audit for code_puppy_core

**Date:** 2026-04-08  
**Issue:** code_puppy-68x.16  
**Goal:** Audit for `gil_used = false` compatibility (free-threaded Python)

## Summary

The `code_puppy_core` crate has been audited for thread-safety. All `#[pyclass]` types now use `frozen` and all mutable state uses interior mutability via `std::sync::Mutex`.

## Audit Results

### `#[pyclass]` Types

| Type | `frozen`? | Interior Mutability | Status |
|------|-----------|---------------------|--------|
| `ProcessResult` | ✅ Yes | N/A (immutable) | ✅ Safe |
| `PruneResult` | ✅ Yes | N/A (immutable) | ✅ Safe |
| `SplitResult` | ✅ Yes | N/A (immutable) | ✅ Safe |
| `MessageBatch` | ✅ Yes | `Mutex<T>` for cached fields | ✅ Safe |

### Internal Types (Not `#[pyclass]`)

| Type | Thread-Safe? | Notes |
|------|--------------|-------|
| `Message` | ✅ Yes | Immutable data struct with serde |
| `MessagePart` | ✅ Yes | Immutable data struct with serde |
| `ToolDefinition` | ✅ Yes | Immutable data struct with serde |

### `#[pyfunction]` Functions

All `#[pyfunction]` declarations are **thread-safe**:

| Function | Touches Python Objects | Notes |
|----------|------------------------|-------|
| `process_messages_batch` | ✅ Yes (reads PyList) | Pure computation after conversion |
| `prune_and_filter` | ✅ Yes (reads PyList) | Pure computation after conversion |
| `truncation_indices` | ❌ No | Pure computation on Rust types |
| `split_for_summarization` | ❌ No | Pure computation on Rust types |
| `serialize_session` | ✅ Yes (reads PyList) | Pure conversion |
| `deserialize_session` | ✅ Yes (creates PyList) | Pure conversion |
| `serialize_session_incremental` | ✅ Yes (reads PyList) | Pure conversion |
| `compute_line_hash` | ❌ No | Pure computation |
| `format_hashlines` | ❌ No | Pure computation |
| `strip_hashline_prefixes` | ❌ No | Pure computation |
| `validate_hashline_anchor` | ❌ No | Pure computation |

**Note:** Functions touching Python objects hold the GIL via `Bound<'_, PyAny>` references. This is handled automatically by pyo3.

## Changes Made

### MessageBatch Thread-Safety Fix

The `MessageBatch` class required interior mutability for its cached fields:

```rust
// BEFORE: Not thread-safe
#[pyclass]
pub struct MessageBatch {
    messages: Vec<Message>,
    per_message_tokens: Option<Vec<i64>>,      // ❌ Mutable without sync
    total_tokens: Option<i64>,                    // ❌ Mutable without sync
    message_hashes: Option<Vec<i64>>,            // ❌ Mutable without sync
    context_overhead_tokens: Option<i64>,       // ❌ Mutable without sync
}

// AFTER: Thread-safe with frozen + Mutex
#[pyclass(frozen)]
pub struct MessageBatch {
    messages: Vec<Message>,
    per_message_tokens: Mutex<Option<Vec<i64>>>,      // ✅ Thread-safe
    total_tokens: Mutex<Option<i64>>,                  // ✅ Thread-safe
    message_hashes: Mutex<Option<Vec<i64>>>,            // ✅ Thread-safe
    context_overhead_tokens: Mutex<Option<i64>>,         // ✅ Thread-safe
}
```

All methods updated:
- `process()` now takes `&self` instead of `&mut self`
- All cached field access goes through `.lock().unwrap()`
- Getter methods return cloned data from locked Mutex

## Conclusion

✅ **The `code_puppy_core` crate is now ready for `gil_used = false`.**

All `#[pyclass]` types use `frozen` with appropriate interior mutability, and all functions either work with pure Rust types or properly hold the GIL when accessing Python objects.
