# LLM Request Latency Benchmarks (Pending)

**Status:** ⏳ Pending operator-provided credentials
**Issue:** code_puppy-xmx
**Category:** Performance Baseline

## Summary

LLM request latency benchmarks are planned but cannot be run without operator-provided API credentials. This document explains the pending status and requirements.

## Why Pending?

Live LLM benchmarks require authenticated access to provider APIs:

| Provider | Required Credential | Status |
|----------|---------------------|--------|
| Anthropic | `ANTHROPIC_API_KEY` | Requires operator-provided key |
| OpenAI | `OPENAI_API_KEY` | Requires operator-provided key |

**Policy:** We do NOT:
- Invent synthetic LLM latency numbers
- Mock provider responses (not representative)
- Include API keys in repository
- Run benchmarks against production without explicit opt-in

## Required Credentials

To run LLM latency benchmarks, set one or more of these environment variables:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."      # For Claude models
export OPENAI_API_KEY="sk-..."              # For GPT/Codex models
```

## Planned Benchmarks

When credentials are available, these metrics will be collected:

### Time-to-First-Token (TTFT)
- **Definition:** Time from request sent to first token received
- **Why it matters:** User-perceived latency, streaming responsiveness
- **Target models:** claude-sonnet-4, gpt-4o, o3

### Time-Between-Tokens (TBT)
- **Definition:** Inter-token latency during streaming
- **Why it matters:** Smoothness of streaming experience
- **Measurement:** Median and P95 of inter-token gaps

### Total Request Latency
- **Definition:** End-to-end time for complete response
- **Why it matters:** Batch operation planning
- **Variables:** Prompt size, max_tokens, temperature

### Cached vs Non-Cached
- **Definition:** Comparison of cache hit vs miss latencies
- **Why it matters:** Validates cache effectiveness
- **Method:** Repeated identical prompts

## Reproducible Test Fixture

When implemented, benchmarks will use this deterministic prompt:

```python
# TODO(code_puppy-xmx): Implement standardized test prompts
TEST_PROMPTS = {
    "short": "Write a one-sentence Python function that adds two numbers.",
    "medium": "Explain the difference between async/await and threading in Python.",
    "long": "[100-line code review request]",
    "tool_calling": "List all files in the current directory.",  # Forces tool use
}
```

## Implementation Plan

```python
# TODO(code_puppy-xmx): LLM latency benchmark implementation
# 1. Create LLMBenchmark class with provider-agnostic interface
# 2. Implement Anthropic provider (using claude_cache_client)
# 3. Implement OpenAI provider (using model_factory)
# 4. Add streaming vs non-streaming measurement
# 5. Add cache hit/miss detection
# 6. Document results in docs/benchmarks/llm_results_template.md
```

## Current Tool Execution Baseline

While LLM benchmarks are pending, the tool execution overhead baseline is available:

```bash
# Run tool execution benchmarks (offline, deterministic)
python scripts/bench_baseline_harness.py --category tools
```

These establish baseline metrics for:
- `list_files` - Directory traversal
- `read_file` - File reading
- `grep` - Text search

## Running with Credentials

If you have credentials and want to contribute baseline measurements:

```bash
# 1. Set credentials
export ANTHROPIC_API_KEY="your_key"

# 2. Run full benchmark suite (currently skips LLM - not yet implemented)
python scripts/bench_baseline_harness.py

# 3. Results will indicate which benchmarks ran
```

**Note:** Even with credentials, LLM benchmarks are not yet implemented. The harness will detect credentials but report "not yet implemented" until code_puppy-xmx is complete.

## References

- [ROADMAP.md](../../ROADMAP.md) - Migration tracking
- [ADR-004: Migration Strategy](../adr/ADR-004-python-to-elixir-migration-strategy.md)
- [Baseline Harness](../../scripts/bench_baseline_harness.py)
- Issue: code_puppy-xmx
