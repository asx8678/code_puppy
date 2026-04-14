# Tree-sitter Language Registry

This module provides language grammar loading for the Zig turbo_parse module.

## Overview

The `languages.zig` module bridges tree-sitter C libraries with the Zig parser,
enabling multi-language parsing support through static or dynamic linking.

## Supported Languages

| Language | Function Name | System Libraries |
|----------|---------------|------------------|
| Python | `tree_sitter_python` | libtree-sitter-python |
| Rust | `tree_sitter_rust` | libtree-sitter-rust |
| JavaScript | `tree_sitter_javascript` | libtree-sitter-javascript |
| TypeScript | `tree_sitter_typescript` | libtree-sitter-typescript |
| TSX | `tree_sitter_tsx` | libtree-sitter-tsx |
| C | `tree_sitter_c` | libtree-sitter-c |
| C++ | `tree_sitter_cpp` | libtree-sitter-cpp |
| Go | `tree_sitter_go` | libtree-sitter-go |
| Zig | `tree_sitter_zig` | libtree-sitter-zig |

## Usage

### Basic Usage

```zig
const languages = @import("languages.zig");

// Get a language by name (case-insensitive)
const lang = languages.getLanguage("python");
if (lang) |l| {
    // Use with tree-sitter parser
    parser.setLanguage(l);
}
```

### Check Language Availability

```zig
if (languages.isLanguageAvailable("rust")) {
    std.debug.print("Rust grammar is linked!\n", .{});
}
```

### Diagnostics

```zig
// Print diagnostic information
const diag = languages.diagnoseGrammars();
if (!diag.hasAnyGrammar()) {
    std.debug.print("Warning: No grammars linked!\n", .{});
}
```

## Build Configuration

### Using System Grammars

Link against system-installed tree-sitter grammars:

```bash
zig build zig_turbo_parse -Dsystem-grammars=true
```

### Using Vendored Grammars

Build grammars from source in `vendor/` directory:

```bash
zig build zig_turbo_parse -Dvendor-grammars=true
```

### Combined Approach

```bash
zig build zig_turbo_parse -Dvendor-grammars=true -Dsystem-grammars=true
```

## Vendor Directory Structure

For `-Dvendor-grammars`, the expected structure is:

```
vendor/
├── tree-sitter-python/
│   └── src/
│       ├── parser.c
│       └── scanner.c  (optional)
├── tree-sitter-rust/
│   └── src/
│       └── parser.c
└── ... (other grammars)
```

## Implementation Details

### C ABI Compatibility

The module uses `extern "c"` declarations for C ABI compatibility:

```zig
pub extern "c" fn tree_sitter_python() *const c_api.Language;
```

### Weak Linking

When using system grammars with `-Dsystem-grammars=true`, grammars are linked
with weak references. This allows the binary to run even if some grammars are
not installed, with graceful degradation at runtime.

### Comptime Checking

The `LanguageCapabilities` struct provides compile-time knowledge of which
languages might be available:

```zig
const caps = languages.LanguageCapabilities.detect();
if (caps.python) {
    // Python support was enabled at compile time
}
```

## Testing

Run the language registry tests:

```bash
zig test zig_src/turbo_parse/languages.zig
```

## Troubleshooting

### No Grammars Linked

If `diagnoseGrammars()` shows no linked grammars:

1. Check that tree-sitter libraries are installed:
   ```bash
   # macOS
   brew install tree-sitter tree-sitter-python ...
   
   # Ubuntu/Debian
   apt-get install libtree-sitter-dev ...
   ```

2. Build with vendor grammars:
   ```bash
   zig build zig_turbo_parse -Dvendor-grammars=true
   ```

3. Verify library paths in `build.zig` match your system

### Linking Errors

If you see undefined symbol errors for `tree_sitter_*`:
- The grammar libraries aren't linked correctly
- Check the `GrammarConfig.system_libs` array for library names
- Use `ldd` or `otool -L` to verify library dependencies

## Migration from Rust

The Rust turbo_parse used `tree-sitter-python` and similar crates that bundled
the C grammars. This Zig implementation requires explicit linking of the
grammar libraries, providing more flexibility but requiring explicit configuration.

Key differences:
- **Rust**: Grammars bundled in crates via `tree-sitter-*` dependencies
- **Zig**: Grammars linked as system libraries or built from vendored source
- **Benefit**: Smaller binaries, no unnecessary grammars included
