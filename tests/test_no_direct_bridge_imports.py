"""bd-13: Lint guard — ensure no direct bridge imports outside adapter boundary.

This test scans all Python source files and fails if any file imports directly
from bridge modules instead of routing through NativeBackend.

Allowed files (the adapter boundary itself):
- code_puppy/turbo_parse_bridge.py (IS the bridge module)
- code_puppy/native_backend.py (IS the NativeBackend adapter)
- code_puppy/acceleration/__init__.py (facade that delegates to NativeBackend)

Allowed test files (bridge compatibility tests):
- tests/plugins/test_turbo_parse_integration.py (tests the bridge itself)
"""

import re
from pathlib import Path

import pytest


# Files that are ALLOWED to import from bridge modules
# (they are the adapter boundary or test the bridge itself)
ALLOWED_FILES = {
    # The bridge module itself
    "code_puppy/turbo_parse_bridge.py",
    # The NativeBackend adapter (uses _core_bridge for type re-exports)
    "code_puppy/native_backend.py",
    # Facade that delegates to NativeBackend
    "code_puppy/acceleration/__init__.py",
    # Bridge compatibility test suite (deliberately tests bridge module)
    "tests/plugins/test_turbo_parse_integration.py",
    # Test files that legitimately test the bridge/backends directly
    "tests/test_native_backend.py",
    "tests/test_rust_core.py",
    "tests/bench_rust_vs_python.py",
    "tests/profile_bridge_bottlenecks.py",
    "tests/test_hashline.py",
}

# Patterns that indicate direct bridge imports
BRIDGE_IMPORT_PATTERNS = [
    re.compile(r"from\s+code_puppy\.turbo_parse_bridge\s+import"),
    re.compile(r"import\s+code_puppy\.turbo_parse_bridge"),
    re.compile(r"from\s+code_puppy\s+import\s+turbo_parse_bridge"),
]

# _core_bridge imports outside the adapter boundary
CORE_BRIDGE_PATTERNS = [
    re.compile(r"from\s+code_puppy\._core_bridge\s+import"),
    re.compile(r"import\s+code_puppy\._core_bridge"),
]


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def _find_python_files(root: Path) -> list[Path]:
    """Find all Python source files, excluding rewrite/ directory."""
    files = []
    for py_file in root.rglob("*.py"):
        # Skip rewrite directory (contains old copies)
        if "rewrite/" in str(py_file) or "rewrite\\" in str(py_file):
            continue
        # Skip __pycache__
        if "__pycache__" in str(py_file):
            continue
        files.append(py_file)
    return files


def _relative_path(file_path: Path, root: Path) -> str:
    """Get path relative to project root."""
    try:
        return str(file_path.relative_to(root))
    except ValueError:
        return str(file_path)


class TestNoDirectBridgeImports:
    """bd-13: Ensure no direct bridge imports outside NativeBackend adapter."""

    def test_no_turbo_parse_bridge_imports(self):
        """No file should import directly from turbo_parse_bridge.
        
        All turbo_parse functionality should be accessed via:
            from code_puppy.native_backend import NativeBackend
            NativeBackend.parse_file(...)
            NativeBackend.parse_source(...)
            etc.
        """
        root = _get_project_root()
        violations = []

        for py_file in _find_python_files(root):
            rel_path = _relative_path(py_file, root)
            
            # Skip allowed files
            if any(rel_path.endswith(allowed) for allowed in ALLOWED_FILES):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            for pattern in BRIDGE_IMPORT_PATTERNS:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    violations.append(
                        f"  {rel_path}:{line_num}: {match.group().strip()}"
                    )

        if violations:
            violation_list = "\n".join(violations)
            pytest.fail(
                f"bd-13 violation: {len(violations)} direct turbo_parse_bridge import(s) found.\n"
                f"Use NativeBackend instead:\n"
                f"  from code_puppy.native_backend import NativeBackend\n\n"
                f"Violations:\n{violation_list}\n\n"
                f"If this file tests the bridge itself, add it to ALLOWED_FILES in\n"
                f"tests/test_no_direct_bridge_imports.py"
            )

    def test_no_core_bridge_imports_outside_adapter(self):
        """No file should import from _core_bridge except the adapter layer.
        
        _core_bridge types should be accessed via:
            from code_puppy.native_backend import NativeBackend
            or from code_puppy.acceleration import ...
        """
        root = _get_project_root()
        violations = []

        for py_file in _find_python_files(root):
            rel_path = _relative_path(py_file, root)
            
            # Skip allowed files
            if any(rel_path.endswith(allowed) for allowed in ALLOWED_FILES):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            for pattern in CORE_BRIDGE_PATTERNS:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    violations.append(
                        f"  {rel_path}:{line_num}: {match.group().strip()}"
                    )

        if violations:
            violation_list = "\n".join(violations)
            pytest.fail(
                f"bd-13 violation: {len(violations)} direct _core_bridge import(s) found.\n"
                f"Use NativeBackend or acceleration module instead.\n\n"
                f"Violations:\n{violation_list}\n\n"
                f"If this file is part of the adapter boundary, add it to ALLOWED_FILES in\n"
                f"tests/test_no_direct_bridge_imports.py"
            )
