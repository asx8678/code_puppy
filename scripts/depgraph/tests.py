#!/usr/bin/env python3
"""Self-tests for dependency graph generator (using only stdlib)."""

from __future__ import annotations

import sys
from pathlib import Path

from .analyzer import calculate_module_name
from .models import ModuleInfo
from .porting import compute_porting_order
from .reports import format_timestamp
from .resolver import find_matching_module, resolve_relative_import


def test_resolve_relative_import() -> bool:
    """Test relative import resolution."""
    tests = [
        # (current_module, level, module, expected)
        ("code_puppy.tools.file_ops", 1, "utils", "code_puppy.tools.utils"),
        ("code_puppy.tools.file_ops", 2, "utils", "code_puppy.utils"),
        ("code_puppy.tools.file_ops", 1, None, "code_puppy.tools"),
        ("code_puppy.tools.file_ops", 2, None, "code_puppy"),
        ("code_puppy", 1, "config", "config"),  # Would go above package
        ("code_puppy", 2, None, None),  # Invalid - can't go above root
    ]

    all_passed = True
    for current, level, module, expected in tests:
        result = resolve_relative_import(current, level, module)
        if result != expected:
            print(f"FAIL: resolve_relative_import({current!r}, {level}, {module!r})")
            print(f"  Expected: {expected!r}")
            print(f"  Got:      {result!r}")
            all_passed = False
        else:
            print(f"PASS: relative import {current} + {level}* + {module} = {result}")

    return all_passed


def test_longest_module_matching() -> bool:
    """Test longest-module matching for imports."""
    modules = {
        "code_puppy",
        "code_puppy.tools",
        "code_puppy.tools.file_ops",
        "code_puppy.utils",
    }

    tests = [
        # (import_name, expected_match)
        ("code_puppy.tools.file_ops", "code_puppy.tools.file_ops"),
        ("code_puppy.tools.file_ops.read", "code_puppy.tools.file_ops"),
        ("code_puppy.tools.utils", "code_puppy.tools"),
        ("code_puppy.config", "code_puppy"),
        ("code_puppy.utils.helper", "code_puppy.utils"),
        ("nonexistent", None),
    ]

    all_passed = True
    for import_name, expected in tests:
        result = find_matching_module(import_name, modules)
        if result != expected:
            print(f"FAIL: find_matching_module({import_name!r})")
            print(f"  Expected: {expected!r}")
            print(f"  Got:      {result!r}")
            all_passed = False
        else:
            print(f"PASS: longest match for {import_name} = {result}")

    return all_passed


def test_deterministic_cycles() -> bool:
    """Test that cycle detection is deterministic."""
    from .cycles import find_cycles

    # Create a simple cycle: a -> b -> c -> a
    modules = {
        "mod_a": ModuleInfo(
            name="mod_a",
            file_path=Path("a.py"),
            imports={"mod_b"},
        ),
        "mod_b": ModuleInfo(
            name="mod_b",
            file_path=Path("b.py"),
            imports={"mod_c"},
        ),
        "mod_c": ModuleInfo(
            name="mod_c",
            file_path=Path("c.py"),
            imports={"mod_a"},
        ),
        "mod_d": ModuleInfo(
            name="mod_d",
            file_path=Path("d.py"),
            imports=set(),
        ),
    }

    # Build imported_by relationships
    for mod_name, mod_info in modules.items():
        for imp in mod_info.imports:
            if imp in modules:
                modules[imp].imported_by.add(mod_name)

    # Run cycle detection multiple times
    cycles_runs = []
    for _ in range(3):
        cycles = find_cycles(modules)
        cycles_runs.append(cycles)

    # Check all runs produce the same result
    all_same = all(c == cycles_runs[0] for c in cycles_runs)
    if not all_same:
        print("FAIL: Cycle detection is not deterministic")
        for i, c in enumerate(cycles_runs):
            print(f"  Run {i + 1}: {c}")
        return False

    # Check cycles are sorted
    if cycles_runs[0]:
        first_cycle = cycles_runs[0][0]
        if first_cycle[0] != min(first_cycle[:-1]):
            print(f"FAIL: Cycle not normalized: {first_cycle}")
            return False

    print(
        f"PASS: Cycle detection is deterministic ({len(cycles_runs[0])} cycles found)"
    )
    return True


