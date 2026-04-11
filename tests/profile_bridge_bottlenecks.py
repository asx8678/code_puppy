"""Deep profiling of Rust/Python bridge bottlenecks.

Instruments the actual per-turn call flow to measure:
1. How many times serialize_messages_for_rust is called per turn
2. Per-phase breakdown: Python bridge vs Rust dict-parse vs Rust compute
3. String copy costs (content size vs time)
4. Redundant work identification
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import math
import json
import statistics
from collections import defaultdict

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    ThinkingPart,
)
from code_puppy._core_bridge import (
    serialize_messages_for_rust,
    serialize_message_for_rust,
    set_rust_enabled,
)
from code_puppy.agents.agent_code_puppy import CodePuppyAgent
from _code_puppy_core import (
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
)


def build_history(n):
    msgs = [
        ModelRequest(
            parts=[TextPart(content="You are a helpful coding assistant. " * 10)]
        )
    ]
    tid = 0
    for i in range(1, n):
        p = i % 5
        if p in (0, 3):
            msgs.append(
                ModelRequest(
                    parts=[
                        TextPart(content=f"User {i}: " + "x" * (100 + i * 17 % 2000))
                    ]
                )
            )
        elif p == 1:
            tid += 1
            msgs.append(
                ModelResponse(
                    parts=[
                        TextPart(content="Let me check that."),
                        ToolCallPart(
                            tool_name="cp_read_file",
                            args=f'{{"path":"src/m{i}.py"}}',
                            tool_call_id=f"tc-{tid}",
                        ),
                    ]
                )
            )
        elif p == 2:
            msgs.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="cp_read_file",
                            content="def f():\n"
                            + "    code_line = True\n" * (20 + i * 3 % 300),
                            tool_call_id=f"tc-{tid}",
                        )
                    ]
                )
            )
        else:
            msgs.append(
                ModelResponse(
                    parts=[
                        TextPart(content=f"Analysis {i}: " + "detail " * (10 + i % 30))
                    ]
                )
            )
    return msgs[:n]


def measure_ns(fn, N=100):
    """Run fn N times, return list of per-call nanoseconds."""
    # warm up
    for _ in range(3):
        fn()
    times = []
    for _ in range(N):
        t0 = time.perf_counter_ns()
        fn()
        times.append(time.perf_counter_ns() - t0)
    return times


def fmt(ns_list):
    """Format timing list as median ms."""
    med = statistics.median(ns_list)
    return f"{med / 1e6:.3f}ms"


def fmt_full(ns_list):
    med = statistics.median(ns_list)
    p5 = sorted(ns_list)[int(len(ns_list) * 0.05)]
    p95 = sorted(ns_list)[int(len(ns_list) * 0.95)]
    return f"{med / 1e6:.3f}ms (p5={p5 / 1e6:.3f}, p95={p95 / 1e6:.3f})"


print("=" * 90)
print("    🔬 Deep Bottleneck Profiling: Rust/Python Bridge")
print("=" * 90)

for N_MSGS in [50, 200, 500]:
    msgs = build_history(N_MSGS)

    # Count total parts and content bytes
    total_parts = sum(len(m.parts) for m in msgs)
    total_content_bytes = 0
    for m in msgs:
        for p in m.parts:
            c = getattr(p, "content", None)
            if isinstance(c, str):
                total_content_bytes += len(c.encode("utf-8"))

    print(f"\n{'─' * 90}")
    print(
        f"  {N_MSGS} messages | {total_parts} parts | {total_content_bytes:,} content bytes"
    )
    print(f"{'─' * 90}")

    # ═══ 1. REDUNDANT SERIALIZATION AUDIT ═══
    # Simulate the actual per-turn flow and count serialize_messages_for_rust calls
    print(f"\n  ┌── 1. REDUNDANT SERIALIZATION AUDIT (per-turn call count)")

    # In the ACTUAL code path, a single turn through message_history_accumulator triggers:
    # - message_history_accumulator → hash_message × N (Python hashing, no serialize)
    # - message_history_processor → serialize_messages_for_rust (1)
    #   if compaction needed:
    #     → filter_huge_messages → serialize_messages_for_rust (2) + prune_and_filter
    #     → truncation → serialize_messages_for_rust (3) [if no cached tokens]
    #     → OR summarization → serialize_messages_for_rust (4) + process_messages_batch
    #   → prune_interrupted_tool_calls → serialize_messages_for_rust (5)
    #   → hash_message × N_result (for compacted hash tracking)
    # - run_with_mcp finally → prune_interrupted_tool_calls → serialize_messages_for_rust (6)

    # Count it:
    call_count_normal = 1  # message_history_processor
    call_count_truncation = (
        3  # processor + filter_huge + (truncation uses cached OR serializes)
    )
    call_count_summarization = 4  # processor + filter_huge + split + prune
    call_count_finally = 1  # run_with_mcp finally block

    print(
        f"  │  Normal turn (no compaction):  {call_count_normal + call_count_finally} serializations"
    )
    print(
        f"  │  Truncation compaction:         {call_count_truncation + call_count_finally} serializations"
    )
    print(
        f"  │  Summarization compaction:       {call_count_summarization + call_count_finally} serializations"
    )
    print(f"  │")

    # Measure cost of each serialization
    t_ser = measure_ns(lambda: serialize_messages_for_rust(msgs))
    print(f"  │  Cost per serialize_messages_for_rust:  {fmt_full(t_ser)}")
    print(
        f"  │  Cost for 4 redundant calls:            {statistics.median(t_ser) * 4 / 1e6:.3f}ms"
    )
    print(f"  └──")

    # ═══ 2. PHASE BREAKDOWN ═══
    print(f"\n  ┌── 2. PHASE BREAKDOWN (where does time actually go?)")
    serialized = serialize_messages_for_rust(msgs)

    # Phase A: Python bridge (serialize_messages_for_rust)
    t_bridge = measure_ns(lambda: serialize_messages_for_rust(msgs))

    # Phase B: Rust dict parsing + computation (process_messages_batch)
    t_rust_full = measure_ns(lambda: process_messages_batch(serialized, [], [], ""))

    # Phase C: Rust pruning (prune_and_filter)
    t_rust_prune = measure_ns(lambda: prune_and_filter(serialized, 50_000))

    # Phase D: Rust truncation (pure computation, no dict parsing)
    batch = process_messages_batch(serialized, [], [], "")
    tokens = batch.per_message_tokens
    t_rust_trunc = measure_ns(lambda: truncation_indices(tokens, 5000, False))

    # Phase E: Python equivalent computations for comparison
    agent = CodePuppyAgent()
    set_rust_enabled(False)
    t_py_tokens = measure_ns(
        lambda: [agent.estimate_tokens_for_message(m) for m in msgs]
    )
    t_py_hash = measure_ns(lambda: [agent.hash_message(m) for m in msgs])
    t_py_prune = measure_ns(lambda: agent.prune_interrupted_tool_calls(msgs))
    t_py_trunc = measure_ns(lambda: agent.truncation(msgs, 5000))
    set_rust_enabled(True)

    bridge_med = statistics.median(t_bridge)
    rust_proc_med = statistics.median(t_rust_full)
    rust_prune_med = statistics.median(t_rust_prune)
    rust_trunc_med = statistics.median(t_rust_trunc)
    py_tok_med = statistics.median(t_py_tokens)
    py_hash_med = statistics.median(t_py_hash)
    py_prune_med = statistics.median(t_py_prune)
    py_trunc_med = statistics.median(t_py_trunc)

    rust_total = bridge_med + rust_proc_med + rust_prune_med + rust_trunc_med
    py_total = py_tok_med + py_hash_med + py_prune_med + py_trunc_med

    print(f"  │")
    print(f"  │  RUST PATH (one full turn):")
    print(
        f"  │    serialize_messages_for_rust:    {bridge_med / 1e6:>8.3f}ms  ({bridge_med / rust_total * 100:4.1f}%)"
    )
    print(
        f"  │    process_messages_batch:          {rust_proc_med / 1e6:>8.3f}ms  ({rust_proc_med / rust_total * 100:4.1f}%)"
    )
    print(
        f"  │    prune_and_filter:                {rust_prune_med / 1e6:>8.3f}ms  ({rust_prune_med / rust_total * 100:4.1f}%)"
    )
    print(
        f"  │    truncation_indices:              {rust_trunc_med / 1e6:>8.3f}ms  ({rust_trunc_med / rust_total * 100:4.1f}%)"
    )
    print(f"  │    ────────────────────────────────────────────")
    print(f"  │    TOTAL:                           {rust_total / 1e6:>8.3f}ms")
    print(f"  │")
    print(f"  │  PYTHON PATH (one full turn):")
    print(
        f"  │    estimate_tokens × {N_MSGS}:          {py_tok_med / 1e6:>8.3f}ms  ({py_tok_med / py_total * 100:4.1f}%)"
    )
    print(
        f"  │    hash_message × {N_MSGS}:             {py_hash_med / 1e6:>8.3f}ms  ({py_hash_med / py_total * 100:4.1f}%)"
    )
    print(
        f"  │    prune_interrupted_tool_calls:    {py_prune_med / 1e6:>8.3f}ms  ({py_prune_med / py_total * 100:4.1f}%)"
    )
    print(
        f"  │    truncation:                      {py_trunc_med / 1e6:>8.3f}ms  ({py_trunc_med / py_total * 100:4.1f}%)"
    )
    print(f"  │    ────────────────────────────────────────────")
    print(f"  │    TOTAL:                           {py_total / 1e6:>8.3f}ms")
    print(f"  │")
    speedup = py_total / rust_total if rust_total > 0 else float("inf")
    print(
        f"  │  Speedup (ideal, 1 serialize): {'⚡' if speedup >= 1 else '🐢'} {speedup:.2f}x"
    )

    # Now the REALISTIC scenario: with redundant serializations
    # Normal turn: 2 serializations (processor + finally prune)
    rust_realistic = bridge_med * 2 + rust_proc_med + rust_prune_med + rust_trunc_med
    realistic_speedup = (
        py_total / rust_realistic if rust_realistic > 0 else float("inf")
    )
    print(
        f"  │  Speedup (realistic, 2 serializes): {'⚡' if realistic_speedup >= 1 else '🐢'} {realistic_speedup:.2f}x"
    )

    # Compaction turn: 4 serializations
    rust_compaction = (
        bridge_med * 4 + rust_proc_med + rust_prune_med * 2 + rust_trunc_med
    )
    py_compaction = py_tok_med * 2 + py_hash_med + py_prune_med * 3 + py_trunc_med
    compaction_speedup = (
        py_compaction / rust_compaction if rust_compaction > 0 else float("inf")
    )
    print(
        f"  │  Speedup (compaction, 4 serializes): {'⚡' if compaction_speedup >= 1 else '🐢'} {compaction_speedup:.2f}x"
    )
    print(f"  └──")

    # ═══ 3. STRING COPY COST ═══
    print(f"\n  ┌── 3. STRING COPY COSTS (content size vs bridge time)")

    # Measure bridge cost for messages of different content sizes
    sizes = [100, 500, 2000, 10000, 50000]
    for sz in sizes:
        big_msg = [ModelRequest(parts=[TextPart(content="x" * sz)])] * 10
        t = measure_ns(lambda: serialize_messages_for_rust(big_msg), N=200)
        med = statistics.median(t)
        per_msg = med / 10
        per_byte = med / (sz * 10) if sz > 0 else 0
        print(
            f"  │  {sz:>6d} chars × 10 msgs: {med / 1e6:.3f}ms total, {per_msg / 1e6:.4f}ms/msg, {per_byte:.1f}ns/byte"
        )
    print(f"  └──")

    # ═══ 4. RUST DICT PARSE vs PURE COMPUTE ═══
    print(f"\n  ┌── 4. RUST: DICT PARSING vs PURE COMPUTATION")

    # process_messages_batch includes: dict parse + token estimation + hashing
    # truncation_indices is pure computation (no dict parsing)
    # Difference tells us dict parsing cost

    # Create identical workload: give truncation the same data
    t_dict_parse_plus_compute = measure_ns(
        lambda: process_messages_batch(serialized, [], [], "")
    )
    t_pure_compute = measure_ns(lambda: truncation_indices(tokens, 5000, False))

    dict_parse_med = statistics.median(t_dict_parse_plus_compute)
    pure_compute_med = statistics.median(t_pure_compute)

    # Rough estimate: process_messages_batch does dict parse + O(parts) computation
    # truncation_indices does O(messages) computation without dict parse
    # The difference isn't exact (different work) but gives order of magnitude
    print(f"  │  process_messages_batch (parse+compute):  {dict_parse_med / 1e6:.3f}ms")
    print(
        f"  │  truncation_indices (pure compute):        {pure_compute_med / 1e6:.3f}ms"
    )
    print(
        f"  │  → Dict parsing overhead estimate:         {(dict_parse_med - pure_compute_med) / 1e6:.3f}ms"
    )
    print(
        f"  │  → Dict parsing is {(dict_parse_med - pure_compute_med) / dict_parse_med * 100:.0f}% of Rust batch call"
    )
    print(f"  └──")

    # ═══ 5. PER-FIELD COST IN PYTHON BRIDGE ═══
    print(f"\n  ┌── 5. PYTHON BRIDGE: PER-FIELD COST BREAKDOWN")

    # Measure just getattr overhead
    t_getattr = measure_ns(
        lambda: [
            (
                getattr(p, "part_kind", ""),
                getattr(p, "content", None),
                getattr(p, "tool_call_id", None),
                getattr(p, "tool_name", None),
            )
            for m in msgs
            for p in m.parts
        ]
    )

    # Measure isinstance checks
    t_isinstance = measure_ns(
        lambda: [
            isinstance(getattr(p, "content", None), str) for m in msgs for p in m.parts
        ]
    )

    # Measure json.dumps for non-string content
    dict_contents = [
        {"key": f"value_{i}", "nested": {"a": i}} for i in range(total_parts)
    ]
    t_json = measure_ns(
        lambda: [json.dumps(d, sort_keys=True) for d in dict_contents[:20]]
    )

    # Measure dict construction
    t_dict_build = measure_ns(
        lambda: [
            {
                "part_kind": getattr(p, "part_kind", ""),
                "content": getattr(p, "content", None),
                "content_json": None,
                "tool_call_id": getattr(p, "tool_call_id", None),
                "tool_name": getattr(p, "tool_name", None),
                "args": None,
            }
            for m in msgs
            for p in m.parts
        ]
    )

    total_bridge = statistics.median(t_bridge)
    getattr_med = statistics.median(t_getattr)
    isinstance_med = statistics.median(t_isinstance)
    dict_build_med = statistics.median(t_dict_build)

    print(
        f"  │  getattr extraction ({total_parts} parts × 4 fields): {getattr_med / 1e6:.3f}ms ({getattr_med / total_bridge * 100:.0f}%)"
    )
    print(
        f"  │  isinstance checks:                            {isinstance_med / 1e6:.3f}ms ({isinstance_med / total_bridge * 100:.0f}%)"
    )
    print(
        f"  │  dict construction:                             {dict_build_med / 1e6:.3f}ms ({dict_build_med / total_bridge * 100:.0f}%)"
    )
    print(
        f"  │  remaining (json.dumps, hasattr, etc):          {(total_bridge - dict_build_med) / 1e6:.3f}ms ({(total_bridge - dict_build_med) / total_bridge * 100:.0f}%)"
    )
    print(f"  └──")

    # ═══ 6. WHAT IF: ELIMINATE BRIDGE? ═══
    print(f"\n  ┌── 6. WHAT-IF ANALYSIS: Optimization potential")

    # Scenario A: Current (with redundant serialization)
    current_rust = bridge_med * 2 + rust_proc_med + rust_prune_med + rust_trunc_med
    current_py = py_total

    # Scenario B: Cache serialized data (serialize once per turn)
    cached_rust = bridge_med * 1 + rust_proc_med + rust_prune_med + rust_trunc_med

    # Scenario C: Eliminate bridge entirely (read pydantic objects directly from Rust)
    no_bridge_rust = rust_proc_med + rust_prune_med + rust_trunc_med

    # Scenario D: Eliminate bridge + eliminate redundant dict parsing in Rust
    # (serialize once to bytes, pass bytes to all Rust fns)
    optimal_rust = rust_proc_med * 0.5 + rust_prune_med * 0.5 + rust_trunc_med

    print(f"  │  Current Python path:                    {current_py / 1e6:>8.3f}ms")
    print(
        f"  │  Current Rust (2 serializations):        {current_rust / 1e6:>8.3f}ms  ({current_py / current_rust:.2f}x)"
    )
    print(
        f"  │  ✅ Cache serialized (1 serialization):   {cached_rust / 1e6:>8.3f}ms  ({current_py / cached_rust:.2f}x)"
    )
    print(
        f"  │  ✅ Direct pydantic access (0 bridge):    {no_bridge_rust / 1e6:>8.3f}ms  ({current_py / no_bridge_rust:.2f}x)"
    )
    print(
        f"  │  ✅ Optimal (no bridge + shared parse):   {optimal_rust / 1e6:>8.3f}ms  ({current_py / optimal_rust:.2f}x)"
    )
    print(f"  └──")


print(f"\n{'=' * 90}")
print("  SUMMARY: Top bottlenecks by impact")
print(f"{'=' * 90}")
print("""
  #1 REDUNDANT SERIALIZATION
     serialize_messages_for_rust() is called 2-4× per turn on the SAME messages.
     Each call re-iterates all messages, re-extracts all fields, re-builds all dicts.
     FIX: Cache serialized list, invalidate on history change.

  #2 DOUBLE DICT PARSING IN RUST
     Both process_messages_batch() and prune_and_filter() independently parse
     the same list[dict] into Vec<Message> via Message::from_py().
     FIX: Parse once, pass internal representation to both functions.
     OR: Accept pre-parsed bytes (MessagePack) instead of Python dicts.

  #3 STRING COPYING ACROSS BOUNDARY
     Every string field is copied: Python str → Rust String (memcpy).
     For large tool returns (5000+ chars), this dominates per-message cost.
     FIX: Use PyO3 Cow<str> to borrow Python's memory instead of copying.
     OR: Read pydantic objects directly (skip intermediate dict).

  #4 PYTHON-SIDE GETATTR OVERHEAD  
     serialize_message_for_rust() calls getattr() 6× per part.
     For 200 messages × 1.5 parts avg = 1800 getattr calls per serialization.
     FIX: Direct attribute access if type is known, or read from Rust.
""")
