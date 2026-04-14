#!/usr/bin/env python3
"""Benchmark Zig vs Rust acceleration modules.

FAIRNESS NOTE: Both benchmarks pre-serialize message data OUTSIDE the timing loop
to measure only the native code processing time, not Python JSON serialization.
- Rust: Uses serialize_messages_for_rust() outside loop
- Zig: Uses json.dumps().encode() outside loop, calls cffi directly
"""

import time
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_test_messages(count: int, parts_per_message: int = 3) -> list[dict]:
    """Generate test message data matching the bridge format."""
    messages = []
    for i in range(count):
        parts = []
        for j in range(parts_per_message):
            parts.append({
                "part_kind": "text" if j % 2 == 0 else "tool-call",
                "content": f"This is message {i} part {j} with some content. " * 10,
                "content_json": None,
                "tool_call_id": f"call_{i}_{j}" if j % 2 == 1 else None,
                "tool_name": f"tool_{j}" if j % 2 == 1 else None,
                "args": '{"arg": "value"}' if j % 2 == 1 else None,
            })
        messages.append({
            "kind": "request" if i % 2 == 0 else "response",
            "role": "user" if i % 2 == 0 else "assistant",
            "instructions": None,
            "parts": parts,
        })
    return messages


def bench_rust():
    """Benchmark Rust acceleration."""
    try:
        from code_puppy._core_bridge import (
            RUST_AVAILABLE,
            process_messages_batch as rust_batch,
            serialize_messages_for_rust,
        )
        if not RUST_AVAILABLE:
            return None, "Rust not available"
        
        messages = generate_test_messages(200, 5)
        serialized = serialize_messages_for_rust(messages)
        
        # Warm up
        for _ in range(5):
            rust_batch(serialized, [], [], "System prompt here")
        
        # Benchmark
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            rust_batch(serialized, [], [], "System prompt here")
        elapsed = time.perf_counter() - start
        
        return elapsed / iterations * 1000, None  # ms per iteration
        
    except Exception as e:
        return None, str(e)


def bench_zig():
    """Benchmark Zig JSON acceleration with pre-serialized data (fair comparison)."""
    try:
        from code_puppy.zig_bridge import ZIG_AVAILABLE
        if not ZIG_AVAILABLE:
            return None, "Zig not available"
        
        # Import cffi internals for low-level access
        from code_puppy.zig_bridge import _ffi, _lib_puppy_core, _get_puppy_core_handle
        
        messages = generate_test_messages(200, 5)
        # PRE-SERIALIZE outside timing loop (fair comparison with Rust)
        encoded = json.dumps(messages).encode()
        sys_prompt = b"System prompt here"
        
        h = _get_puppy_core_handle()
        if h is None:
            return None, "Failed to get puppy_core handle"
        
        # Warm up (using pre-serialized data)
        for _ in range(5):
            out = _ffi.new('char**')
            rc = _lib_puppy_core.puppy_core_process_messages(h, encoded, sys_prompt, out)
            if rc == 0 and out[0] != _ffi.NULL:
                _lib_puppy_core.puppy_core_free_string(out[0])
        
        # Benchmark (pre-serialized data, no json.dumps in loop)
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            out = _ffi.new('char**')
            rc = _lib_puppy_core.puppy_core_process_messages(h, encoded, sys_prompt, out)
            if rc == 0 and out[0] != _ffi.NULL:
                _lib_puppy_core.puppy_core_free_string(out[0])
        elapsed = time.perf_counter() - start
        
        return elapsed / iterations * 1000, None  # ms per iteration
        
    except Exception as e:
        return None, str(e)


def bench_zig_binary():
    """Benchmark Zig binary protocol acceleration."""
    try:
        from code_puppy.zig_bridge import (
            ZIG_AVAILABLE,
            process_messages_batch_binary as zig_binary_batch,
        )
        if not ZIG_AVAILABLE:
            return None, "Zig not available"
        
        messages = generate_test_messages(200, 5)
        
        # Warm up
        for _ in range(5):
            zig_binary_batch(messages, "System prompt here")
        
        # Benchmark
        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            zig_binary_batch(messages, "System prompt here")
        elapsed = time.perf_counter() - start
        
        return elapsed / iterations * 1000, None  # ms per iteration
        
    except Exception as e:
        return None, str(e)


