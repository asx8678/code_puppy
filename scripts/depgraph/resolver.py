#!/usr/bin/env python3
"""Import resolution utilities with longest-module matching."""

from __future__ import annotations


def resolve_relative_import(
    current_module: str, level: int, module: str | None
) -> str | None:
    """
    Resolve a relative import to an absolute module name.

    Args:
        current_module: The module containing the import (e.g., 'code_puppy.tools.file_ops')
        level: Number of dots (1 for '.', 2 for '..', etc.)
        module: The module name after the dots (e.g., 'utils' in 'from .utils import x')

    Returns:
        Absolute module name or None if resolution fails
    """
    if level == 0:
        return module

    parts = current_module.split(".")

    # Check if we can go up 'level' times
    if level > len(parts):
        return None

    # Go up 'level' times
    base_parts = parts[:-level]

    if module:
        # from .module import x or from ..pkg.mod import y
        if base_parts:
            return ".".join(base_parts) + "." + module
        return module
    else:
        # from . import x or from .. import y
        if not base_parts:
            return None
        return ".".join(base_parts)


def find_matching_module(import_name: str, modules: set[str]) -> str | None:
    """
    Find the best matching module for an import using longest-module matching.

    This ensures we match the most specific module, not a broad parent.
    For example, if importing 'code_puppy.tools.file_ops' and both
    'code_puppy.tools' and 'code_puppy.tools.file_ops' exist,
    we return 'code_puppy.tools.file_ops' (the longer/more specific one).

    Args:
        import_name: The imported name (e.g., 'code_puppy.tools.file_ops')
        modules: Set of available module names

    Returns:
        The best matching module name or None
    """
    if import_name in modules:
        return import_name

    best_match = None
    best_len = 0

    for mod_name in modules:
        # Check if import_name is the module or a submodule of it
        if import_name == mod_name or import_name.startswith(f"{mod_name}."):
            if len(mod_name) > best_len:
                best_match = mod_name
                best_len = len(mod_name)

    return best_match
