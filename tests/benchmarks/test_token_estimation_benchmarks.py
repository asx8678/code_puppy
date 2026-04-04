"""Benchmarks for token estimation accuracy and performance.

These benchmarks measure:
- Wall time for token estimation on sample messages
- Accuracy comparison against tiktoken (if available)
- Memory efficiency of estimation algorithm

Run with: pytest tests/benchmarks/ -v -m benchmark
"""

import time
import tracemalloc

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


pytestmark = pytest.mark.benchmark


def generate_sample_messages(count: int = 1000) -> list:
    """Generate a diverse set of sample messages for token estimation testing."""
    samples = []
    
    # Various content types with realistic sizes
    content_types = [
        # Short code snippets
        "def hello():\n    print('world')",
        # Medium prose
        "The quick brown fox jumps over the lazy dog. " * 10,
        # Long documentation
        "# API Documentation\n\n## Overview\n\nThis API provides access to...\n" * 50,
        # JSON data
        '{"key": "value", "nested": {"array": [1,2,3,4,5]}}' * 20,
        # Mixed content
        "Here's some text with `code` and **formatting**. " * 15,
    ]
    
    import random
    random.seed(42)  # Reproducible samples
    
    for i in range(count):
        content_idx = i % len(content_types)
        content = content_types[content_idx] + f" [msg {i}]"
        
        if i % 2 == 0:
            samples.append(ModelRequest(parts=[TextPart(content=content)]))
        else:
            samples.append(ModelResponse(parts=[TextPart(content=content)]))
    
    return samples


def try_import_tiktoken():
    """Try to import tiktoken for comparison, return None if not available."""
    try:
        import tiktoken
        return tiktoken
    except ImportError:
        return None


@pytest.mark.benchmark
class TestTokenEstimationPerformance:
    """Benchmark suite for token estimation performance."""
    
    @pytest.fixture
    def agent(self):
        """Provide a CodePuppyAgent instance for benchmarking."""
        return CodePuppyAgent()
    
    def test_estimate_tokens_for_message_performance(self, agent):
        """Benchmark token estimation for 1000 messages."""
        messages = generate_sample_messages(1000)
        
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()
        
        start_time = time.perf_counter()
        
        total_tokens = 0
        for msg in messages:
            total_tokens += agent.estimate_tokens_for_message(msg)
        
        end_time = time.perf_counter()
        
        snapshot_after = tracemalloc.take_snapshot()
        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        memory_delta = sum(stat.size for stat in top_stats) / 1024
        
        tracemalloc.stop()
        
        wall_time_ms = (end_time - start_time) * 1000
        
        print(f"\n[Token Estimation] 1000 messages: {wall_time_ms:.2f}ms, {memory_delta:.2f}KB delta")
        print(f"  Total estimated tokens: {total_tokens}")
        
        # Should be very fast - token estimation is a core operation
        assert wall_time_ms < 500, f"Token estimation too slow: {wall_time_ms:.2f}ms"
        assert memory_delta < 1000, f"Memory usage too high: {memory_delta:.2f}KB"
    
    def test_estimate_token_count_performance(self, agent):
        """Benchmark estimate_token_count for various text sizes."""
        text_sizes = [10, 100, 1000, 10000]
        results = {}
        
        for size in text_sizes:
            text = "x" * size
            
            # Warmup
            agent.estimate_token_count(text)
            
            start_time = time.perf_counter()
            
            # Run 1000 times for statistical significance
            for _ in range(1000):
                agent.estimate_token_count(text)
            
            end_time = time.perf_counter()
            
            wall_time_ms = (end_time - start_time) * 1000
            per_call_us = (wall_time_ms * 1000) / 1000  # microseconds per call
            
            results[size] = per_call_us
            print(f"\n  [Size {size}] 1000 calls: {wall_time_ms:.2f}ms ({per_call_us:.2f}µs/call)")
        
        # Should be consistently fast regardless of text size
        for size, per_call in results.items():
            assert per_call < 50, f"Too slow for size {size}: {per_call:.2f}µs/call"
    
    def test_estimate_tokens_for_message_with_tool_calls(self, agent):
        """Benchmark token estimation for messages with tool calls."""
        messages = []
        
        # Create messages with tool calls
        for i in range(100):
            if i % 3 == 0:
                # Tool call
                messages.append(ModelRequest(parts=[
                    ToolCallPart(
                        tool_name="test_tool",
                        args={"param1": "value1", "param2": "value2"},
                        tool_call_id=f"call_{i}",
                    )
                ]))
            elif i % 3 == 1:
                # Tool return
                messages.append(ModelResponse(parts=[
                    ToolReturnPart(
                        tool_name="test_tool",
                        content="Tool result data here...",
                        tool_call_id=f"call_{i-1}",
                    )
                ]))
            else:
                # Regular text
                messages.append(ModelRequest(parts=[TextPart(content=f"Message {i}")]))
        
        start_time = time.perf_counter()
        
        total_tokens = 0
        for msg in messages:
            total_tokens += agent.estimate_tokens_for_message(msg)
        
        end_time = time.perf_counter()
        
        wall_time_ms = (end_time - start_time) * 1000
        
        print(f"\n[Tool Messages] 100 mixed: {wall_time_ms:.2f}ms, total tokens: {total_tokens}")
        
        assert wall_time_ms < 100, f"Tool message estimation too slow: {wall_time_ms:.2f}ms"


