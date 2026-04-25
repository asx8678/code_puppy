#!/usr/bin/env python3
"""Self-tests for dependency graph generator (using only stdlib).

Tests cover:
- Relative import resolution for package __init__.py
- 'from . import leaf' submodule imports
- Longest-module matching
- Deterministic cycles
- Leaf-first porting order
- Full pipeline with temp packages (analyze_file + build_dependency_graph)
- Symbol imports not counted as module deps
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .analyzer import build_dependency_graph, calculate_module_name
from .cycles import find_cycles
from .models import ModuleInfo
from .porting import compute_porting_order
from .reports import format_timestamp, generate_json_report, generate_markdown_report
from .resolver import find_matching_module, resolve_relative_import


# ── Unit tests: resolver ─────────────────────────────────────────────


def test_resolve_relative_import() -> bool:
    """Test relative import resolution with is_package semantics."""
    tests = [
        # Regular module: current_module's package context = parent
        ("code_puppy.tools.file_ops", 1, "utils", False, "code_puppy.tools.utils"),
        ("code_puppy.tools.file_ops", 2, "utils", False, "code_puppy.utils"),
        ("code_puppy.tools.file_ops", 1, None, False, "code_puppy.tools"),
        ("code_puppy.tools.file_ops", 2, None, False, "code_puppy"),
        # Package __init__.py: package context = self
        ("code_puppy.sub", 1, "leaf", True, "code_puppy.sub.leaf"),
        ("code_puppy.sub", 1, None, True, "code_puppy.sub"),
        ("code_puppy.sub", 2, "sibling", True, "code_puppy.sibling"),
        ("code_puppy.sub", 2, None, True, "code_puppy"),
        # Edge cases
        ("code_puppy", 1, "config", True, "code_puppy.config"),
        ("code_puppy", 2, None, True, None),  # Can't go above root
        ("code_puppy", 1, None, True, "code_puppy"),
        # Triple-dot import from nested
        ("code_puppy.cmd.mcp.stop", 3, "agents", False, "code_puppy.agents"),
    ]

    all_passed = True
    for current, level, module, is_pkg, expected in tests:
        result = resolve_relative_import(current, level, module, is_package=is_pkg)
        if result != expected:
            print(
                f"FAIL: resolve({current!r}, {level}, {module!r}, is_package={is_pkg})"
            )
            print(f"  Expected: {expected!r}")
            print(f"  Got:      {result!r}")
            all_passed = False
        else:
            print(
                f"PASS: resolve({current}, {level}, {module}, pkg={is_pkg}) = {result}"
            )

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
        ("code_puppy.tools.file_ops", "code_puppy.tools.file_ops"),
        ("code_puppy.tools.file_ops.read", "code_puppy.tools.file_ops"),
        ("code_puppy.tools.utils", "code_puppy.tools"),
        ("code_puppy.config", "code_puppy"),
        ("code_puppy.utils.helper", "code_puppy.utils"),
        ("nonexistent", None),
        # Symbol import should match the module, not create a new dep
        ("code_puppy.tools.ask_user_question.models", "code_puppy.tools"),
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


# ── Unit tests: deterministic cycles ─────────────────────────────────


def test_deterministic_cycles() -> bool:
    """Test that cycle detection is deterministic."""
    modules = {
        "mod_a": ModuleInfo(name="mod_a", file_path=Path("a.py"), imports={"mod_b"}),
        "mod_b": ModuleInfo(name="mod_b", file_path=Path("b.py"), imports={"mod_c"}),
        "mod_c": ModuleInfo(name="mod_c", file_path=Path("c.py"), imports={"mod_a"}),
        "mod_d": ModuleInfo(name="mod_d", file_path=Path("d.py"), imports=set()),
    }
    for mod_name, mod_info in modules.items():
        for imp in mod_info.imports:
            if imp in modules:
                modules[imp].imported_by.add(mod_name)

    cycles_runs = [find_cycles(modules) for _ in range(3)]

    all_same = all(c == cycles_runs[0] for c in cycles_runs)
    if not all_same:
        print("FAIL: Cycle detection is not deterministic")
        for i, c in enumerate(cycles_runs):
            print(f"  Run {i + 1}: {c}")
        return False

    if cycles_runs[0]:
        first_cycle = cycles_runs[0][0]
        if first_cycle[0] != min(first_cycle[:-1]):
            print(f"FAIL: Cycle not normalized: {first_cycle}")
            return False

    print(f"PASS: Cycle detection is deterministic ({len(cycles_runs[0])} cycles)")
    return True


# ── Unit tests: porting order ─────────────────────────────────────────


def _check_no_acyclic_violations(
    modules: dict[str, ModuleInfo],
    porting_order: list[tuple[str, int]],
) -> list[tuple[str, str]]:
    """Return list of (importer, dependency) pairs where importer precedes dep.

    Only checks cross-SCC edges; within-SCC violations are expected
    because cycle members cannot be ordered consistently.
    """
    from .porting import _compute_sccs, _resolve_import

    sccs = _compute_sccs(modules)
    mod_to_scc: dict[str, int] = {}
    for i, scc in enumerate(sccs):
        for mod in scc:
            mod_to_scc[mod] = i

    order_map = {name: i for i, (name, _) in enumerate(porting_order)}
    violations: list[tuple[str, str]] = []

    for name, mod in modules.items():
        for imp in mod.imports:
            target = _resolve_import(imp, modules)
            if (
                target
                and target in order_map
                and name in order_map
                and mod_to_scc.get(name) != mod_to_scc.get(target)
            ):
                if order_map[target] > order_map[name]:
                    violations.append((name, target))

    return violations


def test_porting_order() -> bool:
    """Test that porting order puts leaves first, hubs last."""
    modules = {
        "hub": ModuleInfo(
            name="hub",
            file_path=Path("hub.py"),
            imports=set(),
            imported_by={f"middle{i}" for i in range(10)},
        ),
        "middle1": ModuleInfo(
            name="middle1",
            file_path=Path("m1.py"),
            imports={"hub"},
            imported_by={"leaf"},
        ),
        "leaf": ModuleInfo(
            name="leaf",
            file_path=Path("leaf.py"),
            imports={"middle1"},
            imported_by=set(),
        ),
    }

    porting_order = compute_porting_order(modules)
    ordered_names = [name for name, _ in porting_order]

    hub_idx = ordered_names.index("hub")
    leaf_idx = ordered_names.index("leaf")
    mid_idx = ordered_names.index("middle1")

    # Dependency-before-importer: hub before middle1 before leaf
    if hub_idx > mid_idx:
        print("FAIL: hub appears after middle1 (its importer)")
        print(f"  Order: {ordered_names}")
        return False
    if mid_idx > leaf_idx:
        print("FAIL: middle1 appears after leaf (its importer)")
        print(f"  Order: {ordered_names}")
        return False

    # Within same level, fan-in sorting (hub=10 before leaf=0 is wrong
    # only if they share the same level, which they won't here since
    # the chain gives different levels).
    violations = _check_no_acyclic_violations(modules, porting_order)
    if violations:
        print(f"FAIL: {len(violations)} cross-SCC violations: {violations}")
        return False

    print(f"PASS: Porting order correct: {ordered_names}")
    return True


def test_porting_order_dependency_first() -> bool:
    """Test dependency-before-importer on a diamond dependency graph.

    Graph:   base
              / \\
           left  right
              \\ /
             consumer

    Porting order must be: base → left/right → consumer.
    """
    modules = {
        "base": ModuleInfo(
            name="base",
            file_path=Path("base.py"),
            imports=set(),
            imported_by={"left", "right"},
        ),
        "left": ModuleInfo(
            name="left",
            file_path=Path("left.py"),
            imports={"base"},
            imported_by={"consumer"},
        ),
        "right": ModuleInfo(
            name="right",
            file_path=Path("right.py"),
            imports={"base"},
            imported_by={"consumer"},
        ),
        "consumer": ModuleInfo(
            name="consumer",
            file_path=Path("consumer.py"),
            imports={"left", "right"},
            imported_by=set(),
        ),
    }

    porting_order = compute_porting_order(modules)
    order_map = {name: i for i, (name, _) in enumerate(porting_order)}

    # base must come before left and right
    if order_map["base"] > order_map["left"]:
        print(f"FAIL: base after left — {porting_order}")
        return False
    if order_map["base"] > order_map["right"]:
        print(f"FAIL: base after right — {porting_order}")
        return False
    # left and right must come before consumer
    if order_map["left"] > order_map["consumer"]:
        print(f"FAIL: left after consumer — {porting_order}")
        return False
    if order_map["right"] > order_map["consumer"]:
        print(f"FAIL: right after consumer — {porting_order}")
        return False

    violations = _check_no_acyclic_violations(modules, porting_order)
    if violations:
        print(f"FAIL: {len(violations)} violations: {violations}")
        return False

    print(f"PASS: Diamond dependency order correct: {[n for n, _ in porting_order]}")
    return True


def test_porting_order_acyclic_no_violations() -> bool:
    """Pipeline test: temp package with no cycles must have zero violations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "order_pkg"
        pkg_dir.mkdir()

        # Create a layered package:
        #   __init__.py imports .utils
        #   utils.py (leaf, no deps)
        #   services.py imports .utils
        #   agents.py imports .services, .utils
        #   cli.py imports .agents, .services
        (pkg_dir / "__init__.py").write_text("from . import utils\n")
        (pkg_dir / "utils.py").write_text("VALUE = 1\n")
        (pkg_dir / "services.py").write_text("from .utils import VALUE\n")
        (pkg_dir / "agents.py").write_text(
            "from .services import VALUE\nfrom . import utils\n"
        )
        (pkg_dir / "cli.py").write_text(
            "from .agents import VALUE\nfrom . import services\n"
        )

        modules = build_dependency_graph(pkg_dir, "order_pkg")
        porting_order = compute_porting_order(modules)

        violations = _check_no_acyclic_violations(modules, porting_order)
        if violations:
            print(f"FAIL: {len(violations)} violations in acyclic graph:")
            for imp, dep in violations:
                print(f"  {imp} before its dep {dep}")
            return False

        # Explicit ordering check
        order_map = {name: i for i, (name, _) in enumerate(porting_order)}
        if order_map.get("order_pkg.utils", 999) > order_map.get(
            "order_pkg.services", 0
        ):
            print(f"FAIL: utils after services — {porting_order}")
            return False

        print("PASS: Acyclic temp package has zero porting-order violations")
        return True


