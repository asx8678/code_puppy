# Code Puppy: practical Python → Elixir rewrite plan

This repo already has a real Elixir control plane in `elixir/code_puppy_control/`, plus a Python ↔ Elixir bridge and a `NativeBackend` adapter. That means the rewrite should **not** start with agents, prompts, or the CLI. The right first moves are the places where Elixir is already the natural home: file IO, supervision, concurrency, scheduling, and repository indexing.

## What is already on the Elixir side

These are strong signs that the migration should continue from the control plane outward:

- `elixir/code_puppy_control/lib/code_puppy_control/file_ops.ex`
- `elixir/code_puppy_control/lib/code_puppy_control/concurrency/*`
- `elixir/code_puppy_control/lib/code_puppy_control/indexer/*`
- `elixir/code_puppy_control/lib/code_puppy_control/hashline_nif.ex`
- `elixir/code_puppy_control/lib/code_puppy_control/turbo_parse_nif.ex`
- `elixir/code_puppy_control/lib/code_puppy_control/scheduler/*`
- `code_puppy/native_backend.py`
- `code_puppy/plugins/elixir_bridge/*`

In other words: the control-plane foundation already exists. The next work is parity, cleanup, and deletion of duplicate Python paths.

## What to replace first

### 1) Freeze the native boundary before porting more code
Make `code_puppy/native_backend.py` the only Python entry point into native functionality.

First callers to clean up:
- `code_puppy/plugins/turbo_executor/orchestrator.py`
- `code_puppy/code_context/explorer.py`
- `code_puppy/security.py`
- `code_puppy/plugins/file_permission_handler/register_callbacks.py`
- `code_puppy/plugins/code_skeleton/skeleton.py`
- any remaining direct uses of `_core_bridge`, `turbo_parse_bridge`, or Python file-op helpers

Why first:
- it stops new migration work from spreading across multiple bridges
- it gives you one fallback story
- it lets you swap Python/Rust/Elixir internals without changing callers again

Exit criteria:
- feature modules call `NativeBackend`
- direct imports of `_core_bridge`, `turbo_parse_bridge`, and ad hoc native shims are limited to the adapter layer

### 2) Port low-risk leaf utilities that affect FileOps semantics
Start with small, self-contained modules whose behavior is easy to prove:

1. `code_puppy/utils/eol.py` → `CodePuppyControl.Text.EOL` **(included in this bundle)**
2. `code_puppy/utils/gitignore.py` → `CodePuppyControl.Gitignore`
3. normalize any remaining path-safety helpers so Python and Elixir apply the same rules

Why these first:
- they are pure functions or almost-pure helpers
- they directly improve correctness in the existing Elixir `FileOps`
- they are low-risk compared with parser or agent orchestration work

### 3) Finish FileOps parity
The Elixir `FileOps` implementation is already the right destination, but it still needs behavior parity with Python.

Replace or align these Python behaviors next:
- EOL normalization and BOM stripping on read
- `.gitignore`-aware filtering for list/grep/indexing
- path validation parity
- line-range behavior and result-shape parity
- any token/size guardrails you want to enforce consistently

Files to touch:
- `elixir/code_puppy_control/lib/code_puppy_control/file_ops.ex`
- `elixir/code_puppy_control/lib/code_puppy_control/indexer/directory_walker.ex`
- `elixir/code_puppy_control/lib/code_puppy_control/indexer/directory_indexer.ex`
- Python callers that still bypass `NativeBackend`

Exit criteria:
- `NativeBackend.list_files/grep/read_file` prefer Elixir by default
- Python fallback remains available, but parity tests are green

### 4) Promote Elixir indexing to the primary path
Repository indexing is already partially on the Elixir side. Make it the default once FileOps parity is solid.

Priority:
- keep the Python-facing API stable
- route `repo_compass` through one result shape
- only delete the Python fallback after parity and performance checks

Files:
- `code_puppy/plugins/repo_compass/turbo_indexer_bridge.py`
- `elixir/code_puppy_control/lib/code_puppy_control/indexer/*`
- `code_puppy/native_backend.py`

### 5) Keep parsing behind the adapter, but do not start there
`turbo_parse` is too large for the first serious Elixir rewrite slice.

The safe path:
- keep parse capabilities hidden behind `NativeBackend`
- replace by language / feature tier, not by crate size
- do symbol extraction and diagnostics before advanced incremental features

Good order:
1. language normalization + capability checks
2. symbol extraction
3. diagnostics
4. folds / highlights
5. incremental parsing + cache sophistication

### 6) Delete duplicate scheduler / control-plane Python paths only after parity
Scheduler and concurrency are exactly the kinds of things Elixir should own. Much of that work is already present.

Do next:
- audit Python-side scheduler duplication
- move operational ownership to Elixir
- keep Python as a worker / agent runtime, not the scheduler of record

### 7) Leave the LLM-heavy and UI-heavy layers in Python for now
These are bad first rewrite targets:
- `code_puppy/agents/*`
- `code_puppy/model_factory.py`
- `code_puppy/command_line/*`
- `code_puppy/tui/*`
- `code_puppy/api/*`
- Pydantic-AI integration, provider SDK glue, prompt-toolkit, Textual, FastAPI

Why:
- they depend on Python-native ecosystems
- there is no immediate operational win from moving them
- they will slow the migration while giving little control-plane leverage

## Recommended PR order

### PR 1 — boundary cleanup
Goal: make `NativeBackend` the only path to native code.

Touch:
- `code_puppy/native_backend.py`
- `code_puppy/plugins/turbo_executor/orchestrator.py`
- `code_puppy/code_context/explorer.py`
- `code_puppy/security.py`
- `code_puppy/plugins/file_permission_handler/register_callbacks.py`
- `code_puppy/plugins/code_skeleton/skeleton.py`

### PR 2 — port `utils/eol.py` into Elixir
Goal: bring BOM + CRLF normalization to Elixir FileOps.

Touch:
- `elixir/code_puppy_control/lib/code_puppy_control/text/eol.ex`
- `elixir/code_puppy_control/test/code_puppy_control/text/eol_test.exs`
- `elixir/code_puppy_control/lib/code_puppy_control/file_ops.ex`

### PR 3 — port `.gitignore` semantics
Goal: make Elixir list/grep/indexing honor the same repo filters as Python.

Touch:
- new Elixir gitignore matcher module
- `file_ops.ex`
- indexer walker/indexer modules
- parity tests against Python fixtures

### PR 4 — make Elixir FileOps the default
Goal: keep Python fallback, but stop treating it as the main implementation.

Touch:
- `code_puppy/native_backend.py`
- `code_puppy/plugins/turbo_executor/orchestrator.py`
- any fallback selection/config docs

### PR 5 — promote Elixir indexing
Goal: default repo structure and search features to Elixir.

### PR 6+ — staged parse migration
Goal: keep the parse surface stable while replacing internals in chunks.

## Chosen first module in this bundle

I picked `code_puppy/utils/eol.py` for the sample rewrite because it checks every box for a first port:

- no model/provider coupling
- no CLI/TUI dependencies
- already relevant to the Elixir `FileOps`
- easy to test with pure input/output fixtures
- adds visible correctness: CRLF normalization and BOM stripping

## Success definition

The rewrite is on the right path when:
- Python callers go through one adapter
- Elixir owns file IO, scheduling, concurrency, and repo indexing
- Python remains the agent/runtime layer where its ecosystem matters most
- duplicate native stories disappear from docs, config, and code
