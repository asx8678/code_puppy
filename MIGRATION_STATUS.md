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
| Elixir NIF routing | ✅ Done | — | Routed via Elixir |
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

`code_puppy_core` has been **DELETED** as of bd-167 (2026-04-17). All components
migrated to Elixir:

| Module | Lines | Destination | Status |
|--------|-------|-------------|--------|
| `token_estimation.rs` | 335 | Elixir + ETS | ✅ Migrated |
| `pruning.rs` | 289 | Elixir GenServer | ✅ Migrated |
| `serialization.rs` | 91 | Elixir (msgpack) | ✅ Migrated |
| `message_hashing.rs` | 121 | Elixir (FxHash equiv) | ✅ Migrated |
| `types.rs` + `lib.rs` | 464 | Elixir structs | ✅ Migrated |

**Total: ~1,300 lines DELETED** — Cargo workspace removed.

---

## Backend Selection Strategy

### `NativeBackend` Routing Logic (Current)

```python
# Preferred order: Elixir → Python fallback
# Controlled via profile: elixir_first (default), python_only
```

| Profile | Elixir | Python |
|---------|--------|--------|
| `elixir_first` (default) | ✅ Preferred | ✅ Fallback |
| `python_only` | ❌ Disabled | ✅ Only |

**Configure:** `/fast_puppy profile <name>`

> **Note:** `rust_only` profile removed — Rust completely eliminated (bd-167).

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


Elixir pup-ex uses `~/.code_puppy_ex/` (not `~/.code_puppy/`) as its home directory.
Isolation is enforced via guard wrappers (`safe_write!`, `safe_mkdir_p!`, etc.)
that raise `ConfigIsolationViolation` on any write to the legacy home.

| Aspect | Decision |
|--------|----------|
| Elixir home | `~/.code_puppy_ex/` (or `PUP_EX_HOME` env var) |
| Legacy home | `~/.code_puppy/` — READ-ONLY, import only |
| Import | `mix pup_ex.import` — opt-in, allowlisted files only |
| Guard module | `CodePuppyControl.Config.Isolation` |
| ADR | [`docs/adr/ADR-003-dual-home-config-isolation.md`](docs/adr/ADR-003-dual-home-config-isolation.md) |

**Phase progress:**

| Phase | Status | Commit | Description |
|:-:|:-:|--------|-------------|
| 1 — ADR | ✅ | (pre-existing) | ADR-003 design doc accepted 2026-04-19 |
| 2a — Paths + Isolation guard | ✅ | [`86b05f29`](../../commit/86b05f29) | 52 tests, symlink defense, telemetry |
| 2b — Route hardcoded callsites | ✅ | [`2ea04ea9`](../../commit/2ea04ea9) | 8 violation sites routed through Paths |
| 3 — First-run + CLI | ✅ | [`438685ac`](../../commit/438685ac) | mix pup_ex.import/doctor/auth.login + 46 tests |
| 4 — CI isolation gates | ✅ | [`b692dfdb`](../../commit/b692dfdb) | 8 gate tests + GitHub Actions workflow |
| 5 — Docs | 🟡 In progress | — | This update |
| 6 — Review + close | ⏳ Pending | — | elixir-reviewer + security-auditor + bd close |

**5 ADR CI gates — all passing:**
- ✅ GATE-1 (no-write): Fake legacy home byte-identical before/after realistic operations
- ✅ GATE-2 (guard raises): `safe_write!` raises `IsolationViolation` on legacy paths
- ✅ GATE-3 (import opt-in): Default mode is dry-run; `--confirm` required to copy
- ✅ GATE-4 (doctor passes): `mix pup_ex.doctor` reports ISOLATED on healthy env
- ✅ GATE-5 (paths audit): All 20 `Paths.*_dir/*_file` functions resolve under Elixir home

Unblocks Phase 4 of the rewrite: bd-164 (config.py port), bd-165 (sessions),
bd-166 (OAuth), bd-167 (secrets), bd-184 (config compat tests).

---

*Generated by Code Puppy 🐕 — Consolidated in bd-12, Phase 5 in bd-90*
