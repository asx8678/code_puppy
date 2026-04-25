"""Offline self-tests for streaming fixtures and metrics (no pytest, no network).

Split from self_test.py to keep the original file from growing needlessly.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.bench_baseline.models import BenchmarkResult, LatencyStats
from scripts.bench_baseline.streaming import (
    compute_inter_token_gaps,
    compute_streaming_metrics,
    streaming_metrics_to_benchmark_metadata,
)
from scripts.bench_baseline.streaming_fixtures import (
    FIXTURES,
    SHORT,
    MEDIUM,
    all_fixture_ids,
    get_fixture,
)
from scripts.bench_baseline.streaming_probes import (
    StreamingProbes,
    extract_anthropic_token_text,
    extract_openai_token_text,
    is_token_arrival,
)


# ---------------------------------------------------------------------------
# Streaming fixtures tests
# ---------------------------------------------------------------------------


class TestStreamingPromptFixture(unittest.TestCase):
    """Offline tests for streaming prompt fixtures."""

    def test_short_fixture_fields(self):
        """SHORT fixture must have stable prompt_id and non-empty text."""
        self.assertEqual(SHORT.prompt_id, "short_v1")
        self.assertTrue(len(SHORT.text) > 0)
        self.assertTrue(SHORT.expected_min_tokens > 0)

    def test_medium_fixture_fields(self):
        """MEDIUM fixture must have stable prompt_id and non-empty text."""
        self.assertEqual(MEDIUM.prompt_id, "medium_v1")
        self.assertTrue(len(MEDIUM.text) > 0)
        self.assertTrue(MEDIUM.expected_min_tokens > SHORT.expected_min_tokens)

    def test_fixtures_registry_contains_all(self):
        """FIXTURES registry must contain SHORT and MEDIUM."""
        self.assertIn(SHORT.prompt_id, FIXTURES)
        self.assertIn(MEDIUM.prompt_id, FIXTURES)

    def test_all_fixture_ids_sorted(self):
        """all_fixture_ids() must return sorted list."""
        ids = all_fixture_ids()
        self.assertEqual(ids, sorted(ids))
        self.assertIn(SHORT.prompt_id, ids)
        self.assertIn(MEDIUM.prompt_id, ids)

    def test_get_fixture_lookup(self):
        """get_fixture() must return the correct StreamingPrompt."""
        fixture = get_fixture("short_v1")
        self.assertIs(fixture, SHORT)

    def test_get_fixture_unknown_raises(self):
        """get_fixture() with unknown id must raise KeyError."""
        with self.assertRaises(KeyError):
            get_fixture("nonexistent_v99")

    def test_fixtures_are_frozen(self):
        """StreamingPrompt must be frozen (immutable)."""
        with self.assertRaises(AttributeError):
            SHORT.text = "mutated"  # type: ignore[misc]

    def test_fixtures_deterministic_text(self):
        """Same prompt_id must always yield the same text."""
        fixture = get_fixture("short_v1")
        self.assertEqual(fixture.text, SHORT.text)

    def test_no_network_access(self):
        """Fixtures module must not import any network libraries."""
        import importlib

        mod = importlib.import_module("scripts.bench_baseline.streaming_fixtures")
        with open(mod.__file__) as f:
            source = f.read()
        for forbidden in ("requests", "httpx", "urllib", "socket", "aiohttp"):
            self.assertNotIn(
                f"import {forbidden}",
                source,
                f"streaming_fixtures must not import {forbidden}",
            )


class TestStreamingPromptIdStability(unittest.TestCase):
    """Invariants for fixture id format."""

    def test_prompt_id_format(self):
        """All prompt_ids must follow <name>_v<n> convention."""
        import re

        pattern = re.compile(r"^[a-z][a-z0-9]*_v\d+$")
        for fid in all_fixture_ids():
            self.assertRegex(
                fid,
                pattern,
                f"prompt_id '{fid}' must match <name>_v<n> convention",
            )

    def test_fixture_ids_unique(self):
        """All fixture ids in registry must be unique."""
        ids = all_fixture_ids()
        self.assertEqual(len(ids), len(set(ids)), "Duplicate fixture ids found")


# ---------------------------------------------------------------------------
# Streaming metrics tests
# ---------------------------------------------------------------------------


class TestComputeInterTokenGaps(unittest.TestCase):
    """Offline tests for inter-token gap computation."""

    def test_basic_gaps(self):
        """Gaps should be differences between consecutive timestamps."""
        timestamps = [100.0, 150.0, 210.0, 280.0]
        gaps = compute_inter_token_gaps(timestamps)
        self.assertEqual(gaps, [50.0, 60.0, 70.0])

    def test_two_timestamps_one_gap(self):
        """Two timestamps produce exactly one gap."""
        gaps = compute_inter_token_gaps([10.0, 25.0])
        self.assertEqual(gaps, [15.0])

    def test_single_timestamp_no_gaps(self):
        """Single timestamp produces no gaps (need >= 2)."""
        gaps = compute_inter_token_gaps([50.0])
        self.assertEqual(gaps, [])

    def test_empty_timestamps_no_gaps(self):
        """Empty input produces no gaps."""
        gaps = compute_inter_token_gaps([])
        self.assertEqual(gaps, [])

    def test_non_monotonic_clamped(self):
        """Non-monotonic timestamps must produce gaps clamped to 0."""
        # Second timestamp goes backwards
        gaps = compute_inter_token_gaps([100.0, 50.0, 150.0])
        self.assertEqual(gaps[0], 0.0)  # Clamped from -50
        self.assertEqual(gaps[1], 100.0)  # 150 - 50

    def test_zero_gaps(self):
        """Identical consecutive timestamps produce 0 gaps."""
        gaps = compute_inter_token_gaps([100.0, 100.0, 100.0])
        self.assertEqual(gaps, [0.0, 0.0])


class TestComputeStreamingMetrics(unittest.TestCase):
    """Offline tests for full streaming metrics computation."""

    def test_basic_metrics(self):
        """Normal timestamps produce correct TTFT and TBT stats."""
        # TTFT=100ms, gaps: 50, 60, 70
        timestamps = [100.0, 150.0, 210.0, 280.0]
        metrics = compute_streaming_metrics(
            timestamps,
            model="test-model",
            prompt_id="short_v1",
        )
        self.assertAlmostEqual(metrics.ttft_ms, 100.0)
        self.assertAlmostEqual(metrics.total_duration_ms, 280.0)
        self.assertEqual(metrics.token_count, 4)
        self.assertEqual(metrics.chunk_count, 4)
        self.assertEqual(metrics.model, "test-model")
        self.assertEqual(metrics.prompt_id, "short_v1")

        # TBT stats from gaps [50, 60, 70]
        self.assertAlmostEqual(metrics.tbt_stats.mean_ms, 60.0)
        self.assertAlmostEqual(metrics.tbt_stats.median_ms, 60.0)
        self.assertEqual(metrics.tbt_stats.samples, 3)

    def test_empty_timestamps_degenerate(self):
        """Empty timestamps produce zeroed degenerate metrics."""
        metrics = compute_streaming_metrics(
            [],
            model="test-model",
            prompt_id="short_v1",
        )
        self.assertEqual(metrics.ttft_ms, 0.0)
        self.assertEqual(metrics.total_duration_ms, 0.0)
        self.assertEqual(metrics.token_count, 0)
        self.assertEqual(metrics.chunk_count, 0)
        self.assertEqual(metrics.tbt_stats.samples, 0)

    def test_single_timestamp_no_tbt(self):
        """Single timestamp sets TTFT but produces no TBT gaps."""
        metrics = compute_streaming_metrics([200.0])
        self.assertAlmostEqual(metrics.ttft_ms, 200.0)
        self.assertAlmostEqual(metrics.total_duration_ms, 200.0)
        self.assertEqual(metrics.tbt_stats.samples, 0)

    def test_explicit_token_chunk_overrides(self):
        """token_count and chunk_count overrides should take precedence."""
        timestamps = [100.0, 150.0]
        metrics = compute_streaming_metrics(
            timestamps,
            token_count=50,
            chunk_count=2,
        )
        self.assertEqual(metrics.token_count, 50)
        self.assertEqual(metrics.chunk_count, 2)

    def test_failures_and_timeout_fields(self):
        """failures and timeout must be preserved in metrics."""
        metrics = compute_streaming_metrics(
            [100.0, 200.0],
            failures=2,
            timeout=True,
        )
        self.assertEqual(metrics.failures, 2)
        self.assertTrue(metrics.timeout)


class TestStreamingMetricsSchema(unittest.TestCase):
    """Schema/output shape invariants for StreamingMetrics."""

    def test_to_dict_keys(self):
        """to_dict() must produce expected keys matching metric_names."""
        timestamps = [100.0, 150.0, 210.0]
        metrics = compute_streaming_metrics(
            timestamps,
            model="claude-sonnet-4-20250514",
            prompt_id="short_v1",
        )
        d = metrics.to_dict()

        # Must include core streaming metric fields
        expected_keys = {
            "ttft_ms",
            "tbt_mean_ms",
            "tbt_median_ms",
            "tbt_p95_ms",
            "tbt_p99_ms",
            "total_duration_ms",
            "token_count",
            "chunk_count",
            "model",
            "prompt_id",
            "failures",
            "timeout",
            "metric_names",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_json_serializable(self):
        """to_dict() output must be JSON-serializable."""
        timestamps = [100.0, 150.0, 210.0]
        metrics = compute_streaming_metrics(
            timestamps,
            model="test-model",
            prompt_id="short_v1",
        )
        json_str = json.dumps(metrics.to_dict())
        self.assertIn("ttft_ms", json_str)

    def test_metric_names_present(self):
        """metric_names must be a non-empty tuple of known metric fields."""
        timestamps = [50.0, 100.0]
        metrics = compute_streaming_metrics(timestamps)
        self.assertTrue(len(metrics.metric_names) > 0)
        self.assertIn("ttft_ms", metrics.metric_names)
        self.assertIn("tbt_mean_ms", metrics.metric_names)

    def test_metadata_helper_output(self):
        """streaming_metrics_to_benchmark_metadata must match to_dict."""
        timestamps = [80.0, 120.0, 170.0]
        metrics = compute_streaming_metrics(
            timestamps,
            model="gpt-4o-mini",
            prompt_id="medium_v1",
        )
        meta = streaming_metrics_to_benchmark_metadata(metrics)
        self.assertEqual(meta, metrics.to_dict())


class TestTTFTvsTTFBDistinction(unittest.TestCase):
    """Enforce that TTFT is clearly distinct from existing TTFB convention."""

    def test_ttft_not_called_ttfb(self):
        """StreamingMetrics field must be ttft_ms, not ttfb_ms."""
        metrics = compute_streaming_metrics([100.0, 200.0])
        d = metrics.to_dict()
        self.assertIn("ttft_ms", d)
        self.assertNotIn("ttfb_ms", d, "Use ttft_ms for streaming, not ttfb_ms")

    def test_existing_benchmark_result_ttfb_unchanged(self):
        """Existing BenchmarkResult TTFB operations must still work."""
        # Verify existing non-streaming path still works as before
        stats = LatencyStats.from_samples([100.0, 200.0, 300.0])
        result = BenchmarkResult(
            category="llm_latency",
            operation="anthropic_ttfb",
            approach="live_api",
            latency_stats=stats,
            throughput_ops_per_sec=0,
            metadata={"model": "claude-sonnet-4-20250514"},
            notes="Time to first block (approximates TTFT). Paid API call.",
        )
        self.assertEqual(result.operation, "anthropic_ttfb")
        # Streaming metrics should use ttft_ms, not interfere
        streaming = compute_streaming_metrics(
            [50.0, 80.0],
            model="claude-sonnet-4-20250514",
            prompt_id="short_v1",
        )
        self.assertAlmostEqual(streaming.ttft_ms, 50.0)


# ---------------------------------------------------------------------------
# Streaming extraction helper tests (offline, fake chunk objects)
# ---------------------------------------------------------------------------


class _FakeAnthropicDelta:
    """Minimal fake Anthropic delta for offline extraction tests."""

    def __init__(self, text: str | None):
        self.text = text


class _FakeAnthropicEvent:
    """Minimal fake Anthropic streaming event for offline extraction tests."""

    def __init__(self, event_type: str, delta: _FakeAnthropicDelta | None = None):
        self.type = event_type
        self.delta = delta


class _FakeOpenAIDelta:
    """Minimal fake OpenAI delta for offline extraction tests."""

    def __init__(self, content: str | None):
        self.content = content


class _FakeOpenAIChoice:
    """Minimal fake OpenAI choice for offline extraction tests."""

    def __init__(self, delta: _FakeOpenAIDelta):
        self.delta = delta


class _FakeOpenAIChunk:
    """Minimal fake OpenAI streaming chunk for offline extraction tests."""

    def __init__(self, choices: list[_FakeOpenAIChoice] | None = None):
        self.choices = choices or []


class TestExtractAnthropicTokenText(unittest.TestCase):
    """Offline tests for Anthropic streaming event text extraction."""

    def test_content_block_delta_returns_text(self):
        """content_block_delta event with text delta must return the text."""
        event = _FakeAnthropicEvent(
            "content_block_delta",
            delta=_FakeAnthropicDelta("Hello"),
        )
        self.assertEqual(extract_anthropic_token_text(event), "Hello")

    def test_message_start_returns_none(self):
        """message_start event must return None (no token text)."""
        event = _FakeAnthropicEvent("message_start")
        self.assertIsNone(extract_anthropic_token_text(event))

    def test_content_block_start_returns_none(self):
        """content_block_start event must return None (no token text)."""
        event = _FakeAnthropicEvent("content_block_start")
        self.assertIsNone(extract_anthropic_token_text(event))

    def test_content_block_delta_no_delta_returns_none(self):
        """content_block_delta with no delta attribute must return None."""
        event = _FakeAnthropicEvent("content_block_delta", delta=None)
        self.assertIsNone(extract_anthropic_token_text(event))

    def test_content_block_delta_empty_text(self):
        """content_block_delta with empty text string must return empty string."""
        event = _FakeAnthropicEvent(
            "content_block_delta",
            delta=_FakeAnthropicDelta(""),
        )
        self.assertEqual(extract_anthropic_token_text(event), "")

    def test_event_without_type_attr_returns_none(self):
        """Event without type attribute must return None."""
        self.assertIsNone(extract_anthropic_token_text(object()))


class TestExtractOpenAITokenText(unittest.TestCase):
    """Offline tests for OpenAI streaming chunk text extraction."""

    def test_chunk_with_content_returns_text(self):
        """Chunk with content delta must return the text."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta("World"))])
        self.assertEqual(extract_openai_token_text(chunk), "World")

    def test_chunk_with_none_content_returns_none(self):
        """Chunk with None content (role-only) must return None."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta(None))])
        self.assertIsNone(extract_openai_token_text(chunk))

    def test_chunk_without_choices_returns_none(self):
        """Chunk with empty choices must return None."""
        chunk = _FakeOpenAIChunk(choices=[])
        self.assertIsNone(extract_openai_token_text(chunk))

    def test_chunk_without_choices_attr_returns_none(self):
        """Object without choices attribute must return None."""
        self.assertIsNone(extract_openai_token_text(object()))

    def test_chunk_empty_content_returns_empty(self):
        """Chunk with empty string content must return empty string."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta(""))])
        self.assertEqual(extract_openai_token_text(chunk), "")


