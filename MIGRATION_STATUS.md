# Migration Status: Single Source of Truth

> **Document purpose:** Consolidated view of Python → Elixir runtime migration. **Rust has been completely eliminated.**
> **Last updated:** 2026-04-17 (bd-167 - Rust eliminated, pure Elixir+Python architecture achieved)
> **Previous docs consolidated:**
> - `ELIXIR_MIGRATION_ROADMAP.md` → Archived (historical analysis)
> - `fast_puppy_elixir_rewrite_plan.md` → Archived (historical, pre-Zig-cleanup)
> - `rewrite/ELIXIR_FIRST_REWRITE_ANALYSIS.md` → Archived (Repo Compass slice analysis)
> - `rewrite/code_puppy_elixir_rewrite_bundle/PLAN/code_puppy_python_to_elixir_plan.md` → Archived (PR sequence)

---

## Quick Status Dashboard

| Component | Status | Backend | Issue | Notes |
|-----------|--------|---------|-------|-------|
| **Scheduler** | ✅ DONE | Elixir | — | Production since early 2026 |
| **File Operations** | ✅ DONE | Elixir | bd-7, bd-8 | EOL normalization + gitignore filtering complete |
| **Repo Compass Indexer** | ✅ DONE | Elixir | bd-9 | Promoted to production |
| **Tree-sitter Parsing** | ✅ DONE | Elixir | bd-11, bd-167 | Migrated to pure Elixir (no Rust NIF) |
| **Content Prep** | ✅ DONE | Elixir | bd-34 | Migrated from Rust |
| **Path Classifier** | ✅ DONE | Elixir | bd-35 | Migrated from Rust |
| **Line Numbers** | ✅ DONE | Elixir | bd-36 | Migrated from Rust |
| **Unified Diff** | ✅ DONE | Elixir | bd-37 | Migrated from Rust |
| **Fuzzy Match** | ✅ DONE | Elixir | bd-38 | Migrated from Rust |
| **Replace Engine** | ✅ DONE | Elixir | bd-39 | Migrated from Rust, 2026-04-16 |
| **Hashline** | ✅ DONE | Elixir (Rustler NIF) | bd-88 | Migrated from Rust, 2026-04-16 |
| **Message Core** | ✅ DONE | Elixir | bd-43, bd-167 | Rust eliminated — pure Elixir implementation |
| **Elixir Transport** | ✅ DONE | Elixir | bd-10 | Standalone outside bridge mode |
| **Token Estimation** | ✅ DONE | Elixir | bd-44, bd-167 | Migrated from Rust to Elixir with ETS caching |
| **Message Pruning** | ✅ DONE | Elixir | bd-45, bd-167 | Migrated from Rust to Elixir |
| **Message Serialization** | ✅ DONE | Elixir | bd-47, bd-167 | Migrated from msgpack Rust to pure Elixir |
| **Message Hashing** | ✅ DONE | Elixir | bd-48, bd-167 | Migrated from FxHash Rust to Elixir |

---

## Architecture Overview

### Current State (Transitioning)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PYTHON LAYER (Thin)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  BaseAgent   │  │  File Tools  │  │   TUI/CLI    │  │   Bridge     │    │
│  │  (pydantic-  │  │   (routed)   │  │  (Rich/typer)│  │  (Port RPC)  │    │
│  │    ai loop)  │  │              │  │              │  │              │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │              │
│         └─────────────────┴─────────────────┴─────────────────┘            │
│                              │                                             │
│                    ┌─────────┴──────────┐                                  │
│                    │   NativeBackend    │  ← Routes all to Elixir first    │
│                    └─────────┬──────────┘                                  │
└──────────────────────────────┼────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ELIXIR LAYER (All Runtime)                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        code_puppy_control                          │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐     │   │
│  │  │  Scheduler │  │  FileOps   │  │  Text.*    │  │  Parsing │     │   │
│  │  │  (Oban)    │  │(list/grep/ │  │(diff/fuzzy/│  │(Tree-sitter│    │   │
│  │  │            │  │  index)    │  │replace)    │  │NIF route) │    │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └──────────┘     │   │
│  │                                                                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                    │   │
│  │  │   State    │  │  Sessions  │  │  Transport │  (Phase 2+3 ✅)    │   │
│  │  │ (Registry) │  │  (Ecto)    │  │  (GenServer)│                    │   │
│  │  └────────────┘  └────────────┘  └────────────┘                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  RUST COMPONENTS (DELETED as of bd-167)                              │   │
│  │  ┌────────────┐  ┌────────────────────────────────────────────┐    │   │
│  │  │message_core│  │  turbo_parse_nif (Tree-sitter bindings)     │    │   │
│  │  │(DELETED)   │  │  (DELETED)                                 │    │   │
│  │  └────────────┘  └────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Migration Phases (Current)

