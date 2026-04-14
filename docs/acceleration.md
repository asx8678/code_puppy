# Rust Acceleration

Code Puppy uses **Rust acceleration** for native performance, with PyO3 providing seamless Python integration.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Python Code Puppy                         │
├─────────────────────────────────────────────────────────────┤
│  code_puppy/acceleration/  ← Unified Bridge Module          │
├─────────────────────────────────────────────────────────────┤
│                    Rust (PyO3)                              │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │   puppy_core        │  │   turbo_ops         │          │
│  │   - Message batch   │  │   - list_files      │          │
│  │   - Token pruning   │  │   - grep            │          │
│  │   - Session (de)ser │  │   - read_file       │          │
│  ├─────────────────────┤  └─────────────────────┘          │
│  │   turbo_parse       │                                  │
│  │   - Tree-sitter     │                                  │
│  │   - Symbol extract  │                                  │
│  │   - Parsing         │                                  │
│  └─────────────────────┘                                  │
└─────────────────────────────────────────────────────────────┘
```

## Backend Assignment

| Module | Backend | Rationale |
|--------|---------|-----------|
| `puppy_core` | **Rust** | Message processing is extremely FFI-sensitive; PyO3 provides minimal overhead |
| `turbo_parse` | **Rust** | Tree-sitter has excellent Rust bindings; mature ecosystem |
| `turbo_ops` | **Rust** | Batch file operations benefit from Rust's performance and safety |

## Why Rust?

1. **FFI Overhead**: PyO3 has minimal FFI overhead for hot paths
2. **Ecosystem**: Tree-sitter has first-class Rust bindings
3. **Safety**: Rust's ownership model catches memory issues at compile time
4. **Maturity**: PyO3 is battle-tested with excellent Python interop
5. **Performance**: Zero-cost abstractions with predictable performance

## Unified Bridge API

The `code_puppy.acceleration` module provides a unified interface:

```python
from code_puppy.acceleration import (
    # Backend info
    RUST_AVAILABLE,
    get_backend_info,
    # Rust-backed operations
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
    split_for_summarization,
    serialize_session,
    deserialize_session,
    MessageBatchHandle,
    list_files,
    grep,
)

# Check backend status
info = get_backend_info()
# {'puppy_core': 'rust', 'turbo_parse': 'rust', 'turbo_ops': 'rust'}

# File operations use Rust when available
result = list_files("src/", recursive=True)
result = grep("def ", directory="src/")
```

## Feature Flags

The acceleration system respects these environment variables:

| Variable | Effect |
|----------|--------|
| `PUP_DISABLE_RUST` | Force Python fallbacks for Rust-backed operations |
| `PUP_DISABLE_ACCELERATION` | Disable all native acceleration |

## Fallback Chain

Each operation has a fallback chain:

1. **Try Rust** (via PyO3)
2. **Python implementation**
3. **Graceful degradation** (return empty/error result)

## Building

### Rust (Required for acceleration)

```bash
# Build all crates via cargo workspace
cargo build --release --workspace

# Or let fast_puppy plugin auto-build on startup
# First build: ~2-5 minutes (turbo_parse pulls in tree-sitter grammars)
# Subsequent: cached unless .rs sources change
```

Each crate can also be built individually with maturin:

```bash
uv run maturin develop --release --manifest-path code_puppy_core/Cargo.toml
uv run maturin develop --release --manifest-path turbo_ops/Cargo.toml
uv run maturin develop --release --manifest-path turbo_parse/Cargo.toml
```

## Performance Notes

- **Message processing**: Rust is ~5-10x faster than Python via PyO3
- **File operations**: Rust batch operations are 5-20x faster on large repos
- **Parsing**: Tree-sitter in Rust is 10-50x faster than pure Python parsing

## Future Considerations

- Additional Rust crates: Evaluate based on hot path analysis
- Python 3.14 free-threading: All crates support no-GIL operation
- New accelerators: Evaluate based on FFI sensitivity and ecosystem maturity
