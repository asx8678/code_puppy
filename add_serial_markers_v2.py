#!/usr/bin/env python3
"""
Add pytest.mark.serial and pytest.mark.xdist_group markers to test files.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional


def ensure_pytest_import(lines: List[str]) -> List[str]:
    """Add import pytest if not already present."""
    for i, line in enumerate(lines):
        if line.strip().startswith("import pytest"):
            return lines
    # Find the first import line and insert after it
    for i, line in enumerate(lines):
        if line.strip().startswith("import "):
            lines.insert(i + 1, "import pytest\n")
            return lines
    # If no imports, insert at top after docstring
    for i, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith('"""') and not line.strip().startswith("'''"):
            lines.insert(i, "import pytest\n")
            return lines
    # fallback: insert at line 0
    lines.insert(0, "import pytest\n")
    return lines


def find_test_function(lines: List[str], test_name: str) -> Optional[int]:
    """Return line index where test function starts (the line with 'def test_...')."""
    for i, line in enumerate(lines):
        if line.strip().startswith(f"def {test_name}"):
            return i
    return None


def find_class(lines: List[str], class_name: str) -> Optional[int]:
    for i, line in enumerate(lines):
        if line.strip().startswith(f"class {class_name}"):
            return i
    return None


def add_decorator(lines: List[str], line_idx: int, decorator: str) -> None:
    """Insert decorator before the given line index."""
    lines.insert(line_idx, decorator + "\n")


def has_serial_marker(lines: List[str], idx: int) -> bool:
    """Check if there is a @pytest.mark.serial decorator before idx."""
    for j in range(max(0, idx - 3), idx):
        if "@pytest.mark.serial" in lines[j]:
            return True
    return False


def has_xdist_group_marker(lines: List[str], idx: int) -> bool:
    for j in range(max(0, idx - 3), idx):
        if "@pytest.mark.xdist_group" in lines[j]:
            return True
    return False


def add_markers_to_function(lines: List[str], test_name: str, group: str) -> bool:
    """Add markers to a specific test function. Returns True if successful."""
    idx = find_test_function(lines, test_name)
    if idx is None:
        print(f"WARNING: Test function '{test_name}' not found")
        return False
    if has_serial_marker(lines, idx):
        print(f"  Skipping {test_name} (already marked)")
        return False
    add_decorator(lines, idx, "@pytest.mark.serial")
    add_decorator(lines, idx + 1, f'@pytest.mark.xdist_group(name="{group}")')
    return True


def add_markers_to_class(lines: List[str], class_name: str, group: str) -> bool:
    idx = find_class(lines, class_name)
    if idx is None:
        print(f"WARNING: Class '{class_name}' not found")
        return False
    if has_serial_marker(lines, idx):
        print(f"  Skipping class {class_name} (already marked)")
        return False
    add_decorator(lines, idx, "@pytest.mark.serial")
    add_decorator(lines, idx + 1, f'@pytest.mark.xdist_group(name="{group}")')
    return True


def add_markers_to_all_functions(lines: List[str], group: str) -> int:
    """Add markers to all test functions (lines starting with 'def test_')."""
    added = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("def test_"):
            if has_serial_marker(lines, i):
                i += 1
                continue
            add_decorator(lines, i, "@pytest.mark.serial")
            add_decorator(lines, i + 1, f'@pytest.mark.xdist_group(name="{group}")')
            added += 1
            i += 2  # skip the inserted lines
        i += 1
    return added


def add_markers_to_all_classes(lines: List[str], group: str) -> int:
    added = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("class Test"):
            if has_serial_marker(lines, i):
                i += 1
                continue
            add_decorator(lines, i, "@pytest.mark.serial")
            add_decorator(lines, i + 1, f'@pytest.mark.xdist_group(name="{group}")')
            added += 1
            i += 2
        i += 1
    return added


def process_file(filepath: Path, group: str, test_names: Optional[List[str]], mark_all: bool = False, mark_classes: bool = False) -> None:
    """Process a single test file."""
    if not filepath.exists():
        print(f"ERROR: File {filepath} does not exist")
        return
    with open(filepath, "r") as f:
        lines = f.readlines()
    
    # Ensure pytest import
    lines = ensure_pytest_import(lines)
    
    if mark_all:
        added_funcs = add_markers_to_all_functions(lines, group)
        added_classes = add_markers_to_all_classes(lines, group)
        print(f"  Added markers to {added_funcs} functions and {added_classes} classes")
    elif test_names:
        for name in test_names:
            if name.startswith("class:"):
                class_name = name[6:]
                add_markers_to_class(lines, class_name, group)
            else:
                add_markers_to_function(lines, name, group)
    else:
        # If no specific tests, assume all functions
        added = add_markers_to_all_functions(lines, group)
        print(f"  Added markers to {added} functions")
    
    with open(filepath, "w") as f:
        f.writelines(lines)
    print(f"Processed {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Add serial markers to pytest tests")
    parser.add_argument("--file", required=True, help="Path to test file")
    parser.add_argument("--group", required=True, help="xdist_group name")
    parser.add_argument("--tests", help="Comma-separated test function names (or class:ClassName)")
    parser.add_argument("--all", action="store_true", help="Mark all test functions and classes")
    parser.add_argument("--classes", action="store_true", help="Mark all classes (instead of functions)")
    args = parser.parse_args()
    
    filepath = Path(args.file)
    test_names = args.tests.split(",") if args.tests else None
    
    process_file(filepath, args.group, test_names, mark_all=args.all, mark_classes=args.classes)


if __name__ == "__main__":
    main()