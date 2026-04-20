# bd-170: Replace DBOS Workflows with Oban Pro / Ecto State Machine

## Assessment Summary

**Status: ✅ Oban scaffold complete — Python DBOS is optional/soft-deprecated**

The Elixir side already has a fully-functional Oban-based workflow system. The Python DBOS usage is guarded by `try/except ImportError` and `get_use_dbos()` config flags — it degrades gracefully when DBOS is unavailable. No active DBOS workflows need porting; the replacement architecture is already in place.

---

## What Exists (Elixir — Oban Side)

### 1. Workflow Step Schema (`CodePuppyControl.Workflow.Step`)
- **File**: `elixir/code_puppy_control/lib/code_puppy_control/workflow/step.ex`
- **Purpose**: Ecto schema for step-level idempotency tracking
- **State machine**: `pending → running → completed | failed | cancelled`
- **Key features**:
  - `{workflow_id, step_name}` unique constraint → exactly-once semantics
  - `execute/4` — idempotent step execution (returns cached result on re-execution)
  - Retry tracking via `attempt`/`max_attempts`
  - Result storage for step replay
- **Migration**: `20250419000001_create_workflow_steps.exs`

### 2. Agent Invocation Worker (`CodePuppyControl.Workers.AgentInvocation`)
- **File**: `elixir/code_puppy_control/lib/code_puppy_control/workers/agent_invocation.ex`
- **Purpose**: Oban worker that replaces `DBOSAgent` from pydantic_ai
- **Three-step workflow**: `initialize → run_agent → finalize`
- **Configuration**: queue `:workflows`, max_attempts 3, unique by `[:worker, :args]`
- **Integration**: Uses `Run.Manager.start_run/await_run` for actual agent execution

### 3. Workflow Facade (`CodePuppyControl.Workflow`)
- **File**: `elixir/code_puppy_control/lib/code_puppy_control/workflow.ex`
- **Public API**:
  - `invoke_agent/2` — Start a durable workflow (idempotent by workflow_id)
  - `get_status/1` — Query workflow state (job + steps)
  - `cancel/1` — Cancel a running workflow (cancels Oban job + marks steps)
  - `get_history/1` — Get step execution history
  - `list_recent/1` — List recent workflows
- **DBOS migration mapping** documented in module doc

### 4. Scheduler Worker (`CodePuppyControl.Scheduler.Worker`)
- **File**: `elixir/code_puppy_control/lib/code_puppy_control/scheduler/worker.ex`
- **Purpose**: Oban worker for cron-scheduled tasks
- **Queue**: `:scheduled`, max_attempts 3

### 5. Infrastructure
- **Oban config**: `config/config.exs` — Lite engine (SQLite), queues: `default`, `scheduled`, `workflows`
- **Test config**: `config/test.exs` — `testing: :inline`, Basic engine
- **Oban in supervision tree**: `application.ex` — child #22
- **Migrations**:
  - `20250414000001_create_oban_jobs.exs`
  - `20250414000003_create_oban_meta.exs`
  - `20250419000001_create_workflow_steps.exs`
  - `20250414000002_create_scheduled_tasks.exs`

### 6. Tests (38 passing)
- `test/code_puppy_control/workflow/step_test.exs` — 26 tests
- `test/code_puppy_control/workflow/workflow_test.exs` — 12 tests
- `test/code_puppy_control/workers/agent_invocation_test.exs` — Simulated step flow

---

## What Exists (Python — DBOS Side)

### DBOS Usage Map

| File | DBOS Usage | Nature |
|------|-----------|--------|
| `code_puppy/dbos_utils.py` | `is_dbos_initialized()`, `initialize_dbos()`, `reinitialize_dbos()` | Utility module (57 refs) |
| `code_puppy/config.py` | `DBOS_DATABASE_URL`, `get_use_dbos()` | Config gating |
| `code_puppy/app_runner.py` | `DBOS.launch()`, `DBOS.destroy()` | Lifecycle |
| `code_puppy/cli_runner.py` | `DBOS.destroy()` | Lifecycle |
| `code_puppy/agents/base_agent.py` | `DBOS.step()`, `SetWorkflowID()`, `DBOSAgent`, `cancel_workflow_async()` | Agent execution |
| `code_puppy/tools/agent_tools.py` | `DBOSAgent`, `SetWorkflowID()`, `_generate_dbos_workflow_id()`, `cancel_workflow_async()` | Sub-agent invocation |
| `code_puppy/plugins/clean_command/` | `DBOS.destroy()`, `reinitialize_dbos()` | Cleanup |