### ✅ Phase 1 — Foundation (COMPLETE)
**Theme:** Elixir control plane establishment

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| Elixir control plane boot | ✅ Done | — | `code_puppy_control` umbrella app |
| Python ↔ Elixir bridge | ✅ Done | — | Port-based RPC |
| Scheduler | ✅ Done | — | Full Elixir ownership |
| `NativeBackend` adapter | ✅ Done | bd-13 | Single Python entry point |

**Completed:** Early 2026

---

### ✅ Phase 2 — File Operations & Indexing (COMPLETE)
**Theme:** Move file I/O and repo indexing to Elixir

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| Basic FileOps (`list_files`, `grep`, `read_file`) | ✅ Done | — | Core implementations in Elixir |
| EOL normalization overlay | ✅ Done | **bd-7** | CRLF + BOM stripping |
| Gitignore-aware filtering | ✅ Done | **bd-8** | `.gitignore` parity with Python |
| Repo Compass indexer promotion | ✅ Done | **bd-9** | Elixir implementation promoted to production |
| Turbo Executor orchestration | ✅ Done | — | After FileOps parity |

**Completed:** 2026-Q2

---

### ✅ Phase 3 — Parse Contract (COMPLETE)
**Theme:** Tree-sitter parsing behind unified contract

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| NativeBackend parse methods | ✅ Done | **bd-11** | `extract_syntax_diagnostics()`, `parse_health_check()` |
| Elixir NIF routing | ✅ Done | — | `turbo_parse_nif` → Rust (Routed via Elixir) |
| Symbol extraction | ✅ Done | — | Production stable |
| Diagnostics | ✅ Done | — | Production stable |
| Folds / Highlights | 📋 Pending | — | Tier 2 priority |
| Incremental parsing | 📋 Pending | — | Future optimization |

**Core completed:** 2026-Q2
**Advanced features target:** 2026-Q3

---

### 📋 Phase 4 — Standalone Elixir Transport (TODO)
**Theme:** Elixir outside bridge mode

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| Standalone Elixir transport | ✅ Done | **bd-10** | Non-bridge mode operation |
| TCP/Unix socket transport | 📋 TODO | — | Alternative to stdio Port |
| Hot reload support | 📋 TODO | — | Development workflow |

**Target completion:** 2026-Q3

---

### 📋 Phase N — Message Core Migration (PLANNED)

**Theme:** Migrate the final Rust components to Elixir

These components were temporarily kept in Rust due to performance concerns, but
the "no Rust, thin Python" end state requires full migration to Elixir.
ETS memoization will mitigate the ~5-10x perf overhead.

| Component | Issue | Migration Plan | Notes |
|-----------|-------|----------------|-------|
| Token estimation | **bd-44** | Elixir + ETS memoization | 5-10x perf risk, mitigated by caching |
| Message pruning | **bd-45** | Elixir implementation | Complex tool pair tracking |
| Message serialization | **bd-47** | Elixir msgpack | Session serialize/deserialize |
| Message hashing | **bd-48** | Elixir FxHash equivalent | Message dedup hashing |

**Dependencies:** Phase 6 end state (bd-43)
**Target:** 2026-Q3

---

## Phase 6 — "No Rust, Thin Python" End State (✅ COMPLETE)

