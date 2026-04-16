# Migration Status: Single Source of Truth

> **Document purpose:** Consolidated view of Python → Elixir → Rust runtime migration.
> **Last updated:** 2026-04-16 (bd-90 - Phase 5 complete)
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
| **File Operations** | 🔄 IN-PROGRESS | Elixir | bd-7, bd-8 | EOL + gitignore pending |
| **Repo Compass Indexer** | 🔄 IN-PROGRESS | Elixir | bd-9 | Elixir implementation exists, needs promotion |
| **Tree-sitter Parsing** | 🔄 IN-PROGRESS | Rust NIF | bd-11 | NativeBackend contract complete |
| **Message Core** | ✅ DONE | Rust | — | `code_puppy_core` stable |
| **Elixir Transport** | 📋 TODO | Elixir | bd-10 | Standalone outside bridge mode |
| **Replace Engine** | ✅ DONE | Elixir | bd-39 | Migrated from Rust, 2026-04-16 |
| **Hashline** | ✅ DONE | Elixir (Rustler NIF) | bd-88 | Migrated from Rust, 2026-04-16 |
| **Token Estimation** | 🚫 NO MIGRATION | Rust | — | Too hot path, keep Rust |
| **Message Pruning** | 🚫 NO MIGRATION | Rust | — | Performance-critical, keep Rust |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PYTHON LAYER                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  BaseAgent   │  │  File Tools  │  │  Hashline    │  │  Parsing     │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │              │
│         └─────────────────┴─────────────────┴─────────────────┘            │
│                              │                                             │
│                    ┌─────────┴──────────┐                                  │
│                    │   NativeBackend    │  ← Single Python entry point      │
│                    └─────────┬──────────┘                                  │
└──────────────────────────────┼────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
┌────────▼────────┐   ┌────────▼────────┐   ┌────────▼────────┐
│   RUST (Hot)    │   │  RUST (Parse)   │   │  ELIXIR (Warm)  │
│ code_puppy_core │   │  turbo_parse    │   │code_puppy_control│
│                 │   │                 │   │                 │
│ • Message prune │   │ • Tree-sitter   │   │ • File ops      │
│ • Token estim.  │   │ • Symbols       │   │ • Grep/list     │
│ • Hashline      │   │ • Diagnostics   │   │ • Indexing      │
│ • Truncation    │   │ • Folds         │   │ • Scheduler     │
└─────────────────┘   └─────────────────┘   └─────────────────┘
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

### 🔄 Phase 2 — File Operations & Indexing (IN-PROGRESS)
**Theme:** Move file I/O and repo indexing to Elixir

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| Basic FileOps (`list_files`, `grep`, `read_file`) | ✅ Done | — | Core implementations in Elixir |
| EOL normalization overlay | 🔄 Active | **bd-7** | CRLF + BOM stripping |
| Gitignore-aware filtering | 🔄 Active | **bd-8** | `.gitignore` parity with Python |
| Repo Compass indexer promotion | 🔄 Active | **bd-9** | Elixir implementation ready, needs production wiring |
| Turbo Executor orchestration | 📋 Pending | — | After FileOps parity |

**Target completion:** 2026-Q2

---

### 🔄 Phase 3 — Parse Contract (IN-PROGRESS)
**Theme:** Tree-sitter parsing behind unified contract

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| NativeBackend parse methods | ✅ Done | (pre-bd-11) | `extract_syntax_diagnostics()`, `parse_health_check()` |
| Elixir NIF routing | ✅ Done | (pre-bd-11) | `turbo_parse_nif` → Rust |
| Symbol extraction | ✅ Done | (pre-bd-11) | Production stable |
| Diagnostics | ✅ Done | (pre-bd-11) | Production stable |
| Folds / Highlights | 📋 Pending | — | Tier 2 priority |
| Incremental parsing | 📋 Pending | — | Future optimization |

**Target completion:** 2026-Q2 (core), 2026-Q3 (advanced features)

---

### 📋 Phase 4 — Standalone Elixir Transport (TODO)
**Theme:** Elixir outside bridge mode

| Item | Status | Issue | Notes |
|------|--------|-------|-------|
| Standalone Elixir transport | 📋 TODO | **bd-10** | Non-bridge mode operation |
| TCP/Unix socket transport | 📋 TODO | — | Alternative to stdio Port |
| Hot reload support | 📋 TODO | — | Development workflow |

**Target completion:** 2026-Q3

---

### 🚫 Phase N — Keep in Rust (NO MIGRATION PLANNED)
**Theme:** Performance-critical components staying in Rust

| Component | Reason | Notes |
|-----------|--------|-------|
| Message pruning/truncation | Hot path (< 1ms target) | Complex tool pair tracking |
| Token estimation | Hot path | 5-10x slower in pure Elixir |

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
| bd-7 | EOL normalization | Phase 2 | 🔄 Open |
| bd-8 | Gitignore filtering | Phase 2 | 🔄 Open |
| bd-9 | Repo Compass indexer | Phase 2 | 🔄 Open |
| bd-10 | Standalone Elixir transport | Phase 4 | 🔄 Open |
| bd-11 | Parse contract verification | Phase 3 | 🔄 Open |
| bd-13 | NativeBackend routing fix | Phase 1 | ✅ Closed |
| bd-12 | Doc consolidation | — | ✅ Closed |
| bd-34 | Content Prep | Phase 1 | ✅ Closed |
| bd-35 | Path Classify | Phase 1 | ✅ Closed |
| bd-36 | Line Numbers | Phase 2 | ✅ Closed |
| bd-37 | Unified Diff | Phase 3 | ✅ Closed |
| bd-38 | Fuzzy Match | Phase 3 | ✅ Closed |
| bd-39 | Replace Engine | Phase 3 | ✅ Closed |
| bd-88 | Hashline | Phase 5 | ✅ Closed |

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
| `ELIXIR_MIGRATION_ROADMAP.md` | 📁 Archived | Tiered migration candidate analysis (which components should migrate) |
| `fast_puppy_elixir_rewrite_plan.md` | 📁 Archived (historical) | 5-phase rewrite plan from pre-Zig-cleanup era |
| `rewrite/ELIXIR_FIRST_REWRITE_ANALYSIS.md` | 📁 Archived | Why Repo Compass was picked as first migration slice |
| `rewrite/code_puppy_elixir_rewrite_bundle/PLAN/...` | 📁 Archived | Detailed PR sequence for practical migration |

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

---

## Final Rust Architecture

### Stays as Rust: message_core (Performance Critical)
Token estimation, pruning, serialization, and message hashing run on
EVERY LLM turn in the hot path. Elixir would add ~5-10x overhead for
these CPU-bound string/hash operations.

**~1,300 lines** in `code_puppy_core/`

### Stays as Rust: turbo_parse (Inherently Native)
Tree-sitter parsing requires C/Rust native code. Already exposed to
Elixir via `turbo_parse_nif` (Rustler NIF).

**~13,100 lines** in `turbo_parse/` + `turbo_parse_core/`

### Migrated to Elixir: Text/Edit Operations
All text processing that was in Rust has been migrated:

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
| Capability | Route | Backend |
|-----------|-------|---------|
| message_core | Python → Rust (PyO3) | code_puppy_core |
| file_ops | Python → Elixir → Python fallback | Elixir FileOps |
| edit_ops | Python → Elixir → Python fallback | Elixir Text.* |
| parse | Python → Elixir NIF → Rust → Python | turbo_parse_nif |

---

*Generated by Code Puppy 🐕 — Consolidated in bd-12, Phase 5 in bd-90*
