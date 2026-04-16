"""Comprehensive benchmark: Rust _code_puppy_core vs pure Python.

Measures actual speedup for all accelerated operations across multiple
message history sizes.  Produces a formatted summary table at the end.

KEY INSIGHT: Rust's advantage is in *batch* processing and *combined* pipelines.
Individual micro-operations (len(text)/2.5) may be faster in Python due to the
PyO3 bridge overhead being larger than the trivial computation.  The real win
is the end-to-end pipeline: one serialize → batch-process → prune → truncate
replaces dozens of separate Python method calls that re-iterate messages.

Run:
    python -m pytest tests/bench_rust_vs_python.py -v -s
    python -m pytest tests/bench_rust_vs_python.py -v -s -k "200"   # just 200-msg tests
    python -m pytest tests/bench_rust_vs_python.py -v -s -k "end_to_end"  # key benchmark
"""

import pickle
import statistics
import time

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    serialize_messages_for_rust,
    set_rust_enabled,
)
from code_puppy.agents.agent_code_puppy import CodePuppyAgent

# Skip entire module if Rust extension is not installed
pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust module (_code_puppy_core) not installed"
)

# ── Configuration ────────────────────────────────────────────────────────────

ITERATIONS = 50  # timing iterations per benchmark
WARM_UP = 3  # warm-up iterations (discarded)
SCALES = [10, 50, 100, 200, 500]  # message-history sizes to test

# Collected across all tests for the final summary table
_summary_rows: list[dict] = []


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_realistic_history(n: int) -> list[ModelMessage]:
    """Build a realistic *n*-message history with mixed content types.

    Pattern (repeating cycle of 7):
      0: continuation / orphan tool-call
      1: user text
      2: assistant text + tool call
      3: tool return
      4: assistant explanation
      5: user follow-up
      6: assistant with thinking part
    """
    messages: list[ModelMessage] = []

    # System prompt — always first
    messages.append(
        ModelRequest(
            parts=[
                TextPart(
                    content=(
                        "You are a helpful coding assistant. "
                        "You have access to tools for reading files, writing files, "
                        "and running shell commands. "
                        "Always explain your reasoning before taking actions.\n"
                    )
                    * 3
                )
            ]
        )
    )

    tool_id = 0
    tool_names = ["cp_read_file", "cp_agent_run_shell_command", "cp_grep"]
    orphan_injected = False

    for i in range(1, n):
        phase = i % 7

        if phase == 1 or phase == 5:
            # User text (varying length)
            length = 50 + (i * 17) % 2000
            messages.append(
                ModelRequest(
                    parts=[TextPart(content=f"User message {i}: " + "x" * length)]
                )
            )

        elif phase == 2:
            # Assistant with tool call
            tool_id += 1
            tname = tool_names[tool_id % len(tool_names)]
            args = (
                f'{{"file_path": "src/module_{i}.py"}}'
                if tname == "cp_read_file"
                else f'{{"command": "grep -rn pattern_{i} src/"}}'
            )
            messages.append(
                ModelResponse(
                    parts=[
                        TextPart(content="Let me check that for you."),
                        ToolCallPart(
                            tool_name=tname,
                            args=args,
                            tool_call_id=f"tc-{tool_id}",
                        ),
                    ]
                )
            )

        elif phase == 3:
            # Tool return (varying size)
            content_size = 200 + (i * 13) % 5000
            messages.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_names[tool_id % len(tool_names)],
                            content="def function():\n"
                            + "    line_of_code = True\n" * (content_size // 25),
                            tool_call_id=f"tc-{tool_id}",
                        )
                    ]
                )
            )

        elif phase == 4:
            # Assistant explanation
            messages.append(
                ModelResponse(
                    parts=[
                        TextPart(
                            content=(
                                f"Looking at module {i}, I can see the following: "
                                + "This is a detailed analysis of the code. "
                                * (3 + i % 7)
                            )
                        )
                    ]
                )
            )

        elif phase == 6:
            # Assistant with a thinking part (tests thinking-part filtering)
            messages.append(
                ModelResponse(
                    parts=[
                        ThinkingPart(content=f"Hmm, let me think about step {i}..."),
                        TextPart(
                            content=f"After careful consideration about step {i}..."
                        ),
                    ]
                )
            )

        else:  # phase == 0 (after the first)
            # Inject one orphaned tool call at ~30% mark to stress pruning
            if not orphan_injected and i > n * 0.3:
                orphan_injected = True
                tool_id += 1
                messages.append(
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="cp_read_file",
                                args='{"file_path": "ORPHAN.py"}',
                                tool_call_id=f"tc-{tool_id}",
                            )
                        ]
                    )
                )
            else:
                messages.append(
                    ModelRequest(parts=[TextPart(content=f"Continuing task {i}...")])
                )

    return messages[:n]  # ensure exact count


