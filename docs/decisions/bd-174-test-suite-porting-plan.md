# bd-174 — Test suite porting plan: Python → Elixir

- **Status**: Proposed
- **Date**: 2026-04-19
- **Owner**: planning-agent-019da7
- **Related**: bd-141 (epic parent), bd-174, bd-132, bd-138
- **Phase**: Phase 8 — Testing & Evaluation

## Executive summary

**Recommendation: 5-wave phased approach, not a one-shot port.** StreamData will be added as a test-only dependency and one pilot property test written to prove the pattern. The 585 Python test files do NOT port 1:1 — the actual port count is ~150–200 files after accounting for Python-specific plumbing, dead code, and code that already has Elixir coverage. Each wave is a separate bd issue; bd-174 closes when Wave 1 lands.

## Current state

### What exists today

- **585 Python test files** in `tests/` — pytest-based, heavy use of `pytest-asyncio`, `unittest.mock`, `pydantic` test helpers.
- **112 Elixir ExUnit test files** in `elixir/code_puppy_control/test/` — covering the Elixir-side modules shipped so far.
- **StreamData NOT in `mix.exs` deps** — no property-testing infrastructure yet.
- **No stated coverage gates per Elixir module** — the Python side has ad-hoc coverage enforcement; the Elixir side has none.

### What this decision adds

- `:stream_data` as a test-only dependency.
- A pilot property test proving the `to_wire`/`from_wire` round-trip invariant for `CodePuppyControl.Stream.Event`.
- A documented 5-wave plan that bounds the remaining work.

## Not all 585 files will port 1:1

Many Python tests are obsolete or irrelevant after the Elixir migration:

| Python test category | Verdict | Rationale |
|---|---|---|
| `asyncio` / `pytest-asyncio` plumbing | **DROP** | No Elixir analog — BEAM processes replace asyncio patterns |
| `pydantic` validation tests | **DROP** | Elixir uses pattern matching + typespecs, not Pydantic |
| `typer` / `rich` / Textual TUI tests | **DROP** | Elixir has no TUI in Phase 8 |
| `native_backend` / `turbo_parse` tests | **DROP** | Dead code removed in bd-208 |
| `code_puppy/config.py` tests | **SKIP** | Superseded by `config/*_test.exs` already landed (bd-164) |
| `plugins/*` tests | **DEFER** | Port only if/when the plugin migrates; most won't in v1 |
| `tools/*` tests | **PORT (spirit)** | Elixir has its own tool behaviour (bd-196); port the contract, not the implementation |
| `agents/*` tests | **PORT** | Elixir agent tests landed in bd-157 |
| `streaming/*` / `messaging/*` | **PORT** | Core pipeline — high value, property-testable |
| `llm/*` / `providers/*` | **PORT** | LLM provider adapters — mock HTTP, verify canonical events |
| `run_manager/*` / `scheduler/*` | **PORT** | Runtime loop — integration-heavy |

**Expected actual port count: ~150–200 files, not 585.**

## Proposed 5-wave plan

### Wave 1 — Infrastructure (this bd-174 deliverable)

**Scope**: Add StreamData, document property-testing conventions, write one pilot property test.

**Deliverables**:
- `mix.exs`: `{:stream_data, "~> 1.0", only: :test}`
- `test/code_puppy_control/stream/event_property_test.exs`: round-trip invariant, JSON survival, index non-negative
- This decision document

**Exit criteria**: All 3 property tests pass; no regressions in existing `event_test.exs`.

**bd-174 closes here.**

### Wave 2 — Core contracts (~30 files)

**Scope**: Tool behaviour, config loader, paths, isolation.

**Why second**: These are the foundation that everything else depends on. Property-test the config loader's merge semantics and the tool behaviour's callback contracts.

**Estimated files**: ~30.

### Wave 3 — Messaging + streaming (~25 files)

**Scope**: Hasher, pruner, normalizer, event.

**Why third**: The streaming pipeline is self-contained and highly property-testable. Codec invariants (round-trip, idempotence, monotonicity) are natural property tests.

**Estimated files**: ~25.

### Wave 4 — LLM layer (~40 files)

**Scope**: Provider, Anthropic/OpenAI adapters, model_factory.

**Why fourth**: Requires mock HTTP infrastructure. Property-test that all provider outputs normalize to the same canonical event set.

**Estimated files**: ~40.

### Wave 5 — Runtime (~50 files)

**Scope**: Agent loop, run_manager, scheduler, MCP.

**Why last**: These are integration-heavy and depend on everything above. Mostly example-based tests with a few state-machine property tests for the scheduler.

**Estimated files**: ~50.

### Wave summary

