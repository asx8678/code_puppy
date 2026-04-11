# Speed Improvement: Rewrite Hot Paths in Rust (PyO3)

## Purpose

This document instructs an AI agent to create a Rust extension module (`_code_puppy_core`) that replaces the CPU-bound hot paths in Code Puppy's message processing pipeline. The goal is a 10-30x speedup on the per-turn message processing that runs every LLM interaction.

## Workspace Structure (April 2025)

The repository uses a Cargo workspace with pyo3 managed at the workspace level:

```toml
[workspace]
members = ["code_puppy_core", "turbo_ops", "turbo_parse"]
resolver = "2"

[workspace.dependencies]
pyo3 = { version = "0.28", features = ["extension-module", "serde"] }
```

All workspace crates inherit pyo3 via `pyo3 = { workspace = true }` for consistent versioning.

---

## Context: What Code Puppy Is

Code Puppy is a CLI-based AI coding agent (Python 3.11+, entry point `code_puppy/main.py` -> `code_puppy/cli_runner.py`). The core loop is:

1. User enters prompt in REPL
2. `BaseAgent.run_with_mcp()` calls `pydantic_ai.Agent.run()` which streams LLM responses
3. On **every turn** (user message or tool call), pydantic-ai invokes `message_history_accumulator()` -> `message_history_processor()` to process the full message history
4. This involves token estimation, message hashing, dedup, pruning, and optional compaction

The message types come from `pydantic_ai.messages`: `ModelRequest`, `ModelResponse`, `TextPart`, `ToolCallPart`, `ToolReturnPart`, `ThinkingPart`, etc.

---

## The Bottlenecks (measured by call frequency x cost)

### Bottleneck 1: Token Estimation

**File**: `code_puppy/agents/base_agent.py`

**Current code** (called every turn, O(messages * parts)):

```python
# Line 454-459
def estimate_token_count(self, text: str) -> int:
    return max(1, math.floor((len(text) / 2.5)))

# Line 461-473
def estimate_tokens_for_message(self, message: ModelMessage) -> int:
    total_tokens = 0
    for part in message.parts:
        part_str = self.stringify_message_part(part)
        if part_str:
            total_tokens += self.estimate_token_count(part_str)
    return max(1, total_tokens)
```

**The expensive part** is `stringify_message_part()` (lines 408-452) which does:
- `hasattr()` checks on every part
- `json.dumps(part.content.model_dump())` for Pydantic models
- `json.dumps(part.content)` for dicts
- String concatenation for tool names + args
- Called for EVERY part of EVERY message, EVERY turn

**Also**: `estimate_context_overhead_tokens()` (lines 475-579) recomputes system prompt + all tool schema token counts every turn. It iterates all registered tools and MCP tools, calling `json.dumps()` on each schema.

### Bottleneck 2: Message Hashing

**File**: `code_puppy/agents/base_agent.py`

**`_stringify_part()`** (lines 349-390):
```python
def _stringify_part(self, part: Any) -> str:
    attributes: List[str] = [part.__class__.__name__]
    if hasattr(part, "role") and part.role:
        attributes.append(f"role={part.role}")
    if hasattr(part, "instructions") and part.instructions:
        attributes.append(f"instructions={part.instructions}")
    if hasattr(part, "tool_call_id") and part.tool_call_id:
        attributes.append(f"tool_call_id={part.tool_call_id}")
    if hasattr(part, "tool_name") and part.tool_name:
        attributes.append(f"tool_name={part.tool_name}")
    # ... content handling with json.dumps for dicts/models ...
    result = "|".join(attributes)
    return result
```

**`hash_message()`** (lines 392-406):
```python
def hash_message(self, message: Any) -> int:
    role = getattr(message, "role", None)
    instructions = getattr(message, "instructions", None)
    header_bits: List[str] = []
    if role:
        header_bits.append(f"role={role}")
    if instructions:
        header_bits.append(f"instructions={instructions}")
    part_strings = [self._stringify_part(part) for part in getattr(message, "parts", [])]
    canonical = "||".join(header_bits + part_strings)
    return hash(canonical)
```

**Called from `message_history_accumulator()`** (line 1582):
```python
message_history_hashes = set([self.hash_message(m) for m in _message_history])
```

