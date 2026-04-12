# Thread-Safety Audit: turbo_parse

**Date**: 2026-04-12
**Issue**: code_puppy-68x.18
**Auditor**: code-puppy-clone-3-019d7e

## Summary

turbo_parse is the most complex Rust crate in Code Puppy, providing tree-sitter-based parsing with PyO3 bindings. The audit found the crate to be **already well-designed for thread safety**, with `parking_lot` used in the hot paths (cache, stats). Two minor inconsistencies were found and fixed.

## Changes Applied

### 1. Added `frozen` to all `#[pyclass]` types

All four `#[pyclass]` types are immutable data carriers — they have no mutable methods and all fields are set at construction. Adding `#[pyclass(frozen)]` makes PyO3 enforce immutability at the Python level, which is the correct pattern for free-threaded Python (PEP 703).

| Type | File | Change |
|------|------|--------|
| `InputEdit` | `incremental.rs:22` | `#[pyclass]` → `#[pyclass(frozen)]` |
| `SerializedTree` | `incremental.rs:158` | `#[pyclass]` → `#[pyclass(frozen)]` |
| `InjectionRange` | `injection.rs:26` | `#[pyo3::pyclass]` → `#[pyo3::pyclass(frozen)]` |
| `HighlightCapture` | `highlights.rs:42` | `#[pyo3::pyclass]` → `#[pyo3::pyclass(frozen)]` |

**Rationale**: None of these types have mutable `#[pymethods]`. All fields are set via `#[new]` and never mutated. `frozen` prevents Python code from attempting attribute assignment and signals to PyO3 that these types are inherently thread-safe without per-object locking.

### 2. Migrated `dynamic.rs` from `std::sync` to `parking_lot`

**Before**: Used `std::sync::RwLock` and `std::sync::Mutex` for `grammars`, `allowed_directories`, and `allow_any_directory` fields.

**After**: Uses `parking_lot::RwLock` and `parking_lot::Mutex` — consistent with the rest of the crate.

**Why**: `parking_lot` locks don't suffer from lock poisoning (no `.unwrap()` needed on acquire), are faster in contended scenarios, and are already a dependency used by `cache.rs` and `stats.rs`. Using `std::sync` in one module and `parking_lot` in others was inconsistent.

### 3. Migrated `registry.rs` DYNAMIC_GRAMMARS to `parking_lot::Mutex`

**Before**: `static DYNAMIC_GRAMMARS: OnceLock<std::sync::Mutex<HashMap<...>>>`

**After**: `static DYNAMIC_GRAMMARS: OnceLock<parking_lot::Mutex<HashMap<...>>>`

**Why**: Same rationale as above — consistency with the crate's locking strategy and avoiding lock poisoning.

## Audit Findings by Module

### `cache.rs` — ✅ Clean

- Uses `parking_lot::RwLock<LruCache<CacheKey, CacheValue>>` for the LRU cache
- Uses `parking_lot::RwLock<CacheStats>` for statistics
- `get()` acquires write lock (needed because `lru::LruCache::get` updates access order)
- `put()`, `remove()`, `clear()` correctly acquire write locks
- `contains()`, `len()`, `capacity()`, `stats()` correctly acquire read locks
- `CacheKey` and `CacheValue` are `Clone + Send + Sync` — safe to share across threads
- Global `OnceLock<ParseCache>` is correct for singleton initialization

### `stats.rs` — ✅ Clean

- Uses `parking_lot::RwLock` for `total_parses`, `total_parse_time_ms`, and `languages`
- `record_parse()` correctly acquires write locks for all three fields
- `total_parses()`, `average_parse_time_ms()`, `languages_used()` use read locks
- Global `OnceLock<Metrics>` singleton is correct

### `registry.rs` — ✅ Clean (after fix)

- `LanguageRegistry` holds `HashMap<String, Language>` — no interior mutability needed because it's behind `OnceLock` and populated at construction
- `Language` is `Clone + Send + Sync` — safe for concurrent access
- DYNAMIC_GRAMMARS now uses `parking_lot::Mutex` (was `std::sync::Mutex`)

