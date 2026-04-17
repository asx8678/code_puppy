# Native Acceleration (Fast Puppy)

Code Puppy uses a **pure Elixir + Python architecture** for high-performance operations.

## Architecture Overview (Pure Elixir)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python Code Puppy                             │
├─────────────────────────────────────────────────────────────────┤
│  NativeBackend (unified interface)                              │
├─────────────────────────────────────────────────────────────────┤
│                    Backend Routing                               │
├───────────────┬─────────────────────────────────────────────────┤
│  Elixir       │  Python (Fallback)                               │
│  ┌─────────┐  │  ┌─────────────────────┐                        │
│  │File Ops │  │  │list_files           │                        │
│  │Repo Idx │  │  │grep                 │                        │
│  │Parse    │  │  │read_file            │                        │
│  │Message  │  │  │message operations   │                        │
│  │Core     │  │  └─────────────────────┘                        │
│  └─────────┘  │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```

## Backend Assignment

| Capability | Primary Backend | Fallback | Purpose |
|------------|-----------------|----------|---------|
| `message_core` | **Elixir** | Python | Message serialization, pruning, hashing |
| `file_ops` | **Elixir** | Python | Batch file ops (`list_files`, `grep`, `read_file`) |
| `repo_index` | **Elixir** | Python | Repository indexing |
| `parse` | **Elixir** | Python | Tree-sitter parsing, symbols, diagnostics |

## Backend Profiles

The runtime supports two backend profiles:

```python
from code_puppy.native_backend import NativeBackend

# Elixir-first routing (default) - all operations route through Elixir
NativeBackend.set_backend_preference("elixir_first")

# Python-only (no native acceleration)
NativeBackend.set_backend_preference("python_only")
```

> **Note:** The `rust_only` profile has been removed as of bd-167 — Rust has been completely eliminated from the architecture.

## Why This Architecture?

| Backend | Best For | Rationale |
|---------|----------|-----------|
| **Elixir** | All runtime operations | Distributed coordination, fault tolerance, BEAM VM concurrency |
| **Python** | Agent orchestration, CLI, TUI | Rich ecosystem for LLM integration, rapid development |

**Benefits of pure Elixir + Python:**
- **Simpler builds**: No Rust toolchain, no PyO3, no maturin
- **Faster CI**: Python-only builds, no native compilation
- **Easier onboarding**: Just Python + Elixir knowledge required
- **Consistent performance**: Single optimized backend (Elixir BEAM/OTP)

## Unified Bridge API

The `NativeBackend` class provides a single interface:

```python
from code_puppy.native_backend import NativeBackend

# Check backend status
status = NativeBackend.get_status()

# File operations (route through Elixir)
result = NativeBackend.list_files("src/", recursive=True)
result = NativeBackend.grep("def ", directory="src/")

# Message processing (Elixir MessageCore)
result = NativeBackend.serialize_messages(messages)

# Parsing (Elixir native)
ast = NativeBackend.parse_file("main.py", language="python")
```

## Feature Flags

Environment variables to control acceleration:

| Variable | Effect |
|----------|--------|
| `PUP_DISABLE_ELIXIR` | Disable Elixir routing (use Python fallbacks) |
| `PUP_DISABLE_ACCELERATION` | Disable all native acceleration (pure Python mode) |

> **Note:** `PUP_DISABLE_RUST` has been removed as Rust is no longer part of the architecture (bd-167).

## Fallback Chain

Each operation follows this priority:

1. **Try Elixir** (if `elixir_first` profile and available)
2. **Python implementation** (always available)
3. **Graceful degradation** (return empty/error result)

> **Note:** The Rust step has been removed as Rust has been completely eliminated from the architecture (bd-167).

## Building

### Elixir Components

The Elixir control plane provides all native acceleration:

```bash
# Start the Elixir control plane
cd code_puppy_control/
mix deps.get
iex -S mix
```

No additional build steps required — the Python layer communicates with Elixir via JSON-RPC over stdio.

## Performance Notes

| Operation | Speedup | Backend |
|-----------|---------|---------|
| Message processing | 10-30x | Elixir |
| File operations | 5-20x | Elixir |
| Parsing | 10-50x | Elixir |

## Migration Notes

- **bd-167**: Rust has been completely eliminated from the architecture
- **bd-93**: Parse operations route through `NativeBackend` with Elixir-first routing
- **bd-94**: File operations route through Elixir
- Direct `turbo_parse_bridge` imports are deprecated — use `NativeBackend`

## Future Considerations

- Python 3.14 free-threading: Full support for no-GIL operation
- Elixir BEAM/OTP provides distributed, fault-tolerant operation
- Future backends evaluated based on FFI sensitivity and ecosystem maturity

## Capability Routing Table (bd-13, bd-167)

NativeBackend routes operations to the optimal backend based on the active profile. Use `NativeBackend.get_capability_routing(capability)` to introspect at runtime.

### Routing by Profile

| Capability | `elixir_first` (default) | `python_only` |
|------------|-------------------------|---------------|
| **message_core** | Elixir → Python | Python |
| **file_ops** | Elixir → Python | Python |
| **repo_index** | Elixir → Python | Python |
| **parse** | Elixir → Python | Python |

### Fallback Behavior

- Elixir is tried first; Python fallback is always available
- Python fallback is always available (never fails to import)
- All native operations now route through Elixir (Rust eliminated in bd-167)

### Runtime Introspection

```python
from code_puppy.native_backend import NativeBackend

# Get routing plan for a capability
routing = NativeBackend.get_capability_routing("parse")
print(routing["will_use"])     # "elixir" or "python_fallback"
print(routing["backends"])     # [("elixir", True), ("python", True), ...]
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
