#!/usr/bin/env python3
"""
Benchmark regression detection script.

Compares current benchmark results against a stored baseline and fails if
performance has regressed beyond the threshold (default: 15%).

Usage:
    python check_regression.py [--baseline PATH] [--threshold PERCENT] [--output PATH]
    python check_regression.py --ci [--baseline PATH] [--threshold PERCENT]

Returns:
    Exit code 0 if no regression detected
    Exit code 1 if regression detected
    Exit code 2 if error occurred
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkResult:
    name: str
    duration_ns: float
    throughput: float | None = None


def load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    """Load baseline benchmark results from JSON file."""
    if not path.exists():
        print(f"ERROR: Baseline file not found: {path}")
        print(
            "Run 'cargo bench -- --save-baseline=initial' first, then copy to baseline.json"
        )
        sys.exit(2)

    with open(path) as f:
        data = json.load(f)

    # Support both formats: with "benchmarks" key and flat format
    if "benchmarks" in data:
        entries = data["benchmarks"]
    else:
        entries = data

    # Normalize to a simple dict format
    results = {}
    for entry in entries:
        name = entry.get("name", entry.get("id", "unknown"))
        results[name] = {
            "duration_ns": entry.get("duration_ns", entry.get("mean", 0)),
            "throughput": entry.get("throughput"),
        }

    return results


def run_benchmarks() -> list[dict[str, Any]]:
    """Run cargo bench and capture JSON output."""
    print("Running benchmarks (this may take a few minutes)...")
    print("=" * 60)

    try:
        result = subprocess.run(
            ["cargo", "bench", "--", "--output-format=json"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
    except subprocess.TimeoutExpired:
        print("ERROR: Benchmark timed out after 5 minutes")
        sys.exit(2)
    except FileNotFoundError:
        print("ERROR: 'cargo' command not found. Is Rust installed?")
        sys.exit(2)

    if result.returncode != 0:
        print(f"ERROR: Benchmark failed with exit code {result.returncode}")
        print("STDERR:", result.stderr)
        sys.exit(2)

    # Parse JSON output lines
    benchmarks = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if "reason" in data and data["reason"] == "benchmark-complete":
                benchmarks.append(
                    {
                        "name": data.get("id", "unknown"),
                        "duration_ns": data.get("mean", 0),
                        "throughput": data.get("throughput", None),
                    }
                )
        except json.JSONDecodeError:
            continue

    return benchmarks


def check_regression(
    current: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    threshold_percent: float,
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Compare current results against baseline.

    Returns:
        Tuple of (has_regression, comparison_details)
    """
    regressions = []
    improvements = []
    unchanged = []
    missing = []

    for result in current:
        name = result["name"]
        current_ns = result["duration_ns"]

        if name not in baseline:
            missing.append({"name": name, "current_ns": current_ns})
            continue

        baseline_ns = baseline[name]["duration_ns"]
        if baseline_ns == 0:
            continue

        change_percent = ((current_ns - baseline_ns) / baseline_ns) * 100

        comparison = {
            "name": name,
            "baseline_ns": baseline_ns,
            "current_ns": current_ns,
            "change_percent": change_percent,
            "baseline_ms": baseline_ns / 1_000_000,
            "current_ms": current_ns / 1_000_000,
        }

        if change_percent > threshold_percent:
            regressions.append(comparison)
        elif change_percent < -threshold_percent:
            improvements.append(comparison)
        else:
            unchanged.append(comparison)

    # Check for missing benchmarks in current run
    current_names = {r["name"] for r in current}
    for name in baseline:
        if name not in current_names:
            missing.append({"name": name, "note": "Missing in current run"})

    return len(regressions) > 0, {
        "regressions": regressions,
        "improvements": improvements,
        "unchanged": unchanged,
        "missing": missing,
    }