| Wave | Scope | Files | Property tests? | New bd issue |
|---|---|---|---|---|
| 1 | Infrastructure | 1 (pilot) | Yes (pilot) | bd-174 |
| 2 | Core contracts | ~30 | Config merge, tool callbacks | To be filed |
| 3 | Messaging + streaming | ~25 | Codec invariants | To be filed |
| 4 | LLM layer | ~40 | Provider normalization | To be filed |
| 5 | Runtime | ~50 | Scheduler state machine | To be filed |

## Property-testing conventions

### Pattern

Use `use ExUnitProperties` from `stream_data`. Prefer invariant-style tests over example-based where it adds signal:

| Invariant style | When to use |
|---|---|
| Round-trip (`f(g(x)) == x`) | Codec, serialization, parser pairs |
| Idempotence (`f(f(x)) == f(x)`) | Normalization, pruning, dedup |
| Monotonicity (`f(x) ≤ f(y)` when `x ≤ y`) | Hashing, ordering, scoring |
| Preservation (`P(x) → P(f(x))`) | Type-stable transformations |

### Generators

- Co-located in `test/support/` for reuse across test modules.
- Named `*_gen/0` (e.g., `text_delta_gen/0`, `tool_call_end_gen/0`).
- Use `StreamData` primitives: `string/1`, `non_negative_integer/0`, `one_of/1`, `optional/1`.

### Run configuration

- `max_runs: 100` default.
- `max_runs: 500` for fast pure-function tests (< 1 ms per iteration).
- Shrinking enabled by default (StreamData default behavior).
- **NO property tests that hit the filesystem or network.** Pure-function tests only.

## Coverage gates

### Existing gates (Python side, from CONTRIBUTING.md)

| Module pattern | Minimum coverage |
|---|---|
| `code_puppy/plugins/pack_parallelism/*` | ≥85% |
| `code_puppy/utils/file_display.py` | Integration-tested |
| `code_puppy/tools/command_runner.py` | Security-scanned + tested |

### Proposed gates for Elixir ports

**Rule**: Match the Python coverage floor for the equivalent module. If the Python file had 95% coverage, the Elixir port must too.

Enforcement via `mix test --cover` with threshold configuration. Fail CI below threshold.

| Elixir module pattern | Minimum coverage | Rationale |
|---|---|---|
| `CodePuppyControl.Stream.*` | ≥90% | Codec correctness is critical |
| `CodePuppyControl.Config.*` | ≥85% | Match Python `config.py` gate |
| `CodePuppyControl.LLM.*` | ≥80% | Provider adapters; mock HTTP adds variance |
| `CodePuppyControl.Runtime.*` | ≥75% | Integration-heavy; lower floor acceptable |

## Waves 2–5 as bd issues

Not created by this document. They will be filed **after** bd-174 closes so the plan lives first. Each wave gets its own bd issue with:

- Explicit scope (module list)
- Entry criteria (previous wave green)
- Exit criteria (coverage gate met, no regressions)
- Property test targets listed

## Dependencies this wave adds

| Dependency | Version | Scope | Purpose |
|---|---|---|---|
| `:stream_data` | `~> 1.0` | `only: :test` | Property-based testing framework |

No production dependencies added.

## Risks & mitigations

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-Low | StreamData upgrade churn (v1.x → v2.x) | Low | Low | `~> 1.0` constraint pins the major version; Elixir ecosystem dep stability is high |
| R-Low | Property tests catch real bugs in `lib/` not planned for this wave | Low | Medium | File a new bd issue; do NOT fix in Wave 1. Wave 1 is infrastructure, not bug-fix. |
| R-Medium | Waves 2–5 drift in scope | Medium | Medium | One bd issue per wave with explicit entry/exit criteria. Scope changes require a new decision doc. |

## Follow-up actions

- [ ] Close bd-174 after Wave 1 lands (this session).
- [ ] File 4 new bd issues (one per wave) after bd-174 closes.
- [ ] Add `stream_data` generators to `test/support/` as Wave 2 modules need them.
- [ ] Document coverage gate thresholds in `CONTRIBUTING.md` (separate PR).

## References

- bd-141 — Epic parent: rewrite Code Puppy from Python to Pure Elixir
- bd-132 — Phase tracking issue
- bd-138 — Phase 5 task definition
- bd-164 — Config module migration (already has Elixir tests)
- bd-157 — Agent module migration (already has Elixir tests)
- bd-196 — Tool behaviour implementation
- bd-208 — Removal of native_backend / turbo_parse (dead code)
- bd-181 — LiveView evaluation decision doc (format reference)
- StreamData docs: https://hexdocs.pm/stream_data
- StreamData hex.pm: https://hex.pm/packages/stream_data
