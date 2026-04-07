# turbo_parse CI Documentation

This document describes the Continuous Integration (CI) setup for `turbo_parse`, how it works, how to run it locally, and troubleshooting common issues.

## Overview

The CI pipeline for `turbo_parse` ensures that the Rust crate builds and tests successfully across multiple platforms, and that Python wheels are built correctly for distribution.

## CI Workflow

The CI is defined in `.github/workflows/turbo_parse.yml` and runs on:
- Every push to `main` that touches `turbo_parse/`, `Cargo.toml`, `Cargo.lock`, or the workflow itself
- Every pull request to `main` that touches the same paths
- Manual trigger via `workflow_dispatch`

### Jobs

#### 1. `cargo-test`
Tests the Rust crate across all supported platforms.

| Platform | Checks |
|----------|--------|
| `ubuntu-latest` | ✓ Formatting, clippy, unit tests |
| `macos-latest` | ✓ Formatting, clippy, unit tests |
| `windows-latest` | ✓ Formatning, clippy, unit tests |

**Steps:**
1. Checkout code
2. Install Rust toolchain with `rustfmt` and `clippy`
3. Restore Rust cache (`Swatinem/rust-cache@v2`)
4. Check code formatting: `cargo fmt -- --check`
5. Run clippy lints: `cargo clippy --all-features -- -D warnings`
6. Run unit tests: `cargo test -p turbo_parse --release`

#### 2. `maturin-build`
Builds Python wheels using maturin for distribution.

| OS | Python Versions |
|----|-----------------|
| `ubuntu-latest` | 3.10, 3.11, 3.12 |
| `macos-latest` | 3.10, 3.11, 3.12 |
| `windows-latest` | 3.10, 3.11, 3.12 |

**Steps:**
1. Checkout code
2. Install Rust toolchain
3. Set up Python version matrix
4. Install `maturin`
5. Build release wheel: `maturin build --release --strip` (Linux/macOS) or `maturin build --release` (Windows)
6. Upload wheel artifacts

#### 3. `test-wheel-install`
Verifies that the built wheels can be installed and imported.

**Steps:**
1. Download built wheels from `maturin-build`
2. Install wheel: `pip install wheels/*.whl`
3. Test import and basic functionality: `python -c "import turbo_parse; print(turbo_parse.health_check())"`

#### 4. `maturin-build-manylinux`
Builds portable Linux wheels using the manylinux standard.

| Target | Manylinux |
|--------|-----------|
| `x86_64` | auto (manylinux2014) |
| `aarch64` | auto (manylinux2014) |

Uses `PyO3/maturin-action@v1` for cross-platform manylinux builds.

#### 5. `check`
Summary job that waits for all other jobs and marks the CI as successful or failed.

## Running CI Locally

You can run what CI runs locally to verify your changes before pushing.

### Prerequisites

- Rust toolchain (install from [rustup.rs](https://rustup.rs))
- Python 3.10+ with pip
- maturin (`pip install maturin`)

### Commands

#### 1. Format Check
```bash
cargo fmt -p turbo_parse -- --check
```

#### 2. Run Clippy (Linting)
```bash
cargo clippy -p turbo_parse --all-features -- -D warnings
```

#### 3. Run Unit Tests
```bash
# Debug build (faster compilation)
cargo test -p turbo_parse

# Release build (optimized, matches CI)
cargo test -p turbo_parse --release
```

#### 4. Build Wheels (Development)
```bash
cd turbo_parse
maturin develop --release
```

This builds and installs the wheel into your current Python environment.

#### 5. Build Wheels (Distribution)
```bash
cd turbo_parse

# For local platform
maturin build --release --strip

# For manylinux (requires Docker - Linux only)
maturin build --release --strip --target x86_64-unknown-linux-gnu --manylinux 2014
```

#### 6. Test Wheel Installation
```bash
cd turbo_parse

# Build wheel
maturin build --release

# Install and test
pip install target/wheels/turbo_parse-*.whl
python -c "import turbo_parse; print(turbo_parse.health_check())"
```

### Local Development Workflow

For rapid development iteration:

```bash
# 1. Make changes to Rust code

# 2. Check formatting and lints
cargo fmt -p turbo_parse -- --check && cargo clippy -p turbo_parse

# 3. Run tests
cargo test -p turbo_parse

# 4. Build and install for Python testing
cd turbo_parse && maturin develop --release

# 5. Test Python integration
cd ..
python -c "import turbo_parse; print(turbo_parse.health_check())"
```

## Troubleshooting

### Common Issues

#### 1. Compilation Failures on Windows

**Issue:** Linking errors or missing system libraries.

**Solution:**
- Ensure you have the Windows SDK installed (via Visual Studio Build Tools)
- Run `rustup update` to get the latest toolchain
- For `ring` or `openssl-sys` issues, install `vcpkg` and required libraries

#### 2. Tests Pass Locally but Fail in CI

**Issue:** Platform-specific behavior or environment differences.

**Solution:**
- Check for hardcoded paths (use `std::path::Path` instead)
- Ensure line endings are consistent (use `.gitattributes` with `* text=auto`)
- Be aware of case-sensitivity differences (Linux is case-sensitive, macOS/Windows are not by default)

#### 3. maturin Build Fails

**Issue:** Python headers not found or maturin version mismatch.

**Solution:**
```bash
# Ensure Python development headers are installed
# On Ubuntu/Debian:
sudo apt-get install python3-dev

# On macOS (if using Homebrew Python):
brew install python@3.11

# Update maturin
pip install --upgrade maturin

# Check Python detection
maturin build --release --find-interpreter
```

#### 4. Rust Cache Issues in CI

**Issue:** CI builds taking too long or using stale cache.

**Solution:**
- The workflow uses `Swatinem/rust-cache@v2` with shared keys per job
- To clear cache manually, bump the `shared-key` in the workflow file or use GitHub's cache management UI

#### 5. Manylinux Wheel Fails to Install

**Issue:** `turbo_parse-*.whl is not a supported wheel on this platform`.

**Solution:**
- Manylinux wheels target specific glibc versions
- Check your system's glibc: `ldd --version`
- Build a local platform wheel instead: `maturin build --release`

#### 6. Formatting Check Fails in CI but Passes Locally

**Issue:** Rustfmt version mismatch.

**Solution:**
```bash
# Update rustfmt
rustup component add rustfmt --toolchain stable

# Reformat all code
cargo fmt -p turbo_parse
```

### Debugging CI Failures

1. **Check the job logs** - GitHub Actions provides detailed logs for each step
2. **Reproduce locally** - Run the exact commands from the workflow
3. **Check Rust version** - CI uses stable Rust; run `rustup update` locally
4. **Check Python version** - Ensure you're testing with the same version as CI

### Getting Help

- Check existing [GitHub Issues](https://github.com/mpfaffenberger/code_puppy/issues)
- Review the [main project README](../README.md)
- Look at [Cargo.toml](./Cargo.toml) and [pyproject.toml](./pyproject.toml) for dependency details
