#!/usr/bin/env python3
"""Regression gate: Compare current test results against baseline."""

import subprocess
import json
import sys
import re
from pathlib import Path


def parse_test_summary(output: str, test_type: str) -> dict:
    """Parse test output to extract pass/fail counts."""
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0
    }
    
    if test_type == "pytest":
        # Look for pytest summary line like "5 passed, 1 failed, 2 skipped"
        match = re.search(r'(\d+) passed', output)
        if match:
            summary["passed"] = int(match.group(1))
        match = re.search(r'(\d+) failed', output)
        if match:
            summary["failed"] = int(match.group(1))
        match = re.search(r'(\d+) skipped', output)
        if match:
            summary["skipped"] = int(match.group(1))
        match = re.search(r'(\d+) error', output)
        if match:
            summary["errors"] = int(match.group(1))
        summary["total"] = summary["passed"] + summary["failed"] + summary["skipped"] + summary["errors"]
    
    elif test_type == "cargo":
        # Parse cargo test output - look for "test result:"
        for line in output.split('\n'):
            if 'test result:' in line:
                # Example: "test result: ok. 45 passed; 0 failed; 0 ignored;"
                passed_match = re.search(r'(\d+) passed', line)
                failed_match = re.search(r'(\d+) failed', line)
                ignored_match = re.search(r'(\d+) ignored', line)
                
                if passed_match:
                    summary["passed"] = int(passed_match.group(1))
                if failed_match:
                    summary["failed"] = int(failed_match.group(1))
                if ignored_match:
                    summary["skipped"] = int(ignored_match.group(1))
                
                summary["total"] = summary["passed"] + summary["failed"] + summary["skipped"]
                break
    
    return summary


def load_baseline():
    """Load most recent baseline from /tmp/code_puppy_baselines/"""
    baselines_dir = Path("/tmp/code_puppy_baselines")
    if not baselines_dir.exists():
        print("ERROR: No baselines found. Run capture_baselines.py first.")
        sys.exit(1)
    
    baseline_files = sorted(baselines_dir.glob("baseline_*.json"), reverse=True)
    if not baseline_files:
        print("ERROR: No baseline files found.")
        sys.exit(1)
    
    with open(baseline_files[0]) as f:
        return json.load(f)


def run_current_tests():
    """Run tests and return results."""
    print("Running cargo test...")
    cargo_result = subprocess.run(
        ["cargo", "test", "--workspace"],
        capture_output=True, text=True, cwd="/Users/adam2/projects/code_puppy"
    )
    cargo_summary = parse_test_summary(cargo_result.stdout, "cargo")
    
    print("Running pytest...")
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v"],
        capture_output=True, text=True, cwd="/Users/adam2/projects/code_puppy"
    )
    pytest_summary = parse_test_summary(pytest_result.stdout + pytest_result.stderr, "pytest")
    
    return {
        "cargo_test": {
            "returncode": cargo_result.returncode,
            "stdout": cargo_result.stdout,
            "summary": cargo_summary
        },
        "pytest": {
            "returncode": pytest_result.returncode,
            "stdout": pytest_result.stdout,
            "summary": pytest_summary
        }
    }


def compare_results(baseline, current):
    """Compare test results and report diffs."""
    issues = []
    
    # Compare cargo test
    baseline_cargo_passed = baseline["cargo_test"]["summary"]["passed"]
    current_cargo_passed = current["cargo_test"]["summary"]["passed"]
    
    if current["cargo_test"]["returncode"] != 0:
        issues.append(f"FAIL: Cargo tests failed (exit {current['cargo_test']['returncode']})")
    elif current_cargo_passed < baseline_cargo_passed:
        issues.append(f"FAIL: Cargo tests regression: {current_cargo_passed} < {baseline_cargo_passed} passed")
    else:
        print(f"✓ PASS: Cargo tests: {current_cargo_passed} >= {baseline_cargo_passed} baseline")
    
    # Compare pytest
    baseline_py_passed = baseline["pytest"]["summary"]["passed"]
    current_py_passed = current["pytest"]["summary"]["passed"]
    
    if current["pytest"]["returncode"] != 0:
        issues.append(f"FAIL: Pytest failed (exit {current['pytest']['returncode']})")
    elif current_py_passed < baseline_py_passed:
        issues.append(f"FAIL: Pytest regression: {current_py_passed} < {baseline_py_passed} passed")
    else:
        print(f"✓ PASS: Pytest: {current_py_passed} >= {baseline_py_passed} baseline")
    
    return issues


def main():
    baseline = load_baseline()
    current = run_current_tests()
    
    git_result = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        capture_output=True, text=True, cwd="/Users/adam2/projects/code_puppy"
    )
    current_commit = git_result.stdout.strip()
    
    print("\n" + "=" * 60)
    print("REGRESSION GATE")
    print("=" * 60)
    print(f"Baseline commit: {baseline['git_commit'][:8]}")
    print(f"Current commit:  {current_commit[:8]}")
    print()
    
    issues = compare_results(baseline, current)
    
    # Show detailed counts
    print()
    print("Detailed Comparison:")
    print(f"  Cargo:  {current['cargo_test']['summary']['passed']} passed "
          f"(baseline: {baseline['cargo_test']['summary']['passed']})")
    print(f"  Pytest: {current['pytest']['summary']['passed']} passed "
          f"(baseline: {baseline['pytest']['summary']['passed']})")
    
    if issues:
        print("\n" + "❌" * 20)
        print("REGRESSION GATE FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        print("❌" * 20)
        sys.exit(1)
    else:
        print("\n" + "✅" * 20)
        print("REGRESSION GATE PASSED: All tests match or exceed baseline")
        print("✅" * 20)
        sys.exit(0)


if __name__ == "__main__":
    main()
