# Native Acceleration (Fast Puppy)

Code Puppy uses a **multi-backend acceleration stack** for native performance, with intelligent routing based on capability type.

## Architecture Overview (Elixir-First)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python Code Puppy                             │
├─────────────────────────────────────────────────────────────────┤
│  NativeBackend (unified interface)                              │
├─────────────────────────────────────────────────────────────────┤
│                    Backend Routing                               │
├───────────────┬───────────────────┬─────────────────────────────┤
│  Elixir       │  Rust (PyO3)      │  Python (Fallback)          │
│  ┌─────────┐  │  ┌─────────────┐  │  ┌─────────────────────┐   │
│  │File Ops │  │  │message_core │  │  │list_files           │   │
│  │Repo Idx │  │  │- batch      │  │  │grep                 │   │
│  │Parse NIF│  │  │- pruning    │  │  │read_file            │   │
│  └─────────┘  │  │- hashing    │  │  └─────────────────────┘   │
│               │  │- serialize  │  │                             │
│               │  ├─────────────┤  │                             │
│               │  │turbo_parse  │  │                             │
│               │  │- symbols    │  │                             │
│               │  │- parsing    │  │                             │
│               │  └─────────────┘  │                             │
└───────────────┴───────────────────┴─────────────────────────────┘
```

## Backend Assignment

| Capability | Primary Backend | Fallback | Purpose |
|------------|-----------------|----------|---------|
| `message_core` | **Rust** | Python | Message serialization, pruning, hashing |
| `file_ops` | **Elixir** | Python | Batch file ops (`list_files`, `grep`, `read_file`) |
| `repo_index` | **Elixir** | Python | Repository indexing |
| `parse` | **Elixir NIF** → Rust | Python | Tree-sitter parsing, symbols, diagnostics |

## Backend Profiles

The runtime supports three backend profiles:

```python
from code_puppy.native_backend import NativeBackend

# Elixir-first routing (default)
NativeBackend.set_backend_preference("elixir_first")

# Rust-only (no Elixir)
NativeBackend.set_backend_preference("rust_only")

# Python-only (no native acceleration)
NativeBackend.set_backend_preference("python_only")
```

## Why This Architecture?

| Backend | Best For | Rationale |
|---------|----------|-----------|
| **Elixir** | File operations, indexing | Distributed coordination, fault tolerance, BEAM VM |
| **Rust** | Message processing | Minimal FFI overhead for hot paths, memory safety |
| **Python** | Fallback | Always works, zero build requirements |

## Unified Bridge API

The `NativeBackend` class provides a single interface:

```python
from code_puppy.native_backend import NativeBackend

# Check backend status
status = NativeBackend.get_status()

# File operations (route through Elixir)
result = NativeBackend.list_files("src/", recursive=True)
result = NativeBackend.grep("def ", directory="src/")

# Message processing (route through Rust)
result = NativeBackend.serialize_messages(messages)

# Parsing (route through Elixir NIF → Rust)
ast = NativeBackend.parse_file("main.py", language="python")
```

## Feature Flags

Environment variables to control acceleration:

| Variable | Effect |
|----------|--------|
| `PUP_DISABLE_RUST` | Force Python fallbacks for Rust-backed operations |
| `PUP_DISABLE_ELIXIR` | Disable Elixir routing |
| `PUP_DISABLE_ACCELERATION` | Disable all native acceleration |

## Fallback Chain

Each operation follows this priority:

1. **Try Elixir** (if `elixir_first` profile and available)
2. **Try Rust** (if `rust_only` profile and available)
3. **Python implementation**
4. **Graceful degradation** (return empty/error result)

## Building

### Rust Components

```bash
# Build Rust crates
cargo build --release --workspace

# Or use maturin for individual crates
uv run maturin develop --release --manifest-path code_puppy_core/Cargo.toml
uv run maturin develop --release --manifest-path turbo_parse/Cargo.toml
```

### Elixir Components

```bash
# Start the Elixir control plane
cd elixir/
mix deps.get
iex -S mix
```

## Performance Notes

| Operation | Speedup | Backend |
|-----------|---------|---------|
| Message processing | 10-30x | Rust |
| File operations | 5-20x | Elixir |
| Parsing | 10-50x | Elixir NIF → Rust |

## Migration Notes

- **bd-93**: Parse operations now route through `NativeBackend` with Elixir-first routing
- **bd-94**: Removed `turbo_ops` crate - file operations now route through Elixir
- Direct `turbo_parse_bridge` imports are deprecated — use `NativeBackend`

## Future Considerations

- Python 3.14 free-threading: All crates support no-GIL operation
- Additional backends evaluated based on FFI sensitivity and ecosystem maturity

## Capability Routing Table (bd-13)

NativeBackend routes operations to the optimal backend based on the active profile. Use `NativeBackend.get_capability_routing(capability)` to introspect at runtime.

### Routing by Profile

| Capability | `elixir_first` (default) | `rust_first` | `python_only` |
|------------|-------------------------|-------------|---------------|
| **message_core** | Rust → Python | Rust → Python | Python |
| **file_ops** | Elixir → Python | Elixir → Python | Python |
| **repo_index** | Elixir → Python | Elixir → Python | Python |
| **parse** | Elixir → Rust → Python | Rust → Elixir → Python | Python |

### Fallback Behavior

- Each backend is tried in order; first available wins
- Python fallback is always available (never fails to import)
- `rust_first` for PARSE: skips Elixir when `turbo_parse` Rust crate is available
- `rust_first` for FILE_OPS/REPO_INDEX: still uses Elixir (no Rust backend exists since turbo_ops removed in bd-76)

### Runtime Introspection

```python
from code_puppy.native_backend import NativeBackend

# Get routing plan for a capability
routing = NativeBackend.get_capability_routing("parse")
print(routing["will_use"])     # "elixir", "turbo_parse", or "python_fallback"
print(routing["backends"])     # [("elixir", True), ("turbo_parse", False), ...]
print(routing["preference"])   # "elixir_first"

# Get full status
for cap, info in NativeBackend.get_status().items():
    print(f"{cap}: {info.status} (configured={info.configured})")

# Check specific availability
NativeBackend.is_available(NativeBackend.Capabilities.PARSE)  # bool
NativeBackend.is_active(NativeBackend.Capabilities.PARSE)     # bool (available AND enabled)
```

### Direct Bridge Imports (Deprecated)

Direct imports from `turbo_parse_bridge` are **deprecated** (bd-13). Use NativeBackend methods instead:

| Deprecated Import | NativeBackend Equivalent |
|-------------------|--------------------------|
| `turbo_parse_bridge.parse_source(src, lang)` | `NativeBackend.parse_source(src, lang)` |
| `turbo_parse_bridge.parse_file(path, lang)` | `NativeBackend.parse_file(path, lang)` |
| `turbo_parse_bridge.extract_symbols(src, lang)` | `NativeBackend.extract_symbols(src, lang)` |
| `turbo_parse_bridge.stats()` | `NativeBackend.parse_stats()` |
| `turbo_parse_bridge.health_check()` | `NativeBackend.parse_health_check()` |
| `turbo_parse_bridge.TURBO_PARSE_AVAILABLE` | `NativeBackend.is_available(NativeBackend.Capabilities.PARSE)` |
| `turbo_parse_bridge.parse_files_batch(paths)` | `NativeBackend.parse_batch(paths)` |

A CI lint guard (`tests/test_no_direct_bridge_imports.py`) enforces this.