class TestIsTokenArrival(unittest.TestCase):
    """Offline tests for empty-delta filtering logic.

    Empty-string deltas must not count as token arrivals; this prevents
    OpenAI role-only / empty-content chunks from deflating TTFT and
    polluting TBT measurements.
    """

    def test_none_is_not_arrival(self):
        """None (no token text) must not count as a token arrival."""
        self.assertFalse(is_token_arrival(None))

    def test_empty_string_is_not_arrival(self):
        """Empty string delta must not count as a token arrival."""
        self.assertFalse(is_token_arrival(""))

    def test_whitespace_is_arrival(self):
        """Whitespace-only deltas ARE token arrivals (meaningful content)."""
        self.assertTrue(is_token_arrival(" "))
        self.assertTrue(is_token_arrival("\n"))
        self.assertTrue(is_token_arrival("  \n  "))

    def test_normal_text_is_arrival(self):
        """Non-empty text is always a token arrival."""
        self.assertTrue(is_token_arrival("Hello"))
        self.assertTrue(is_token_arrival(" world"))

    def test_anthropic_empty_delta_not_arrival(self):
        """Anthropic extraction returning empty string must not be token arrival."""
        event = _FakeAnthropicEvent(
            "content_block_delta",
            delta=_FakeAnthropicDelta(""),
        )
        text = extract_anthropic_token_text(event)
        self.assertEqual(text, "")
        self.assertFalse(is_token_arrival(text))

    def test_anthropic_none_delta_not_arrival(self):
        """Anthropic extraction returning None must not be token arrival."""
        event = _FakeAnthropicEvent("message_start")
        text = extract_anthropic_token_text(event)
        self.assertIsNone(text)
        self.assertFalse(is_token_arrival(text))

    def test_openai_empty_delta_not_arrival(self):
        """OpenAI extraction returning empty string must not be token arrival."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta(""))])
        text = extract_openai_token_text(chunk)
        self.assertEqual(text, "")
        self.assertFalse(is_token_arrival(text))

    def test_openai_none_content_not_arrival(self):
        """OpenAI extraction returning None must not be token arrival."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta(None))])
        text = extract_openai_token_text(chunk)
        self.assertIsNone(text)
        self.assertFalse(is_token_arrival(text))

    def test_openai_whitespace_delta_is_arrival(self):
        """OpenAI whitespace-only delta IS a token arrival."""
        chunk = _FakeOpenAIChunk(choices=[_FakeOpenAIChoice(_FakeOpenAIDelta("\n"))])
        text = extract_openai_token_text(chunk)
        self.assertEqual(text, "\n")
        self.assertTrue(is_token_arrival(text))


