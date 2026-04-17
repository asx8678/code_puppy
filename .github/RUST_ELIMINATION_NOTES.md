# Rust Elimination Notes (bd-164, bd-165)

## What Was Removed
- `code_puppy_core/` - The internal PyO3 Rust crate (1,266 lines of Rust)  
- `Cargo.toml` - Root Cargo workspace

## What Was Intentionally Kept
The following files reference `cargo`/`rust` but are **user-facing tool support**,
not internal build dependencies. They help Code Puppy work WITH user Rust projects:

- `code_puppy/plugins/repo_compass/tech_stack.py` - Detects Rust in user repos
- `code_puppy/plugins/proactive_guidance/_guidance.py` - Gives guidance for user Rust code
- `code_puppy/agents/pack/watchdog.py` - Helps QA user Rust projects  
- `code_puppy/utils/install_hints.py` - Helps users install Rust toolchain
- `code_puppy/mcp_/system_tools.py` - Detects system Rust tools for users

These are features, not build dependencies. Code Puppy assists with Rust projects
even though Code Puppy itself no longer contains Rust.
