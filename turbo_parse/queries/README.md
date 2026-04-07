# Tree-Sitter Query Files

This directory contains tree-sitter query files vendored from the [Helix Editor](https://github.com/helix-editor/helix) project.

## Source

- **Repository**: https://github.com/helix-editor/helix
- **License**: MPL-2.0 (Mozilla Public License 2.0)
- **Path in Helix**: `runtime/queries/{language}/`

## Included Languages

| Language | Highlights | Folds | Indents | Notes |
|----------|------------|-------|---------|-------|
| Python | ✓ | ✓ | ✓ | |
| Rust | ✓ | ✓ | ✓ | |
| JavaScript | ✓ | ✓ | ✓ | Merged from ecma + _javascript |
| TypeScript | ✓ | ✓ | ✓ | Merged from ecma + _typescript |
| TSX | ✓ | ✓ | ✓ | Merged from ecma + _typescript + _jsx |
| Elixir | ✓ | ✓ | ✓ | |

## File Types

- **highlights.scm** - Syntax highlighting queries that map AST nodes to highlight scopes
- **folds.scm** - Code folding queries that define foldable regions
- **indents.scm** - Indentation rules for auto-indentation support

## License Compatibility

The Helix Editor queries are licensed under MPL-2.0, which is compatible with MIT-licensed projects like turbo_parse. 

Key points:
- MPL-2.0 is a file-level copyleft license
- Using MPL-licensed files in a larger project doesn't affect the licensing of other files
- Modifications must remain under MPL-2.0

See `LICENSE` or `ATTRIBUTION` file for full license text and attribution details.

## Usage

These query files are loaded by the `queries` module and used by:
- `highlights.rs` - For syntax highlighting
- `folds.rs` - For code folding
- `indents.rs` - For smart indentation

Query strings are embedded at compile time using `include_str!` or loaded dynamically from the filesystem.

## Modification History

- JavaScript: Merged from `ecma/highlights.scm` + `_javascript/highlights.scm`
- TypeScript: Merged from `ecma/highlights.scm` + `_typescript/highlights.scm`  
- TSX: Merged from `ecma/highlights.scm` + `_typescript/highlights.scm` + `_jsx/highlights.scm`

This merging resolves Helix's "inherits" directive system to create standalone, self-contained query files suitable for use with tree-sitter.
