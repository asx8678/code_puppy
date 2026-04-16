# Fast Puppy rewrite plan (Elixir-first) — ARCHIVED

> **⚠️ HISTORICAL DOCUMENT — ARCHIVED 2026-04-16**
> 
> This document is preserved for historical reference only. It describes the migration planning state **before** the Zig cleanup (early 2026).
> 
> **Current status:** See `MIGRATION_STATUS.md` for the single source of truth.
> 
> **Note on Zig references:** Any Zig references in this document describe the pre-cleanup architecture state. Zig has been removed from the active runtime as of early 2026.


## Why the rewrite needed a reset (Historical Context)

> This section describes the state of the repository **before** the Zig cleanup and `NativeBackend` unification (bd-13).

The repo previously had a split-brain Fast Puppy story:

- `code_puppy/plugins/fast_puppy/builder.py` and `README.md` treated **all three** accelerators as Rust crates: `code_puppy_core`, `turbo_ops`, `turbo_parse`.
- `code_puppy/acceleration/__init__.py`, `code_puppy/config.py`, and related docs described a **hybrid Zig/Rust** model with `turbo_ops` on Zig. *(Zig has since been removed)*
- `code_puppy/plugins/turbo_executor/orchestrator.py` and `code_puppy/plugins/repo_compass/turbo_indexer_bridge.py` imported **Rust `turbo_ops` directly**, bypassing the "hybrid" abstraction.
- There was already an Elixir-native seed for repository indexing in `elixir/code_puppy_control/lib/code_puppy_control/indexer*`, but it only covered part of the `turbo_ops` surface.

**Resolution (completed):** `NativeBackend` was created as the single Python entry point (bd-13). Zig was removed. See `MIGRATION_STATUS.md` for current state.

## Target State (Achieved ✅)

> **2026-04-16 Update:** The target state described here has been achieved. See `MIGRATION_STATUS.md` for current details.

Fast Puppy is now a **single Elixir-owned native runtime surface** with Python fallbacks, not a crate-builder plus multiple competing bridges.

### Desired Properties (All Achieved ✅)

- ✅ One backend contract for Python consumers (`NativeBackend`)
- ✅ One status/config story for `/fast_puppy`
- ✅ Elixir-native implementations for repo/file acceleration
- ✅ Python-only CLI still works when the Elixir control plane is absent
- ✅ No runtime monkey-patching as the primary activation mechanism

## Rewrite phases

### Phase 1 — freeze the interface before porting anything

Create a single backend contract used by all Python callers, for example:

- `code_puppy/native_backend.py`
- capabilities: `message_core`, `file_ops`, `repo_index`, `parse`
- backends: `elixir`, `python` (and temporary `rust` only during migration)

Do this first:

- Move all direct native imports behind one adapter.
- Stop feature modules from importing `_core_bridge`, `turbo_ops`, `turbo_parse`, or `zig_bridge` directly.
- Make `/fast_puppy` report capability-level status rather than “crate freshness”.
- Make `/accel` reflect the same source of truth or retire it.

**Exit criteria**

- `turbo_executor`, `repo_compass`, and parse consumers call one adapter only.
- No direct native import remains outside the adapter and the migration shims.

### Phase 2 — port `turbo_ops` to Elixir first

This is the best next slice because:

- it is smaller than `turbo_parse`
- there is already Elixir-native indexing code to build on
- current repo behavior is especially inconsistent here (Rust in practice, Zig in config/docs)

Port these features into Elixir:

- `list_files`
- `grep`
- `read_file` / `read_files`
- batch execution semantics used by `TurboOrchestrator`
- repo indexing used by Repo Compass

Reuse and extend:

- `CodePuppyControl.Indexer`
- `DirectoryWalker`
- `DirectoryIndexer`
- `SymbolExtractor`

Also port or preserve:

- path validation / security gates currently enforced in Python
- result shapes expected by `TurboOrchestrator`
- ignored-dir behavior and token-count fields

**Implementation note**

Do **not** put hot file operations behind Phoenix HTTP routes. Use an embedded/local Elixir runtime boundary suitable for low-latency calls (Port, stdio service, or another local IPC layer). The benchmark file in the repo shows control-plane overhead is acceptable for orchestration but still slower than direct in-process Python for hot loops.

**Exit criteria**

