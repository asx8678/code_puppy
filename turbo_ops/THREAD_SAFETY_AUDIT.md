# Thread Safety Audit: turbo_ops

**Issue**: code_puppy-68x.17
**Date**: 2026-04-12
**Scope**: Free-threading compatibility (PEP 703 / Python 3.13+)

## Summary

turbo_ops is largely thread-safe by design — it uses rayon for internal parallelism
and avoids mutable shared state. One fix was required for `index_directory`.

## Audit Results

### #[pyclass] types

| Type | File | `frozen`? | Mutable fields? | Verdict |
|------|------|-----------|-----------------|---------|
| `FileSummary` | `indexer.rs` | ✅ Yes | None (all `&str` / `Vec<String>`) | ✅ Safe |

No other `#[pyclass]` types exist. All Rust-internal structs (`TurboOperation`,
`OperationResult`, `BatchResult`, `FileInfo`, `GrepMatch`, `FileReadResult`) are
pure Rust — never exposed to Python directly.

### #[pyfunction] functions

| Function | File | GIL released? | Verdict |
|----------|------|---------------|---------|
| `batch_execute_ops` | `lib.rs` | ✅ `py.detach()` | ✅ Safe |
| `batch_execute_grouped_ops` | `lib.rs` | ✅ `py.detach()` | ✅ Safe |
| `list_files` | `lib.rs` | ✅ `py.detach()` | ✅ Safe |
| `grep` | `lib.rs` | ✅ `py.detach()` | ✅ Safe |
| `read_files` | `lib.rs` | ✅ `py.detach()` | ✅ Safe |
| `read_file` | `lib.rs` | Via `read_files` | ✅ Safe |
| `health_check` | `lib.rs` | N/A (trivial) | ✅ Safe |
| `index_directory` | `indexer.rs` | ✅ **Fixed** (was missing) | ✅ Safe |

### Internal modules (pure Rust, no Python boundary)

| Module | Thread-safety mechanism | Verdict |
|--------|------------------------|---------|
| `operations.rs` | No shared mutable state | ✅ Safe |
| `batch_executor.rs` | rayon `par_iter()` on immutable data | ✅ Safe |
| `models.rs` | Plain data structs, no interior mutability | ✅ Safe |

## Change Made

### `indexer.rs`: `index_directory` — GIL release for rayon work

**Before**: The function held the GIL for its entire duration, including the
rayon `into_par_iter()` parallel processing. Under free-threaded Python, this
unnecessarily blocks other Python threads.

**After**: Wrapped the filesystem traversal (`collect_candidates`) and rayon
parallel processing inside `py.detach()` so the GIL is released during heavy
work. GIL is re-acquired only for the final `Vec<FileSummary>` return.

## Architectural Notes

1. **No interior mutability**: No `Mutex`, `RwLock`, or `Atomic*` types needed
   because all data flows through owned values or immutable references.

2. **rayon usage**: rayon's `par_iter()` is inherently safe — it borrows the
   collection immutably and produces owned results.

3. **JSON round-trip**: The current `json.dumps`/`json.loads` conversion pattern
   in `lib.rs` is thread-safe (no shared state) but has performance overhead.
   See TODO(PERF-02) in `lib.rs` for optimization path.

4. **`frozen` attribute**: `FileSummary` was already marked `frozen` — no
   additional pyclass needed this attribute.
