#!/usr/bin/env python3
"""Report generation for dependency graph analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ModuleInfo


def format_timestamp(stable: bool = False) -> str:
    """Generate timestamp for reports."""
    if stable:
        # Use a fixed timestamp for reproducible builds
        return "2026-01-01T00:00:00+00:00"
    return datetime.now(timezone.utc).isoformat()


def short_name(module_name: str) -> str:
    """Convert full module name to short display name."""
    if module_name.startswith("code_puppy."):
        return module_name[len("code_puppy.") :]
    return module_name


def generate_markdown_report(
    modules: dict[str, ModuleInfo],
    cycles: list[list[str]],
    porting_order: list[tuple[str, int]],
    output_path: Path | None = None,
    stable: bool = False,
) -> str:
    """Generate a markdown report of the dependency analysis."""
    lines: list[str] = []

    # Header
    lines.append("# Python Module Dependency Graph")
    lines.append("")
    lines.append(
        "> Generated for Python-to-Elixir migration planning. "
        "See [ADR-004](adr/ADR-004-python-to-elixir-migration-strategy.md)."
    )
    lines.append("")
    lines.append(f"**Generated**: {format_timestamp(stable)}")
    lines.append(f"**Total modules analyzed**: {len(modules)}")
    lines.append("")

    # Summary statistics
    total_loc = sum(m.lines_of_code for m in modules.values())
    leaf_count = sum(1 for m in modules.values() if m.is_leaf)
    hub_count = sum(1 for m in modules.values() if m.is_hub)

    lines.append("## Summary Statistics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total modules | {len(modules)} |")
    lines.append(f"| Total lines of code | {total_loc:,} |")
    lines.append(f"| Leaf modules (no internal deps) | {leaf_count} |")
    lines.append(f"| Hub modules (≥10 importers) | {hub_count} |")
    lines.append(f"| Import cycles detected | {len(cycles)} |")
    lines.append("")

    # High-fan-in hubs
    lines.append("## High-Fan-In Hub Modules (Port LAST)")
    lines.append("")
    lines.append(
        "> These modules are imported by many others. Porting them early breaks dependents."
    )
    lines.append("")
    hubs = sorted(modules.values(), key=lambda m: (-m.fan_in, m.name))[:20]
    lines.append("| Module | Fan-In | Fan-Out | LOC | Description |")
    lines.append("|--------|--------|---------|-----|-------------|")
    for hub in hubs:
        if hub.fan_in >= 5:  # Only show significant hubs
            short = short_name(hub.name)
            lines.append(
                f"| `{short}` | {hub.fan_in} | {hub.fan_out} | {hub.lines_of_code:,} | |"
            )
    lines.append("")

    # Leaf candidates - sort by fan_in ascending (lowest first), then by LOC descending
    lines.append("## Low-Dependency Leaf Candidates (Port FIRST)")
    lines.append("")
    lines.append(
        "> These modules have few or no internal dependencies. Safe to port early."
    )
    lines.append("")
    # Sort leaves: lowest fan-in first, then highest LOC
    leaves = sorted(
        [m for m in modules.values() if m.is_leaf],
        key=lambda m: (m.fan_in, -m.lines_of_code, m.name),
    )[:30]
    lines.append("| Module | Fan-In | LOC | Notes |")
    lines.append("|--------|--------|-----|-------|")
    for leaf in leaves:
        sname = short_name(leaf.name)
        notes = "Pure leaf" if leaf.fan_in == 0 else f"Imported by {leaf.fan_in}"
        lines.append(
            f"| `{sname}` | {leaf.fan_in} | {leaf.lines_of_code:,} | {notes} |"
        )
    lines.append("")

    # Cycles
    if cycles:
        lines.append("## Import Cycles Detected")
        lines.append("")
        lines.append(
            "> Cycles must be broken before porting (refactor to remove circular deps)."
        )
        lines.append("")
        for i, cycle in enumerate(cycles[:10], 1):  # Show first 10
            cycle_str = " → ".join(short_name(c) for c in cycle)
            lines.append(f"{i}. `{cycle_str}`")
        if len(cycles) > 10:
            lines.append(f"\n... and {len(cycles) - 10} more cycles")
        lines.append("")
    else:
        lines.append("## Import Cycles")
        lines.append("")
        lines.append("No import cycles detected.")
        lines.append("")

    # Porting order
    lines.append("## Recommended Porting Order")
    lines.append("")
    lines.append(
        "> Ordered by dependency depth (leaves first). "
        "Within each depth, sorted by fan-in (lowest first)."
    )
    lines.append("")
    lines.append("| Phase | Modules | Criteria |")
    lines.append("|-------|---------|----------|")

    # Group by depth
    from collections import defaultdict

    depth_groups: dict[int, list[str]] = defaultdict(list)
    for mod, depth in porting_order:
        depth_groups[depth].append(mod)

    phase_names = ["Foundation", "Utilities", "Core Services", "Agents", "Integration"]
    for depth in sorted(depth_groups.keys()):
        phase_name = phase_names[min(depth, len(phase_names) - 1)]
        mods = depth_groups[depth][:5]  # Show first 5 per depth
        mod_str = ", ".join(f"`{short_name(m)}`" for m in mods)
        if len(depth_groups[depth]) > 5:
            mod_str += f" (+{len(depth_groups[depth]) - 5} more)"
        lines.append(f"| {phase_name} (depth={depth}) | {mod_str} | Leaves → Hubs |")

    lines.append("")

    # Limitations
    lines.append("## Limitations of This Analysis")
    lines.append("")
    lines.append(
        "1. **Static analysis only**: Dynamic imports (importlib, __import__) are not detected."
    )
    lines.append(
        "2. **Conditional imports**: Imports inside try/except or if TYPE_CHECKING are treated equally."
    )
    lines.append("3. **Star imports**: from x import * dependencies may be incomplete.")
    lines.append(
        "4. **External dependencies**: Third-party package internals are not analyzed."
    )
    lines.append(
        "5. **Runtime dependencies**: Plugin loading, config-driven imports are not captured."
    )
    lines.append("")
    lines.append(
        "For complete accuracy, supplement with runtime profiling and manual review."
    )
    lines.append("")

    # Appendix: Full module list
    lines.append("## Appendix: All Modules")
    lines.append("")
    lines.append("| Module | Fan-In | Fan-Out | LOC |")
    lines.append("|--------|--------|---------|-----|")
    for mod_name in sorted(modules.keys()):
        m = modules[mod_name]
        short = short_name(mod_name)
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
    stable: bool = False,
) -> str:
    """Generate a JSON report for programmatic use."""
    data = {
        "metadata": {
            "generated_at": format_timestamp(stable),
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
            for m in sorted(modules.values(), key=lambda x: (-x.fan_in, x.name))[:20]
            if m.fan_in >= 5
        ],
        "leaves": [
            m.to_dict()
            for m in sorted(
                [m for m in modules.values() if m.is_leaf],
                key=lambda x: (x.fan_in, -x.lines_of_code, x.name),
            )[:30]
        ],
        "cycles": [c for c in cycles],
        "porting_order": [
            {"module": mod, "depth": depth, "priority": i + 1}
            for i, (mod, depth) in enumerate(porting_order)
        ],
        "all_modules": {name: mod.to_dict() for name, mod in sorted(modules.items())},
    }

    content = json.dumps(data, indent=2)

    if output_path:
        output_path.write_text(content)
        print(f"JSON report written to: {output_path}")

    return content
