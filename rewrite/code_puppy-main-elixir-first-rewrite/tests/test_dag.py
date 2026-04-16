"""Comprehensive tests for code_puppy/utils/dag.py.

Covers:
- build_dependency_graph: normalization, missing-node injection, edge cases
- detect_cycles: acyclic, 2-node, 3-node, mixed, self-loops
- build_execution_waves: linear, diamond, independent, cycles, complex scenarios
"""

import pytest

from code_puppy.utils.dag import (
    build_dependency_graph,
    build_execution_waves,
    detect_cycles,
)


# ---------------------------------------------------------------------------
# build_dependency_graph
# ---------------------------------------------------------------------------


class TestBuildDependencyGraph:
    """Tests for build_dependency_graph()."""

    def test_empty_input(self) -> None:
        """Empty dict returns empty graph."""
        assert build_dependency_graph({}) == {}

    def test_single_node_no_deps(self) -> None:
        """Single node with no dependencies."""
        result = build_dependency_graph({"A": []})
        assert result == {"A": set()}

    def test_linear_chain(self) -> None:
        """A→B→C: each node has exactly one predecessor."""
        result = build_dependency_graph({"A": ["B"], "B": ["C"], "C": []})
        assert result == {"A": {"B"}, "B": {"C"}, "C": set()}

    def test_diamond_dependency(self) -> None:
        """Classic diamond: A depends on B and C, both depend on D."""
        deps = {
            "A": ["B", "C"],
            "B": ["D"],
            "C": ["D"],
            "D": [],
        }
        result = build_dependency_graph(deps)
        assert result == {
            "A": {"B", "C"},
            "B": {"D"},
            "C": {"D"},
            "D": set(),
        }

    def test_missing_dep_nodes_are_added(self) -> None:
        """Nodes mentioned only as dependencies get added with empty dep set."""
        result = build_dependency_graph({"A": ["B", "C"]})
        assert "B" in result
        assert "C" in result
        assert result["B"] == set()
        assert result["C"] == set()
        assert result["A"] == {"B", "C"}

    def test_self_referencing_node(self) -> None:
        """A node depending on itself is represented as a self-loop."""
        result = build_dependency_graph({"A": ["A"]})
        assert result == {"A": {"A"}}

    def test_values_are_sets_not_lists(self) -> None:
        """Output values should be sets regardless of input type."""
        result = build_dependency_graph({"X": ["Y", "Z"]})
        assert isinstance(result["X"], set)

    def test_duplicate_deps_deduplicated(self) -> None:
        """Duplicate entries in the dependency list collapse into one set entry."""
        result = build_dependency_graph({"A": ["B", "B", "B"]})
        assert result["A"] == {"B"}

    def test_integer_nodes(self) -> None:
        """Graph nodes don't have to be strings — integers work fine."""
        result = build_dependency_graph({1: [2, 3], 2: [3], 3: []})
        assert result == {1: {2, 3}, 2: {3}, 3: set()}

    def test_independent_nodes(self) -> None:
        """Multiple nodes with no inter-dependencies."""
        result = build_dependency_graph({"A": [], "B": [], "C": []})
        assert result == {"A": set(), "B": set(), "C": set()}

    def test_existing_key_not_overwritten_by_dep_insertion(self) -> None:
        """A node that appears both as a key and a dep retains its own deps."""
        result = build_dependency_graph({"A": ["B"], "B": ["C"]})
        # B is both a key (with dep C) and referenced as dep of A
        assert result["B"] == {"C"}

    def test_deep_chain_all_nodes_present(self) -> None:
        """Long chain — every node from root to leaf must be in the graph."""
        chain = {str(i): [str(i + 1)] for i in range(10)}
        chain["10"] = []
        result = build_dependency_graph(chain)
        assert len(result) == 11
        for i in range(10):
            assert str(i + 1) in result[str(i)]


# ---------------------------------------------------------------------------
# detect_cycles
# ---------------------------------------------------------------------------