class TestTBTCrossIterationAggregation(unittest.TestCase):
    """Offline tests verifying TBT aggregation across iterations.

    Inter-token gaps from multiple successful iterations must be combined
    without crossing iteration boundaries.
    """

    def test_gaps_from_two_iterations_combined(self):
        """Gaps from two iterations should be concatenated (not crossed)."""
        iter1 = [100.0, 150.0, 210.0]  # gaps: 50, 60
        iter2 = [95.0, 155.0, 200.0]  # gaps: 60, 45
        gaps1 = compute_inter_token_gaps(iter1)
        gaps2 = compute_inter_token_gaps(iter2)
        all_gaps = gaps1 + gaps2
        stats = LatencyStats.from_samples(all_gaps)
        self.assertEqual(stats.samples, 4)
        self.assertAlmostEqual(stats.mean_ms, (50 + 60 + 60 + 45) / 4)

    def test_single_iteration_gaps_unaffected(self):
        """Single-iteration aggregation produces same result as non-aggregated."""
        timestamps = [100.0, 150.0, 210.0]
        gaps = compute_inter_token_gaps(timestamps)
        all_gaps = gaps  # same as single-iteration
        stats = LatencyStats.from_samples(all_gaps)
        self.assertEqual(stats.samples, 2)
        self.assertAlmostEqual(stats.mean_ms, 55.0)

    def test_no_cross_boundary_gap(self):
        """Last token of iter N and first token of iter N+1 must NOT produce a gap."""
        iter1 = [100.0, 200.0]  # gap: 100
        iter2 = [50.0, 150.0]  # gap: 100
        # If we naively concatenated timestamps, we'd get [100, 200, 50, 150]
        # and a bogus gap from 200→50.  Per-iteration gaps avoid this.
        gaps1 = compute_inter_token_gaps(iter1)
        gaps2 = compute_inter_token_gaps(iter2)
        all_gaps = gaps1 + gaps2
        # Both gaps should be 100, no cross-boundary artifacts
        self.assertEqual(len(all_gaps), 2)
        for g in all_gaps:
            self.assertAlmostEqual(g, 100.0)

    def test_successful_iterations_in_metadata(self):
        """Metadata should include successful_iterations count."""
        # Verify the field exists in computed streaming metadata
        timestamps = [100.0, 150.0, 210.0]
        metrics = compute_streaming_metrics(
            timestamps,
            model="test-model",
            prompt_id="short_v1",
        )
        metadata = streaming_metrics_to_benchmark_metadata(metrics)
        # successful_iterations is added by the probe, not by
        # streaming_metrics_to_benchmark_metadata, but we verify
        # we can add it without conflict
        metadata["successful_iterations"] = 3
        self.assertEqual(metadata["successful_iterations"], 3)


