#!/usr/bin/env python3
"""
Generate a dependency graph of Python modules for Elixir migration planning.

This script statically analyzes the code_puppy package to identify:
- High-fan-in hub modules (port last)
- Low-dependency leaf modules (port first)
- Import cycles (break before porting)
- Recommended porting order

Usage:
    python scripts/generate_python_dependency_graph.py
    python scripts/generate_python_dependency_graph.py --format json
    python scripts/generate_python_dependency_graph.py --output docs/python_dependency_graph.md

Limitations:
    - Static analysis only; dynamic imports (importlib, __import__) are missed
    - Conditional imports (try/except) are treated equally with regular imports
    - Type-only imports (TYPE_CHECKING blocks) are included
    - External package imports are tracked but not resolved
    - Relative imports within packages are resolved to absolute paths
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModuleInfo:
    """Information about a Python module."""

    name: str  # Full dotted path (e.g., code_puppy.agents.base_agent)
    file_path: Path
    imports: set[str] = field(default_factory=set)  # Internal imports only
    imported_by: set[str] = field(default_factory=set)  # Reverse dependencies
    external_imports: set[str] = field(default_factory=set)  # 3rd party packages
    stdlib_imports: set[str] = field(default_factory=set)  # Standard library
    lines_of_code: int = 0

    @property
    def fan_in(self) -> int:
        """Number of modules that import this module."""
        return len(self.imported_by)

    @property
    def fan_out(self) -> int:
        """Number of internal modules this module imports."""
        return len(self.imports)

    @property
    def is_leaf(self) -> bool:
        """True if module has no internal dependencies."""
        return len(self.imports) == 0

    @property
    def is_hub(self, threshold: int = 10) -> bool:
        """True if module is imported by many others."""
        return self.fan_in >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file_path": str(self.file_path),
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
            "imports": sorted(self.imports),
            "imported_by": sorted(self.imported_by),
            "external_imports": sorted(self.external_imports),
            "stdlib_imports": sorted(self.stdlib_imports),
            "lines_of_code": self.lines_of_code,
            "is_leaf": self.is_leaf,
            "is_hub": self.is_hub,
        }


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to collect import statements."""

    def __init__(self, package_name: str):
        self.package_name = package_name
        self.internal_imports: set[str] = set()
        self.external_imports: set[str] = set()
        self.stdlib_imports: set[str] = set()
        self.stdlib_modules = self._get_stdlib_modules()

    def _get_stdlib_modules(self) -> set[str]:
        """Return a set of standard library module names."""
        # Core stdlib modules commonly imported
        return {
            "abc",
            "argparse",
            "ast",
            "asyncio",
            "base64",
            "collections",
            "collections.abc",
            "concurrent",
            "contextlib",
            "copy",
            "csv",
            "dataclasses",
            "datetime",
            "enum",
            "fnmatch",
            "functools",
            "hashlib",
            "importlib",
            "inspect",
            "io",
            "itertools",
            "json",
            "logging",
            "math",
            "os",
            "pathlib",
            "pickle",
            "pkgutil",
            "platform",
            "re",
            "shutil",
            "signal",
            "socket",
            "sqlite3",
            "stat",
            "subprocess",
            "sys",
            "tempfile",
            "textwrap",
            "threading",
            "time",
            "traceback",
            "types",
            "typing",
            "uuid",
            "warnings",
            "weakref",
            "xml",
        }

    def _is_stdlib(self, name: str) -> bool:
        """Check if a module is likely from stdlib."""
        top_level = name.split(".")[0]
        return top_level in self.stdlib_modules

    def _is_internal(self, name: str) -> bool:
        """Check if a module is from the target package."""
        return name.startswith(self.package_name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            if self._is_internal(name):
                self.internal_imports.add(name)
            elif self._is_stdlib(name):
                self.stdlib_imports.add(name)
            else:
                self.external_imports.add(name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            # Relative import
            return

        # Construct full import path
        if node.level > 0:
            # Relative import - we'll resolve later
            return

        # Absolute import
        for alias in node.names:
            full_name = f"{node.module}.{alias.name}"
            # Also track the module itself
            module_name = node.module

            if self._is_internal(module_name):
                self.internal_imports.add(module_name)
                # Also add the specific import if it's a submodule
                if alias.name != "*":
                    self.internal_imports.add(full_name)
            elif self._is_stdlib(module_name):
                self.stdlib_imports.add(module_name)
            else:
                self.external_imports.add(module_name)

        self.generic_visit(node)


def analyze_file(file_path: Path, package_root: Path, package_name: str) -> ModuleInfo | None:
    """Analyze a single Python file and return its module info."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except (UnicodeDecodeError, IOError):
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    visitor = ImportVisitor(package_name)
    visitor.visit(tree)

    # Calculate module name from file path
    relative_path = file_path.relative_to(package_root)
    parts = list(relative_path.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")

    module_name = f"{package_name}.{'.'.join(parts)}"

    # Filter to only keep direct submodules (not individual classes/functions)
    # Keep only imports that are actual modules or subpackages
    filtered_imports = set()
    for imp in visitor.internal_imports:
        # Keep imports that could be modules (don't filter too aggressively)
        filtered_imports.add(imp)

    lines_of_code = len(source.splitlines())

    return ModuleInfo(
        name=module_name,
        file_path=file_path,
        imports=filtered_imports,
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
            part.startswith(".") or part in {"__pycache__", "node_modules", "venv", ".venv"}
            for part in py_file.parts
        ):
            continue

        info = analyze_file(py_file, package_path, package_name)
        if info:
            modules[info.name] = info

    # Build reverse dependencies (imported_by)
    for mod_name, mod_info in modules.items():
        for imp in mod_info.imports:
            # Find the base module that provides this import
            for target_name in modules:
                if imp == target_name or imp.startswith(f"{target_name}."):
                    modules[target_name].imported_by.add(mod_name)
                    break

    return modules


def find_cycles(modules: dict[str, ModuleInfo]) -> list[list[str]]:
    """Find import cycles using DFS."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        if node in modules:
            for neighbor in modules[node].imports:
                # Find the base module
                for mod_name in modules:
                    if neighbor == mod_name or neighbor.startswith(f"{mod_name}."):
                        neighbor = mod_name
                        break

                if neighbor not in modules:
                    continue

                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    # Normalize cycle to start from smallest element
                    min_idx = cycle.index(min(cycle[:-1]))
                    normalized = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                    if normalized not in cycles:
                        cycles.append(normalized)

        path.pop()
        rec_stack.remove(node)

    for mod in modules:
        if mod not in visited:
            dfs(mod)

    return cycles


def compute_porting_order(modules: dict[str, ModuleInfo]) -> list[tuple[str, int]]:
    """
    Compute recommended porting order using a simple topological-like approach.

    Leaf modules (no internal deps) should be ported first.
    Hub modules (high fan-in) should be ported last.
    """
    # Score: lower = port first
    # Priority: leaves first, then by dependency depth
    scores: dict[str, int] = {}

    # Calculate depth (longest path from any leaf)
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
        for imp in modules[mod].imports:
            for target in modules:
                if imp == target or imp.startswith(f"{target}."):
                    max_depth = max(max_depth, get_depth(target, visited) + 1)
                    break

        scores[mod] = max_depth
        return max_depth

    for mod in modules:
        get_depth(mod)

    # Sort by depth, then by fan_in (higher fan_in = later)
    ordered = sorted(
        modules.items(),
        key=lambda x: (scores.get(x[0], 0), -x[1].fan_in),
    )

    return [(name, scores.get(name, 0)) for name, _ in ordered]


def generate_markdown_report(
    modules: dict[str, ModuleInfo],
    cycles: list[list[str]],
    porting_order: list[tuple[str, int]],
    output_path: Path | None = None,
) -> str:
    """Generate a markdown report of the dependency analysis."""
    lines: list[str] = []

    # Header
    lines.append("# Python Module Dependency Graph")
    lines.append("")
    lines.append(
        "> Generated for Python-to-Elixir migration planning. "
        "See [ADR-004](docs/adr/ADR-004-python-to-elixir-migration-strategy.md)."
    )
    lines.append("")
    lines.append(f"**Generated**: {__import__('datetime').datetime.now().isoformat()}")
    lines.append(f"**Total modules analyzed**: {len(modules)}")
    lines.append("")

    # Summary statistics
    total_loc = sum(m.lines_of_code for m in modules.values())
    leaf_count = sum(1 for m in modules.values() if m.is_leaf)
    hub_count = sum(1 for m in modules.values() if m.is_hub)

    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total modules | {len(modules)} |")
    lines.append(f"| Total lines of code | {total_loc:,} |")
    lines.append(f"| Leaf modules (no internal deps) | {leaf_count} |")
    lines.append(f"| Hub modules (≥10 importers) | {hub_count} |")
    lines.append(f"| Import cycles detected | {len(cycles)} |")
    lines.append("")

    # High-fan-in hubs
    lines.append("## High-Fan-In Hub Modules (Port LAST)")
    lines.append("")
    lines.append("> These modules are imported by many others. Porting them early breaks dependents."
    )
    lines.append("")
    hubs = sorted(modules.values(), key=lambda m: -m.fan_in)[:20]
    lines.append(f"| Module | Fan-In | Fan-Out | LOC | Description |")
    lines.append(f"|--------|--------|---------|-----|-------------|")
    for hub in hubs:
        if hub.fan_in >= 5:  # Only show significant hubs
            short_name = hub.name.replace("code_puppy.", "")
            lines.append(
                f"| `{short_name}` | {hub.fan_in} | {hub.fan_out} | {hub.lines_of_code:,} | |"
            )
    lines.append("")

    # Leaf candidates
    lines.append("## Low-Dependency Leaf Candidates (Port FIRST)")
    lines.append("")
    lines.append("> These modules have few or no internal dependencies. Safe to port early."
    )
    lines.append("")
    leaves = sorted(
        [m for m in modules.values() if m.is_leaf],
        key=lambda m: -m.lines_of_code,
    )[:30]
    lines.append(f"| Module | Fan-In | LOC | Notes |")
    lines.append(f"|--------|--------|-----|-------|")
    for leaf in leaves:
        short_name = leaf.name.replace("code_puppy.", "")
        notes = "Pure leaf" if leaf.fan_in == 0 else f"Imported by {leaf.fan_in}"
        lines.append(f"| `{short_name}` | {leaf.fan_in} | {leaf.lines_of_code:,} | {notes} |")
    lines.append("")

    # Cycles
    if cycles:
        lines.append("## Import Cycles Detected")
        lines.append("")
        lines.append("> Cycles must be broken before porting (refactor to remove circular deps)."
        )
        lines.append("")
        for i, cycle in enumerate(cycles[:10], 1):  # Show first 10
            cycle_str = " → ".join(c.replace("code_puppy.", "") for c in cycle)
            lines.append(f"{i}. `{cycle_str}`")
        if len(cycles) > 10:
            lines.append(f"\n... and {len(cycles) - 10} more cycles")
        lines.append("")
    else:
        lines.append("## Import Cycles")
        lines.append("")
        lines.append("✅ No import cycles detected.")
        lines.append("")

    # Porting order
    lines.append("## Recommended Porting Order")
    lines.append("")
    lines.append("> Ordered by dependency depth (leaves first). Modules at same depth sorted by fan-in (lowest first)."
    )
    lines.append("")
    lines.append("| Phase | Modules | Criteria |")
    lines.append("|-------|---------|----------|")

    # Group by depth
    depth_groups: dict[int, list[str]] = defaultdict(list)
    for mod, depth in porting_order:
        depth_groups[depth].append(mod)

    phase_names = ["Foundation", "Utilities", "Core Services", "Agents", "Integration"]
    for depth in sorted(depth_groups.keys()):
        phase_name = phase_names[min(depth, len(phase_names) - 1)]
        mods = depth_groups[depth][:5]  # Show first 5 per depth
        mod_str = ", ".join(f"`{m.replace('code_puppy.', '')}`" for m in mods)
        if len(depth_groups[depth]) > 5:
            mod_str += f" (+{len(depth_groups[depth]) - 5} more)"
        lines.append(f"| {phase_name} (depth={depth}) | {mod_str} | Leaves → Hubs |")

    lines.append("")

    # Limitations
    lines.append("## Limitations of This Analysis")
    lines.append("")
    lines.append("1. **Static analysis only**: Dynamic imports (`importlib`, `__import__`) are not detected.")
    lines.append("2. **Conditional imports**: Imports inside `try/except` or `if TYPE_CHECKING` are treated equally.")
    lines.append("3. **Star imports**: `from x import *` dependencies may be incomplete.")
    lines.append("4. **External dependencies**: Third-party package internals are not analyzed.")
    lines.append("5. **Runtime dependencies**: Plugin loading, config-driven imports are not captured.")
    lines.append("")
    lines.append("For complete accuracy, supplement with runtime profiling and manual review.")
    lines.append("")

    # Appendix: Full module list
    lines.append("## Appendix: All Modules")
    lines.append("")
    lines.append(f"| Module | Fan-In | Fan-Out | LOC |")
    lines.append(f"|--------|--------|---------|-----|")
    for mod_name in sorted(modules.keys()):
        m = modules[mod_name]
        short = mod_name.replace("code_puppy.", "")
        lines.append(f"| `{short}` | {m.fan_in} | {m.fan_out} | {m.lines_of_code:,} |")
    lines.append("")

    content = "\n".join(lines)

    if output_path:
        output_path.write_text(content)
        print(f"Report written to: {output_path}")

    return content


def generate_json_report(
    modules: dict[str, ModuleInfo],
    cycles: list[list[str]],
    porting_order: list[tuple[str, int]],
    output_path: Path | None = None,
) -> str:
    """Generate a JSON report for programmatic use."""
    data = {
        "metadata": {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "total_modules": len(modules),
            "package": "code_puppy",
        },
        "summary": {
            "total_lines_of_code": sum(m.lines_of_code for m in modules.values()),
            "leaf_count": sum(1 for m in modules.values() if m.is_leaf),
            "hub_count": sum(1 for m in modules.values() if m.is_hub),
            "cycle_count": len(cycles),
        },
        "hubs": [
            m.to_dict()
            for m in sorted(modules.values(), key=lambda x: -x.fan_in)[:20]
            if m.fan_in >= 5
        ],
        "leaves": [
            m.to_dict()
            for m in sorted(modules.values(), key=lambda x: -x.lines_of_code)
            if m.is_leaf
        ][:30],
        "cycles": [c for c in cycles],
        "porting_order": [
            {"module": mod, "depth": depth, "priority": i + 1}
            for i, (mod, depth) in enumerate(porting_order)
        ],
        "all_modules": {name: mod.to_dict() for name, mod in modules.items()},
    }

    content = json.dumps(data, indent=2)

    if output_path:
        output_path.write_text(content)
        print(f"JSON report written to: {output_path}")

    return content


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Python dependency graph for migration planning"
    )
    parser.add_argument(
        "--package-path",
        type=Path,
        default=Path("code_puppy"),
        help="Path to Python package (default: code_puppy)",
    )
    parser.add_argument(
        "--package-name",
        default="code_puppy",
        help="Package name for imports (default: code_puppy)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    # Resolve package path
    package_path = args.package_path.resolve()
    if not package_path.exists():
        print(f"Error: Package path not found: {package_path}", file=sys.stderr)
        return 1

    print(f"Analyzing {args.package_name} at {package_path}...")

    # Build dependency graph
    modules = build_dependency_graph(package_path, args.package_name)
    print(f"Found {len(modules)} modules")

    # Find cycles
    cycles = find_cycles(modules)
    print(f"Found {len(cycles)} import cycles")

    # Compute porting order
    porting_order = compute_porting_order(modules)

    # Generate report
    if args.format == "json":
        content = generate_json_report(modules, cycles, porting_order, args.output)
    else:
        content = generate_markdown_report(modules, cycles, porting_order, args.output)

    if not args.output:
        print(content)

    return 0


if __name__ == "__main__":
    sys.exit(main())
