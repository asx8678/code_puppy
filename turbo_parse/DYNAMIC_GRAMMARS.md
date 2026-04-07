# Dynamic Grammars Feature

The `dynamic-grammars` feature enables turbo_parse to load tree-sitter grammar libraries at runtime from `.so`/`.dylib`/`.dll` files.

## Overview

This feature allows users to:
- Use custom tree-sitter grammars without recompiling turbo_parse
- Add support for languages not included in the built-in set (Python, Rust, JavaScript, TypeScript, TSX, Elixir)
- Load grammars distributed separately from the main package

## Security Considerations ⚠️

**IMPORTANT**: Loading dynamic libraries carries security risks:

1. **Code Execution**: Dynamic libraries execute native code with the same privileges as the application. Only load libraries from **trusted sources**.

2. **Path Validation**: The library includes path traversal protection to prevent escaping allowed directories, but you should still validate paths before loading.

3. **Library Integrity**: Consider verifying checksums of grammar libraries before loading them in production.

4. **Isolation**: The feature is disabled by default and must be explicitly enabled at compile time.

## Usage

### Building with Dynamic Grammar Support

```bash
# Build with dynamic grammar support
cd turbo_parse
cargo build --features dynamic-grammars

# Build Python extension with dynamic grammars
maturin develop --features dynamic-grammars
```

### Python API

```python
import turbo_parse

# Check if dynamic grammars are enabled
print(turbo_parse.dynamic_grammars_enabled())  # True/False

# Get information about dynamic grammar loading
def info = turbo_parse.dynamic_grammar_info()
print(info)
# {
#   "enabled": true,
#   "platform": "linux",
#   "library_extension": ".so",
#   "loaded_count": 0,
#   "loaded_grammars": []
# }

# Register a grammar
result = turbo_parse.register_grammar("go", "/usr/local/lib/tree-sitter-go.so")
print(result)
# {
#   "success": True,
#   "name": "go",
#   "version": 14,
#   "error": None
# }

# Check if grammar is registered
print(turbo_parse.is_grammar_registered("go"))  # True

# List all registered grammars
def grammars = turbo_parse.list_registered_grammars()
print(grammars)
# {
#   "grammars": [
#     {"name": "python", "type": "built-in", "version": 14},
#     {"name": "go", "type": "dynamic", "version": 14}
#   ],
#   "total_count": 7,
#   "built_in_count": 6,
#   "dynamic_count": 1
# }

# Use the grammar for parsing
result = turbo_parse.parse_source("package main", "go")
print(result["success"])  # True

# Unregister when done (optional)
turbo_parse.unregister_grammar("go")
```

### Rust API

```rust
use std::path::PathBuf;
use turbo_parse::registry::{register_dynamic_grammar, is_language_supported};
use turbo_parse::dynamic::{DynamicGrammarLoader, global_loader};

// Register a grammar
register_dynamic_grammar("go", "/usr/local/lib/tree-sitter-go.so")?;

// Check if available
assert!(is_language_supported("go"));

// Use for parsing
let lang = turbo_parse::registry::get_language("go")?;
```

## Platform-Specific Library Extensions

The correct extension is automatically detected:

- **Linux**: `.so`
- **macOS**: `.dylib`
- **Windows**: `.dll`

If you provide a path without an extension, the correct one will be appended automatically.

## Obtaining Grammar Libraries

Grammar libraries can be obtained from:

1. **Official tree-sitter repositories**: Many languages have official tree-sitter grammars
2. **Package managers**: Some systems distribute compiled grammars
3. **Build from source**: Compile from the tree-sitter grammar repository

### Building from Source

Example for Go grammar:

```bash
# Clone the grammar repository
git clone https://github.com/tree-sitter/tree-sitter-go.git
cd tree-sitter-go

# Build the shared library
cargo build --release
# or for C-based grammars:
cc -shared -fPIC -o libtree-sitter-go.so src/parser.c
```

## Configuration Options

The `DynamicGrammarLoader` provides security configuration:

```rust
use turbo_parse::dynamic::global_loader;
use std::path::PathBuf;

let loader = global_loader();

// Add allowed directories (empty = any directory with traversal checks)
loader.add_allowed_directory(PathBuf::from("/usr/local/lib/grammars"));

// Or restrict to specific directories only
loader.set_allowed_directories(vec![
    PathBuf::from("/usr/local/lib/grammars"),
    PathBuf::from("/opt/grammars"),
]);
loader.set_allow_any_directory(false);
```

## Error Handling

Common errors and their meanings:

| Error | Cause | Solution |
|-------|-------|----------|
| `PathNotFound` | Library file doesn't exist | Verify the path |
| `PathTraversal` | Path contains `..` or escapes allowed directories | Use absolute paths or configure allowed directories |
| `LibraryLoadError` | Invalid library format | Ensure the library is compiled for your platform |
| `MissingSymbol` | Library doesn't export `tree_sitter_<name>` | Verify it's a valid tree-sitter grammar |
| `FeatureNotEnabled` | Compiled without `dynamic-grammars` | Rebuild with the feature enabled |
| `AlreadyRegistered` | Grammar with this name already loaded | Use a different name or unload first |

## Testing

Run the tests (without the feature):

```bash
cd turbo_parse
cargo test
```

Run the tests (with the feature enabled):

```bash
cd turbo_parse
cargo test --features dynamic-grammars
```

Run integration tests that attempt to load real grammars:

```bash
# Requires TEST_GRAMMAR_PATH environment variable
TEST_GRAMMAR_PATH=/path/to/grammar.so cargo test --features dynamic-grammars -- --ignored
```

## External Scanners

Some grammars require external scanners (additional C code for lexing). These can be loaded alongside the main grammar:

```python
# Python API (when available)
result = turbo_parse.register_grammar_with_scanner(
    "ruby",
    "/path/to/tree-sitter-ruby.so",
    "/path/to/tree-sitter-ruby-scanner.so"
)
```

## Troubleshooting

### "Failed to load library"

- Verify the library file exists and is readable
- Check that it's compiled for your platform and architecture
- Ensure the symbol name matches (e.g., `tree_sitter_go` for "go")

### "Path traversal detected"

- Use absolute paths instead of relative paths with `..`
- Configure allowed directories to include the parent directory

### "Feature not enabled"

- Rebuild with `--features dynamic-grammars`
- Verify `turbo_parse.dynamic_grammars_enabled()` returns True

## See Also

- [Tree-sitter documentation](https://tree-sitter.github.io/tree-sitter/)
- [Grammar repository list](https://tree-sitter.github.io/tree-sitter/#parsers)
- Security checklist in `SECURITY_CHECKLIST.md`