def test_porting_order_scc_documented() -> bool:
    """SCC members may appear in any order; only cross-SCC edges are strict.

    Build a cycle: a→b→c→a, plus leaf d (no deps) imported by a.
    d must appear before a/b/c; a/b/c can be in any order.
    """
    modules = {
        "a": ModuleInfo(name="a", file_path=Path("a.py"), imports={"b", "d"}),
        "b": ModuleInfo(name="b", file_path=Path("b.py"), imports={"c"}),
        "c": ModuleInfo(name="c", file_path=Path("c.py"), imports={"a"}),
        "d": ModuleInfo(name="d", file_path=Path("d.py"), imports=set()),
    }
    # Populate imported_by so fan_in is correct
    for mod_name, mod_info in modules.items():
        for imp in mod_info.imports:
            if imp in modules:
                modules[imp].imported_by.add(mod_name)

    porting_order = compute_porting_order(modules)
    order_map = {name: i for i, (name, _) in enumerate(porting_order)}

    # d (leaf, level 0) must come before a, b, c (cycle, level 1+)
    for cyc_mod in ("a", "b", "c"):
        if order_map["d"] > order_map[cyc_mod]:
            print(
                f"FAIL: leaf 'd' (pos {order_map['d']}) appears after "
                f"cycle member '{cyc_mod}' (pos {order_map[cyc_mod]})"
            )
            return False

    # Cross-SCC violations must be zero
    violations = _check_no_acyclic_violations(modules, porting_order)
    if violations:
        print(f"FAIL: {len(violations)} cross-SCC violations: {violations}")
        return False

    # Within-SCC: a imports b, but a may appear before b — that's OK.
    # Document this explicitly.
    within_scc = []
    for name, mod in modules.items():
        for imp in mod.imports:
            if imp in order_map and name in order_map:
                if order_map[imp] > order_map[name]:
                    within_scc.append((name, imp))

    print(
        f"PASS: SCC order correct (d first, cycle members grouped). "
        f"Within-SCC order: {[n for n, _ in porting_order]}. "
        f"Within-SCC violations (expected): {len(within_scc)}"
    )
    return True