This hashes the ENTIRE history every turn. For 200 messages with 5 parts each, that's 1000 `_stringify_part()` calls per turn.

### Bottleneck 3: Tool Call Pruning

**`prune_interrupted_tool_calls()`** (lines 987-1033) runs 3+ times per turn:
1. In `message_history_processor()` (line 1038 area - via filter paths)
2. In `filter_huge_messages()` (line 658)
3. In `run_with_mcp()` finally block (line 2006)
4. In `run_with_mcp()` at start (line 1887)

Each call does two O(n) passes over all messages scanning every part for `tool_call_id`.

### Bottleneck 4: Session Serialization

**File**: `code_puppy/session_storage.py` (lines 83-117)

```python
def save_session(*, history, session_name, base_dir, timestamp, token_estimator, ...):
    pickle_data = pickle.dumps(history)       # Full re-pickle every time
    # ... write to disk ...
    total_tokens = sum(token_estimator(message) for message in history)  # Re-estimate all tokens
```

Called after every interaction via `auto_save_session_if_enabled()`. Full pickle of entire history + full token re-estimation.

---

## What to Build

### Rust Extension Module: `_code_puppy_core`

Create a Rust crate using PyO3 and maturin that exposes these Python-callable functions. The module should be importable as `import _code_puppy_core` from Python.

### Directory Structure

```
code_puppy_core/
    Cargo.toml
    pyproject.toml          # maturin build config
    src/
        lib.rs              # PyO3 module definition
        token_estimation.rs # Token counting + message stringification
        message_hashing.rs  # Fast hashing with FxHash
        pruning.rs          # Single-pass prune + filter
        serialization.rs    # MessagePack-based session serialization
```

Also create a Python wrapper module for fallback:
```
code_puppy/
    _core_bridge.py         # try import _code_puppy_core, fallback to Python
```

### Cargo.toml

```toml
[package]
name = "code_puppy_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "_code_puppy_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.24", features = ["extension-module"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
rustc-hash = "2"           # FxHashMap/FxHashSet - fast non-crypto hashing
rmp-serde = "1"             # MessagePack serialization
```

### pyproject.toml (for the Rust crate)

```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[tool.maturin]
features = ["pyo3/extension-module"]
```

---

## Function Specifications

### Function 1: `process_messages_batch()`

**Purpose**: Replaces `estimate_tokens_for_message()`, `hash_message()`, `estimate_context_overhead_tokens()` with a single-pass batch operation.

**Python signature**:
```python
def process_messages_batch(
    messages: list[dict],           # Serialized message data (see format below)
    tool_definitions: list[dict],   # Tool name + description + schema
    mcp_tool_definitions: list[dict], # MCP tool definitions
    system_prompt: str,             # Current system prompt/instructions
) -> ProcessResult:
    """
    Returns:
        ProcessResult with fields:
            per_message_tokens: list[int]    # Token count per message
            total_message_tokens: int        # Sum of all message tokens
            context_overhead_tokens: int     # Tokens from tools + system prompt
            message_hashes: list[int]        # Stable hash per message (i64)
    """
```

**Message serialization format** (Python side converts pydantic-ai messages to this before calling Rust):

```python
# Each message dict looks like:
{
    "kind": "request" | "response",
    "role": str | None,
    "instructions": str | None,
    "parts": [
        {
            "part_kind": "text" | "tool-call" | "tool-return" | "thinking" | ...,
            "content": str | None,         # Text content if available
            "content_json": str | None,    # Pre-serialized JSON for dicts/models
            "tool_call_id": str | None,
            "tool_name": str | None,
            "args": str | None,            # Tool args as string
        },
        ...
    ]
}
```

**Token estimation logic** (replicate in Rust):
```
tokens = max(1, floor(len(stringified_part) / 2.5))
```

**Hashing logic** (replicate in Rust, using FxHash instead of Python hash):
- Build canonical string: `"||".join(header_bits + [stringify_part(p) for p in parts])`
- Header bits: `role={role}` if role, `instructions={instructions}` if instructions
- Part string: `"{ClassName}|role={role}|instructions={instructions}|tool_call_id={id}|tool_name={name}|content={content}"`
- Hash the canonical string with FxHash, return as i64

**IMPORTANT**: The hash values must be deterministic across calls but do NOT need to match the Python `hash()` values. The hashes are only compared within the same process session. When integrating, the Python side will use Rust hashes exclusively (not mix Rust and Python hashes).

