# 🚀 Rust → Elixir Migration Roadmap — ARCHIVED

> **⚠️ HISTORICAL DOCUMENT — ARCHIVED 2026-04-16 (bd-12)**
> 
> This document is preserved for historical reference. It contains the tiered migration candidate analysis.
> 
> **Current status:** See **`MIGRATION_STATUS.md`** for the single source of truth.
> 
> **What's in this doc:** Analysis of which components should/shouldn't migrate to Elixir, with tiered recommendations.

---

# 🚀 Rust → Elixir Migration Roadmap (Historical Content)

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PYTHON LAYER                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  BaseAgent   │  │  File Tools  │  │  Hashline    │  │  Parsing     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │                 │            │
│         └─────────────────┴─────────────────┴─────────────────┘            │
│                              │                                           │
│                    ┌─────────┴──────────┐                                │
│                    │   NativeBackend    │                                │
│                    └─────────┬──────────┘                                │
└──────────────────────────────┼──────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
┌────────▼────────┐   ┌────────▼────────┐   ┌────────▼────────┐
│   RUST (Hot)    │   │  RUST (Parse)   │   │  ELIXIR (Warm)  │
│ code_puppy_core │   │  turbo_parse    │   │ code_puppy_ctl  │
│                 │   │                 │   │                 │
│ • Message prune │   │ • Tree-sitter   │   │ • File ops      │
│ • Token estim.  │   │ • Symbols       │   │ • Grep/list     │
│ • Hashline      │   │ • Diagnostics   │   │ • Indexing      │
│ • Truncation    │   │ • Folds         │   │ • Scheduler     │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## Migration Candidates (Ranked by Feasibility)

### ✅ **TIER 1: Easy Wins** (Low Risk, Clear Value)

#### 1. **Hashline Computation** → Elixir NIF
**Current:** `code_puppy_core/src/hashline.rs` (uses xxHash32)
**Effort:** Medium (2-3 days)
**Value:** Medium

**Why migrate:**
- Simple computation (hash line content + index)
- Elixir's binary pattern matching is excellent for this
- Could use `:crypto.hash/2` or xxHash NIF

**Blockers:**
- xxHash32 availability (but can use SHA256 or other hash)
- Performance not critical (called per line, but not in hot loop)

**Migration path:**
```elixir
# Elixir implementation
defmodule Hashline do
  def compute_line_hash(index, line) do
    cleaned = String.trim_trailing(line, ["\r", " ", "\t", "\n"])
    seed = if has_alphanumeric?(cleaned), do: 0, else: index
    
    :crypto.hash(:sha256, <<seed::32, cleaned::binary>>)
    |> binary_part(0, 2)  # Take first 2 bytes → 2-char hash
    |> encode_nibbles()
  end
end
```

**Recommendation:** ✅ **DO IT** - Good starter project

---

#### 2. **Tree-sitter Parsing** → Elixir NIF
**Current:** `turbo_parse` crate
**Effort:** High (1-2 weeks)
**Value:** High

**Why migrate:**
- Elixir already has `tree_sitter` hex package
- Can use tree-sitter directly from Elixir
- Async-friendly (parsing can be done in separate processes)
- Better integration with Elixir supervision tree

**Blockers:**
- Need to ensure tree-sitter grammars are available
- Some languages may need custom grammars
- Performance parity testing required

**Existing work:** There's already `native/turbo_parse_nif/` in the Elixir codebase!

**Recommendation:** ✅ **IN PROGRESS** - Already started

---

### ⚠️ **TIER 2: Maybe** (Needs Careful Evaluation)

#### 3. **Token Estimation** → Elixir (with Rust NIF for hot path)
**Current:** `code_puppy_core/src/token_estimation.rs`
**Effort:** High
**Value:** Medium

**Why stay in Rust:**
- Extremely hot path (called on EVERY message batch)
- Token estimation needs to be < 1ms for good UX
- Pure Elixir might be too slow (5-10x slower than Rust)

**Hybrid approach:**
- Keep core estimation in Rust NIF
- Move batch orchestration to Elixir

**Recommendation:** ❌ **DON'T** - Too performance-critical

---

#### 4. **Message Serialization** → Elixir
**Current:** `code_puppy/_core_bridge.py::serialize_message_for_rust()`
**Effort:** Medium
**Value:** Low

**Why stay in Python:**
- Already works well
- Pydantic-AI objects are Python-native
- Elixir would need JSON-RPC bridge, adding latency

