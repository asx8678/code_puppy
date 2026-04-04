"""Benchmarks for message_history_processor performance.

These benchmarks measure:
- Wall time for processing message histories of varying sizes
- Memory delta during processing
- Allocation count (if available via tracemalloc)

Run with: pytest tests/benchmarks/ -v -m benchmark
"""

import tracemalloc
import time
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


pytestmark = pytest.mark.benchmark


def generate_messages(count: int, content_length: int = 100) -> list:
    """Generate a list of alternating ModelRequest/ModelResponse messages."""
    messages = []
    for i in range(count):
        content = f"Message {i}: " + "x" * (content_length - len(f"Message {i}: "))
        if i % 2 == 0:
            messages.append(ModelRequest(parts=[TextPart(content=content)]))
        else:
            messages.append(ModelResponse(parts=[TextPart(content=content)]))
    return messages


def run_message_history_benchmark(message_count: int, agent: CodePuppyAgent) -> dict:
    """Run a single benchmark iteration for message_history_processor.
    
    Returns dict with:
        - wall_time_ms: Wall clock time in milliseconds
        - memory_delta_kb: Memory change in KB (if tracemalloc available)
        - peak_memory_kb: Peak memory usage in KB
    """
    # Generate test messages
    messages = generate_messages(message_count)
    
    # Create mock RunContext
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.model_name = "gpt-4o"
    
    # Set up the agent with a large context window to avoid compaction
    agent._config = {"context_length": 128000}
    
    # Start memory tracking if available
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    
    # Run the benchmark
    start_time = time.perf_counter()
    
    with patch("code_puppy.agents.base_agent.update_spinner_context"):
        with patch.object(agent, "get_model_context_length", return_value=128000):
            agent.message_history_processor(mock_ctx, messages)
    
    end_time = time.perf_counter()
    
    # Calculate memory delta
    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    memory_delta = sum(stat.size for stat in top_stats)
    peak_memory = tracemalloc.get_traced_memory()[1] / 1024  # KB
    
    tracemalloc.stop()
    
    wall_time_ms = (end_time - start_time) * 1000
    
    return {
        "wall_time_ms": wall_time_ms,
        "memory_delta_kb": memory_delta / 1024,
        "peak_memory_kb": peak_memory,
        "message_count": message_count,
    }


@pytest.mark.benchmark
class TestMessageHistoryProcessorBenchmarks:
    """Benchmark suite for message_history_processor method."""
    
    @pytest.fixture
    def agent(self):
        """Provide a CodePuppyAgent instance for benchmarking."""
        return CodePuppyAgent()
    
    def test_message_history_processor_50_messages(self, agent, benchmark_repeats=5):
        """Benchmark message_history_processor with 50 messages."""
        results = []
        for _ in range(benchmark_repeats):
            result = run_message_history_benchmark(50, agent)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Benchmark] 50 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        # Soft assertions - these are baselines for tracking, not hard limits
        assert avg_time < 1000, f"Expected <1000ms, got {avg_time:.2f}ms"
        assert avg_memory < 10000, f"Expected <10000KB, got {avg_memory:.2f}KB"
    
    def test_message_history_processor_100_messages(self, agent, benchmark_repeats=5):
        """Benchmark message_history_processor with 100 messages."""
        results = []
        for _ in range(benchmark_repeats):
            result = run_message_history_benchmark(100, agent)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Benchmark] 100 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 2000, f"Expected <2000ms, got {avg_time:.2f}ms"
        assert avg_memory < 20000, f"Expected <20000KB, got {avg_memory:.2f}KB"
    
    def test_message_history_processor_200_messages(self, agent, benchmark_repeats=5):
        """Benchmark message_history_processor with 200 messages."""
        results = []
        for _ in range(benchmark_repeats):
            result = run_message_history_benchmark(200, agent)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Benchmark] 200 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 4000, f"Expected <4000ms, got {avg_time:.2f}ms"
        assert avg_memory < 40000, f"Expected <40000KB, got {avg_memory:.2f}KB"
    
    def test_message_history_processor_500_messages(self, agent, benchmark_repeats=3):
        """Benchmark message_history_processor with 500 messages."""
        results = []
        for _ in range(benchmark_repeats):
            result = run_message_history_benchmark(500, agent)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Benchmark] 500 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 10000, f"Expected <10000ms, got {avg_time:.2f}ms"
        assert avg_memory < 100000, f"Expected <100000KB, got {avg_memory:.2f}KB"


@pytest.mark.benchmark
def test_message_history_processor_scaling():
    """Test that processing time scales reasonably with message count.
    
    This test verifies that doubling message count doesn't more than triple
    the processing time (allowing for some fixed overhead).
    """
    agent = CodePuppyAgent()
    
    # Warm up to get stable results
    run_message_history_benchmark(10, agent)
    
    # Benchmark different sizes
    times_50 = run_message_history_benchmark(50, agent)["wall_time_ms"]
    times_100 = run_message_history_benchmark(100, agent)["wall_time_ms"]
    times_200 = run_message_history_benchmark(200, agent)["wall_time_ms"]
    
    # Check scaling - doubling messages shouldn't more than triple time
    ratio_50_to_100 = times_100 / times_50 if times_50 > 0 else 1
    ratio_100_to_200 = times_200 / times_100 if times_100 > 0 else 1
    
    print(f"\n[Scaling] 50->100: {ratio_50_to_100:.2f}x, 100->200: {ratio_100_to_200:.2f}x")
    
    # Allow up to 3x scaling factor (generous to avoid flaky failures)
    assert ratio_50_to_100 < 3.0, f"Scaling 50->100 too steep: {ratio_50_to_100:.2f}x"
    assert ratio_100_to_200 < 3.0, f"Scaling 100->200 too steep: {ratio_100_to_200:.2f}x"


@pytest.mark.benchmark
def test_message_history_processor_with_large_content():
    """Benchmark processing of messages with large content (10KB per message)."""
    agent = CodePuppyAgent()
    
    # Generate 50 messages with 10KB content each
    messages = generate_messages(50, content_length=10000)
    
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.model_name = "gpt-4o"
    
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    
    start_time = time.perf_counter()
    
    with patch("code_puppy.agents.base_agent.update_spinner_context"):
        with patch.object(agent, "get_model_context_length", return_value=128000):
            agent.message_history_processor(mock_ctx, messages)
    
    end_time = time.perf_counter()
    
    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    memory_delta = sum(stat.size for stat in top_stats) / 1024
    
    tracemalloc.stop()
    
    wall_time_ms = (end_time - start_time) * 1000
    
    print(f"\n[Large Content] 50x10KB messages: {wall_time_ms:.2f}ms, {memory_delta:.2f}KB delta")
    
    # Processing large content should still complete in reasonable time
    assert wall_time_ms < 5000, f"Large content processing too slow: {wall_time_ms:.2f}ms"
