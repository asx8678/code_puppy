# Code Puppy Elixir rewrite bundle

This bundle contains a repo-specific migration plan plus a concrete Elixir port of one Python module.

Included:
- `PLAN/code_puppy_python_to_elixir_plan.md` — step-by-step rewrite order for this repo
- `overlay/elixir/code_puppy_control/lib/code_puppy_control/text/eol.ex` — Elixir port of `code_puppy/utils/eol.py`
- `overlay/elixir/code_puppy_control/test/code_puppy_control/text/eol_test.exs` — unit tests for the port
- `overlay/elixir/code_puppy_control/test/code_puppy_control/file_ops_eol_integration_test.exs` — integration tests for `FileOps.read_file/2`
- `patches/file_ops_eol_integration.patch` — patch that wires the new module into `CodePuppyControl.FileOps`

Suggested apply flow:
1. Copy the `overlay/elixir/code_puppy_control/...` files into the repo root.
2. From the repo root, run:
   `git apply patches/file_ops_eol_integration.patch`
3. Run:
   `cd elixir/code_puppy_control && mix test test/code_puppy_control/text/eol_test.exs test/code_puppy_control/file_ops_eol_integration_test.exs`

Notes:
- The container used to prepare this bundle does not have Elixir installed, so the ExUnit files were written but not executed here.
- The chosen first module is `code_puppy/utils/eol.py` because it is a leaf utility, already matters to file reading behavior, and fits directly into the existing Elixir `FileOps` implementation.
