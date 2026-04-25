# LLM Request Latency Benchmarks

**Status:** 🔑 Implemented, credential-gated — requires operator API keys to run
**Issue:** code_puppy-xmx
**Category:** Performance Baseline

## Summary

LLM request latency benchmarks are implemented in the harness as a
credential-gated probe. They execute live API calls only when
`PUP_ANTHROPIC_API_KEY` or `PUP_OPENAI_API_KEY` is set. Without
credentials, the harness reports `not_implemented` in JSON output and
continues.

**No live baseline numbers are committed to the repository.** Baseline
measurements depend on operator-provided credentials and network
conditions, so they are not reproducible in CI. Operators who run the
probe should record results locally.

## Current Implementation

The probe measures **time-to-first-block (TTFB)** for single-shot API
requests using each provider's SDK with the harness `timeout` setting
(default 60 s) passed to the HTTP client:

| Provider | Model | Credential env var | Status |
|----------|-------|--------------------|--------|
| Anthropic | claude-sonnet-4-20250514 | `PUP_ANTHROPIC_API_KEY` | Implemented |
| OpenAI | gpt-4o-mini | `PUP_OPENAI_API_KEY` | Implemented |

Legacy env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are also
accepted as fallbacks.

## Running the Probe

```bash
# Set credentials
export PUP_ANTHROPIC_API_KEY="sk-ant-..."
export PUP_OPENAI_API_KEY="sk-..."

# Run LLM probe only
python scripts/bench_baseline_harness.py --category llm

# Run full suite (tools + LLM)
python scripts/bench_baseline_harness.py

# Without credentials: reports "not_implemented", no live calls made
```

## Planned Enhancements

The current probe measures only TTFB for single-shot, non-streaming
requests. Planned improvements (tracked in ROADMAP.md):

### Time-to-First-Token (TTFT)
- **Definition:** Time from request sent to first token received
- **Why it matters:** User-perceived latency, streaming responsiveness
- **Requires:** Streaming API integration

### Time-Between-Tokens (TBT)
- **Definition:** Inter-token latency during streaming
- **Why it matters:** Smoothness of streaming experience
- **Measurement:** Median and P95 of inter-token gaps

### Cached vs Non-Cached
- **Definition:** Comparison of cache hit vs miss latencies
- **Why it matters:** Validates cache effectiveness
- **Method:** Repeated identical prompts

### Reproducible Test Fixture

When streaming benchmarks are implemented, they will use deterministic
prompts:

```python
# TODO(code_puppy-xmx): Implement standardized test prompts for streaming
TEST_PROMPTS = {
    "short": "Write a one-sentence Python function that adds two numbers.",
    "medium": "Explain the difference between async/await and threading in Python.",
    "long": "[100-line code review request]",
    "tool_calling": "List all files in the current directory.",  # Forces tool use
}
```

## Tool Execution Baseline (Always Available)

Tool execution overhead benchmarks run offline without credentials:

```bash
python scripts/bench_baseline_harness.py --category tools
```

These establish baseline metrics for:
- `list_files` — Directory traversal
- `read_file` — File reading
- `grep` — Text search

## Policy

- We do NOT invent synthetic LLM latency numbers
- We do NOT mock provider responses (not representative)
- We do NOT include API keys in the repository
- We do NOT commit live baseline numbers (not reproducible in CI)
- We DO run live probes when credentials are available

## References

- [ROADMAP.md](../../ROADMAP.md) — Migration tracking
- [ADR-004: Migration Strategy](../adr/ADR-004-python-to-elixir-migration-strategy.md)
- [Baseline Harness](../../scripts/bench_baseline_harness.py)
- [Benchmarks README](README.md)
- Issue: code_puppy-xmx
