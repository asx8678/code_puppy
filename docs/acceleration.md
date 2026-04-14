# Hybrid Acceleration Architecture

Code Puppy uses a **hybrid Zig/Rust architecture** for native acceleration, leveraging the strengths of each language for different workloads.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Python Code Puppy                         │
├─────────────────────────────────────────────────────────────┤
│  code_puppy/acceleration/  ← Unified Bridge Module          │
├─────────────────────────────────────────────────────────────┤
│        Rust (PyO3)          │         Zig (cffi)            │
│  ┌─────────────────────┐  │  ┌─────────────────────┐       │
│  │   puppy_core        │  │  │   turbo_ops         │       │
│  │   - Message batch   │  │  │   - list_files      │       │
│  │   - Token pruning   │  │  │   - grep            │       │
│  │   - Session (de)ser │  │  │                     │       │
│  ├─────────────────────┤  │  └─────────────────────┘       │
│  │   turbo_parse       │  │                                │
│  │   - Tree-sitter     │  │  ┌─────────────────────┐       │
│  │   - Symbol extract  │  │  │   turbo_parse       │       │
│  │   - Parsing         │  │  │   (via cffi)        │       │
│  └─────────────────────┘  │  │   (stub/disabled)   │       │
│                           │  └─────────────────────┘       │
└───────────────────────────┴─────────────────────────────────┘
```

## Backend Assignment

| Module | Backend | Rationale |
|--------|---------|-----------|
| `puppy_core` | **Rust** | Message processing is extremely FFI-sensitive; PyO3 has 80x lower overhead than cffi |
| `turbo_parse` | **Rust** | Tree-sitter grammars are complex to vendor/maintain in Zig; Rust has mature ecosystem |
| `turbo_ops` | **Zig** | File I/O is less FFI-sensitive; Zig has simpler cross-compilation |

## Rationale

### Why Rust for Performance-Critical Code?

1. **FFI Overhead**: PyO3 has ~80x lower FFI overhead than cffi for hot paths
2. **Ecosystem**: Tree-sitter has first-class Rust bindings
3. **Safety**: Rust's ownership model catches memory issues at compile time
4. **Maturity**: PyO3 is battle-tested with excellent Python interop

### Why Zig for File Operations?

1. **Build Simplicity**: Zig can cross-compile without complex toolchain setup
2. **FFI Friendliness**: File I/O is batch-oriented, less sensitive to per-call overhead
3. **Binary Size**: Zig produces smaller shared libraries
4. **C Interop**: Easy C ABI compatibility via cffi

## Unified Bridge API

The `code_puppy.acceleration` module provides a unified interface:

```python
from code_puppy.acceleration import (
    # Backend info
    RUST_AVAILABLE,
    ZIG_AVAILABLE,
    get_backend_info,
    # Rust-backed operations
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
    split_for_summarization,
    serialize_session,
    deserialize_session,
    MessageBatchHandle,
    # Zig-backed operations
    list_files,
    grep,
)

# Check which backends are active
info = get_backend_info()
# {'puppy_core': 'rust', 'turbo_parse': 'rust', 'turbo_ops': 'zig'}

# File operations automatically use Zig if available
result = list_files("src/", recursive=True)
result = grep("def ", directory="src/")
```

## Feature Flags

The acceleration system respects these environment variables:

| Variable | Effect |
|----------|--------|
| `PUP_DISABLE_RUST` | Force Python fallbacks for Rust-backed operations |
| `PUP_DISABLE_ZIG` | Force Python fallbacks for Zig-backed operations |
| `PUP_DISABLE_ACCELERATION` | Disable all native acceleration |

## Fallback Chain

Each operation has a fallback chain:

1. **Try native** (Rust or Zig based on assignment)
2. **Try alternative native** (if primary unavailable)
3. **Python implementation**
4. **Graceful degradation** (return empty/error result)

## Building

### Rust (Required for core)

```bash
cd rust_code_puppy_core
cargo build --release
# Produces: target/release/libcode_puppy_core.dylib
```

### Zig (Optional for file ops)

```bash
zig build -Doptimize=ReleaseFast
# Produces: zig-out/lib/libzig_turbo_ops.dylib
```

## Performance Notes

- Message processing: Rust is ~5-10x faster than Python, ~80x lower FFI overhead than Zig+cffi
- File listing: Zig is comparable to Python's `os.walk`, but with better parallelism
- Grep: Zig's regex engine is fast; comparable to ripgrep for simple patterns

## Future Considerations

- Tree-sitter in Zig: Currently not pursued due to grammar maintenance burden
- Full Zig migration: Not planned; hybrid approach is optimal for our use case
- New accelerators: Evaluate based on FFI sensitivity and ecosystem maturity
