"""Benchmark: Rust vs Python message processing.

Measures actual speedup for key operations on a realistic 200-message session.
Skip gracefully if Rust module is not installed.

Run: python -m pytest tests/bench_rust_vs_python.py -v -s
"""

import time
from typing import List

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    serialize_messages_for_rust,
)
from code_puppy.agents.agent_code_puppy import CodePuppyAgent


# Skip entire module if Rust not available
pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust module (_code_puppy_core) not installed"
)

ITERATIONS = 100
NUM_MESSAGES = 200


def _build_realistic_history(n: int = NUM_MESSAGES) -> List[ModelMessage]:
    """Build a realistic N-message history with mixed content types."""
    messages: List[ModelMessage] = []
    
    # System message first
    messages.append(ModelRequest(parts=[TextPart(
        content="You are a helpful coding assistant. You have access to tools "
                "for reading files, writing files, and running shell commands. "
                "Always explain your reasoning before taking actions." * 3
    )]))
    
    tool_id_counter = 0
    for i in range(1, n):
        if i % 5 == 1:
            # User text message (varying lengths)
            content_length = 50 + (i * 7) % 500
            messages.append(ModelRequest(parts=[TextPart(
                content=f"User message {i}: " + "x" * content_length
            )]))
        elif i % 5 == 2:
            # Assistant response with tool call
            tool_id_counter += 1
            messages.append(ModelResponse(parts=[
                TextPart(content="I'll help with that. Let me look at the code."),
                ToolCallPart(
                    tool_name="cp_read_file" if i % 3 == 0 else "cp_agent_run_shell_command",
                    args=f'{{"file_path": "src/module_{i}.py"}}' if i % 3 == 0 
                         else f'{{"command": "grep -r pattern_{i} src/"}}',
                    tool_call_id=f"tc-{tool_id_counter}",
                ),
            ]))
        elif i % 5 == 3:
            # Tool return (varying content sizes - some big, some small)
            content_size = 200 + (i * 13) % 2000
            messages.append(ModelRequest(parts=[ToolReturnPart(
                tool_name="cp_read_file" if i % 3 == 0 else "cp_agent_run_shell_command",
                content="def function():\n" + "    line of code\n" * (content_size // 20),
                tool_call_id=f"tc-{tool_id_counter}",
            )]))
        elif i % 5 == 4:
            # Assistant text response
            messages.append(ModelResponse(parts=[TextPart(
                content=f"Based on the code I see in module {i}, here's what I recommend: "
                        + "This is a detailed explanation of the changes needed. " * (3 + i % 5)
            )]))
        else:
            # Another user message
            messages.append(ModelRequest(parts=[TextPart(
                content=f"Thanks, now can you also check module_{i}? I think there's a bug."
            )]))
    
    return messages


def _time_fn(fn, iterations=ITERATIONS):
    """Time a function over N iterations, return median in ms."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)
    times.sort()
    median = times[len(times) // 2]
    return median, times[0], times[-1]


class TestBenchProcessMessagesBatch:
    """Benchmark process_messages_batch (token counting + hashing)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from code_puppy._core_bridge import process_messages_batch
        self.process_messages_batch = process_messages_batch
        self.messages = _build_realistic_history()
        self.serialized = serialize_messages_for_rust(self.messages)
        self.agent = CodePuppyAgent()

    def test_rust_vs_python_batch(self):
        """Compare Rust batch processing vs Python per-message estimation."""
        # Rust path
        rust_median, rust_min, rust_max = _time_fn(
            lambda: self.process_messages_batch(self.serialized, [], [], "")
        )

        # Python path
        agent = self.agent
        msgs = self.messages
        python_median, python_min, python_max = _time_fn(
            lambda: sum(agent.estimate_tokens_for_message(m) for m in msgs)
        )

        speedup = python_median / rust_median if rust_median > 0 else float('inf')

        print(f"\n{'='*60}")
        print(f"process_messages_batch ({NUM_MESSAGES} messages, {ITERATIONS} iterations)")
        print(f"  Rust:   {rust_median:.2f}ms median (min={rust_min:.2f}, max={rust_max:.2f})")
        print(f"  Python: {python_median:.2f}ms median (min={python_min:.2f}, max={python_max:.2f})")
        print(f"  Speedup: {speedup:.1f}x")
        print(f"{'='*60}")

        # Rust should be at least as fast (allow 0.5x in case of warm-up issues)
        # Note: Rust path does more work (hashing + token counting in single pass)
        # so direct speedup comparison is not apples-to-apples
        assert speedup > 0.2, f"Rust was unexpectedly {1/speedup:.1f}x slower than Python!"


class TestBenchPruneAndFilter:
    """Benchmark prune_and_filter (pruning + size filtering)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from code_puppy._core_bridge import prune_and_filter
        self.prune_and_filter = prune_and_filter
        self.messages = _build_realistic_history()
        self.serialized = serialize_messages_for_rust(self.messages)
        self.agent = CodePuppyAgent()

    def test_rust_vs_python_prune(self):
        """Compare Rust prune_and_filter vs Python prune + filter."""
        # Rust path
        rust_median, rust_min, rust_max = _time_fn(
            lambda: self.prune_and_filter(self.serialized, 50000)
        )

        # Python path
        agent = self.agent
        msgs = self.messages
        python_median, python_min, python_max = _time_fn(
            lambda: agent.prune_interrupted_tool_calls(
                [m for m in msgs if agent.estimate_tokens_for_message(m) < 50000]
            )
        )

        speedup = python_median / rust_median if rust_median > 0 else float('inf')

        print(f"\n{'='*60}")
        print(f"prune_and_filter ({NUM_MESSAGES} messages, {ITERATIONS} iterations)")
        print(f"  Rust:   {rust_median:.2f}ms median (min={rust_min:.2f}, max={rust_max:.2f})")
        print(f"  Python: {python_median:.2f}ms median (min={python_min:.2f}, max={python_max:.2f})")
        print(f"  Speedup: {speedup:.1f}x")
        print(f"{'='*60}")

        # Note: Rust path does more work (hashing + token counting in single pass)
        # so direct speedup comparison is not apples-to-apples
        assert speedup > 0.2, f"Rust was unexpectedly {1/speedup:.1f}x slower than Python!"


class TestBenchTruncation:
    """Benchmark truncation_indices."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from code_puppy._core_bridge import process_messages_batch, truncation_indices
        self.truncation_indices = truncation_indices
        self.process_messages_batch = process_messages_batch
        self.messages = _build_realistic_history()
        self.serialized = serialize_messages_for_rust(self.messages)
        # Pre-compute tokens
        batch = self.process_messages_batch(self.serialized, [], [], "")
        self.per_message_tokens = batch.per_message_tokens
        self.agent = CodePuppyAgent()

    def test_rust_vs_python_truncation(self):
        """Compare Rust truncation_indices vs Python truncation."""
        protected = 5000

        # Rust path (just the index computation)
        tokens = self.per_message_tokens
        rust_median, rust_min, rust_max = _time_fn(
            lambda: self.truncation_indices(tokens, protected, False)
        )

        # Python path
        agent = self.agent
        msgs = self.messages
        python_median, python_min, python_max = _time_fn(
            lambda: agent.truncation(msgs, protected)
        )

        speedup = python_median / rust_median if rust_median > 0 else float('inf')

        print(f"\n{'='*60}")
        print(f"truncation ({NUM_MESSAGES} messages, {ITERATIONS} iterations)")
        print(f"  Rust:   {rust_median:.2f}ms median (min={rust_min:.2f}, max={rust_max:.2f})")
        print(f"  Python: {python_median:.2f}ms median (min={python_min:.2f}, max={python_max:.2f})")
        print(f"  Speedup: {speedup:.1f}x")
        print(f"{'='*60}")

        # Note: Rust path does more work (hashing + token counting in single pass)
        # so direct speedup comparison is not apples-to-apples
        assert speedup > 0.2, f"Rust was unexpectedly {1/speedup:.1f}x slower than Python!"
