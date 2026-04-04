"""Benchmarks for session save/load performance with large histories.

These benchmarks measure:
- Wall time for save_session and load_session operations
- Memory delta during save/load
- File I/O performance for large session files

Run with: pytest tests/benchmarks/ -v -m benchmark
"""

import time
import tracemalloc
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

from code_puppy.agents.agent_code_puppy import CodePuppyAgent
from code_puppy.session_storage import save_session, load_session, load_session_with_hashes


pytestmark = pytest.mark.benchmark


def generate_large_history(message_count: int, content_length: int = 500) -> list:
    """Generate a large message history for benchmarking."""
    history = []
    for i in range(message_count):
        content = f"Message {i}: " + "x" * (content_length - len(f"Message {i}: "))
        if i % 2 == 0:
            history.append(ModelRequest(parts=[TextPart(content=content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=content)]))
    return history


def benchmark_save_session(history: list, tmp_dir: Path) -> dict:
    """Benchmark save_session operation.
    
    Returns dict with:
        - wall_time_ms: Wall clock time
        - memory_delta_kb: Memory change
        - file_size_kb: Size of saved file
    """
    agent = CodePuppyAgent()
    session_name = "benchmark_session"
    timestamp = "2026-01-01T00:00:00"
    
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    
    start_time = time.perf_counter()
    
    metadata = save_session(
        history=history,
        session_name=session_name,
        base_dir=tmp_dir,
        timestamp=timestamp,
        token_estimator=agent.estimate_tokens_for_message,
    )
    
    end_time = time.perf_counter()
    
    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    memory_delta = sum(stat.size for stat in top_stats) / 1024
    
    tracemalloc.stop()
    
    wall_time_ms = (end_time - start_time) * 1000
    file_size_kb = metadata.pickle_path.stat().st_size / 1024 if metadata.pickle_path.exists() else 0
    
    return {
        "wall_time_ms": wall_time_ms,
        "memory_delta_kb": memory_delta,
        "file_size_kb": file_size_kb,
        "message_count": len(history),
    }


def benchmark_load_session(message_count: int, tmp_dir: Path) -> dict:
    """Benchmark load_session operation.
    
    First saves a session, then benchmarks the load.
    """
    # First create and save a session
    history = generate_large_history(message_count)
    save_result = benchmark_save_session(history, tmp_dir)
    session_name = "benchmark_session"
    
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    
    start_time = time.perf_counter()
    
    loaded_history = load_session(session_name, tmp_dir)
    
    end_time = time.perf_counter()
    
    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    memory_delta = sum(stat.size for stat in top_stats) / 1024
    
    tracemalloc.stop()
    
    wall_time_ms = (end_time - start_time) * 1000
    
    return {
        "wall_time_ms": wall_time_ms,
        "memory_delta_kb": memory_delta,
        "message_count": len(loaded_history),
        "file_size_kb": save_result["file_size_kb"],
    }