### Function 2: `prune_and_filter()`

**Purpose**: Replaces `prune_interrupted_tool_calls()` + ThinkingPart filtering + `ensure_history_ends_with_request()` + `filter_huge_messages()` in a single pass.

**Python signature**:
```python
def prune_and_filter(
    messages: list[dict],              # Same serialized format as above
    compacted_hashes: set[int],        # Hashes of already-compacted messages
    max_tokens_per_message: int = 50000, # filter_huge_messages threshold
) -> PruneResult:
    """
    Returns:
        PruneResult with fields:
            surviving_indices: list[int]   # Indices of messages that survived
            dropped_count: int             # Number of messages dropped
            had_pending_tool_calls: bool   # Whether unmatched tool calls exist
            pending_tool_call_count: int   # Count of pending tool calls
    """
```

**Logic to replicate** (single pass):

1. **Collect all tool_call_ids and tool_return_ids** from all parts of all messages
2. **Compute mismatched set** = symmetric_difference of call_ids and return_ids
3. **Filter out messages** where any part has a tool_call_id in the mismatched set
4. **Filter out messages** with estimated tokens > `max_tokens_per_message`
5. **Filter out single-part messages** that are empty ThinkingParts (`part_kind == "thinking"` and content is empty/None)
6. **For multi-part messages**, note which ones need ThinkingPart stripping (return this info so Python can do the `dataclasses.replace()`)
7. **Trim trailing responses**: if last surviving message has `kind == "response"`, exclude it (repeat until last is "request" or empty)
8. **Return surviving indices** (Python uses these to slice the original message list, preserving the actual pydantic-ai objects)

### Function 3: `truncation_indices()`

**Purpose**: Replaces `truncation()` method - determines which messages to keep during truncation compaction.

**Python signature**:
```python
def truncation_indices(
    per_message_tokens: list[int],   # From process_messages_batch()
    protected_tokens: int,           # User-configured protected token count
    second_has_thinking: bool,       # Whether message[1] contains ThinkingPart
) -> list[int]:
    """
    Returns indices of messages to keep.
    Always keeps index 0 (system prompt).
    Keeps index 1 if second_has_thinking is True.
    Then keeps most recent messages up to protected_tokens budget.
    """
```

### Function 4: `serialize_session()` and `deserialize_session()`

**Purpose**: Replace pickle with faster MessagePack serialization.

**Python signature**:
```python
def serialize_session(messages: list[dict]) -> bytes:
    """Serialize message history to MessagePack bytes."""

def deserialize_session(data: bytes) -> list[dict]:
    """Deserialize MessagePack bytes back to message dicts."""

def serialize_session_incremental(
    new_messages: list[dict],
    existing_data: bytes | None,
) -> bytes:
    """Append new messages to existing serialized data."""
```

### Function 5: `split_for_summarization()`

**Purpose**: Replaces `split_messages_for_protected_summarization()` + `_find_safe_split_index()`.

**Python signature**:
```python
def split_for_summarization(
    per_message_tokens: list[int],  # From process_messages_batch()
    tool_call_ids_per_message: list[list[tuple[str, str]]],  # [(id, kind)] per message
    protected_tokens_limit: int,
) -> SplitResult:
    """
    Returns:
        SplitResult with fields:
            summarize_indices: list[int]   # Message indices to summarize
            protected_indices: list[int]   # Message indices to protect
            protected_token_count: int     # Actual tokens in protected zone
    """
```

---

## Python Integration: `_core_bridge.py`

Create `code_puppy/_core_bridge.py` that provides the fallback:

