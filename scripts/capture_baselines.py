#!/usr/bin/env python3
"""Capture test and benchmark baselines for regression detection."""

import subprocess
import json
import sys
import re
from datetime import datetime
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


def capture_baselines():
    baselines_dir = Path("/tmp/code_puppy_baselines")
    baselines_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().isoformat()
    
    # Get git commit
    git_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd="/Users/adam2/projects/code_puppy"
    )
    git_commit = git_result.stdout.strip()
    
    # Run cargo test
    print("Running cargo test --workspace...")
    cargo_result = subprocess.run(
        ["cargo", "test", "--workspace"],
        capture_output=True,
        text=True,
        cwd="/Users/adam2/projects/code_puppy"
    )
    cargo_summary = parse_test_summary(cargo_result.stdout, "cargo")
    print(f"  Cargo tests: {cargo_summary['passed']} passed, {cargo_summary['failed']} failed, {cargo_summary['skipped']} skipped")
    
    # Run pytest
    print("Running pytest...")
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-xvs"],
        capture_output=True,
        text=True,
        cwd="/Users/adam2/projects/code_puppy"
    )
    pytest_summary = parse_test_summary(pytest_result.stdout + pytest_result.stderr, "pytest")
    print(f"  Pytest tests: {pytest_summary['passed']} passed, {pytest_summary['failed']} failed, {pytest_summary['skipped']} skipped")
    
    baseline = {
        "timestamp": timestamp,
        "git_commit": git_commit,
        "cargo_test": {
            "returncode": cargo_result.returncode,
            "stdout": cargo_result.stdout,
            "stderr": cargo_result.stderr,
            "summary": cargo_summary
        },
        "pytest": {
            "returncode": pytest_result.returncode,
            "stdout": pytest_result.stdout,
            "stderr": pytest_result.stderr,
            "summary": pytest_summary
        }
    }
    
    # Create filename with sanitized timestamp
    filename_timestamp = timestamp.replace(':', '-').split('.')[0]
    output_file = baselines_dir / f"baseline_{filename_timestamp}.json"
    
    with open(output_file, 'w') as f:
        json.dump(baseline, f, indent=2)
    
    print(f"\n✅ Baseline saved to: {output_file}")
    return output_file, cargo_summary, pytest_summary


if __name__ == "__main__":
    output_file, cargo_summary, pytest_summary = capture_baselines()
    print(f"\n{'='*60}")
    print("BASELINE CAPTURE SUMMARY")
    print(f"{'='*60}")
    print(f"File: {output_file}")
    print(f"\nCargo Tests:  {cargo_summary['passed']:3d} passed, {cargo_summary['failed']:3d} failed, {cargo_summary['skipped']:3d} skipped (total: {cargo_summary['total']})")
    print(f"Pytest Tests: {pytest_summary['passed']:3d} passed, {pytest_summary['failed']:3d} failed, {pytest_summary['skipped']:3d} skipped (total: {pytest_summary['total']})")