def test_porting_order() -> bool:
    """Test that porting order puts leaves first, hubs last."""
    # Create modules: leaf (no deps), hub (many importers), middle
    modules = {
        "hub": ModuleInfo(
            name="hub",
            file_path=Path("hub.py"),
            imports=set(),
            imported_by={
                "middle1",
                "middle2",
                "middle3",
                "middle4",
                "middle5",
                "middle6",
                "middle7",
                "middle8",
                "middle9",
                "middle10",
            },
        ),
        "middle1": ModuleInfo(
            name="middle1",
            file_path=Path("m1.py"),
            imports={"hub"},
            imported_by={"leaf"},
        ),
        "middle2": ModuleInfo(
            name="middle2",
            file_path=Path("m2.py"),
            imports={"hub"},
            imported_by=set(),
        ),
        "leaf": ModuleInfo(
            name="leaf",
            file_path=Path("leaf.py"),
            imports={"middle1"},
            imported_by=set(),
        ),
    }

    porting_order = compute_porting_order(modules)

    # Extract just the module names in order
    ordered_names = [name for name, _ in porting_order]

    # Check that leaf comes before hub (hub has high fan-in, should be last)
    hub_idx = ordered_names.index("hub")
    leaf_idx = ordered_names.index("leaf")

    # Both should be at depth 0 (no internal imports)
    hub_depth = next(d for n, d in porting_order if n == "hub")
    leaf_depth = next(d for n, d in porting_order if n == "leaf")

    # At same depth, leaf (fan_in=0) should come before hub (fan_in=10)
    if hub_depth == leaf_depth and hub_idx < leaf_idx:
        print("FAIL: Hub appears before leaf at same depth")
        print(f"  Order: {ordered_names}")
        return False

    print(f"PASS: Porting order correct: {ordered_names}")
    return True


def test_module_name_calculation() -> bool:
    """Test module name calculation from file paths."""
    tests = [
        # (file_path, package_root, package_name, expected)
        (
            Path("/pkg/code_puppy/__init__.py"),
            Path("/pkg/code_puppy"),
            "code_puppy",
            "code_puppy",
        ),
        (
            Path("/pkg/code_puppy/tools.py"),
            Path("/pkg/code_puppy"),
            "code_puppy",
            "code_puppy.tools",
        ),
        (
            Path("/pkg/code_puppy/utils/file.py"),
            Path("/pkg/code_puppy"),
            "code_puppy",
            "code_puppy.utils.file",
        ),
        (
            Path("/pkg/code_puppy/agents/__init__.py"),
            Path("/pkg/code_puppy"),
            "code_puppy",
            "code_puppy.agents",
        ),
    ]

    all_passed = True
    for file_path, package_root, package_name, expected in tests:
        result = calculate_module_name(file_path, package_root, package_name)
        if result != expected:
            print(
                f"FAIL: calculate_module_name({file_path}, {package_root}, {package_name})"
            )
            print(f"  Expected: {expected!r}")
            print(f"  Got:      {result!r}")
            all_passed = False
        else:
            print(f"PASS: {file_path.name} -> {result}")

    return all_passed


def test_stable_timestamp() -> bool:
    """Test stable timestamp generation."""
    ts1 = format_timestamp(stable=True)
    ts2 = format_timestamp(stable=True)

    if ts1 != ts2:
        print(f"FAIL: Stable timestamps differ: {ts1} vs {ts2}")
        return False

    if "2026-01-01" not in ts1:
        print(f"FAIL: Stable timestamp format unexpected: {ts1}")
        return False

    print(f"PASS: Stable timestamp: {ts1}")
    return True


def run_self_tests() -> int:
    """Run all self-tests."""
    print("=" * 60)
    print("Dependency Graph Generator - Self Tests")
    print("=" * 60)
    print()

    tests = [
        ("Relative Import Resolution", test_resolve_relative_import),
        ("Longest Module Matching", test_longest_module_matching),
        ("Deterministic Cycles", test_deterministic_cycles),
        ("Porting Order", test_porting_order),
        ("Module Name Calculation", test_module_name_calculation),
        ("Stable Timestamp", test_stable_timestamp),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((name, False))

    print()
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print()
    print(f"Total: {passed_count}/{total_count} passed")

    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(run_self_tests())