```python
"""Bridge to Rust extension module with Python fallback."""

try:
    from _code_puppy_core import (
        process_messages_batch,
        prune_and_filter,
        truncation_indices,
        serialize_session,
        deserialize_session,
        serialize_session_incremental,
        split_for_summarization,
        ProcessResult,
        PruneResult,
        SplitResult,
    )
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

# Also provide a message serialization helper used by both paths:

def serialize_message_for_rust(message) -> dict:
    """Convert a pydantic-ai ModelMessage to the dict format expected by Rust functions.

    This is the ONLY place where pydantic-ai message objects are converted to dicts.
    The Rust module never touches pydantic-ai objects directly.
    """
    from pydantic_ai.messages import ModelRequest, ModelResponse

    kind = "request" if isinstance(message, ModelRequest) else "response"
    role = getattr(message, "role", None)
    instructions = getattr(message, "instructions", None)

    parts = []
    for part in getattr(message, "parts", []):
        part_dict = {
            "part_kind": getattr(part, "part_kind", str(type(part).__name__)),
            "content": None,
            "content_json": None,
            "tool_call_id": getattr(part, "tool_call_id", None),
            "tool_name": getattr(part, "tool_name", None),
            "args": str(getattr(part, "args", "")) if hasattr(part, "args") else None,
        }

        content = getattr(part, "content", None)
        if content is None:
            pass
        elif isinstance(content, str):
            part_dict["content"] = content
        elif isinstance(content, list):
            # Handle list content (may contain strings and BinaryContent)
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                # Skip BinaryContent for token estimation (just note its presence)
            part_dict["content"] = "\n".join(text_parts) if text_parts else None
        else:
            # Dicts, Pydantic models, other - serialize to JSON string
            import json
            try:
                if hasattr(content, "model_dump"):
                    part_dict["content_json"] = json.dumps(content.model_dump(), sort_keys=True)
                elif isinstance(content, dict):
                    part_dict["content_json"] = json.dumps(content, sort_keys=True)
                else:
                    part_dict["content"] = repr(content)
            except (TypeError, ValueError):
                part_dict["content"] = repr(content)

        parts.append(part_dict)

    return {
        "kind": kind,
        "role": role,
        "instructions": instructions,
        "parts": parts,
    }


def serialize_messages_for_rust(messages: list) -> list[dict]:
    """Batch convert messages for Rust consumption."""
    return [serialize_message_for_rust(m) for m in messages]
```

---

## Integration Points in Existing Code

### 1. Replace `message_history_processor()` internals

**File**: `code_puppy/agents/base_agent.py`, method `message_history_processor()` (line 1035)

**Current flow**:
```python
message_tokens = sum(self.estimate_tokens_for_message(msg) for msg in messages)
context_overhead = self.estimate_context_overhead_tokens()
total_current_tokens = message_tokens + context_overhead
proportion_used = total_current_tokens / model_max
```

**New flow**:
```python
from code_puppy._core_bridge import RUST_AVAILABLE, process_messages_batch, serialize_messages_for_rust

if RUST_AVAILABLE:
    serialized = serialize_messages_for_rust(messages)
    result = process_messages_batch(serialized, tool_defs, mcp_tool_defs, system_prompt)
    message_tokens = result.total_message_tokens
    context_overhead = result.context_overhead_tokens
    # Cache per_message_tokens and message_hashes for use in other methods
    self._cached_per_message_tokens = result.per_message_tokens
    self._cached_message_hashes = result.message_hashes
else:
    # Original Python path
    message_tokens = sum(self.estimate_tokens_for_message(msg) for msg in messages)
    context_overhead = self.estimate_context_overhead_tokens()
```

### 2. Replace `message_history_accumulator()` hashing

**File**: `code_puppy/agents/base_agent.py`, method `message_history_accumulator()` (line 1572)

**Current**:
```python
message_history_hashes = set([self.hash_message(m) for m in _message_history])
```

**New**: Use `self._cached_message_hashes` from the batch call, or call `process_messages_batch()` if cache is stale.

### 3. Replace `prune_interrupted_tool_calls()` calls

All 3-4 call sites should call `prune_and_filter()` ONCE and reuse the result indices.

### 4. Replace `truncation()` method

Use `truncation_indices()` from Rust, then slice the original Python message list.

### 5. Replace session pickle in `session_storage.py`

Use `serialize_session()` / `deserialize_session()` with the dict format.

---

## Build Integration

### Add to project root `pyproject.toml`

The Rust crate has its own `pyproject.toml` in `code_puppy_core/`. To build:

```bash
cd code_puppy_core
maturin develop --release   # For local development
maturin build --release     # For distributable wheels
```

### Optional dependency approach

Keep the Rust module as an optional accelerator. The app works without it (Python fallback). Add to main `pyproject.toml`:

```toml
[project.optional-dependencies]
fast = ["code-puppy-core"]  # The built Rust wheel
```

---

## Testing Strategy