- `TurboOrchestrator` uses Elixir-backed file ops through the shared adapter.
- `Repo Compass` indexer uses the same backend contract.
- Legacy Zig path for `turbo_ops` is fully retired.

### Phase 3 — simplify Fast Puppy activation and build flow

Once `turbo_ops` is Elixir-backed, rewrite Fast Puppy itself:

- Replace crate-centric build logic with backend/runtime management.
- Remove the dynamic reload-and-patch approach in `builder.py`.
- Make startup perform capability discovery, not module rebinding.
- Persist user preferences by capability or runtime profile, not just `enable_fast_puppy` for `_core_bridge`.

Recommended runtime profiles:

- `native_elixir`
- `python_fallback`
- temporary `migration_mixed` (short-lived)

**Exit criteria**

- `/fast_puppy enable` and `/fast_puppy disable` affect the whole backend profile, not only `code_puppy_core`.
- No import-time monkey-patching is required for steady-state operation.

### Phase 4 — migrate `turbo_parse` in stages

`turbo_parse` is the hardest slice left. It is much larger and more feature-rich than `turbo_ops`, with:

- 14 Rust source files
- 20 query files
- 6 supported languages
- symbols, diagnostics, folds, highlights, batch parsing, caching, incremental parsing

Do not rewrite it as one giant milestone. Break it up:

1. symbol extraction + diagnostics for the most important languages
2. folds + highlights
3. batch parsing + caching
4. incremental parsing
5. long-tail language parity

Pragmatic rule:

- Put `turbo_parse` behind the same Elixir-owned adapter first.
- Then replace the internals incrementally.
- Keep Python fallback available until each language tier is green.

If strict pure Elixir proves too expensive for tree-sitter-grade parsing, keep the **surface area Elixir-owned** and isolate any remaining native helper behind that boundary.

**Exit criteria**

- Parse consumers no longer import `turbo_parse_bridge` directly.
- Required language tiers pass parity tests.
- Feature flags can disable unfinished parse capabilities cleanly.

### Phase 5 — delete the hybrid leftovers (✅ COMPLETED)

> **Historical note:** This phase was completed in early 2026. The Zig runtime has been removed.

After `turbo_ops` was migrated and `turbo_parse` was placed behind the Elixir boundary:

- ✅ Removed `code_puppy/zig_bridge/`
- ✅ Removed Zig-first config defaults from `code_puppy/config.py`
- ✅ Rewrote `code_puppy/acceleration/__init__.py` to reflect the new truth (see `NativeBackend`)
- ✅ Updated `/accel` and `/fast_puppy` commands
- ✅ Removed stale docs describing the Zig/Rust split (see `MIGRATION_STATUS.md`)
- ✅ Retired build paths for dead backends

**Exit criteria** (Achieved)

- The repo has one coherent backend story.
- Docs, commands, config, and runtime behavior all match.

## Delivery order

1. Contract unification
2. `turbo_ops` Elixir migration
3. Fast Puppy command/build rewrite
4. `turbo_parse` staged migration
5. Legacy cleanup and deletion

## What I would not do

- I would not route hot-path file ops through Phoenix controllers.
- I would not keep both `/fast_puppy` and `/accel` with conflicting models.
- I would not start with `turbo_parse`; it is too large for the first migration slice.
- I would not leave direct native imports scattered through feature modules.

## Concrete first PRs

### PR 1
Create the shared backend adapter and switch these callers to it:

- `code_puppy/plugins/turbo_executor/orchestrator.py`
- `code_puppy/plugins/repo_compass/turbo_indexer_bridge.py`
- `code_puppy/acceleration/__init__.py`

### PR 2
Rewrite status/config UX:

- `code_puppy/plugins/fast_puppy/register_callbacks.py`
- `code_puppy/plugins/accel_status/register_callbacks.py`
- `docs/acceleration.md`
- Fast Puppy section in `README.md`

### PR 3
Port `turbo_ops` file ops into Elixir and wire the adapter to them.

### PR 4+
Port `turbo_parse` by feature set, not by crate-size milestone.

## Success definition

The rewrite is complete when:

- `code_puppy_core` stays green on Elixir
- `turbo_ops` is Elixir-backed in production paths
- `turbo_parse` is either Elixir-backed or fully hidden behind an Elixir-owned runtime boundary
- Python feature code depends on one backend contract only
- Fast Puppy no longer feels like a Rust/Zig crate manager and instead behaves like a native runtime selector
