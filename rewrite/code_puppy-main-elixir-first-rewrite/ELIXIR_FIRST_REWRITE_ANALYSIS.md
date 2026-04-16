# Elixir-first rewrite analysis

## What should be rewritten first?

The best first Python → Elixir rewrite slice in this repo is the **Repo Compass indexing path**:

- Python entrypoint today: `code_puppy/plugins/repo_compass/indexer.py`
- Python bridge caller: `code_puppy/native_backend.py::index_directory()`
- Elixir execution surface: `CodePuppyControl.PythonWorker.Port.handle_file_request("index_directory", ...)`

## Why this slice first

1. It already sits behind a stable adapter (`NativeBackend.index_directory()`), so the port does not require broad application rewiring.
2. It is bounded and low-risk compared with agent orchestration, model routing, or token-pruning hot paths.
3. It directly improves prompt construction quality for Repo Compass, which affects many user-facing runs.
4. The repo already contains Elixir indexing primitives, so this is a realistic incremental migration instead of a greenfield rewrite.
5. It avoids touching the Rust-critical paths (`code_puppy_core`, `turbo_parse`) where Elixir would be a riskier first move.

## What I changed

### Added
- `elixir/code_puppy_control/lib/code_puppy_control/indexer/repo_compass.ex`
  - New Elixir port of the compact Python Repo Compass structure-map builder.
  - Preserves the prompt-oriented output shape used by Repo Compass.
  - Produces Python-style symbol summaries such as:
    - `class Greeter methods=hello,later`
    - `def wave(person, times)`

### Updated
- `elixir/code_puppy_control/lib/code_puppy_control/indexer.ex`
  - Added delegates for `repo_compass_index/2` and `repo_compass_index!/2`.
- `elixir/code_puppy_control/lib/code_puppy_control/python_worker/port.ex`
  - Routed `index_directory` requests through the new Repo Compass indexer instead of the broader generic indexer.

### Added tests
- `elixir/code_puppy_control/test/code_puppy_control/indexer/repo_compass_test.exs`
  - Covers parity-oriented behavior, limits, ordering, and error handling.

## Why I did not pick these first

- **Agent runtime / orchestration**: too wide, too stateful, too much blast radius.
- **Message core / pruning**: currently performance-sensitive and already optimized in Rust.
- **General file tools** (`list_files`, `grep`, `read_file`): important, but the repo already has an Elixir implementation; Repo Compass indexing was the cleaner bounded gap to close first.
- **Parse / tree-sitter**: larger migration and already partially represented by the Elixir/Rust NIF surface.

## Recommended next slices after this

1. Finish the rest of the `turbo_ops`-style prompt/file surface in Elixir (`list_files`, `grep`, `read_file`, `read_files`) and make the Elixir transport available outside bridge mode.
2. Merge Repo Compass and generic indexing behavior intentionally instead of letting them drift.
3. Only after that, tackle broader parse-routing cleanup.

## Validation note

I could not run `mix test` in this environment because the Elixir toolchain (`mix`) is not installed here, so this change is provided as a code-level rewrite with parity-oriented tests included for you to run locally.
