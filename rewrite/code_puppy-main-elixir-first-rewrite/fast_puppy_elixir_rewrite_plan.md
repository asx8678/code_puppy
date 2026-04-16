# Fast Puppy rewrite plan (Elixir-first)

Assumption: `code_puppy_core` is already migrated and stable in native Elixir, so this plan excludes it from the remaining rewrite scope.

## Why the rewrite needs a reset first

The repo currently has a split-brain Fast Puppy story:

- `code_puppy/plugins/fast_puppy/builder.py` and `README.md` treat **all three** accelerators as Rust crates: `code_puppy_core`, `turbo_ops`, `turbo_parse`.
- `code_puppy/acceleration/__init__.py`, `code_puppy/config.py`, `code_puppy/plugins/accel_status/register_callbacks.py`, and `docs/acceleration.md` still describe a **hybrid Zig/Rust** model with `turbo_ops` on Zig.
- `code_puppy/plugins/turbo_executor/orchestrator.py` and `code_puppy/plugins/repo_compass/turbo_indexer_bridge.py` already import **Rust `turbo_ops` directly**, bypassing the “hybrid” abstraction.
- There is already an Elixir-native seed for repository indexing in `elixir/code_puppy_control/lib/code_puppy_control/indexer*`, but it only covers part of the `turbo_ops` surface.

## Target state

Fast Puppy becomes a **single Elixir-owned native runtime surface** with Python fallbacks, not a crate-builder plus multiple competing bridges.

### Desired properties

- One backend contract for Python consumers.
- One status/config story for `/fast_puppy` and `/accel`.
- Elixir-native implementations for repo/file acceleration where practical.
- Python-only CLI still works when the Elixir control plane is absent.
- No runtime monkey-patching as the primary activation mechanism.

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

### Phase 5 — delete the hybrid leftovers

After `turbo_ops` is migrated and `turbo_parse` is either migrated or fully hidden behind the Elixir boundary:

- remove or archive `code_puppy/zig_bridge/`
- remove Zig-first config defaults from `code_puppy/config.py`
- rewrite `code_puppy/acceleration/__init__.py` to reflect the new truth
- update `/accel` or fold it into `/fast_puppy`
- remove stale docs that still describe the old Zig/Rust split
- retire build paths that only exist for dead backends

**Exit criteria**

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
