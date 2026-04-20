# bd-175 — Port Python evals/ harness to Elixir

**Status:** accepted
**Date:** 2026-04-20
**Phase:** 8.2 (parent: bd-141, rollup: bd-132)
**Owner:** planning-agent-019dac

## Summary

Ported the Python `evals/` LLM evaluation harness (4 files, 4.6 KB) to Elixir so
that Elixir-based agent runs can emit eval logs in the same JSON schema as the
Python harness. This enables cross-runtime parity diffs during Phase 9 dual-run
validation (bd-177).

## Scope

**In scope (this issue):**
- Port `EvalPolicy` enum, `ToolCall` dataclass, `EvalResult` dataclass, `log_eval/2`
- Port `conftest.py` gate mechanism (`RUN_EVALS=1`) to ExUnit
- Port sample eval (`test_sample_eval.py`) to ExUnit
- JSON schema parity gate test (key-for-key, modulo timestamp)

**Out of scope (follow-up issues):**
- Authoring a corpus of real-LLM `:usually_passes` eval cases
- CI nightly eval job wiring
- Parity diff CLI (`mix pup_ex.evals.diff`)

## Decisions

### D1. Shared log directory at repo root

Elixir writes eval logs to `<cwd>/evals/logs/` — the same directory Python writes
to. This intentionally sits OUTSIDE the ADR-003 `~/.code_puppy_ex/` isolation
boundary because:

1. Eval logs are **dev-time artifacts**, not user config or credentials.
2. The entire point of bd-175 is **byte-level parity diffs**; putting logs in
   different directories would require a harness just to find and align them.
3. The directory is `.gitignore`d (or can be), not checked in.

ADR-003's isolation rule targets `~/.code_puppy/` vs `~/.code_puppy_ex/` for
user-level config and sessions. Project-local test artifact dirs (like
`_build/`, `cover/`, and `evals/logs/`) are unaffected.

### D2. Atom policies, string JSON values

Elixir `EvalPolicy` is an atom (`:always_passes | :usually_passes`) but
serializes to the Python string form (`"always_passes" | "usually_passes"`) in
JSON output via `CodePuppyControl.Evals.Policy.to_string/1`.

### D3. Key-order preservation in JSON

Python's `json.dumps` emits keys in insertion order: `name`, `timestamp`,
`model`, `duration_seconds`, `response_text`, `tool_calls`. We preserve this
with `Jason.OrderedObject` (available in jason ~> 1.4). A regression test in
`logger_test.exs` walks raw JSON byte offsets to catch any drift.

### D4. Naive UTC timestamp

Python uses `datetime.now().isoformat()` — **naive local** time. We instead
emit `NaiveDateTime.utc_now() |> NaiveDateTime.to_iso8601()` to avoid
test-host-timezone drift while keeping the Python-compatible naive format
(no trailing `Z` or `+00:00`). Timestamps are excluded from parity diffs
because they always differ per run.

### D5. `async: false` for eval cases

The `CodePuppyControl.Evals.Case` template sets `async: false` because:
- Evals may hit rate-limited real LLM APIs.
- All evals in a run share `evals/logs/` (filesystem contention if two tests
  use the same name — unlikely but possible).

## Artifacts

### Source modules
| File | Role |
|------|------|
| `lib/code_puppy_control/evals.ex` | Umbrella + `log_eval/2` delegate |
| `lib/code_puppy_control/evals/policy.ex` | Policy atom ↔ string |
| `lib/code_puppy_control/evals/tool_call.ex` | `%ToolCall{name, args, result}` |
| `lib/code_puppy_control/evals/result.ex` | `%Result{response_text, tool_calls, ...}` |
| `lib/code_puppy_control/evals/logger.ex` | `log_eval/2`, `sanitize_name/1`, `resolve_log_dir/0` |

### Test infrastructure
| File | Role |
|------|------|
| `test/support/eval_case.ex` | `use CodePuppyControl.Evals.Case` template + `eval_test/2` macro |
| `test/evals/sample_eval_test.exs` | Port of `test_sample_eval.py` |
| `test/fixtures/evals/python_reference.json` | Canonical Python log_eval output |
| `test/code_puppy_control/evals/logger_test.exs` | **Acceptance gate** (parity + unit tests) |
| `test/test_helper.exs` | `RUN_EVALS=1` gate for `:eval` tag |

## Running evals

```bash
# Run everything EXCEPT evals (default)
cd elixir/code_puppy_control
mix test

# Run ONLY the eval suite
RUN_EVALS=1 mix test --only eval

# Run just the parity gate (always on; not tagged :eval)
mix test test/code_puppy_control/evals/logger_test.exs
```

## Parity procedure

```bash
# 1. Capture Python baseline
cd /Users/adam2/projects/code_puppy
RUN_EVALS=1 pytest evals/ -v

# 2. Capture Elixir output with the same eval name
cd elixir/code_puppy_control
RUN_EVALS=1 mix test test/evals/sample_eval_test.exs

# 3. Diff the JSON (timestamps differ by design; ignore them)
diff <(jq 'del(.timestamp)' ../../evals/logs/sample_eval_framework.json) \
     <(jq 'del(.timestamp)' ../../evals/logs/sample_eval_framework.json)
```

(When the real-LLM eval corpus lands in the follow-up issue, this diff will
catch schema drift between the two harnesses before any real LLM disagreement
can mask it.)

## References

- Python source: `evals/__init__.py`, `conftest.py`, `eval_helpers.py`, `test_sample_eval.py`
- Parent epic: bd-141 (Phase 8 — Tests, Evals & Benchmarks)
- Sibling issues: bd-174 (8.1 closed), bd-176 (8.3 perf benchmarks, open)
- Rollup: bd-132 (Python → Elixir rewrite)
- Dual-run validation: bd-177 (Phase 9)