@pytest.mark.benchmark
class TestSessionSaveBenchmarks:
    """Benchmark suite for session save operations."""
    
    def test_save_session_100_messages(self, tmp_path):
        """Benchmark saving session with 100 messages."""
        history = generate_large_history(100)
        
        results = []
        for _ in range(5):
            result = benchmark_save_session(history, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        avg_file_size = sum(r["file_size_kb"] for r in results) / len(results)
        
        print(f"\n[Save] 100 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta, {avg_file_size:.2f}KB file")
        
        assert avg_time < 1000, f"Save too slow: {avg_time:.2f}ms"
        assert avg_memory < 5000, f"Memory usage too high: {avg_memory:.2f}KB"
    
    def test_save_session_500_messages(self, tmp_path):
        """Benchmark saving session with 500 messages."""
        history = generate_large_history(500)
        
        results = []
        for _ in range(3):
            result = benchmark_save_session(history, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        avg_file_size = sum(r["file_size_kb"] for r in results) / len(results)
        
        print(f"\n[Save] 500 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta, {avg_file_size:.2f}KB file")
        
        assert avg_time < 3000, f"Save too slow: {avg_time:.2f}ms"
        assert avg_memory < 20000, f"Memory usage too high: {avg_memory:.2f}KB"
    
    def test_save_session_1000_messages(self, tmp_path):
        """Benchmark saving session with 1000 messages."""
        history = generate_large_history(1000)
        
        results = []
        for _ in range(3):
            result = benchmark_save_session(history, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        avg_file_size = sum(r["file_size_kb"] for r in results) / len(results)
        
        print(f"\n[Save] 1000 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta, {avg_file_size:.2f}KB file")
        
        assert avg_time < 6000, f"Save too slow: {avg_time:.2f}ms"
        assert avg_memory < 50000, f"Memory usage too high: {avg_memory:.2f}KB"


@pytest.mark.benchmark
class TestSessionLoadBenchmarks:
    """Benchmark suite for session load operations."""
    
    def test_load_session_100_messages(self, tmp_path):
        """Benchmark loading session with 100 messages."""
        results = []
        for _ in range(5):
            result = benchmark_load_session(100, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Load] 100 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 1000, f"Load too slow: {avg_time:.2f}ms"
        assert avg_memory < 5000, f"Memory usage too high: {avg_memory:.2f}KB"
    
    def test_load_session_500_messages(self, tmp_path):
        """Benchmark loading session with 500 messages."""
        results = []
        for _ in range(3):
            result = benchmark_load_session(500, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Load] 500 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 2000, f"Load too slow: {avg_time:.2f}ms"
        assert avg_memory < 15000, f"Memory usage too high: {avg_memory:.2f}KB"
    
    def test_load_session_1000_messages(self, tmp_path):
        """Benchmark loading session with 1000 messages."""
        results = []
        for _ in range(3):
            result = benchmark_load_session(1000, tmp_path)
            results.append(result)
        
        avg_time = sum(r["wall_time_ms"] for r in results) / len(results)
        avg_memory = sum(r["memory_delta_kb"] for r in results) / len(results)
        
        print(f"\n[Load] 1000 messages: {avg_time:.2f}ms, {avg_memory:.2f}KB delta")
        
        assert avg_time < 4000, f"Load too slow: {avg_time:.2f}ms"
        assert avg_memory < 30000, f"Memory usage too high: {avg_memory:.2f}KB"
    
    def test_load_session_with_hashes(self, tmp_path):
        """Benchmark load_session_with_hashes with 500 messages."""
        # First create and save a session
        history = generate_large_history(500)
        session_name = "benchmark_hashes_session"
        agent = CodePuppyAgent()
        
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2026-01-01T00:00:00",
            token_estimator=agent.estimate_tokens_for_message,
            compacted_hashes=["hash1", "hash2", "hash3"],
        )
        
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()
        
        start_time = time.perf_counter()
        
        loaded_history, hashes = load_session_with_hashes(session_name, tmp_path)
        
        end_time = time.perf_counter()
        
        snapshot_after = tracemalloc.take_snapshot()
        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        memory_delta = sum(stat.size for stat in top_stats) / 1024
        
        tracemalloc.stop()
        
        wall_time_ms = (end_time - start_time) * 1000
        
        print(f"\n[Load with Hashes] 500 messages: {wall_time_ms:.2f}ms, {memory_delta:.2f}KB delta")
        
        assert wall_time_ms < 3000, f"Load with hashes too slow: {wall_time_ms:.2f}ms"
        assert len(loaded_history) == 500
        assert len(hashes) == 3


@pytest.mark.benchmark
def test_session_roundtrip_performance(tmp_path):
    """Benchmark full roundtrip: save then load for large session."""
    message_count = 500
    history = generate_large_history(message_count)
    session_name = "roundtrip_session"
    agent = CodePuppyAgent()
    
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    
    start_time = time.perf_counter()
    
    # Save
    save_session(
        history=history,
        session_name=session_name,
        base_dir=tmp_path,
        timestamp="2026-01-01T00:00:00",
        token_estimator=agent.estimate_tokens_for_message,
    )
    
    # Load
    loaded_history = load_session(session_name, tmp_path)
    
    end_time = time.perf_counter()
    
    snapshot_after = tracemalloc.take_snapshot()
    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    memory_delta = sum(stat.size for stat in top_stats) / 1024
    
    tracemalloc.stop()
    
    wall_time_ms = (end_time - start_time) * 1000
    
    print(f"\n[Roundtrip] {message_count} messages: {wall_time_ms:.2f}ms, {memory_delta:.2f}KB delta")
    
    assert wall_time_ms < 4000, f"Roundtrip too slow: {wall_time_ms:.2f}ms"
    assert len(loaded_history) == message_count
