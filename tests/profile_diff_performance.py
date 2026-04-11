#!/usr/bin/env python3
from collections.abc import Callable
"""Profile diff generation performance to determine if Rust acceleration is needed.

This measures:
1. difflib.unified_diff performance at various file sizes
2. Time breakdown: splitlines vs diff computation vs join
3. Real-world scenarios (small edits, large rewrites)

Decision criteria:
- If typical diffs take >100ms, consider Rust acceleration
- If <10ms, not worth optimizing
"""

import difflib
import time
import random
import string


def generate_code_file(num_lines: int, line_length: int = 80) -> str:
    """Generate realistic-looking Python code."""
    lines = []
    indent = 0
    for i in range(num_lines):
        if random.random() < 0.1:  # 10% chance of class/function
            indent = 0
            if random.random() < 0.5:
                lines.append(f"def function_{i}(arg1, arg2):")
            else:
                lines.append(f"class Class{i}:")
            indent = 4
        elif random.random() < 0.05:  # 5% chance of dedent
            indent = max(0, indent - 4)
            lines.append(" " * indent + "return result")
        else:
            # Regular code line
            content_len = line_length - indent - 1
            content = ''.join(random.choices(string.ascii_lowercase + ' ', k=content_len))
            lines.append(" " * indent + f"# {content}")
    return "\n".join(lines)


def apply_small_edit(content: str, num_edits: int = 3) -> str:
    """Apply small scattered edits (typical LLM behavior)."""
    lines = content.splitlines()
    for _ in range(num_edits):
        if lines:
            idx = random.randint(0, len(lines) - 1)
            lines[idx] = lines[idx] + " # edited"
    return "\n".join(lines)


def apply_block_rewrite(content: str, block_size: int = 50) -> str:
    """Rewrite a contiguous block (function rewrite)."""
    lines = content.splitlines()
    if len(lines) > block_size:
        start = random.randint(0, len(lines) - block_size)
        for i in range(start, start + block_size):
            lines[i] = f"    # rewritten line {i}"
    return "\n".join(lines)


def apply_large_rewrite(content: str, fraction: float = 0.5) -> str:
    """Rewrite a large fraction of the file."""
    lines = content.splitlines()
    num_to_change = int(len(lines) * fraction)
    indices = random.sample(range(len(lines)), min(num_to_change, len(lines)))
    for idx in indices:
        lines[idx] = f"    # completely rewritten {idx}"
    return "\n".join(lines)


def measure_diff(old: str, new: str, context_lines: int = 3) -> dict:
    """Measure diff generation time with breakdown."""
    # Phase 1: splitlines
    t0 = time.perf_counter()
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    t_split = time.perf_counter() - t0
    
    # Phase 2: unified_diff (returns generator)
    t0 = time.perf_counter()
    diff_gen = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="a/file.py", tofile="b/file.py",
        n=context_lines
    )
    t_diff_setup = time.perf_counter() - t0
    
    # Phase 3: materialize (join)
    t0 = time.perf_counter()
    diff_text = "".join(diff_gen)
    t_join = time.perf_counter() - t0
    
    return {
        "split_ms": t_split * 1000,
        "diff_setup_ms": t_diff_setup * 1000,
        "join_ms": t_join * 1000,
        "total_ms": (t_split + t_diff_setup + t_join) * 1000,
        "diff_lines": len(diff_text.splitlines()),
        "old_lines": len(old_lines),
        "new_lines": len(new_lines),
    }


def run_benchmark(name: str, old: str, new: str, iterations: int = 10) -> dict:
    """Run multiple iterations and return statistics."""
    results = []
    for _ in range(iterations):
        results.append(measure_diff(old, new))
    
    totals = [r["total_ms"] for r in results]
    avg_total = sum(totals) / len(totals)
    min_total = min(totals)
    max_total = max(totals)
    
    return {
        "name": name,
        "avg_ms": avg_total,
        "min_ms": min_total,
        "max_ms": max_total,
        "avg_breakdown": {
            "split_ms": sum(r["split_ms"] for r in results) / len(results),
            "diff_setup_ms": sum(r["diff_setup_ms"] for r in results) / len(results),
            "join_ms": sum(r["join_ms"] for r in results) / len(results),
        },
        "diff_lines": results[0]["diff_lines"],
        "file_lines": results[0]["old_lines"],
    }


def main():
    print("=" * 70)
    print("  DIFF PERFORMANCE PROFILER")
    print("  Decision criteria: >100ms = consider Rust, <10ms = skip")
    print("=" * 70)
    
    scenarios = []
    
    # Small file scenarios
    for size in [100, 500, 1000]:
        content = generate_code_file(size)
        
        # Small edit
        edited = apply_small_edit(content, num_edits=3)
        result = run_benchmark(f"{size} lines, 3 small edits", content, edited)
        scenarios.append(result)
        
        # Block rewrite
        rewritten = apply_block_rewrite(content, block_size=min(50, size // 2))
        result = run_benchmark(f"{size} lines, 50-line block rewrite", content, rewritten)
        scenarios.append(result)
    
    # Large file scenarios (where we might see >100ms)
    for size in [5000, 10000, 20000]:
        content = generate_code_file(size)
        
        # Small edit on large file
        edited = apply_small_edit(content, num_edits=5)
        result = run_benchmark(f"{size} lines, 5 small edits", content, edited)
        scenarios.append(result)
        
        # Large rewrite (50% of file)
        rewritten = apply_large_rewrite(content, fraction=0.5)
        result = run_benchmark(f"{size} lines, 50% rewrite", content, rewritten)
        scenarios.append(result)
    
    # Print results
    print(f"\n{'Scenario':<45} {'Avg ms':>10} {'Min ms':>10} {'Max ms':>10} {'Lines':>8}")
    print("-" * 90)
    
    needs_optimization = False
    for s in scenarios:
        flag = " ⚠️" if s["avg_ms"] > 100 else ""
        print(f"{s['name']:<45} {s['avg_ms']:>10.2f} {s['min_ms']:>10.2f} {s['max_ms']:>10.2f} {s['file_lines']:>8}{flag}")
        if s["avg_ms"] > 100:
            needs_optimization = True
    
    print("\n" + "=" * 70)
    print("  BREAKDOWN (average across all scenarios)")
    print("=" * 70)
    
    avg_split = sum(s["avg_breakdown"]["split_ms"] for s in scenarios) / len(scenarios)
    avg_diff = sum(s["avg_breakdown"]["diff_setup_ms"] for s in scenarios) / len(scenarios)
    avg_join = sum(s["avg_breakdown"]["join_ms"] for s in scenarios) / len(scenarios)
    total = avg_split + avg_diff + avg_join
    
    print(f"  splitlines():     {avg_split:>8.3f}ms ({avg_split/total*100:>5.1f}%)")
    print(f"  unified_diff():   {avg_diff:>8.3f}ms ({avg_diff/total*100:>5.1f}%)")
    print(f"  join():           {avg_join:>8.3f}ms ({avg_join/total*100:>5.1f}%)")
    
    print("\n" + "=" * 70)
    print("  RECOMMENDATION")
    print("=" * 70)
    
    if needs_optimization:
        print("  ⚠️  Some scenarios exceed 100ms threshold")
        print("  →  Rust acceleration MAY be beneficial for large file diffs")
        print("  →  Proceed to Task 3.2: Implement Rust diff in turbo_ops")
    else:
        print("  ✅  All scenarios under 100ms threshold")
        print("  →  difflib.unified_diff performance is acceptable")
        print("  →  Skip Task 3.2 - no Rust diff needed")


if __name__ == "__main__":
    main()
