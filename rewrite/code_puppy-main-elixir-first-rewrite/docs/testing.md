# Testing Guide

This document describes the testing infrastructure and regression gates for code_puppy.

## Overview

We run two test suites:

1. **Cargo tests** - Rust workspace tests
2. **Pytest** - Python tests

## Running Tests

### Manual Test Run

```bash
# Run Rust tests
cargo test --workspace

# Run Python tests
uv run pytest -v
# or
pytest -v
```

### Regression Gate

The regression gate compares current test results against a baseline to ensure no regressions are introduced.

#### Step 1: Capture Baseline

Before making changes, capture the current baseline:

```bash
python scripts/capture_baselines.py
```

This creates a baseline file in `/tmp/code_puppy_baselines/` with test results and git commit info.

#### Step 2: Run Regression Gate

After making changes, verify no regressions:

```bash
python scripts/regression_gate.py
```

The gate will:
- Load the most recent baseline
- Run current cargo test and pytest
- Compare results
- Exit with code 0 on pass, 1 on failure

#### Regression Gate Criteria

The gate **FAILS** if:
- Cargo tests exit with non-zero code
- Pytest exits with non-zero code  
- Number of passed tests is less than baseline

The gate **PASSES** if:
- All tests pass or exceed baseline counts

### Presubmit/CI Integration

Run the regression gate before committing:

```bash
# Recommended presubmit workflow
python scripts/capture_baselines.py   # Establish baseline
# ... make your changes ...
python scripts/regression_gate.py       # Verify no regressions
```

#### Git Hook Integration

To add the regression gate to lefthook pre-push:

```yaml
# lefthook.yml
pre-push:
  commands:
    regression-gate:
      run: python scripts/regression_gate.py
```

Note: Consider the runtime - full test suite may take 3-5 minutes.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/capture_baselines.py` | Save current test results as baseline |
| `scripts/regression_gate.py` | Compare current results against baseline |

## Baseline Storage

Baselines are stored in `/tmp/code_puppy_baselines/baseline_YYYY-MM-DDTHH-MM-SS.json`

Each baseline contains:
- Timestamp
- Git commit hash
- Cargo test results (stdout, stderr, summary, return code)
- Pytest results (stdout, stderr, summary, return code)

## Troubleshooting

**"No baselines found"**
- Run `python scripts/capture_baselines.py` first to establish a baseline

**Gate fails due to unrelated test failures**
- Ensure your environment is clean (`uv sync`, `cargo clean` if needed)
- Check that all dependencies are installed
- Re-capture baseline if tests were flaky

**Long runtime**
- The regression gate runs the full test suite
- Consider using it only in CI or before important commits
- Use individual test runs (`cargo test`, `pytest`) for faster feedback during development
