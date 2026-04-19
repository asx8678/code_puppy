"""bd-13: Lint guard — ensure no direct bridge imports outside adapter boundary.

This test scans all Python source files and fails if any file imports directly
from bridge modules instead of routing through the Elixir bridge.

There is no native_backend.py — parse access goes via
code_puppy.plugins.elixir_bridge. The patterns below guard against
accidental re-introduction of deleted bridge modules.

bd-208: Updated to also forbid native_backend and acceleration imports.
"""

import re
from pathlib import Path

import pytest


# Files that are ALLOWED to import from bridge modules
# (they are the adapter boundary or test the bridge itself)
# bd-86: All bridge modules deleted, this test now guards against
# accidental re-introduction of direct bridge imports.
ALLOWED_FILES = {
    # bd-86: All bridge modules deleted, this test now guards against
    # accidental re-introduction of direct bridge imports.
}

# Patterns that indicate direct bridge imports
BRIDGE_IMPORT_PATTERNS = [
    re.compile(r"from\s+code_puppy\.turbo_parse_bridge\s+import"),
    re.compile(r"import\s+code_puppy\.turbo_parse_bridge"),
    re.compile(r"from\s+code_puppy\s+import\s+turbo_parse_bridge"),
]

# bd-208: native_backend.py and acceleration/ are also gone
DEAD_MODULE_PATTERNS = [
    re.compile(r"from\s+code_puppy\.native_backend\s+import"),
    re.compile(r"import\s+code_puppy\.native_backend"),
    re.compile(r"from\s+code_puppy\s+import\s+native_backend"),
    re.compile(r"from\s+code_puppy\.acceleration"),
    re.compile(r"import\s+code_puppy\.acceleration"),
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
    """bd-13: Ensure no direct bridge imports outside the Elixir bridge adapter."""

    def test_no_turbo_parse_bridge_imports(self):
        """No file should import directly from turbo_parse_bridge.

        All turbo_parse functionality should be accessed via:
            from code_puppy.plugins.elixir_bridge import is_connected, call_method
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
                f"Use the Elixir bridge instead:\n"
                f"  from code_puppy.plugins.elixir_bridge import is_connected, call_method\n\n"
                f"Violations:\n{violation_list}\n\n"
                f"If this file tests the bridge itself, add it to ALLOWED_FILES in\n"
                f"tests/test_no_direct_bridge_imports.py"
            )

    def test_no_native_backend_imports(self):
        """No file should import from native_backend or acceleration (deleted in bd-86/bd-208).

        Parse operations go through the Elixir bridge:
            from code_puppy.plugins.elixir_bridge import is_connected, call_method
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

            for pattern in DEAD_MODULE_PATTERNS:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    violations.append(
                        f"  {rel_path}:{line_num}: {match.group().strip()}"
                    )

        if violations:
            violation_list = "\n".join(violations)
            pytest.fail(
                f"bd-208 violation: {len(violations)} native_backend/acceleration import(s) found.\n"
                f"These modules have been deleted. Use the Elixir bridge instead:\n"
                f"  from code_puppy.plugins.elixir_bridge import is_connected, call_method\n\n"
                f"Violations:\n{violation_list}\n\n"
                f"If this file tests the bridge itself, add it to ALLOWED_FILES in\n"
                f"tests/test_no_direct_bridge_imports.py"
            )

    def test_no_core_bridge_imports_outside_adapter(self):
        """No file should import from _core_bridge except the adapter layer.

        _core_bridge types should be accessed via:
            from code_puppy.plugins.elixir_bridge import is_connected, call_method
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
                f"Use the Elixir bridge instead:\n"
                f"  from code_puppy.plugins.elixir_bridge import is_connected, call_method\n\n"
                f"Violations:\n{violation_list}\n\n"
                f"If this file is part of the adapter boundary, add it to ALLOWED_FILES in\n"
                f"tests/test_no_direct_bridge_imports.py"
            )