class _Stats:
    """Lightweight timing statistics."""

    __slots__ = ("times_ns",)

    def __init__(self) -> None:
        self.times_ns: list[int] = []

    def record(self, ns: int) -> None:
        self.times_ns.append(ns)

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times_ns) / 1_000_000

    @property
    def p5_ms(self) -> float:
        ts = sorted(self.times_ns)
        idx = max(0, int(len(ts) * 0.05))
        return ts[idx] / 1_000_000

    @property
    def p95_ms(self) -> float:
        ts = sorted(self.times_ns)
        idx = min(len(ts) - 1, int(len(ts) * 0.95))
        return ts[idx] / 1_000_000

    @property
    def min_ms(self) -> float:
        return min(self.times_ns) / 1_000_000

    @property
    def max_ms(self) -> float:
        return max(self.times_ns) / 1_000_000


def _time_fn(fn, iterations: int = ITERATIONS, warm_up: int = WARM_UP) -> _Stats:
    """Run *fn* with warm-up, then collect *iterations* timings."""
    for _ in range(warm_up):
        fn()
    stats = _Stats()
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        stats.record(time.perf_counter_ns() - t0)
    return stats


def _print_result(
    label: str,
    n_msgs: int,
    py_stats: _Stats,
    rs_stats: _Stats,
) -> float:
    """Print a single benchmark row and return the speedup ratio."""
    speedup = (
        py_stats.median_ms / rs_stats.median_ms
        if rs_stats.median_ms > 0
        else float("inf")
    )

    marker = "⚡" if speedup >= 1.0 else "🐢"

    print(
        f"  {label:<28s} │ {n_msgs:>4d} msgs │ "
        f"Python {py_stats.median_ms:>8.3f}ms  (p5={py_stats.p5_ms:.3f}, p95={py_stats.p95_ms:.3f}) │ "
        f"Rust {rs_stats.median_ms:>8.3f}ms  (p5={rs_stats.p5_ms:.3f}, p95={rs_stats.p95_ms:.3f}) │ "
        f"{marker} {speedup:>6.1f}x"
    )

    _summary_rows.append(
        {
            "op": label,
            "n": n_msgs,
            "py_ms": py_stats.median_ms,
            "rs_ms": rs_stats.median_ms,
            "speedup": speedup,
        }
    )
    return speedup


# ── Benchmark: Token Estimation (individual operation) ───────────────────────
# NOTE: Rust process_messages_batch does BOTH tokens AND hashing in one pass.
# Comparing against just token estimation understates Rust's value.  The
# Combined Token+Hash and End-to-End Pipeline benchmarks are the fair tests.