def bench_python():
    """Benchmark pure Python implementation."""
    messages = generate_test_messages(200, 5)
    
    def estimate_tokens(text: str) -> int:
        return max(1, int(len(text) / 4.0))
    
    def process_batch(msgs: list) -> dict:
        total = 0
        per_message = []
        for msg in msgs:
            msg_tokens = 0
            for part in msg.get("parts", []):
                content = part.get("content") or part.get("content_json") or ""
                msg_tokens += estimate_tokens(content)
            per_message.append(msg_tokens)
            total += msg_tokens
        return {"total": total, "per_message": per_message}
    
    # Warm up
    for _ in range(5):
        process_batch(messages)
    
    # Benchmark
    start = time.perf_counter()
    iterations = 100
    for _ in range(iterations):
        process_batch(messages)
    elapsed = time.perf_counter() - start
    
    return elapsed / iterations * 1000, None  # ms per iteration


def main():
    print("=" * 60)
    print("Zig vs Rust vs Python Benchmark")
    print("=" * 60)
    print(f"Test: process_messages_batch with 200 messages × 5 parts")
    print(f"Iterations: 100")
    print()
    
    results = {}
    
    # Python baseline
    py_time, py_err = bench_python()
    if py_err:
        print(f"Python:      ERROR - {py_err}")
    else:
        print(f"Python:      {py_time:7.3f} ms/iter (baseline)")
        results["python"] = py_time
    
    # Rust
    rust_time, rust_err = bench_rust()
    if rust_err:
        print(f"Rust:        ERROR - {rust_err}")
    else:
        speedup = py_time / rust_time if py_time else 0
        print(f"Rust:        {rust_time:7.3f} ms/iter ({speedup:.1f}x vs Python)")
        results["rust"] = rust_time
    
    # Zig JSON
    zig_time, zig_err = bench_zig()
    if zig_err:
        print(f"Zig (JSON):  ERROR - {zig_err}")
    else:
        speedup_py = py_time / zig_time if py_time else 0
        speedup_rust = rust_time / zig_time if rust_time else 0
        print(f"Zig (JSON):  {zig_time:7.3f} ms/iter ({speedup_py:.1f}x vs Python, {speedup_rust:.1f}x vs Rust)")
        results["zig_json"] = zig_time
    
    # Zig Binary
    zig_bin_time, zig_bin_err = bench_zig_binary()
    if zig_bin_err:
        print(f"Zig (Binary): ERROR - {zig_bin_err}")
    else:
        speedup_py = py_time / zig_bin_time if py_time else 0
        speedup_rust = rust_time / zig_bin_time if rust_time else 0
        speedup_json = zig_time / zig_bin_time if zig_time else 0
        print(f"Zig (Binary): {zig_bin_time:7.3f} ms/iter ({speedup_py:.1f}x vs Python, {speedup_rust:.1f}x vs Rust, {speedup_json:.1f}x vs Zig JSON)")
        results["zig_binary"] = zig_bin_time
    
    print()
    print("=" * 60)
    
    # Find fastest implementation
    if results:
        fastest = min(results, key=results.get)
        fastest_time = results[fastest]
        print(f"🏆 Winner: {fastest.upper()} at {fastest_time:.3f} ms/iter")
        
        # Compare Zig implementations
        if "zig_json" in results and "zig_binary" in results:
            if results["zig_binary"] < results["zig_json"]:
                print(f"✅ Zig Binary is {results['zig_json']/results['zig_binary']:.1f}x faster than Zig JSON")
            else:
                print(f"⚠️  Zig Binary is {results['zig_binary']/results['zig_json']:.1f}x slower than Zig JSON")
        
        # Compare Zig vs Rust
        if "zig_binary" in results and "rust" in results:
            if results["zig_binary"] < results["rust"]:
                print(f"✅ Zig Binary is {results['rust']/results['zig_binary']:.1f}x FASTER than Rust")
            else:
                print(f"⚠️  Zig Binary is {results['zig_binary']/results['rust']:.1f}x slower than Rust")
    
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