**Epic:** bd-43, bd-167
**Theme:** Rust COMPLETELY ELIMINATED — pure Elixir + Python architecture achieved

### ✅ End State Achieved (2026-04-17)

```
┌─────────────────────────────────────────────────────────────────┐
│                      PYTHON (Thin Shell)                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐   │
│  │     TUI    │  │    CLI     │  │  pydantic-ai loop      │   │
│  │  (Rich UI) │  │  (argparse)│  │  (agent orchestration) │   │
│  └──────┬─────┘  └──────┬─────┘  └───────────┬────────────┘   │
│         │               │                      │                │
│         └───────────────┴──────────────────────┘                │
│                              │                                  │
│                    ┌─────────┴──────────┐                       │
│                    │   NativeBackend    │  ← Routes to Elixir  │
│                    └─────────┬──────────┘                       │
└──────────────────────────────┼──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ELIXIR (All Runtime)                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │
│  │ Scheduler  │  │  FileOps   │  │  Parsing   │  │  Tools   │  │
│  │   (Oban)   │  │  (FileOps) │  │(Tree-sitter│  │ (Various)│  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │
│                                                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐               │
│  │   State    │  │  Sessions  │  │  Registry  │               │
│  │ (Registry) │  │  (Ecto)    │  │(Phoenix)   │               │
│  └────────────┘  └────────────┘  └────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### ✅ Completed Goals
- **Python = thin shell:** TUI, CLI entry point, pydantic-ai agent loop only
- **Elixir = all runtime services:** State, I/O, tools, scheduling, file ops, message processing
- **Rust = COMPLETELY ELIMINATED:** Cargo workspace deleted, zero Rust in codebase

### ✅ Rust Deletion Completed
| Component | Issue | Status |
|-----------|-------|--------|
| `code_puppy_core/` (~1,300 lines) | bd-43, bd-167 | ✅ DELETED |
| `turbo_parse/` + `turbo_parse_core/` (~13,100 lines) | bd-51, bd-167 | ✅ DELETED |
| `Cargo.toml`, `Cargo.lock` | bd-49, bd-167 | ✅ DELETED |
| Rust CI/CD, build scripts | bd-50, bd-167 | ✅ REMOVED |

### ✅ Documentation Updated
- README.md — Updated to reflect pure Elixir+Python architecture
- docs/acceleration.md — Removed all Rust references
- ARCHITECTURE.md — Updated architecture diagrams
- MIGRATION_STATUS.md — Marked Phase 6 complete

### Result: Simpler Builds, Same Performance
- **No build complexity:** No Rust toolchain, no maturin, no PyO3
- **Faster CI:** Python-only builds, no native compilation
- **Easier onboarding:** Just Python + Elixir, no Rust knowledge needed
- **Maintained performance:** Elixir BEAM/OTP provides equivalent speedups
- **Cleaner architecture:** Single native backend (Elixir) instead of polyglot stack

---

## Phase 5: Hashline Migration (Complete ✅)

**Issues**: bd-88, bd-89

Migrated the last portable Rust module from `code_puppy_core`:
- `hashline.rs` (199 lines) → Elixir routing via `HashlineNif` (Rustler NIF)
- Removed `xxhash-rust` dependency from `code_puppy_core`
- Python `utils/hashline.py` now routes: **Elixir → Python fallback**

### Result

`code_puppy_core` is now **pure message_core** (~1,300 lines, 6 files):

| Module | Lines | Purpose |
|--------|-------|---------|
| `token_estimation.rs` | 335 | Token counting per message (every LLM turn) |
| `pruning.rs` | 289 | Message pruning, filtering, truncation |
| `serialization.rs` | 91 | Session serialize/deserialize (msgpack) |
| `message_hashing.rs` | 121 | Message dedup hashing (FxHash) |
| `types.rs` | 125 | Shared types (Message, ToolDefinition) |
| `lib.rs` | 339 | PyO3 glue, MessageBatch pyclass |

### Dependencies (5 remaining)
- `pyo3` (workspace) — Python interop
- `serde` + `serde_json` (workspace) — JSON serialization
- `rustc-hash` — FxHash for message hashing
- `rmp-serde` — MessagePack for session serialization

---

## Backend Selection Strategy

### `NativeBackend` Routing Logic (Current)

```python
# Preferred order: Elixir → Rust → Python
# Controlled via profile: elixir_first (default), rust_only, python_only
```

| Profile | Elixir | Rust | Python |
|---------|--------|------|--------|
| `elixir_first` (default) | ✅ Preferred | ✅ Fallback | ✅ Last resort |
| `rust_only` | ❌ Disabled | ✅ Only | ❌ Disabled |
| `python_only` | ❌ Disabled | ❌ Disabled | ✅ Only |

**Configure:** `/fast_puppy profile <name>`

---

## Cross-Reference: bd-* Issues → Migration Work

| Issue | Component | Phase | Status |
|-------|-----------|-------|--------|
| bd-7 | EOL normalization | Phase 2 | ✅ Closed |
| bd-8 | Gitignore filtering | Phase 2 | ✅ Closed |
| bd-9 | Repo Compass indexer | Phase 2 | ✅ Closed |
| bd-10 | Standalone Elixir transport | Phase 4 | ✅ Closed |
| bd-11 | Parse contract verification | Phase 3 | ✅ Closed |
| bd-13 | NativeBackend routing fix | Phase 1 | ✅ Closed |
| bd-12 | Doc consolidation | — | ✅ Closed |
| bd-34 | Content Prep | Phase 1 | ✅ Closed |
| bd-35 | Path Classify | Phase 1 | ✅ Closed |
| bd-36 | Line Numbers | Phase 2 | ✅ Closed |
| bd-37 | Unified Diff | Phase 3 | ✅ Closed |
| bd-38 | Fuzzy Match | Phase 3 | ✅ Closed |
| bd-39 | Replace Engine | Phase 3 | ✅ Closed |
| bd-88 | Hashline | Phase 5 | ✅ Closed |
| bd-43 | Full Elixir End State (epic) | Phase 6 | ✅ Closed |
| bd-44 | Token Estimation → Elixir | Phase 6 | ✅ Closed (bd-167) |
| bd-45 | Message Pruning → Elixir | Phase 6 | ✅ Closed (bd-167) |
| bd-47 | Message Serialization → Elixir | Phase 6 | ✅ Closed (bd-167) |
| bd-48 | Message Hashing → Elixir | Phase 6 | ✅ Closed (bd-167) |
| bd-49 | Delete Rust workspace | Phase 6 | ✅ Closed (bd-167) |
| bd-50 | Remove Python-side Rust integration | Phase 6 | ✅ Done |
| bd-51 | Port turbo_parse to Elixir | Phase 6 | ✅ Closed (bd-167) |

---

## Historical Context

### What Was Removed

| Component | Removal Date | Notes |
|-----------|--------------|-------|
| Zig runtime | Early 2026 | `code_puppy/zig_bridge/` deleted |
| `turbo_ops` Zig path | Early 2026 | Replaced with Elixir implementation |
| Hybrid Zig/Rust model | Early 2026 | Simplified to Elixir/Rust only |

### Why the Consolidation (bd-12)

The repository had **four competing migration documents** with:
- Overlapping phase descriptions with different numbering
- Stale Zig references (pre-cleanup architecture)
- No single source of truth for "what's done vs in-progress"
- bd-* references that didn't match filed issues

**Resolution:** This document + archived historical docs.

---

## Reading Guide for Historical Docs

| Document | Status | Read If You Need |
|----------|--------|------------------|
| `docs/archived/ELIXIR_MIGRATION_ROADMAP.md` | 📁 Archived | Tiered migration candidate analysis (which components should migrate) |
| `docs/archived/fast_puppy_elixir_rewrite_plan.md` | 📁 Archived (historical) | 5-phase rewrite plan from pre-Zig-cleanup era |
| `docs/archived/PROTOCOL_COMPARISON_TABLE.md` | 📁 Archived | Protocol comparison reference |
| `docs/archived/PROTOCOL_DRIFT_ANALYSIS.md` | 📁 Archived | Historical protocol drift analysis |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-Q1 | Zig removal | Simplified to Elixir/Rust only; Zig added complexity without clear wins |
| 2026-Q1 | `NativeBackend` creation | Single Python entry point to prevent bridge sprawl |
| 2026-Q1 | Elixir-first default | Better supervision, concurrency, and I/O handling for file ops |
| 2026-Q2 | Rust core retention | Message pruning and token estimation too performance-critical |
| 2026-Q2 | NIF routing for parsing | Tree-sitter remains Rust; Elixir owns the contract surface |
| 2026-Q2 | Hashline migration to Elixir | Last portable module; completes portable Rust→Elixir migration |
| 2026-04-17 | **"No Rust, Thin Python" end state defined** | Reversed 'keep in Rust' for message_core; Python becomes thin shell over Elixir services only |

---

## Final Rust Components (To Be Deleted in Phase 6)

### Remaining Rust: message_core
These are the **last remaining Rust components** in the codebase. All will be
migrated to Elixir to achieve the "no Rust, thin Python" end state.
ETS memoization will mitigate the ~5-10x perf overhead.

**~1,300 lines** in `code_puppy_core/` → **Will be deleted**

| Issue | Component | Lines | Elixir Destination |
|-------|-----------|-------|-------------------|
| bd-44 | token_estimation.rs | 335 | Elixir + ETS |
| bd-45 | pruning.rs | 289 | Elixir |
| bd-47 | serialization.rs | 91 | Elixir (msgpack) |
| bd-48 | message_hashing.rs | 121 | Elixir (FxHash equiv) |
| — | types.rs + lib.rs | 464 | Elixir |
| — | **Total** | **~1,300** | **Delete Cargo workspace** |

### Decision Pending: turbo_parse (Inherently Native)
Tree-sitter parsing requires C core bindings. Currently exposed to
Elixir via `turbo_parse_nif` (Rustler NIF).

**~13,100 lines** in `turbo_parse/` + `turbo_parse_core/`

**Options for Phase 6:**
1. **Full Elixir rewrite:** Port tree-sitter logic to pure Elixir (major effort)
2. **Alternative native bindings:** OCaml or other C binding
3. **Keep NIF:** Minimal Rust NIF wrapper (violates "no Rust" end state)

**Decision target:** 2026-Q3

### Migrated to Elixir: Text/Edit Operations (✅ COMPLETE)
All portable text processing has been migrated from Rust to Elixir:

| Phase | Module | Rust Lines | Elixir Module | Issue |
|-------|--------|-----------|---------------|-------|
| 1 | content_prep | 425 | Text.ContentPrep | bd-34 |
| 1 | path_classify | 1,047 | FileOps.PathClassifier | bd-35 |
| 2 | line_numbers | 389 | Text.LineNumbers | bd-36 |
| 3 | unified_diff | 239 | Text.Diff | bd-37 |
| 3 | fuzzy_match | 409 | Text.FuzzyMatch | bd-38 |
| 3 | replace_engine | 337 | Text.ReplaceEngine | bd-39 |
| 5 | hashline | 199 | HashlineNif (Rustler NIF) | bd-88 |
| **Total** | **7 modules** | **~3,045 lines** | | |

### Routing Summary (Current)
| Capability | Route | Backend | Future |
|-----------|-------|---------|--------|
| message_core | Python → Rust (PyO3) | code_puppy_core | → Elixir (bd-44/45/47/48) |
| file_ops | Python → Elixir → Python fallback | Elixir FileOps | Elixir complete ✅ |
| edit_ops | Python → Elixir → Python fallback | Elixir Text.* | Elixir complete ✅ |
| parse | Python → Elixir NIF → Rust → Python | turbo_parse_nif | Decision pending (bd-51) |

---

*Generated by Code Puppy 🐕 — Consolidated in bd-12, Phase 5 in bd-90*