def print_report(
    comparison: dict[str, Any], threshold: float, ci_mode: bool = False
) -> None:
    """Print a formatted comparison report.

    In CI mode, outputs GitHub Actions annotations for regressions.
    """
    regressions = comparison.get("regressions", [])
    improvements = comparison.get("improvements", [])
    unchanged = comparison.get("unchanged", [])
    missing = comparison.get("missing", [])

    if ci_mode:
        # CI-friendly output with GitHub Actions annotations
        print("\n" + "=" * 80)
        print("BENCHMARK REGRESSION REPORT (CI Mode)")
        print("=" * 80)
        print(f"Threshold: {threshold:.1f}%")
        print()

        if regressions:
            print(
                f"::error title=Performance Regressions Detected::{len(regressions)} benchmark(s) exceeded {threshold:.1f}% regression threshold"
            )
            for r in regressions:
                # GitHub Actions error annotation
                print(
                    f"::error title={r['name']} regression::{r['name']}: +{r['change_percent']:.1f}% ({r['baseline_ms']:.3f}ms -> {r['current_ms']:.3f}ms)"
                )

        if improvements:
            print(
                f"::notice title=Performance Improvements::{len(improvements)} benchmark(s) showed significant improvement"
            )
            for i in improvements:
                print(
                    f"::notice title={i['name']} improvement::{i['name']}: {i['change_percent']:.1f}% ({i['baseline_ms']:.3f}ms -> {i['current_ms']:.3f}ms)"
                )

        if missing:
            print(
                f"::warning title=Missing Benchmarks::{len(missing)} benchmark(s) missing or new"
            )
            for m in missing:
                if "note" in m:
                    print(f"::warning::{m['name']}: {m['note']}")
                else:
                    print(f"::notice::{m['name']}: New benchmark (no baseline)")

        # Summary table for CI logs
        print("\n" + "-" * 80)
        print("SUMMARY TABLE")
        print("-" * 80)
        print(f"{'Benchmark':<40} {'Baseline':>12} {'Current':>12} {'Change':>10}")
        print("-" * 80)

        all_tests = regressions + improvements + unchanged
        for test in all_tests:
            symbol = (
                "🔴" if test in regressions else "🟢" if test in improvements else "✓"
            )
            print(
                f"{symbol} {test['name']:<38} {test['baseline_ms']:>10.3f}ms {test['current_ms']:>10.3f}ms {test['change_percent']:>+8.1f}%"
            )

        for m in missing:
            if "note" in m:
                print(f"⚠️  {m['name']:<38} {'MISSING':>12} {'N/A':>12} {'N/A':>10}")
            else:
                print(f"✨ {m['name']:<38} {'NEW':>12} {'N/A':>12} {'N/A':>10}")

        print("-" * 80)
        return

    # Interactive mode (original output)
    print("\n" + "=" * 80)
    print("BENCHMARK REGRESSION REPORT")
    print("=" * 80)
    print(f"Threshold: {threshold:.1f}%")
    print()

    if regressions:
        print(f"🔴 REGRESSIONS DETECTED ({len(regressions)} tests):")
        print("-" * 80)
        for r in regressions:
            print(f"  {r['name']}")
            print(f"    Baseline: {r['baseline_ms']:.3f}ms")
            print(f"    Current:  {r['current_ms']:.3f}ms")
            print(f"    Change:   +{r['change_percent']:.1f}% ⚠️")
            print()

    if improvements:
        print(f"🟢 IMPROVEMENTS ({len(improvements)} tests):")
        print("-" * 80)
        for i in improvements:
            print(f"  {i['name']}")
            print(f"    Baseline: {i['baseline_ms']:.3f}ms")
            print(f"    Current:  {i['current_ms']:.3f}ms")
            print(f"    Change:   {i['change_percent']:.1f}% ✓")
            print()

    if missing:
        print(f"⚠️  MISSING ({len(missing)} tests):")
        print("-" * 80)
        for m in missing:
            if "note" in m:
                print(f"  {m['name']}: {m['note']}")
            else:
                print(f"  {m['name']}: New benchmark (no baseline)")
        print()

    if unchanged:
        print(f"✓ UNCHANGED ({len(unchanged)} tests within threshold)")
        print()


def save_results(results: list[dict], output_path: Path) -> None:
    """Save benchmark results to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {output_path}")


def create_baseline_template(output_path: Path) -> None:
    """Create a baseline template with performance goals."""
    template = {
        "_metadata": {
            "description": "Turbo Parse Performance Baseline",
            "target_goals": {
                "python_parse/1k_loc/cold_parse": "< 5ms",
                "python_parse/10k_loc/cold_parse": "< 30ms",
                "python_parse/100k_loc/cold_parse": "< 250ms",
                "rust_parse/1k_loc/cold_parse": "< 5ms",
                "rust_parse/10k_loc/cold_parse": "< 30ms",
                "rust_parse/100k_loc/cold_parse": "< 250ms",
                "javascript_parse/1k_loc/cold_parse": "< 5ms",
                "javascript_parse/10k_loc/cold_parse": "< 30ms",
                "javascript_parse/100k_loc/cold_parse": "< 250ms",
            },
            "notes": "Times are for cold parse on Apple M1 MacBook Pro",
        },
        "benchmarks": [],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(template, f, indent=2)
    print(f"Baseline template created at: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for benchmark regressions against baseline"
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).parent / "baseline.json",
        help="Path to baseline JSON file (default: baseline.json)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=15.0,
        help="Regression threshold percentage (default: 15%%)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save current results to JSON file",
    )
    parser.add_argument(
        "--create-baseline",
        action="store_true",
        help="Create a baseline template file",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Save current results as new baseline",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: non-interactive with GitHub Actions annotations",
    )

    args = parser.parse_args()

    # Auto-detect CI mode from environment
    ci_mode = args.ci or os.environ.get("CI", "").lower() in ("true", "1", "yes")

    if args.create_baseline:
        create_baseline_template(args.baseline)
        return 0

    # Run benchmarks
    current_results = run_benchmarks()

    if not current_results:
        print("ERROR: No benchmark results found")
        return 2

    # Save results if requested
    if args.output:
        save_results(current_results, args.output)

    # Save as new baseline if requested
    if args.save_baseline:
        save_results(current_results, args.baseline)
        print(f"New baseline saved to: {args.baseline}")
        return 0

    # Load baseline and compare
    baseline = load_baseline(args.baseline)

    has_regression, comparison = check_regression(
        current_results,
        baseline,
        args.threshold,
    )

    # Print report
    print_report(comparison, args.threshold, ci_mode=ci_mode)

    # Summary
    if ci_mode:
        print("=" * 80)
    else:
        print("=" * 80)

    if has_regression:
        if ci_mode:
            print(
                "::error title=Benchmark Regression::❌ REGRESSION DETECTED: Performance has degraded beyond threshold"
            )
            print("   Run with --save-baseline to update baseline if this is expected")
        else:
            print("❌ REGRESSION DETECTED: Performance has degraded beyond threshold")
            print("   Run with --save-baseline to update baseline if this is expected")
        return 1
    else:
        if ci_mode:
            print(
                "::notice title=Benchmark Check Passed::✅ NO REGRESSION: Performance is within acceptable range"
            )
        else:
            print("✓ NO REGRESSION: Performance is within acceptable range")
        return 0


if __name__ == "__main__":
    sys.exit(main())
