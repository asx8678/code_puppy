# Migration Status: Single Source of Truth

> **Document purpose:** Consolidated view of Python → Elixir → Rust runtime migration.
> **Last updated:** 2026-04-16 (bd-12)
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
| Hashline computation | Fast enough in Rust | xxHash32 stable |

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
| bd-39 | Replace Engine | Phase 3 | ✅ Closed |

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

---

*Generated by Code Puppy 🐕 — Consolidated in bd-12*