class TestDetectCycles:
    """Tests for detect_cycles()."""

    def test_empty_graph_is_acyclic(self) -> None:
        assert detect_cycles({}) == []

    def test_single_node_no_deps_is_acyclic(self) -> None:
        assert detect_cycles({"A": set()}) == []

    def test_linear_chain_is_acyclic(self) -> None:
        graph = build_dependency_graph({"A": ["B"], "B": ["C"], "C": []})
        assert detect_cycles(graph) == []

    def test_diamond_is_acyclic(self) -> None:
        graph = build_dependency_graph(
            {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        )
        assert detect_cycles(graph) == []

    def test_two_node_cycle(self) -> None:
        """A→B and B→A form a simple 2-node cycle."""
        graph: dict[str, set[str]] = {"A": {"B"}, "B": {"A"}}
        cycle_nodes = detect_cycles(graph)
        assert set(cycle_nodes) == {"A", "B"}

    def test_three_node_cycle(self) -> None:
        """A→B→C→A: full 3-node cycle."""
        graph: dict[str, set[str]] = {"A": {"B"}, "B": {"C"}, "C": {"A"}}
        cycle_nodes = detect_cycles(graph)
        assert set(cycle_nodes) == {"A", "B", "C"}

    def test_self_loop(self) -> None:
        """A node that depends on itself is a cycle of length 1."""
        graph: dict[str, set[str]] = {"A": {"A"}}
        cycle_nodes = detect_cycles(graph)
        assert "A" in cycle_nodes

    def test_cycle_in_subgraph_only_cycle_nodes_reported(self) -> None:
        """When only part of the graph is cyclic, acyclic nodes are not flagged."""
        # D→E→F→E (cycle), A→B→C (acyclic)
        graph: dict[str, set[str]] = {
            "A": {"B"},
            "B": {"C"},
            "C": set(),
            "D": {"E"},
            "E": {"F"},
            "F": {"E"},  # cycle: E↔F
        }
        cycle_nodes = set(detect_cycles(graph))
        # E and F must be flagged
        assert "E" in cycle_nodes
        assert "F" in cycle_nodes
        # Acyclic nodes must NOT be flagged
        assert "A" not in cycle_nodes
        assert "B" not in cycle_nodes
        assert "C" not in cycle_nodes

    def test_multiple_independent_cycles(self) -> None:
        """Two disconnected cycles both get detected."""
        graph: dict[str, set[str]] = {
            "A": {"B"},
            "B": {"A"},
            "C": {"D"},
            "D": {"C"},
        }
        cycle_nodes = set(detect_cycles(graph))
        assert cycle_nodes == {"A", "B", "C", "D"}

    def test_returns_list_not_set(self) -> None:
        """Return type should be a list (even if order is arbitrary)."""
        graph: dict[str, set[str]] = {"A": {"B"}, "B": {"A"}}
        result = detect_cycles(graph)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# build_execution_waves
# ---------------------------------------------------------------------------


class TestBuildExecutionWaves:
    """Tests for build_execution_waves()."""

    def test_empty_graph_returns_empty_waves(self) -> None:
        assert build_execution_waves({}) == []

    def test_single_node_no_deps(self) -> None:
        """Single independent node goes into wave 0."""
        waves = build_execution_waves({"A": set()})
        assert waves == [["A"]]

    def test_linear_chain_one_node_per_wave(self) -> None:
        """A depends on B which depends on C → waves are [C], [B], [A]."""
        graph = build_dependency_graph({"A": ["B"], "B": ["C"], "C": []})
        waves = build_execution_waves(graph)
        assert len(waves) == 3
        assert waves[0] == ["C"]
        assert waves[1] == ["B"]
        assert waves[2] == ["A"]

    def test_diamond_produces_three_waves(self) -> None:
        """Diamond: D first, B and C in parallel, A last."""
        graph = build_dependency_graph(
            {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        )
        waves = build_execution_waves(graph)
        assert len(waves) == 3
        assert waves[0] == ["D"]
        assert set(waves[1]) == {"B", "C"}
        assert waves[2] == ["A"]

    def test_independent_nodes_all_in_wave_0(self) -> None:
        """Nodes with no dependencies all appear in the first wave."""
        graph = build_dependency_graph({"A": [], "B": [], "C": []})
        waves = build_execution_waves(graph)
        assert len(waves) == 1
        assert set(waves[0]) == {"A", "B", "C"}

    def test_cycle_raises_value_error(self) -> None:
        """A cycle must cause build_execution_waves to raise ValueError."""
        graph: dict[str, set[str]] = {"A": {"B"}, "B": {"A"}}
        with pytest.raises(ValueError, match="cycle"):
            build_execution_waves(graph)

    def test_self_loop_raises_value_error(self) -> None:
        graph: dict[str, set[str]] = {"A": {"A"}}
        with pytest.raises(ValueError):
            build_execution_waves(graph)

    def test_three_node_cycle_raises_value_error(self) -> None:
        graph: dict[str, set[str]] = {"A": {"B"}, "B": {"C"}, "C": {"A"}}
        with pytest.raises(ValueError):
            build_execution_waves(graph)

    def test_all_nodes_appear_exactly_once(self) -> None:
        """Every node appears in exactly one wave."""
        graph = build_dependency_graph(
            {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        )
        waves = build_execution_waves(graph)
        all_nodes = [n for wave in waves for n in wave]
        assert sorted(all_nodes) == sorted(graph.keys())
        # No duplicates
        assert len(all_nodes) == len(set(all_nodes))

    def test_wave_ordering_respects_dependencies(self) -> None:
        """For every node N with dep D, D's wave index < N's wave index."""
        graph = build_dependency_graph(
            {
                "A": ["B", "C"],
                "B": ["D"],
                "C": ["D"],
                "D": ["E"],
                "E": [],
            }
        )
        waves = build_execution_waves(graph)
        wave_index = {n: i for i, wave in enumerate(waves) for n in wave}
        for node, deps in graph.items():
            for dep in deps:
                assert wave_index[dep] < wave_index[node], (
                    f"{dep} (wave {wave_index[dep]}) should come before "
                    f"{node} (wave {wave_index[node]})"
                )

    def test_within_wave_nodes_sorted_by_str(self) -> None:
        """Nodes within a single wave are sorted by their str() representation."""
        graph: dict[str, set[str]] = {"Z": set(), "A": set(), "M": set()}
        waves = build_execution_waves(graph)
        assert waves == [["A", "M", "Z"]]

    def test_complex_real_world_scenario(self) -> None:
        """Six-node scenario mimicking a real build pipeline.

        Dependency graph (X depends on Y means X→Y):
            lint      → (nothing)
            typecheck → (nothing)
            unit      → (nothing)
            build     → lint, typecheck
            test      → unit, build
            deploy    → test
        Expected waves:
            Wave 0: lint, typecheck, unit   (no deps)
            Wave 1: build                   (depends on lint + typecheck)
            Wave 2: test                    (depends on unit + build)
            Wave 3: deploy                  (depends on test)
        """
        deps = {
            "lint": [],
            "typecheck": [],
            "unit": [],
            "build": ["lint", "typecheck"],
            "test": ["unit", "build"],
            "deploy": ["test"],
        }
        graph = build_dependency_graph(deps)
        waves = build_execution_waves(graph)

        wave_index = {n: i for i, wave in enumerate(waves) for n in wave}

        # Root tasks are in wave 0
        assert wave_index["lint"] == 0
        assert wave_index["typecheck"] == 0
        assert wave_index["unit"] == 0

        # build comes after lint and typecheck
        assert wave_index["build"] > wave_index["lint"]
        assert wave_index["build"] > wave_index["typecheck"]

        # test comes after unit and build
        assert wave_index["test"] > wave_index["unit"]
        assert wave_index["test"] > wave_index["build"]

        # deploy is last
        assert wave_index["deploy"] > wave_index["test"]

        # Total waves: 4
        assert len(waves) == 4

    def test_two_independent_chains(self) -> None:
        """Two completely independent linear chains are interleaved by wave."""
        # Chain 1: A1 → A2 → A3
        # Chain 2: B1 → B2 → B3  (independent of chain 1)
        deps = {
            "A1": ["A2"],
            "A2": ["A3"],
            "A3": [],
            "B1": ["B2"],
            "B2": ["B3"],
            "B3": [],
        }
        graph = build_dependency_graph(deps)
        waves = build_execution_waves(graph)

        assert len(waves) == 3  # 3 levels deep

        wave_index = {n: i for i, wave in enumerate(waves) for n in wave}

        # Both chains progress at the same rate
        assert wave_index["A3"] == wave_index["B3"] == 0
        assert wave_index["A2"] == wave_index["B2"] == 1
        assert wave_index["A1"] == wave_index["B1"] == 2

    def test_integer_node_keys(self) -> None:
        """Waves work fine with integer node keys."""
        graph = build_dependency_graph({1: [2], 2: [3], 3: []})
        waves = build_execution_waves(graph)
        assert len(waves) == 3
        assert waves[0] == [3]
        assert waves[1] == [2]
        assert waves[2] == [1]

    def test_error_message_names_cycle_participants(self) -> None:
        """ValueError message should mention the nodes involved in the cycle."""
        graph: dict[str, set[str]] = {"Alpha": {"Beta"}, "Beta": {"Alpha"}}
        with pytest.raises(ValueError) as exc_info:
            build_execution_waves(graph)
        message = str(exc_info.value)
        assert "Alpha" in message or "Beta" in message

    def test_fan_out_then_join(self) -> None:
        """One root fans out to N workers, all join into one final node."""
        # root → w1, w2, w3, w4
        # final → w1, w2, w3, w4
        deps = {
            "root": [],
            "w1": ["root"],
            "w2": ["root"],
            "w3": ["root"],
            "w4": ["root"],
            "final": ["w1", "w2", "w3", "w4"],
        }
        graph = build_dependency_graph(deps)
        waves = build_execution_waves(graph)

        wave_index = {n: i for i, wave in enumerate(waves) for n in wave}

        assert wave_index["root"] == 0
        # All workers in same wave
        worker_waves = {wave_index[f"w{i}"] for i in range(1, 5)}
        assert len(worker_waves) == 1, "All workers should be in the same wave"
        assert wave_index["final"] > next(iter(worker_waves))
        assert len(waves) == 3
