# Code Puppy Performance Benchmarks

This directory contains performance benchmarks and documentation for the Python-to-Elixir migration.

## Quick Start

Run the baseline benchmark harness:

```bash
# Run all benchmarks
python scripts/bench_baseline_harness.py

# Quick mode (CI friendly)
python scripts/bench_baseline_harness.py --quick

# Tools only
python scripts/bench_baseline_harness.py --category tools

# Save results to JSON
python scripts/bench_baseline_harness.py --output results.json

# Run offline self-tests (no pytest required)
python scripts/bench_baseline_harness.py --self-test
```

## Benchmark Categories

### 1. Tool Execution Overhead (Offline Filesystem Primitives)

Benchmarks offline filesystem primitives to establish a baseline for comparison.

**IMPORTANT:** These measure raw filesystem operations (pathlib, rglob, read_text), NOT full Code Puppy tool-path overhead. Full tool-path would include:
- Permission callbacks
- Logging/telemetry
- Elixir transport serialization (when bridge connected)

**Operations measured:**
- `list_files` - Directory traversal via `pathlib.rglob()`
- `read_file` - File content reading via `pathlib.read_text()`
- `grep` - Text search via Python loops

**Metrics:**
- Mean latency (ms)
- P95/P99 latency (ms)
- Throughput (ops/sec)
- Failure count (truthful error capture)

**Run offline:** Yes (creates temporary test files)

### 2. LLM Request Latency

Credential-gated probe for LLM API latency. **Requires operator-provided API
keys; no live baseline numbers are committed to the repository.**

**Status:** Implemented, credential-gated

When `PUP_ANTHROPIC_API_KEY` or `PUP_OPENAI_API_KEY` is set, runs a minimal probe:
- Single-shot request to claude-sonnet-4 or gpt-4o-mini
- Measures time-to-first-block (TTFB)
- Harness `timeout` setting (default 60 s) passed to HTTP client

Without credentials, reports `not_implemented` in JSON output.

See [llm_latency_pending.md](llm_latency_pending.md) for planned streaming benchmarks
and reproducible test fixtures.

## Existing Benchmarks

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/bench_baseline_harness.py` | Baseline metrics for migration | ✅ Active |
| `scripts/bench_elixir_vs_python.py` | Control plane vs Python-only | ✅ Active |
| `scripts/bench_message_transport.py` | Message processing comparison | ✅ Active |
| `benchmarks/bench_message_ops.py` | Message operations (pytest) | ✅ Active |

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PUP_BENCH_QUICK` | Enable quick mode | `0` |
| `PUP_BENCH_OUTPUT` | Output file path | stdout |
| `PUP_BENCH_CATEGORY` | Category filter | `all` |
| `PUP_ANTHROPIC_API_KEY` | Anthropic API key for LLM probe | (none) |
| `PUP_OPENAI_API_KEY` | OpenAI API key for LLM probe | (none) |

Legacy variable names (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are also accepted.

## Output Format

Benchmark results are stored as JSON:

```json
{
  "timestamp": "2026-01-15T10:30:00+00:00",
  "version": "1.1.0",
  "mode": "full",
  "results": [
    {
      "category": "tool_execution",
      "operation": "list_files",
      "approach": "python_offline_primitive",
      "latency_stats": {
        "mean_ms": 5.234,
        "median_ms": 4.891,
        "min_ms": 3.456,
        "max_ms": 12.345,
        "p95_ms": 8.901,
        "p99_ms": 11.234,
        "stdev_ms": 1.567,
        "samples": 50
      },
      "throughput_ops_per_sec": 191.2,
      "metadata": {"file_count": 20, "failures": 0},
      "notes": "Offline filesystem primitive (pathlib.rglob) - not full Code Puppy tool-path"
    }
  ],
  "pending_benchmarks": [],
  "not_implemented": ["llm_latency_no_credentials"],
  "failed_benchmarks": []
}
```

## CI Integration

The benchmark harness is designed for CI:

```yaml
# Example GitHub Actions step
- name: Run self-tests
  run: python scripts/bench_baseline_harness.py --self-test

- name: Run benchmarks
  run: python scripts/bench_baseline_harness.py --quick --output benchmark-results.json

- name: Upload results
  uses: actions/upload-artifact@v4
  with:
    name: benchmark-results
    path: benchmark-results.json
```

## Migration Baseline

These benchmarks establish the performance baseline for the Python-to-Elixir migration tracked in [ROADMAP.md](../../ROADMAP.md).

See also:
- [ADR-004: Migration Strategy](../adr/ADR-004-python-to-elixir-migration-strategy.md)
- [Native Acceleration](../acceleration.md)
