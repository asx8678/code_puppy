#!/usr/bin/env python3
"""AST-based Python module analyzer with proper import resolution."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ModuleInfo
from .stdlib_list import STDLIB_MODULES

if TYPE_CHECKING:
    pass


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to collect import statements with proper resolution."""

    def __init__(self, package_name: str, current_module: str):
        self.package_name = package_name
        self.current_module = current_module
        self.internal_imports: set[str] = set()
        self.external_imports: set[str] = set()
        self.stdlib_imports: set[str] = set()

    def _is_stdlib(self, name: str) -> bool:
        """Check if a module is from stdlib."""
        top_level = name.split(".")[0]
        return top_level in STDLIB_MODULES

    def _is_internal(self, name: str) -> bool:
        """Check if a module is from the target package."""
        return name.startswith(self.package_name + ".") or name == self.package_name

    def _resolve_relative(self, level: int, module: str | None) -> str | None:
        """Resolve a relative import to absolute module name."""
        if level == 0:
            return module

        # Split current module into parts
        parts = self.current_module.split(".")

        # Go up 'level' times
        if level > len(parts):
            # Would go above package root - invalid
            return None

        base_parts = parts[:-level] if level <= len(parts) else []

        if module:
            # from .module import x or from ..pkg import y
            return ".".join(base_parts + [module])
        else:
            # from . import x or from .. import y
            # This case is for 'from . import something' which imports from current package
            if not base_parts:
                return None
            return ".".join(base_parts)

    def _add_import(self, full_name: str) -> None:
        """Add an import, classifying it appropriately."""
        # Only track module-level imports, not individual symbols
        # Get the top-level module or package
        if self._is_internal(full_name):
            self.internal_imports.add(full_name)
        elif self._is_stdlib(full_name):
            self.stdlib_imports.add(full_name)
        else:
            self.external_imports.add(full_name)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        """Handle 'import x' statements."""
        for alias in node.names:
            name = alias.name
            if name:
                self._add_import(name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        """Handle 'from x import y' statements with relative import resolution."""
        if node.level > 0:
            # Relative import - resolve to absolute
            base_module = self._resolve_relative(node.level, node.module)
            if base_module is None:
                self.generic_visit(node)
                return

            # Add the base module
            self._add_import(base_module)

            # Also track specific imports like 'from . import x'
            for alias in node.names:
                if alias.name == "*":
                    continue
                if node.module is None:
                    # from . import x -> imports x from current package
                    full_name = f"{base_module}.{alias.name}"
                    self._add_import(full_name)
                else:
                    # from .module import x
                    full_name = f"{base_module}.{alias.name}"
                    self._add_import(full_name)
        else:
            # Absolute import
            if node.module:
                # Add the module itself
                self._add_import(node.module)

                # For 'from module import name', we might import submodules
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    # Could be importing from a submodule
                    full_name = f"{node.module}.{alias.name}"
                    self._add_import(full_name)

        self.generic_visit(node)


def calculate_module_name(
    file_path: Path, package_root: Path, package_name: str
) -> str | None:
    """Calculate the full module name from a file path."""
    try:
        relative_path = file_path.relative_to(package_root)
    except ValueError:
        return None

    parts = list(relative_path.parts)

    # Handle __init__.py
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")

    if not parts:
        # This is the package root __init__.py
        return package_name

    return f"{package_name}.{'.'.join(parts)}"


def analyze_file(
    file_path: Path, package_root: Path, package_name: str
) -> ModuleInfo | None:
    """Analyze a single Python file and return its module info."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except UnicodeDecodeError, IOError:
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    module_name = calculate_module_name(file_path, package_root, package_name)
    if module_name is None:
        return None

    visitor = ImportVisitor(package_name, module_name)
    visitor.visit(tree)

    lines_of_code = len(source.splitlines())

    # Calculate relative path for cleaner output
    try:
        rel_path = file_path.relative_to(package_root.parent)
    except ValueError:
        rel_path = file_path

    return ModuleInfo(
        name=module_name,
        file_path=rel_path,
        imports=visitor.internal_imports,
        external_imports=visitor.external_imports,
        stdlib_imports=visitor.stdlib_imports,
        lines_of_code=lines_of_code,
    )


def build_dependency_graph(
    package_path: Path, package_name: str = "code_puppy"
) -> dict[str, ModuleInfo]:
    """Build dependency graph for all modules in package."""
    modules: dict[str, ModuleInfo] = {}

    # Find all Python files
    for py_file in package_path.rglob("*.py"):
        # Skip common non-source directories
        if any(
            part.startswith(".")
            or part in {"__pycache__", "node_modules", "venv", ".venv"}
            for part in py_file.parts
        ):
            continue

        info = analyze_file(py_file, package_path, package_name)
        if info and info.name:
            modules[info.name] = info

    # Build reverse dependencies (imported_by) using longest-module matching
    for mod_name, mod_info in modules.items():
        for imp in mod_info.imports:
            # Find the longest matching module (most specific)
            best_match = None
            best_len = 0

            for target_name in modules:
                if imp == target_name or imp.startswith(f"{target_name}."):
                    # This import matches this module
                    if len(target_name) > best_len:
                        best_match = target_name
                        best_len = len(target_name)

            if best_match:
                modules[best_match].imported_by.add(mod_name)

    return modules