class TestBenchTokenEstimation:
    """process_messages_batch (Rust) vs estimate_tokens_for_message (Python).

    NOTE: Rust does more work (hashing too).  See Combined benchmark for
    apples-to-apples comparison.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import process_messages_batch

        self._process = process_messages_batch
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_token_estimation(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        # Rust path (does tokens + hashing combined)
        rs = _time_fn(lambda: self._process(serialized, [], [], ""))

        # Python path (only tokens)
        agent = self._agent
        set_rust_enabled(False)
        try:
            py = _time_fn(lambda: [agent.estimate_tokens_for_message(m) for m in msgs])
        finally:
            set_rust_enabled(True)

        print()
        _print_result("Token Est. (Rust=batch)", n, py, rs)
        # No hard assertion — Rust batch does more work than pure Python tokens


# ── Benchmark: Combined Token + Hash (fair comparison) ───────────────────────


class TestBenchCombinedTokenHash:
    """process_messages_batch vs Python token estimation + hashing combined.

    This is the FAIR comparison — Rust does both in a single pass.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import process_messages_batch

        self._process = process_messages_batch
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_combined_token_hash(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        # Rust: single call does both token estimation and hashing
        rs = _time_fn(lambda: self._process(serialized, [], [], ""))

        # Python: separate token estimation + hashing (what actually happens per turn)
        agent = self._agent
        set_rust_enabled(False)
        try:

            def python_combined():
                for m in msgs:
                    agent.estimate_tokens_for_message(m)
                for m in msgs:
                    agent.hash_message(m)

            py = _time_fn(python_combined)
        finally:
            set_rust_enabled(True)

        print()
        speedup = _print_result("Combined Token+Hash", n, py, rs)
        # At 200+ messages, Rust should win when doing combined work
        if n >= 200:
            assert speedup > 0.3, (
                f"Rust combined was unexpectedly {1 / speedup:.1f}x slower at {n} msgs"
            )


# ── Benchmark: Message Hashing ───────────────────────────────────────────────


class TestBenchMessageHashing:
    """process_messages_batch hashing (Rust) vs hash_message loop (Python)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import process_messages_batch

        self._process = process_messages_batch
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_message_hashing(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        rs = _time_fn(lambda: self._process(serialized, [], [], "").message_hashes)

        agent = self._agent
        set_rust_enabled(False)
        try:
            py = _time_fn(lambda: [agent.hash_message(m) for m in msgs])
        finally:
            set_rust_enabled(True)

        print()
        _print_result("Message Hashing", n, py, rs)
        # Informational — Rust batch also computes tokens, so not 1:1


# ── Benchmark: Pruning ───────────────────────────────────────────────────────


class TestBenchPruning:
    """prune_and_filter (Rust) vs prune_interrupted_tool_calls (Python)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import prune_and_filter

        self._prune = prune_and_filter
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_pruning(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        rs = _time_fn(lambda: self._prune(serialized, 50_000))

        agent = self._agent
        set_rust_enabled(False)
        try:
            py = _time_fn(lambda: agent.prune_interrupted_tool_calls(msgs))
        finally:
            set_rust_enabled(True)

        print()
        _print_result("Pruning & Filtering", n, py, rs)
        # Informational — Rust prune also does token-based size filtering


# ── Benchmark: Pruning with size filtering (fair comparison) ─────────────────


class TestBenchPruningWithFilter:
    """prune_and_filter (Rust single-pass) vs Python prune + filter_huge (multi-pass)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import prune_and_filter

        self._prune = prune_and_filter
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_pruning_with_filter(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        # Rust: single pass does prune + size filter + thinking filter
        rs = _time_fn(lambda: self._prune(serialized, 50_000))

        # Python: must do prune + manual size filter (two passes)
        agent = self._agent
        set_rust_enabled(False)
        try:

            def python_multi_pass():
                filtered = [
                    m for m in msgs if agent.estimate_tokens_for_message(m) < 50_000
                ]
                agent.prune_interrupted_tool_calls(filtered)

            py = _time_fn(python_multi_pass)
        finally:
            set_rust_enabled(True)

        print()
        speedup = _print_result("Prune+Filter (multi-pass)", n, py, rs)
        if n >= 200:
            assert speedup > 0.3, (
                f"Rust was unexpectedly {1 / speedup:.1f}x slower at {n} msgs"
            )


# ── Benchmark: Truncation ────────────────────────────────────────────────────


class TestBenchTruncation:
    """truncation_indices (Rust) vs truncation fallback (Python)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import (
            process_messages_batch,
            truncation_indices as rust_trunc,
        )

        self._process = process_messages_batch
        self._trunc = rust_trunc
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_truncation(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)
        protected = 5000

        # Pre-compute per-message tokens for Rust path
        batch = self._process(serialized, [], [], "")
        tokens = batch.per_message_tokens

        # Rust: just the index computation (tokens pre-computed)
        rs = _time_fn(lambda: self._trunc(tokens, protected, False))

        # Python: must re-estimate tokens internally
        agent = self._agent
        set_rust_enabled(False)
        try:
            py = _time_fn(lambda: agent.truncation(msgs, protected))
        finally:
            set_rust_enabled(True)

        print()
        speedup = _print_result("Truncation", n, py, rs)
        assert speedup > 0.5, (
            f"Rust was unexpectedly {1 / speedup:.1f}x slower at {n} msgs"
        )


# ── Benchmark: Session Serialization ─────────────────────────────────────────


class TestBenchSerialization:
    """MessagePack via Rust vs pickle (Python)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import (
            deserialize_session,
            serialize_session,
        )

        self._ser = serialize_session
        self._de = deserialize_session

    @pytest.mark.parametrize("n", SCALES)
    def test_serialize(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        # Rust: MessagePack serialize (from pre-built dicts)
        rs = _time_fn(lambda: self._ser(serialized))

        # Python: pickle
        py = _time_fn(lambda: pickle.dumps(msgs))

        print()
        _print_result("Serialize", n, py, rs)
        # Informational — pickle serializes rich pydantic objects, Rust gets plain dicts

    @pytest.mark.parametrize("n", SCALES)
    def test_deserialize(self, n: int) -> None:
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        rust_bytes = self._ser(serialized)
        pickle_bytes = pickle.dumps(msgs)

        rs = _time_fn(lambda: self._de(rust_bytes))
        py = _time_fn(lambda: pickle.loads(pickle_bytes))  # noqa: S301

        print()
        _print_result("Deserialize", n, py, rs)

    @pytest.mark.parametrize("n", SCALES)
    def test_serialize_size(self, n: int) -> None:
        """Compare serialized sizes: MessagePack vs pickle."""
        msgs = _build_realistic_history(n)
        serialized = serialize_messages_for_rust(msgs)

        rust_bytes = self._ser(serialized)
        pickle_bytes = pickle.dumps(msgs)

        ratio = len(pickle_bytes) / len(rust_bytes) if len(rust_bytes) > 0 else 0
        print(
            f"\n  Serialized size             │ {n:>4d} msgs │ "
            f"pickle {len(pickle_bytes):>8,d} bytes │ "
            f"msgpack {len(rust_bytes):>8,d} bytes │ "
            f"pickle is {ratio:.1f}x larger"
        )
        _summary_rows.append(
            {
                "op": "Size (pickle/msgpack)",
                "n": n,
                "py_ms": len(pickle_bytes) / 1024,  # KB
                "rs_ms": len(rust_bytes) / 1024,  # KB
                "speedup": ratio,
            }
        )


# ── Benchmark: End-to-End Hot Path (THE KEY BENCHMARK) ──────────────────────


class TestBenchEndToEnd:
    """Full per-turn hot path: serialize → batch-process → prune → truncate.

    THIS is where Rust's advantage shows: one serialize + three fast Rust calls
    replaces dozens of Python iterations over the message history.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        from code_puppy._core_bridge import (
            process_messages_batch,
            prune_and_filter,
            truncation_indices as rust_trunc,
        )

        self._process = process_messages_batch
        self._prune = prune_and_filter
        self._trunc = rust_trunc
        self._agent = CodePuppyAgent()

    @pytest.mark.parametrize("n", SCALES)
    def test_end_to_end(self, n: int) -> None:
        """Rust pipeline vs Python pipeline — the headline benchmark."""
        msgs = _build_realistic_history(n)
        protected = 5000

        def rust_pipeline():
            ser = serialize_messages_for_rust(msgs)
            batch = self._process(ser, [], [], "")
            self._prune(ser, 50_000)
            self._trunc(batch.per_message_tokens, protected, False)

        def python_pipeline():
            agent = self._agent
            # Token estimation (called every turn)
            for m in msgs:
                agent.estimate_tokens_for_message(m)
            # Hashing (called every turn for dedup)
            for m in msgs:
                agent.hash_message(m)
            # Pruning (called 3-4x per turn in practice!)
            agent.prune_interrupted_tool_calls(msgs)
            # Size filter + second prune
            filtered = [
                m for m in msgs if agent.estimate_tokens_for_message(m) < 50_000
            ]
            agent.prune_interrupted_tool_calls(filtered)
            # Truncation
            agent.truncation(msgs, protected)

        rs = _time_fn(rust_pipeline)

        set_rust_enabled(False)
        try:
            py = _time_fn(python_pipeline)
        finally:
            set_rust_enabled(True)

        print()
        speedup = _print_result("★ End-to-End Pipeline", n, py, rs)
        if n >= 100:
            assert speedup > 0.5, (
                f"Rust pipeline was unexpectedly {1 / speedup:.1f}x slower at {n} msgs"
            )


# ── Benchmark: Serialization Overhead ────────────────────────────────────────


class TestBenchSerializationOverhead:
    """Measure the serialize_messages_for_rust() bridge cost alone."""

    @pytest.mark.parametrize("n", SCALES)
    def test_bridge_serialization_cost(self, n: int) -> None:
        msgs = _build_realistic_history(n)

        stats = _time_fn(lambda: serialize_messages_for_rust(msgs))

        print(
            f"\n  Bridge serialize overhead   │ {n:>4d} msgs │ "
            f"{stats.median_ms:>8.3f}ms  (p5={stats.p5_ms:.3f}, p95={stats.p95_ms:.3f})"
        )
        _summary_rows.append(
            {
                "op": "Bridge Serialize Cost",
                "n": n,
                "py_ms": stats.median_ms,
                "rs_ms": 0.0,
                "speedup": 0.0,
            }
        )


# ── Summary Table (printed once at session end) ─────────────────────────────


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print the grand summary table after all benchmarks complete."""
    if not _summary_rows:
        return

    # Filter into comparison rows (with speedup) and info rows
    comparison = [
        r
        for r in _summary_rows
        if r["speedup"] > 0 and "Size" not in r["op"] and "Bridge" not in r["op"]
    ]
    sizes = [r for r in _summary_rows if "Size" in r["op"]]
    bridge = [r for r in _summary_rows if "Bridge" in r["op"]]

    terminalreporter.write_line("")
    terminalreporter.write_line("=" * 85)
    terminalreporter.write_line("                 🐕 Fast Puppy Benchmark Results 🦀")
    terminalreporter.write_line("=" * 85)
    terminalreporter.write_line(
        f"  {'Operation':<28s} │ {'Msgs':>5s} │ {'Python':>10s} │ {'Rust':>10s} │ {'Speedup':>8s}"
    )
    terminalreporter.write_line(
        "  "
        + "─" * 28
        + "─┼─"
        + "─" * 5
        + "─┼─"
        + "─" * 10
        + "─┼─"
        + "─" * 10
        + "─┼─"
        + "─" * 8
    )

    for r in comparison:
        marker = "⚡" if r["speedup"] >= 1.0 else "  "
        terminalreporter.write_line(
            f"  {r['op']:<28s} │ {r['n']:>5d} │ {r['py_ms']:>8.3f}ms │ {r['rs_ms']:>8.3f}ms │ {marker}{r['speedup']:>5.1f}x"
        )

    if sizes:
        terminalreporter.write_line("  " + "─" * 85)
        terminalreporter.write_line("  Serialized sizes (pickle vs msgpack):")
        for r in sizes:
            terminalreporter.write_line(
                f"    {r['n']:>5d} msgs │ pickle {r['py_ms']:>7.1f}KB │ msgpack {r['rs_ms']:>7.1f}KB │ {r['speedup']:.1f}x smaller"
            )

    if bridge:
        terminalreporter.write_line("  " + "─" * 85)
        terminalreporter.write_line(
            "  Bridge serialization overhead (included in Rust E2E timings):"
        )
        for r in bridge:
            terminalreporter.write_line(f"    {r['n']:>5d} msgs │ {r['py_ms']:>8.3f}ms")

    # Overall summary (only for comparison rows)
    if comparison:
        # Split into end-to-end and individual
        e2e = [r for r in comparison if "End-to-End" in r["op"]]
        individual = [r for r in comparison if "End-to-End" not in r["op"]]

        terminalreporter.write_line("  " + "─" * 85)
        if e2e:
            avg_e2e = statistics.mean(r["speedup"] for r in e2e)
            best_e2e = max(r["speedup"] for r in e2e)
            terminalreporter.write_line(
                f"  ★ End-to-End Pipeline:  avg {avg_e2e:.1f}x  │  best {best_e2e:.1f}x"
            )
        if individual:
            wins = sum(1 for r in individual if r["speedup"] >= 1.0)
            total = len(individual)
            terminalreporter.write_line(
                f"    Individual ops: Rust faster in {wins}/{total} benchmarks"
            )
        all_speedups = [r["speedup"] for r in comparison]
        terminalreporter.write_line(
            f"    Overall: avg {statistics.mean(all_speedups):.1f}x  │  "
            f"best {max(all_speedups):.1f}x  │  worst {min(all_speedups):.1f}x"
        )

    terminalreporter.write_line("=" * 85)