# ── Unit tests: module name calculation ────────────────────────────────


def test_module_name_calculation() -> bool:
    """Test module name calculation from file paths."""
    tests = [
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


# ── Integration tests: temp package with __init__.py ──────────────────


def _make_temp_pkg(tmpdir: Path) -> Path:
    """Create a temp package with __init__.py relative imports."""
    pkg = tmpdir / "my_pkg"
    pkg.mkdir()

    # my_pkg/__init__.py: from . import leaf; from .sub import Sub
    (pkg / "__init__.py").write_text("from . import leaf\nfrom . import sub\n")

    # my_pkg/leaf.py: standalone module
    (pkg / "leaf.py").write_text("VALUE = 42\n")

    # my_pkg/sub/__init__.py: from .leaf import Leaf; from .. import leaf
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text(
        "from .leaf import Leaf\nfrom .. import leaf as parent_leaf\n"
    )

    # my_pkg/sub/leaf.py
    (sub / "leaf.py").write_text("class Leaf: pass\n")

    # my_pkg/sub/sibling.py: from .. import leaf
    (sub / "sibling.py").write_text("from .. import leaf as top_leaf\n")

    return pkg


def test_init_relative_imports() -> bool:
    """Test that __init__.py relative imports resolve correctly via build_dependency_graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = _make_temp_pkg(Path(tmpdir))
        modules = build_dependency_graph(pkg, "my_pkg")

        # my_pkg.__init__ should import my_pkg.leaf and my_pkg.sub
        init = modules.get("my_pkg")
        if not init:
            print("FAIL: my_pkg not found in modules")
            return False

        expected_imports = {"my_pkg.leaf", "my_pkg.sub"}
        if init.imports != expected_imports:
            print(f"FAIL: my_pkg imports = {init.imports}, expected {expected_imports}")
            return False

        # my_pkg.sub.__init__ should import my_pkg.sub.leaf and my_pkg.leaf
        sub_init = modules.get("my_pkg.sub")
        if not sub_init:
            print("FAIL: my_pkg.sub not found")
            return False

        expected_sub_imports = {"my_pkg.sub.leaf", "my_pkg.leaf"}
        if sub_init.imports != expected_sub_imports:
            print(
                f"FAIL: my_pkg.sub imports = {sub_init.imports}, expected {expected_sub_imports}"
            )
            return False

        # my_pkg.sub.sibling should import my_pkg.leaf (not my_pkg.sub.leaf or other)
        sibling = modules.get("my_pkg.sub.sibling")
        if not sibling:
            print("FAIL: my_pkg.sub.sibling not found")
            return False

        if "my_pkg.leaf" not in sibling.imports:
            print(f"FAIL: sibling imports = {sibling.imports}, expected my_pkg.leaf")
            return False

        print("PASS: __init__.py relative imports resolve correctly")
        return True


def test_from_dot_import_leaf() -> bool:
    """Test that 'from . import leaf' in __init__.py counts pkg.sub.leaf."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = _make_temp_pkg(Path(tmpdir))
        modules = build_dependency_graph(pkg, "my_pkg")

        sub_init = modules.get("my_pkg.sub")
        if not sub_init:
            print("FAIL: my_pkg.sub not found")
            return False

        # from .leaf import Leaf → dep on my_pkg.sub.leaf (NOT my_pkg.sub.leaf.Leaf)
        if "my_pkg.sub.leaf" not in sub_init.imports:
            print(f"FAIL: missing my_pkg.sub.leaf dep, got: {sub_init.imports}")
            return False

        # Ensure no class-level deps leaked
        for imp in sub_init.imports:
            if imp.endswith(".Leaf"):
                print(f"FAIL: class-level dep leaked: {imp}")
                return False

        print("PASS: 'from . import leaf' / 'from .leaf import X' correct")
        return True


def test_symbols_not_counted() -> bool:
    """Test that imported classes/functions are NOT counted as module deps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "sym_pkg"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "models.py").write_text("class AskUserQuestionInput: pass\n")
        (pkg_dir / "consumer.py").write_text(
            "from .models import AskUserQuestionInput\n"
        )

        modules = build_dependency_graph(pkg_dir, "sym_pkg")
        consumer = modules.get("sym_pkg.consumer")
        if not consumer:
            print("FAIL: sym_pkg.consumer not found")
            return False

        # Should depend on sym_pkg.models, NOT sym_pkg.models.AskUserQuestionInput
        if "sym_pkg.models.AskUserQuestionInput" in consumer.imports:
            print(f"FAIL: class-level dep in imports: {consumer.imports}")
            return False

        if "sym_pkg.models" not in consumer.imports:
            print(f"FAIL: missing module-level dep, got: {consumer.imports}")
            return False

        print("PASS: imported symbols not counted as module deps")
        return True


def test_longest_module_match_in_pipeline() -> bool:
    """Test that longest-module matching works end-to-end in build_dependency_graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_dir = Path(tmpdir) / "long_pkg"
        pkg_dir.mkdir()

        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "tools.py").write_text("pass\n")
        (pkg_dir / "tools_file_ops.py").write_text("pass\n")
        # consumer imports long_pkg.tools.file_ops (doesn't exist as module),
        # should match long_pkg.tools (parent), not add a phantom dep
        (pkg_dir / "consumer.py").write_text("from long_pkg.tools import nonexistent\n")

        modules = build_dependency_graph(pkg_dir, "long_pkg")
        consumer = modules.get("long_pkg.consumer")
        if not consumer:
            print("FAIL: long_pkg.consumer not found")
            return False

        # Should match long_pkg.tools, not a non-existent submodule
        for imp in consumer.imports:
            if imp not in modules:
                print(f"FAIL: import '{imp}' doesn't match any known module")
                return False

        if "long_pkg.tools" not in consumer.imports:
            print(f"FAIL: missing tools dep, got: {consumer.imports}")
            return False

        print("PASS: longest-module matching in pipeline")
        return True


