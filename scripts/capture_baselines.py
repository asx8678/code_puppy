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
    summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}

    if test_type == "pytest":
        # Look for pytest summary line like "5 passed, 1 failed, 2 skipped"
        match = re.search(r"(\d+) passed", output)
        if match:
            summary["passed"] = int(match.group(1))
        match = re.search(r"(\d+) failed", output)
        if match:
            summary["failed"] = int(match.group(1))
        match = re.search(r"(\d+) skipped", output)
        if match:
            summary["skipped"] = int(match.group(1))
        match = re.search(r"(\d+) error", output)
        if match:
            summary["errors"] = int(match.group(1))
        summary["total"] = (
            summary["passed"]
            + summary["failed"]
            + summary["skipped"]
            + summary["errors"]
        )

    return summary


def capture_baselines():
    baselines_dir = Path("/tmp/code_puppy_baselines")
    baselines_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().isoformat()

    # Get git commit
    git_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd="/Users/adam2/projects/code_puppy",
    )
    git_commit = git_result.stdout.strip()

    # Run pytest
    print("Running pytest...")
    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-xvs"],
        capture_output=True,
        text=True,
        cwd="/Users/adam2/projects/code_puppy",
    )
    pytest_summary = parse_test_summary(
        pytest_result.stdout + pytest_result.stderr, "pytest"
    )
    print(
        f"  Pytest tests: {pytest_summary['passed']} passed, {pytest_summary['failed']} failed, {pytest_summary['skipped']} skipped"
    )

    baseline = {
        "timestamp": timestamp,
        "git_commit": git_commit,
        "pytest": {
            "returncode": pytest_result.returncode,
            "stdout": pytest_result.stdout,
            "stderr": pytest_result.stderr,
            "summary": pytest_summary,
        },
    }

    # Create filename with sanitized timestamp
    filename_timestamp = timestamp.replace(":", "-").split(".")[0]
    output_file = baselines_dir / f"baseline_{filename_timestamp}.json"

    with open(output_file, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"\n✅ Baseline saved to: {output_file}")
    return output_file, pytest_summary


if __name__ == "__main__":
    output_file, pytest_summary = capture_baselines()
    print(f"\n{'=' * 60}")
    print("BASELINE CAPTURE SUMMARY")
    print(f"{'=' * 60}")
    print(f"File: {output_file}")
    print(
        f"\nPytest Tests: {pytest_summary['passed']:3d} passed, {pytest_summary['failed']:3d} failed, {pytest_summary['skipped']:3d} skipped (total: {pytest_summary['total']})"
    )