**Recommendation:** ❌ **DON'T** - No clear benefit

---

### 🚫 **TIER 3: Don't Migrate** (High Risk / Low Value)

#### 5. **Message Pruning/Truncation** 
**Current:** `code_puppy_core/src/pruning.rs`
**Effort:** Very High
**Value:** Negative (would slow down)

**Why keep in Rust:**
- Critical path for every agent run
- Complexity (tool pair tracking, thinking parts, etc.)
- Rust's zero-cost abstractions shine here
- Elixir NIF would still need Rust code anyway

**Recommendation:** 🚫 **DEFINITELY NOT** - Core performance path

---

#### 6. **Summarization Split Logic**
**Current:** `split_for_summarization` in Rust
**Effort:** High
**Value:** Low

**Why keep in Rust:**
- Complex algorithm with tight performance requirements
- Needs to process potentially 100K+ tokens
- Rust's memory layout is optimal for this

**Recommendation:** 🚫 **NO** - Complexity not worth it

---

## Recommended Migration Priority

| Priority | Component | Effort | Impact | Status |
|----------|-----------|--------|--------|--------|
| 1 | **Hashline** | 2-3 days | Medium | Not started |
| 2 | **Tree-sitter (turbo_parse)** | 1-2 weeks | High | In Progress |
| 3 | **Scheduler** | N/A | N/A | ✅ Done in Elixir |
| 4 | **File Ops** | N/A | N/A | ✅ Done in Elixir |
| 5 | **Token Estimation** | 1 week | Low | Keep in Rust |
| 6 | **Message Pruning** | 2 weeks | Negative | Keep in Rust |

---

## Technical Considerations

### What Makes a Good Elixir Migration Target?

✅ **Good candidates:**
- I/O bound operations (file ops, network)
- Async-friendly workloads
- Lower performance requirements (> 10ms acceptable)
- State machines / process supervision needs
- Clear failure modes (can crash and restart)

❌ **Bad candidates:**
- CPU-bound hot paths (< 1ms target)
- Complex data structure manipulation
- Heavy string/binary processing in tight loops
- Zero-copy requirements

### NIF Strategy

For things that must be fast AND in Elixir, use Rustler:

```elixir
# In mix.exs
{:rustler, "~> 0.30", runtime: false}

# lib/hashline_nif.ex
defmodule HashlineNif do
  use Rustler, otp_app: :code_puppy_control, crate: "hashline"
  
  def compute_line_hash(_index, _line), do: :erlang.nif_error(:nif_not_loaded)
end
```

```rust
// native/hashline/src/lib.rs
use rustler::{Encoder, Env, Term};

#[rustler::nif]
fn compute_line_hash(env: Env, index: i64, line: &str) -> Term {
    // xxHash32 implementation
    let hash = xxhash_rust::xxh32::xxh32(line.as_bytes(), index as u32);
    let encoded = encode_nibbles(hash as u8);
    encoded.encode(env)
}
```

---

## Migration Phases

### Phase 1: Hashline (Week 1-2)
1. Create `native/hashline_nif/` Rustler project
2. Port xxHash32 logic
3. Update `hashline.py` to use Elixir bridge when available
4. Benchmark vs pure Python and Rust

### Phase 2: Tree-sitter (Week 3-4)
1. Complete existing `native/turbo_parse_nif/`
2. Add missing tree-sitter grammars
3. Port Python bridge to use Elixir endpoint
4. Test with all supported languages

### Phase 3: Evaluation (Week 5)
1. Measure performance deltas
2. Document trade-offs
3. Decide on further migrations

---

## Summary

**The only strong candidates for Elixir migration are:**
1. ✅ **Hashline** - Simple, not ultra-hot path
2. ✅ **Tree-sitter** - Already in progress, good async fit

**Keep in Rust:**
- Message pruning/truncation (performance-critical)
- Token estimation (hot path)
- Complex serialization (Python-native ecosystem)

**Conclusion:** The Rust → Elixir migration is mostly complete with file ops and scheduler. The remaining Rust code (`code_puppy_core`) is **correctly placed** for performance reasons. Future work should focus on:
1. Completing the tree-sitter NIF
2. Adding hashline NIF if needed
3. Optimizing the Elixir → Python bridge protocol

---

*Generated by Code Puppy 🐕 - Architected on a rainy weekend*