# ── Stability / reproducibility tests ─────────────────────────────────


def test_stable_timestamp() -> bool:
    """Test stable timestamp generation."""
    ts1 = format_timestamp(stable=True)
    ts2 = format_timestamp(stable=True)
    if ts1 != ts2 or "2026-01-01" not in ts1:
        print(f"FAIL: Stable timestamps: {ts1} vs {ts2}")
        return False
    print(f"PASS: Stable timestamp: {ts1}")
    return True


def test_reproducible_reports() -> bool:
    """Test that stable reports are byte-identical across runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = _make_temp_pkg(Path(tmpdir))
        modules = build_dependency_graph(pkg, "my_pkg")
        cycles = find_cycles(modules)
        porting = compute_porting_order(modules)

        md1 = generate_markdown_report(modules, cycles, porting, stable=True)
        md2 = generate_markdown_report(modules, cycles, porting, stable=True)

        if md1 != md2:
            print("FAIL: Markdown reports differ between runs")
            return False

        json1 = generate_json_report(modules, cycles, porting, stable=True)
        json2 = generate_json_report(modules, cycles, porting, stable=True)

        if json1 != json2:
            print("FAIL: JSON reports differ between runs")
            return False

        print("PASS: Reports are reproducible")
        return True


# ── Runner ────────────────────────────────────────────────────────────


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
        ("Porting Order: Diamond", test_porting_order_dependency_first),
        (
            "Porting Order: Acyclic No Violations",
            test_porting_order_acyclic_no_violations,
        ),
        ("Porting Order: SCC Documented", test_porting_order_scc_documented),
        ("Module Name Calculation", test_module_name_calculation),
        ("Init Relative Imports", test_init_relative_imports),
        ("From-Dot Import Leaf", test_from_dot_import_leaf),
        ("Symbols Not Counted", test_symbols_not_counted),
        ("Longest Match in Pipeline", test_longest_module_match_in_pipeline),
        ("Stable Timestamp", test_stable_timestamp),
        ("Reproducible Reports", test_reproducible_reports),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback

            traceback.print_exc()
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