### `dynamic.rs` — ✅ Clean (after fix)

- `DynamicGrammarLoader` uses `RwLock` for `grammars` (frequent reads, infrequent writes)
- Uses `Mutex` for config fields (`allowed_directories`, `allow_any_directory`)
- `LoadedGrammar` is behind `Arc` for shared ownership
- All lock acquisitions are short-lived — no risk of deadlocks
- Path validation is done before acquiring write locks — good practice

### `parser.rs` — ✅ Clean

- No shared state. Creates fresh `Parser` per call.
- `parse_source_internal()` is purely functional — takes inputs, returns results
- `ParseResult`, `ParseError` are `Clone + Serialize + Deserialize` — no thread-safety concerns

### `batch.rs` — ✅ Clean

- Uses `rayon` for parallelism with `par_iter()`
- Each file is parsed independently — no shared mutable state during batch
- `BatchParseResult` and `BatchParseOptions` are `Clone + Send + Sync`

### `diagnostics.rs` — ✅ Clean

- Pure functions — `walk_tree_for_diagnostics` and `extract_diagnostics` create fresh state
- `SyntaxDiagnostics` and `Diagnostic` are `Clone + Serialize + Deserialize`

### `folds.rs`, `highlights.rs`, `symbols.rs`, `queries.rs` — ✅ Clean

- All follow the same pattern: pure functions, results are owned data, no shared state
- All result types are `Clone + Serialize + Deserialize`

### `injection.rs` — ✅ Clean

- `InjectionRange` is now `#[pyclass(frozen)]` — immutable data carrier
- Detection functions are pure — no shared mutable state

### `incremental.rs` — ✅ Clean (after fix)

- `InputEdit` is now `#[pyclass(frozen)]` — immutable data carrier
- `SerializedTree` is now `#[pyclass(frozen)]` — immutable data carrier
- `IncrementalParseContext` holds `Option<Tree>` but is not exposed to Python — internal only
- `parse_with_edits` correctly releases GIL via `py.detach()`

### `lib.rs` — ✅ Clean

- All `#[pyfunction]`s correctly use `py.detach()` for CPU-intensive work
- Results are converted to Python dicts after GIL re-acquisition
- Global `OnceLock<ParseCache>` singleton is correctly used
- No mutable module-level state beyond the initialized singletons

## GIL Handling Assessment

All `#[pyfunction]`s follow the correct pattern:

1. Parse Python arguments (requires GIL)
2. Release GIL via `py.detach()` for CPU-intensive work
3. Re-acquire GIL implicitly for result conversion

This is the correct pattern for both standard CPython and free-threaded Python builds.

## Concurrency Primitives Summary

| Module | Primitive | Usage | Status |
|--------|-----------|-------|--------|
| `cache.rs` | `parking_lot::RwLock` | LRU cache + stats | ✅ Correct |
| `stats.rs` | `parking_lot::RwLock` | Metrics counters | ✅ Correct |
| `stats.rs` | `std::sync::OnceLock` | Global singleton | ✅ Correct |
| `dynamic.rs` | `parking_lot::RwLock` | Grammar cache | ✅ Fixed |
| `dynamic.rs` | `parking_lot::Mutex` | Config fields | ✅ Fixed |
| `dynamic.rs` | `std::sync::OnceLock` | Global singleton | ✅ Correct |
| `registry.rs` | `std::sync::OnceLock` | Global registry singleton | ✅ Correct |
| `registry.rs` | `parking_lot::Mutex` | Dynamic grammar paths | ✅ Fixed |
| `lib.rs` | `std::sync::OnceLock` | Global cache singleton | ✅ Correct |

## Verdict

**turbo_parse is thread-safe.** The crate was already well-designed with proper locking and GIL management. The changes applied are:

1. **Defensive** (`frozen` on pyclasses) — prevents future breakage under free-threaded Python
2. **Consistency** (`parking_lot` everywhere) — eliminates lock poisoning risk and unifies the crate's concurrency strategy