### 1. Correctness tests

For each Rust function, write a Python test that:
- Calls the Rust version with sample data
- Calls the equivalent Python version with the same data
- Asserts the results match (token counts, surviving indices, etc.)

Note: Hash VALUES don't need to match between Rust and Python (FxHash vs Python hash). But the BEHAVIOR must match: same messages should produce same hashes, different messages should produce different hashes.

### 2. Performance benchmarks

Create `tests/bench_rust_vs_python.py`:
```python
import time

def bench_token_estimation(message_count=200, parts_per_message=5):
    messages = generate_test_messages(message_count, parts_per_message)
    serialized = serialize_messages_for_rust(messages)

    # Python path
    start = time.perf_counter()
    for _ in range(100):
        for msg in messages:
            agent.estimate_tokens_for_message(msg)
    python_time = time.perf_counter() - start

    # Rust path
    start = time.perf_counter()
    for _ in range(100):
        process_messages_batch(serialized, [], [], "")
    rust_time = time.perf_counter() - start

    print(f"Python: {python_time:.3f}s, Rust: {rust_time:.3f}s, Speedup: {python_time/rust_time:.1f}x")
```

### 3. Property tests

Use `hypothesis` to generate random message structures and verify:
- Token counts are always >= 1
- Hash collisions are rare (< 0.01% for random input)
- Pruning never drops messages that should survive
- Truncation always keeps message[0]

---

## Implementation Notes

### Rust-side message deserialization

In Rust, define structs that match the Python dict format:

```rust
use pyo3::prelude::*;
use serde::Deserialize;

#[derive(Deserialize, Clone)]
struct MessagePart {
    part_kind: String,
    content: Option<String>,
    content_json: Option<String>,
    tool_call_id: Option<String>,
    tool_name: Option<String>,
    args: Option<String>,
}

#[derive(Deserialize, Clone)]
struct Message {
    kind: String,          // "request" or "response"
    role: Option<String>,
    instructions: Option<String>,
    parts: Vec<MessagePart>,
}
```

### Token estimation in Rust

```rust
fn estimate_tokens(text: &str) -> usize {
    std::cmp::max(1, (text.len() as f64 / 2.5).floor() as usize)
}

fn stringify_part_for_tokens(part: &MessagePart) -> String {
    let mut result = String::new();
    result.push_str(&part.part_kind);
    result.push_str(": ");

    if let Some(ref content) = part.content {
        result.push_str(content);
    } else if let Some(ref json) = part.content_json {
        result.push_str(json);
    }

    if let Some(ref tool_name) = part.tool_name {
        result.push_str(tool_name);
        if let Some(ref args) = part.args {
            result.push(' ');
            result.push_str(args);
        }
    }

    result
}
```

### Hashing in Rust

```rust
use rustc_hash::FxHasher;
use std::hash::{Hash, Hasher};

fn hash_message(msg: &Message) -> i64 {
    let mut hasher = FxHasher::default();

    if let Some(ref role) = msg.role {
        "role=".hash(&mut hasher);
        role.hash(&mut hasher);
        "||".hash(&mut hasher);
    }
    if let Some(ref instructions) = msg.instructions {
        "instructions=".hash(&mut hasher);
        instructions.hash(&mut hasher);
        "||".hash(&mut hasher);
    }

    for part in &msg.parts {
        stringify_part_for_hash(part).hash(&mut hasher);
        "||".hash(&mut hasher);
    }

    hasher.finish() as i64
}
```

### Pruning in Rust (single pass)