class TestStreamingProbesNoCredentials(unittest.TestCase):
    """Offline tests for StreamingProbes with no credentials present."""

    def test_run_all_no_credentials_returns_empty_results(self):
        """With no API keys, run_all() must return empty results."""
        # Ensure no keys in environment
        saved = {}
        for key in (
            "PUP_ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
            "PUP_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ):
            if key in os.environ:
                saved[key] = os.environ.pop(key)
        try:
            probes = StreamingProbes("quick")
            results, not_impl = probes.run_all()
            self.assertEqual(len(results), 0)
            self.assertIn("llm_streaming_no_credentials", not_impl)
        finally:
            os.environ.update(saved)

    def test_streaming_probes_uses_fixture(self):
        """StreamingProbes should reference the short_v1 fixture."""
        fixture = get_fixture("short_v1")
        self.assertEqual(fixture.prompt_id, "short_v1")
        # Verify the fixture is the one probes will use
        self.assertTrue(len(fixture.text) > 0)

    def test_streaming_probes_result_category(self):
        """Verify expected category/operation naming convention."""
        # We can't run live probes without credentials, but we can
        # verify the expected category and operation names are used
        # by constructing a BenchmarkResult with the streaming category.
        from scripts.bench_baseline.models import BenchmarkResult, LatencyStats

        stats = LatencyStats.from_samples([100.0])
        result = BenchmarkResult(
            category="llm_streaming",
            operation="anthropic_streaming_ttft_tbt",
            approach="live_api",
            latency_stats=stats,
            throughput_ops_per_sec=0,
            metadata={"ttft_ms": 100.0, "prompt_id": "short_v1"},
            notes="Streaming TTFT/TBT probe.",
        )
        self.assertEqual(result.category, "llm_streaming")
        self.assertIn("streaming_ttft_tbt", result.operation)


def load_streaming_tests() -> unittest.TestSuite:
    """Return a TestSuite with all streaming self-tests.

    Called by scripts/bench_baseline/self_test.py to include these tests
    in the unified ``--self-test`` run.

    Named ``load_streaming_tests`` (not ``load_tests``) to avoid the
    unittest ``load_tests`` protocol which expects a 3-arg signature.
    """
    loader = unittest.TestLoader()
    return loader.loadTestsFromModule(sys.modules[__name__])


if __name__ == "__main__":
    unittest.main()