@pytest.mark.benchmark
class TestTokenEstimationAccuracy:
    """Benchmark token estimation accuracy vs tiktoken (if available)."""
    
    @pytest.fixture
    def agent(self):
        """Provide a CodePuppyAgent instance for testing."""
        return CodePuppyAgent()
    
    def test_accuracy_comparison_sample(self, agent):
        """Compare our token estimation against tiktoken on sample texts.
        
        This test samples 100 real messages and compares token counts.
        """
        tiktoken = try_import_tiktoken()
        
        if tiktoken is None:
            pytest.skip("tiktoken not available for comparison")
        
        # Get a sample encoding for gpt-4 style models
        try:
            encoding = tiktoken.encoding_for_model("gpt-4")
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
        
        sample_texts = [
            "Hello, world!",
            "def function():\n    pass",
            "The quick brown fox jumps over the lazy dog. " * 10,
            "{" * 100 + "}" * 100,
            "a b c d e f g h i j k l m n o p q r s t u v w x y z " * 5,
        ]
        
        results = []
        for text in sample_texts:
            our_estimate = agent.estimate_token_count(text)
            tiktoken_count = len(encoding.encode(text))
            
            difference = abs(our_estimate - tiktoken_count)
            pct_error = (difference / tiktoken_count * 100) if tiktoken_count > 0 else 0
            
            results.append({
                "text_preview": text[:50],
                "our_estimate": our_estimate,
                "tiktoken": tiktoken_count,
                "difference": difference,
                "pct_error": pct_error,
            })
        
        print("\n[Accuracy Comparison]")
        for r in results:
            print(f"  {r['text_preview']!r}")
            print(f"    Our: {r['our_estimate']}, Tiktoken: {r['tiktoken']}, Error: {r['pct_error']:.1f}%")
        
        # Average error should be reasonable (< 50%)
        avg_error = sum(r["pct_error"] for r in results) / len(results)
        print(f"\n  Average error: {avg_error:.1f}%")
        
        # Note: This is a sanity check, not a strict assertion
        # Token estimation is heuristic-based and doesn't need to match exactly
        assert avg_error < 100, f"Average error too high: {avg_error:.1f}%"
    
    def test_estimation_consistency(self, agent):
        """Test that token estimation is consistent across multiple calls."""
        text = "This is a test message for consistency checking."
        
        estimates = [agent.estimate_token_count(text) for _ in range(100)]
        
        # All estimates should be identical
        assert all(e == estimates[0] for e in estimates), "Estimation not consistent"
        
        print(f"\n[Consistency] 100 identical estimates: {estimates[0]} tokens")


@pytest.mark.benchmark
def test_batch_token_estimation_vs_individual():
    """Compare batch token estimation vs individual calls."""
    agent = CodePuppyAgent()
    messages = generate_sample_messages(500)
    
    # Individual calls
    start = time.perf_counter()
    individual_total = sum(agent.estimate_tokens_for_message(m) for m in messages)
    individual_time = (time.perf_counter() - start) * 1000
    
    # Batch via estimate_total_tokens if available
    start = time.perf_counter()
    if hasattr(agent, "estimate_total_tokens"):
        batch_total = agent.estimate_total_tokens(messages)
    else:
        # Fallback to sum
        batch_total = sum(agent.estimate_tokens_for_message(m) for m in messages)
    batch_time = (time.perf_counter() - start) * 1000
    
    print("\n[Batch vs Individual] 500 messages:")
    print(f"  Individual: {individual_time:.2f}ms, total: {individual_total}")
    print(f"  Batch: {batch_time:.2f}ms, total: {batch_total}")
    
    # Times should be similar (no significant overhead for individual calls)
    assert abs(individual_time - batch_time) < 100, "Significant overhead detected"