### Key Observations

1. **All DBOS imports are guarded**: Every `from dbos import ...` is wrapped in `try/except ImportError` with graceful fallback to `None`
2. **Feature-gated**: `get_use_dbos()` returns `False` if `dbos` package is not installed OR `enable_dbos` is set to `false` in `puppy.cfg`
3. **Default behavior**: DBOS is *enabled* by default, but optional — the codebase works without it
4. **DBOSAgent from pydantic_ai**: The `pydantic_ai.durable_exec.dbos.DBOSAgent` wrapper is used alongside raw DBOS API
5. **No custom DBOS workflows**: The codebase doesn't define `@DBOS.workflow` or `@DBOS.step` decorated functions — it only uses DBOS's context manager (`SetWorkflowID`) and the `DBOSAgent` wrapper

---

## Migration Mapping (DBOS → Oban)

| DBOS Concept | Oban Equivalent | Status |
|-------------|-----------------|--------|
| `DBOS()` initialization | `Oban` in app supervision tree | ✅ Done |
| `DBOS.launch()` / `DBOS.destroy()` | Oban starts/stops with OTP app | ✅ Done |
| `DBOSAgent(agent, name)` | `Workers.AgentInvocation` | ✅ Done |
| `SetWorkflowID(id)` | `unique: [fields: [:worker, :args]]` + `workflow_id` arg | ✅ Done |
| `DBOS.cancel_workflow_async(id)` | `Workflow.cancel/1` | ✅ Done |
| `DBOS.step()` decorator | `Workflow.Step.execute/4` | ✅ Done |
| Step-level idempotency | `{workflow_id, step_name}` unique constraint | ✅ Done |
| System database (Postgres) | SQLite via `oban_jobs` table | ✅ Done |
| Retry with backoff | Oban built-in retry with exponential backoff | ✅ Done |

---

## Changes Made in This Branch

1. **Added `cancelled` to `@valid_states`** in `Workflow.Step` — previously only `~w(pending running completed failed)`, but the `Workflow.cancel/1` function sets steps to `"cancelled"` state. Now properly validated.
2. **Updated `cancel_steps/1`** in `Workflow` facade to use `Step.changeset/2` instead of raw `Ecto.Changeset.change/2` — ensures validation runs on cancellation transitions.
3. **Added `cancelled` state handling** in `Step.start/1` — attempting to start a cancelled step returns `{:error, :cancelled}`.
4. **Updated `Step` module docs** to document the `cancelled` lifecycle state.

---

## Remaining Work (Future PRs)

### Python → Elixir Bridge Integration
- **Priority**: Medium (requires Elixir bridge to be running)
- When the Elixir bridge is connected, Python agent invocations should route through `Workflow.invoke_agent/2` instead of `DBOSAgent`
- Add a bridge method like `call_method('workflow.invoke_agent', params)` in the Python elixir_bridge plugin
- This makes the Python side a thin client that delegates to the Elixir Oban system

### Python DBOS Deprecation Path
- **Phase 1** (this PR): Document that DBOS is superseded by Oban
- **Phase 2**: When bridge integration is stable, change `get_use_dbos()` default to `False`
- **Phase 3**: Remove `dbos` from `pyproject.toml` dependencies, remove `dbos_utils.py`

### Additional Workers
- `Workers.FileOperation` — Durable file operations with step tracking
- `Workers.BatchProcessing` — Batch file operations with progress tracking
- These would use the same `Workflow.Step` idempotency model

---

## Test Results

```
38 tests, 0 failures
- step_test.exs: 26 tests (changeset, state machine, retriable, execute)
- workflow_test.exs: 12 tests (invoke, status, cancel, history, list_recent)
- agent_invocation_test.exs: Tests config + simulated step flow
```
