"""Lightweight offline self-tests using stdlib unittest (no pytest dependency)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.bench_baseline.models import BenchmarkResult, BenchmarkSuite, LatencyStats
from scripts.bench_baseline.utils import format_stats, time_function


class TestLatencyStats(unittest.TestCase):
    """Test statistical calculations."""

    def test_empty_samples(self):
        """Empty samples should return zero stats."""
        stats = LatencyStats.from_samples([])
        self.assertEqual(stats.mean_ms, 0.0)
        self.assertEqual(stats.samples, 0)

    def test_single_sample(self):
        """Single sample should have zero stdev."""
        stats = LatencyStats.from_samples([5.0])
        self.assertEqual(stats.mean_ms, 5.0)
        self.assertEqual(stats.stdev_ms, 0.0)
        self.assertEqual(stats.samples, 1)

    def test_percentiles(self):
        """Percentile calculation should be correct."""
        samples = list(range(100))  # 0-99
        stats = LatencyStats.from_samples(samples)
        self.assertEqual(stats.p95_ms, 94)  # 95th percentile of 0-99
        self.assertEqual(stats.p99_ms, 98)  # 99th percentile

    def test_stats_calculation(self):
        """Basic stats should calculate correctly."""
        samples = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = LatencyStats.from_samples(samples)
        self.assertAlmostEqual(stats.mean_ms, 3.0)
        self.assertEqual(stats.median_ms, 3.0)
        self.assertEqual(stats.min_ms, 1.0)
        self.assertEqual(stats.max_ms, 5.0)


class TestTimeFunction(unittest.TestCase):
    """Test timing function with timeout."""

    def test_basic_timing(self):
        """Basic timing should work."""
        import time

        def sleep_10ms():
            time.sleep(0.01)

        times, failures = time_function(
            sleep_10ms, iterations=3, warmup=1, timeout_sec=5.0
        )
        self.assertEqual(len(times), 3)
        self.assertEqual(len(failures), 0)
        # All times should be around 10ms
        for t in times:
            self.assertGreater(t, 5)  # At least 5ms
            self.assertLess(t, 100)  # Less than 100ms

    def test_failure_capture(self):
        """Failures should be captured, not swallowed."""

        def raise_error():
            raise ValueError("test error")

        times, failures = time_function(
            raise_error, iterations=3, warmup=0, timeout_sec=5.0
        )
        self.assertEqual(len(times), 0)
        self.assertEqual(len(failures), 3)
        for f in failures:
            self.assertEqual(f["type"], "ValueError")
            self.assertIn("test error", f["error"])

    def test_timeout_short_op_succeeds(self):
        """Quick operation with generous timeout should complete successfully."""
        import time

        def quick_op():
            time.sleep(0.01)

        times, failures = time_function(
            quick_op, iterations=1, warmup=0, timeout_sec=5.0
        )
        self.assertEqual(len(times), 1)
        self.assertEqual(len(failures), 0)

    @unittest.skipUnless(
        hasattr(__import__("signal"), "SIGALRM"),
        "SIGALRM not available on this platform",
    )
    def test_timeout_exceeded_returns_failure_not_exit(self):
        """Operation exceeding timeout should return failures, not kill process.

        This is the critical self-test: signal.alarm() without a handler causes
        exit 142. With a proper handler, the process survives and records a
        TimeoutError failure instead.
        """
        import time

        def slow_op():
            time.sleep(10)  # Way beyond the short timeout

        # Use a very short timeout (0.25s) to ensure the operation exceeds it
        times, failures = time_function(
            slow_op, iterations=3, warmup=0, timeout_sec=0.25
        )

        # All iterations should be recorded as timeout failures
        self.assertEqual(
            len(times), 0, "Expected no successful samples for timed-out ops"
        )
        self.assertEqual(len(failures), 3, "Expected 3 timeout failure records")
        for f in failures:
            self.assertEqual(f["type"], "TimeoutError")
            self.assertEqual(f["error"], "timeout")

    @unittest.skipUnless(
        hasattr(__import__("signal"), "SIGALRM"),
        "SIGALRM not available on this platform",
    )
    def test_timeout_survives_after_timeout(self):
        """Process must continue normally after a timeout — not exit 142.

        Verifies that signal handler/timer are properly restored so
        subsequent operations work correctly.
        """
        import time

        def slow_op():
            time.sleep(10)

        def fast_op():
            time.sleep(0.01)

        # First: trigger a timeout
        times1, failures1 = time_function(
            slow_op, iterations=1, warmup=0, timeout_sec=0.25
        )
        self.assertEqual(len(times1), 0)
        self.assertEqual(len(failures1), 1)

        # Second: verify a normal operation still works after timeout
        times2, failures2 = time_function(
            fast_op, iterations=2, warmup=0, timeout_sec=5.0
        )
        self.assertEqual(len(times2), 2)
        self.assertEqual(len(failures2), 0)
        # Sanity: times are reasonable
        for t in times2:
            self.assertGreater(t, 5)


class TestBenchmarkSuite(unittest.TestCase):
    """Test suite serialization."""

    def test_to_dict(self):
        """Suite should serialize to dict."""
        suite = BenchmarkSuite(
            timestamp="2026-01-15T10:00:00Z",
            version="1.0.0",
            mode="test",
        )
        d = suite.to_dict()
        self.assertEqual(d["timestamp"], "2026-01-15T10:00:00Z")
        self.assertEqual(d["version"], "1.0.0")
        self.assertEqual(d["mode"], "test")
        self.assertEqual(d["results"], [])

    def test_add_result(self):
        """Should be able to add results."""
        suite = BenchmarkSuite(
            timestamp="2026-01-15T10:00:00Z",
            version="1.0.0",
            mode="test",
        )
        stats = LatencyStats.from_samples([1.0, 2.0, 3.0])
        result = BenchmarkResult(
            category="test",
            operation="test_op",
            approach="python",
            latency_stats=stats,
            throughput_ops_per_sec=100.0,
        )
        suite.add(result)
        self.assertEqual(len(suite.results), 1)

    def test_json_serialization(self):
        """Should be JSON serializable."""
        suite = BenchmarkSuite(
            timestamp="2026-01-15T10:00:00Z",
            version="1.0.0",
            mode="test",
        )
        stats = LatencyStats.from_samples([1.0, 2.0, 3.0])
        result = BenchmarkResult(
            category="test",
            operation="test_op",
            approach="python",
            latency_stats=stats,
            throughput_ops_per_sec=100.0,
            metadata={"key": "value"},
        )
        suite.add(result)
        suite.pending_benchmarks.append("pending_test")
        suite.not_implemented.append("not_impl_test")

        # Should serialize without error
        json_str = json.dumps(suite.to_dict())
        self.assertIn("test_op", json_str)
        self.assertIn("pending_test", json_str)
        self.assertIn("not_impl_test", json_str)


class TestFormatStats(unittest.TestCase):
    """Test stats formatting."""

    def test_format(self):
        """Should format stats nicely."""
        stats = LatencyStats.from_samples([1.0, 2.0, 3.0])
        formatted = format_stats(stats)
        self.assertIn("mean=2.0", formatted)
        self.assertIn("median=2.0", formatted)


class TestCLIEnv(unittest.TestCase):
    """Test CLI and environment behavior."""

    def test_env_override(self):
        """Environment variables should override defaults."""
        # Save original
        orig_quick = os.environ.get("PUP_BENCH_QUICK")
        orig_category = os.environ.get("PUP_BENCH_CATEGORY")

        try:
            os.environ["PUP_BENCH_QUICK"] = "1"
            os.environ["PUP_BENCH_CATEGORY"] = "tools"

            # Simulate parsing
            import argparse

            parser = argparse.ArgumentParser()
            parser.add_argument("--quick", action="store_true")
            parser.add_argument("--category", default="all")
            args = parser.parse_args([])

            # Environment overrides
            mode = (
                "quick" if (args.quick or os.environ.get("PUP_BENCH_QUICK")) else "full"
            )
            category = os.environ.get("PUP_BENCH_CATEGORY", args.category)

            self.assertEqual(mode, "quick")
            self.assertEqual(category, "tools")
        finally:
            # Restore
            if orig_quick is not None:
                os.environ["PUP_BENCH_QUICK"] = orig_quick
            elif "PUP_BENCH_QUICK" in os.environ:
                del os.environ["PUP_BENCH_QUICK"]

            if orig_category is not None:
                os.environ["PUP_BENCH_CATEGORY"] = orig_category
            elif "PUP_BENCH_CATEGORY" in os.environ:
                del os.environ["PUP_BENCH_CATEGORY"]

    def test_json_output(self):
        """JSON output should be valid and readable."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name

        try:
            suite = BenchmarkSuite(
                timestamp="2026-01-15T10:00:00Z",
                version="1.0.0",
                mode="test",
            )
            stats = LatencyStats.from_samples([1.0, 2.0, 3.0])
            result = BenchmarkResult(
                category="test",
                operation="test_op",
                approach="python",
                latency_stats=stats,
                throughput_ops_per_sec=100.0,
            )
            suite.add(result)

            # Write JSON
            with open(path, "w") as f:
                json.dump(suite.to_dict(), f, indent=2)

            # Read and validate
            with open(path) as f:
                data = json.load(f)

            self.assertEqual(data["version"], "1.0.0")
            self.assertEqual(len(data["results"]), 1)
        finally:
            Path(path).unlink(missing_ok=True)


class TestPendingNotImplemented(unittest.TestCase):
    """Test pending vs not_implemented handling."""

    def test_pending_list(self):
        """Pending benchmarks should be tracked."""
        suite = BenchmarkSuite(
            timestamp="2026-01-15T10:00:00Z",
            version="1.0.0",
            mode="test",
        )
        suite.pending_benchmarks.append("llm_latency_credentials_needed")
        d = suite.to_dict()
        self.assertIn("llm_latency_credentials_needed", d["pending_benchmarks"])

    def test_not_implemented_list(self):
        """Not implemented should be tracked separately."""
        suite = BenchmarkSuite(
            timestamp="2026-01-15T10:00:00Z",
            version="1.0.0",
            mode="test",
        )
        suite.not_implemented.append("llm_latency_no_credentials")
        d = suite.to_dict()
        self.assertIn("llm_latency_no_credentials", d["not_implemented"])


def run_tests() -> int:
    """Run all self-tests. Returns 0 on success, 1 on failure."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
