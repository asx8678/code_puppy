# Security Notes for Code Puppy

## Rust Acceleration Security Requirements

### File Operation Validation (MISS1 Fix)

All Rust-accelerated file operations **MUST** call `validate_file_path()` from 
`code_puppy.tools.file_operations` before accessing any file or directory.

**Why**: The Python file operations path blocks sensitive paths (SSH keys, AWS 
credentials, .env files, etc.) before reading. Rust acceleration paths that 
bypass this validation create a security hole.

**Affected operations**:
- `turbo_ops.read_file` / `turbo_ops.read_files`
- `turbo_ops.list_files`
- `turbo_ops.grep`

**Current implementation** (in `code_puppy/plugins/turbo_executor/orchestrator.py`):
- `_execute_read_files`: Validates each file path before calling Rust
- `_execute_list_files`: Validates directory before calling Rust
- `_execute_grep`: Validates directory before calling Rust

**Adding new Rust acceleration**:
1. Add path validation BEFORE calling Rust functions
2. Use the same `validate_file_path()` function for consistency
3. Add tests that verify sensitive paths are blocked
4. Review the sensitive path list in `file_operations.py`

### Dynamic Grammar Loading (SEC-01 Fix)

The `dynamic-grammars` feature in turbo_parse was updated to return owned 
`Language` values instead of forged `&'static` references.

**Previous issue**: Raw pointer casts created references that could become 
dangling if grammars were unloaded.

**Current approach**: `get_language()` returns `Language` (owned/cloned), 
which is safe because `tree_sitter::Language` is cheaply cloneable.

### Audit Trail

| Finding | Status | Fix Location |
|---------|--------|--------------|
| MISS1 (path bypass) | ✅ Fixed | `orchestrator.py` |
| SEC-01 (lifetime) | ✅ Fixed | `registry.rs` |
| BUG-01 (import) | ✅ Fixed | `session_storage.py` |
| BUG-02 (panic) | ✅ Fixed | `operations.rs` |
| BUG-03 (symbol) | ✅ Fixed | `lib.rs` |

## Reporting Security Issues

Please report security issues to the maintainers privately before public disclosure.
