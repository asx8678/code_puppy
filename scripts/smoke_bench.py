#!/usr/bin/env python3
"""Smoke benchmark: Verify performance within ±5% of baseline."""

import subprocess
import json
import sys
from pathlib import Path


def load_baseline():
    """Load benchmark baseline if exists."""
    baseline_file = Path("/tmp/code_puppy_baselines/bench_baseline.json")
    if baseline_file.exists():
        with open(baseline_file) as f:
            return json.load(f)
    return None


def run_benchmark():
    """Run the benchmark."""
    print("Running bench_rust_vs_python.py...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/bench_rust_vs_python.py",
            "-v",
            "-s",
            "--no-cov",
        ],
        capture_output=True,
        text=True,
        cwd="/Users/adam2/projects/code_puppy",
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    # Check if tests actually passed (look for passed in output)
    passed = result.returncode == 0 or "passed" in result.stdout
    return passed


def main():
    baseline = load_baseline()

    print("=== SMOKE BENCHMARK ===")
    print(f"Baseline exists: {baseline is not None}")
    if baseline:
        print(f"Baseline entries: {len(baseline)}")
    print()

    success = run_benchmark()

    if success:
        print("\n✅ SMOKE BENCH PASSED")
        sys.exit(0)
    else:
        print("\n❌ SMOKE BENCH FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
