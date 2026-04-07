# turbo_parse CI Documentation

This document describes the Continuous Integration (CI) setup for `turbo_parse`, how it works, how to run it locally, and troubleshooting common issues.

## Overview

The CI pipeline for `turbo_parse` ensures that the Rust crate builds and tests successfully across multiple platforms, that Python wheels are built correctly for distribution, and that performance regressions are detected before they reach `main`.

## CI Workflow

The CI is defined in `.github/workflows/turbo_parse.yml` and runs on:
- Every push to `main` that touches `turbo_parse/`, `Cargo.toml`, `Cargo.lock`, or the workflow itself
- Every pull request to `main` that touches the same paths
- Manual trigger via `workflow_dispatch` with optional `update_baseline` parameter

### Jobs

#### 1. `cargo-test`
Tests the Rust crate across all supported platforms.

| Platform | Checks |
|----------|--------|
| `ubuntu-latest` | ✓ Formatting, clippy, unit tests |
| `macos-latest` | ✓ Formatting, clippy, unit tests |
| `windows-latest` | ✓ Formatting, clippy, unit tests |

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

#### 5. `benchmark`
**Performance regression detection job.**

Runs on:
- Pull requests to `main`
- Pushes to `main`
- Manual workflow dispatch (for baseline updates)

**Key Features:**
- Runs `cargo bench` to collect performance metrics
- Compares against stored baseline in `turbo_parse/benches/baseline.json`
- Fails CI if any benchmark exceeds **15% regression threshold**
- Outputs GitHub Actions annotations for regressions
- Uploads benchmark results as artifacts

**Workflow Triggers:**
- **PR to main**: Runs benchmark check and compares against baseline
- **Push to main**: Runs benchmark check (as post-merge verification)
- **Manual with `update_baseline=true`**: Updates the baseline with current results

**Thresholds:**
| Metric | Value |
|--------|-------|
| Regression threshold | 15% |
| Target: 1k LOC (cold parse) | < 5ms |
| Target: 10k LOC (cold parse) | < 30ms |
| Target: 100k LOC (cold parse) | < 250ms |

**Steps:**
1. Checkout code
2. Install Rust toolchain
3. Verify baseline file exists
4. Run benchmarks with regression check:
   ```
   python benches/check_regression.py --ci --threshold 15.0
   ```
5. Upload results as artifact (success or failure)

#### 6. `check`
Summary job that waits for all other jobs and marks the CI as successful or failed.

## Benchmark CI Workflow

### What Happens on PR

When a pull request is opened against `main`:

1. The `benchmark` job runs automatically
2. Benchmarks execute and are compared against the baseline
3. If performance degrades >15%, the check fails with:
   - GitHub Actions error annotations in the PR
   - Log output with regression details
   - Blocked merge until resolved

### What Happens on Regression Failure

If the benchmark check fails:

```
❌ Benchmark regression check failed
   If this is a legitimate performance improvement, run the workflow with 'update_baseline' checked
```

**Next steps:**
1. **Accidental regression?** Fix the performance issue in your code
2. **Legitimate improvement?** Update the baseline (see below)

### Updating the Baseline

The baseline stores expected performance metrics. Update it after intentional performance improvements.

**Via GitHub Actions (Recommended):**

1. Go to **Actions → turbo_parse CI** in your repository
2. Click **"Run workflow"** dropdown
3. Select your branch with performance improvements
4. Check **"Update benchmark baseline"** checkbox
5. Click **"Run workflow"**
6. Commit the updated `baseline.json` file in the PR

**Via Local Command (Manual):**

```bash
cd turbo_parse
python benches/check_regression.py --save-baseline
```

This overwrites `baseline.json` with current results. Commit the updated file.

### Running Benchmarks Locally

```bash
cd turbo_parse

# Run benchmarks and check for regression (same as CI)
python benches/check_regression.py --ci --threshold 15.0

# Save current results as new baseline
python benches/check_regression.py --save-baseline

# Save results to separate file for comparison
python benches/check_regression.py --output my_results.json

# Test with stricter threshold (e.g., 10%)
python benches/check_regression.py --threshold 10.0
```

### Baseline File Format

The baseline is stored in `turbo_parse/benches/baseline.json`:

```json
{
  "_metadata": {
    "description": "Turbo Parse Performance Baseline",
    "created": "2025-01-07",
    "platform": "Apple M1 MacBook Pro",
    "notes": "Target goals for cold parse - measured without cache"
  },
  "benchmarks": [
    {
      "name": "python_parse/1k_loc/cold_parse",
      "duration_ns": 5000000,
      "target_ms": 5,
      "note": "Target: 1k Python LOC under 5ms"
    }
  ]
}
```

**Note:** The baseline stores **target goals** in nanoseconds for cold parse scenarios. CI compares actual benchmark results against these targets.

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