```rust
use rustc_hash::{FxHashSet};

fn prune_and_filter(
    messages: &[Message],
    compacted_hashes: &FxHashSet<i64>,
    max_tokens_per_message: usize,
) -> PruneResult {
    // Pass 1: collect tool_call_ids and tool_return_ids
    let mut call_ids = FxHashSet::default();
    let mut return_ids = FxHashSet::default();

    for msg in messages {
        for part in &msg.parts {
            if let Some(ref id) = part.tool_call_id {
                match part.part_kind.as_str() {
                    "tool-call" => { call_ids.insert(id.clone()); }
                    _ => { return_ids.insert(id.clone()); }
                }
            }
        }
    }

    // Symmetric difference = mismatched
    let mismatched: FxHashSet<_> = call_ids.symmetric_difference(&return_ids).cloned().collect();

    // Pass 2: filter
    let mut surviving = Vec::new();
    for (i, msg) in messages.iter().enumerate() {
        // Check mismatched tool calls
        let has_mismatched = msg.parts.iter().any(|p| {
            p.tool_call_id.as_ref().map_or(false, |id| mismatched.contains(id))
        });
        if has_mismatched { continue; }

        // Check huge messages
        let tokens: usize = msg.parts.iter()
            .map(|p| estimate_tokens(&stringify_part_for_tokens(p)))
            .sum();
        if tokens > max_tokens_per_message { continue; }

        // Check empty ThinkingParts
        if msg.parts.len() == 1
            && msg.parts[0].part_kind == "thinking"
            && msg.parts[0].content.as_ref().map_or(true, |c| c.is_empty())
        {
            continue;
        }

        surviving.push(i);
    }

    // Trim trailing responses
    while let Some(&last_idx) = surviving.last() {
        if messages[last_idx].kind == "response" {
            surviving.pop();
        } else {
            break;
        }
    }

    let pending = call_ids.difference(&return_ids).count();

    PruneResult {
        surviving_indices: surviving,
        dropped_count: messages.len() - surviving.len(),  // will be corrected after pop
        had_pending_tool_calls: pending > 0,
        pending_tool_call_count: pending,
    }
}
```

---

## Critical Constraints

1. **Never touch pydantic-ai objects in Rust**. All conversion happens in Python (`_core_bridge.py`). Rust only works with plain dicts/strings.

2. **The Rust module is optional**. Every call site must have a Python fallback path guarded by `if RUST_AVAILABLE`.

3. **Hash values from Rust replace Python hashes entirely**. Don't mix Rust hashes and Python hashes in the same set. When Rust is available, ALL hashing goes through Rust.

4. **Indices, not objects**. Rust functions return indices into the original message list. Python uses these indices to slice the original pydantic-ai objects. Rust never constructs or returns pydantic-ai message objects.

5. **Thread safety**. The Rust functions must be safe to call from multiple Python threads (they will be called from the main async loop and potentially from the summarization thread). Use `#[pyo3(signature = (...))]` and ensure no mutable global state.

6. **The serialization format (`serialize_message_for_rust`)** is the bridge contract. If pydantic-ai message types change in a future version, only `_core_bridge.py` needs updating, not the Rust code.

7. **Build targets**: Must produce wheels for `manylinux` (x86_64, aarch64), `macosx` (x86_64, arm64), and `windows` (x86_64). maturin handles this via CI.

8. **Python version support**: 3.11, 3.12, 3.13, 3.14 (matching `pyproject.toml`).

---

## Expected Results

| Operation | Before (Python) | After (Rust) | Speedup |
|---|---|---|---|
| Token estimation (200 msgs) | ~50-100ms | ~2-5ms | 10-30x |
| Message hashing (200 msgs) | ~30-60ms | ~1-3ms | 20-30x |
| Pruning + filtering | ~15-30ms (3 passes) | ~1-2ms (1 pass) | 15x |
| Session serialization | ~100-200ms (pickle) | ~15-30ms (json) | 5-7x |
| **Total hot path per turn** | **~200-400ms** | **~15-30ms** | **~13x** |

---

## Step-by-Step Execution Order

1. Create `code_puppy_core/` directory with `Cargo.toml` and `pyproject.toml`
2. Implement `src/lib.rs` with PyO3 module skeleton
3. Implement `src/token_estimation.rs` - `process_messages_batch()`
4. Implement `src/message_hashing.rs` - FxHash-based hashing
5. Implement `src/pruning.rs` - `prune_and_filter()` + `truncation_indices()` + `split_for_summarization()`
6. Implement `src/serialization.rs` - MessagePack session serialization
7. Create `code_puppy/_core_bridge.py` with fallback logic
8. Modify `code_puppy/agents/base_agent.py` to use `_core_bridge` at the 5 integration points listed above
9. Modify `code_puppy/session_storage.py` to use Rust serialization
10. Write tests in `tests/test_rust_core.py`
11. Write benchmarks in `tests/bench_rust_vs_python.py`
12. Verify all existing tests still pass with Rust module loaded
13. Verify all existing tests still pass WITHOUT Rust module (Python fallback)
