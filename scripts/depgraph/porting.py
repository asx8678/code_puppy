#!/usr/bin/env python3
"""Porting order computation with proper leaf-first, hub-last semantics."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ModuleInfo


def compute_porting_order(modules: dict[str, ModuleInfo]) -> list[tuple[str, int]]:
    """
    Compute recommended porting order.

    Leaf modules (no internal deps) should be ported first.
    Hub modules (high fan-in) should be ported last.

    Within each depth level, modules are sorted by fan-in (lowest first)
    so leaves appear before hubs at the same depth.

    Returns:
        List of (module_name, depth) tuples, sorted by depth (ascending),
        then by fan-in (ascending), then by name (for determinism).
    """
    # Calculate depth (longest path from any leaf)
    scores: dict[str, int] = {}

    def get_base_module(import_name: str) -> str | None:
        """Find the base module for an import using longest match."""
        if import_name in modules:
            return import_name

        best_match = None
        best_len = 0

        for mod_name in modules:
            if import_name == mod_name or import_name.startswith(f"{mod_name}."):
                if len(mod_name) > best_len:
                    best_match = mod_name
                    best_len = len(mod_name)

        return best_match

    def get_depth(mod: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if mod in scores:
            return scores[mod]
        if mod in visited or mod not in modules:
            return 0

        visited.add(mod)
        if not modules[mod].imports:
            scores[mod] = 0
            return 0

        max_depth = 0
        # Sort imports for deterministic depth calculation
        sorted_imports = sorted(modules[mod].imports)
        for imp in sorted_imports:
            for target in sorted(modules.keys()):
                if imp == target or imp.startswith(f"{target}."):
                    max_depth = max(max_depth, get_depth(target, visited) + 1)
                    break

        scores[mod] = max_depth
        return max_depth

    # Calculate depth for all modules
    for mod in sorted(modules.keys()):
        get_depth(mod)

    # Sort by:
    # 1. Depth (ascending - leaves first)
    # 2. Fan-in (ascending - low fan-in first, hubs last)
    # 3. Module name (for determinism)
    ordered = sorted(
        modules.items(),
        key=lambda x: (scores.get(x[0], 0), x[1].fan_in, x[0]),
    )

    return [(name, scores.get(name, 0)) for name, _ in ordered]
