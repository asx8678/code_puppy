# Code Puppy Roadmap

> Local tracker for planned work. Replaces bd (beads) tracker after its removal in commit `b94b6222`.
>
> Use this file for multi-session work items. For single-session todos, use a scratch file or just remember.

## Format

- `- [ ]` open
- `- [x]` done
- `- [~]` in progress (on a branch)
- `- [?]` blocked / needs decision

Update in the same commit that advances the work. Close an item only when merged to main.

---

## Active

### Phase 0: Pre-port hygiene

Prerequisites before launching the Python-to-Elixir port.

- [x] Remove bd tracker (done — commit `b94b6222`)
- [x] Add local test gates to lefthook (this commit)
- [x] Create ROADMAP.md (this commit)
- [x] Triage 121 pre-existing Elixir test failures (delete / fix / skip-with-reason) — baseline now passes: 5184 tests, 0 failures
- [x] Triage pre-existing ruff errors on Python side (code_puppy-230 — all 44 errors fixed)
- [ ] Choose final naming for the Elixir umbrella app (currently `code_puppy_control`)

### Phase A: Port planning formalization

- [ ] Write ADR-004: Python-to-Elixir migration strategy (scope, phases, rollback)
- [ ] Baseline performance benchmarks (LLM request latency, tool exec overhead)
- [ ] Dependency graph of Python modules — identify leaf modules (port first) vs hub modules (port last)

### Phase B: Elixir LLM client

- [ ] Port `code_puppy/model_factory.py` — provider registry
- [ ] Port `code_puppy/messaging/*` — message types and serialization (partially done in Elixir already)
- [ ] Elixir-native streaming HTTP client for OpenAI / Anthropic / local models
- [ ] Tool-call dispatch plumbing

### Phase C: Base agent port

- [ ] Port `code_puppy/agents/base_agent.py`
- [ ] Port `code_puppy/agents/agent_manager.py`
- [ ] Agent registry in Elixir
- [ ] Behaviour/protocol definitions

### Phase D: Session + state

- [ ] Port session storage (Phoenix PubSub + ETS + disk)
- [ ] Port config system (dual-home isolation, see ADR-003)
- [ ] Port runtime state

### Phase E: Tools

- [ ] Port `code_puppy/tools/*` (file ops, command runner, grep)
- [ ] Port tool permission callbacks

### Phase F: Plugins

- [ ] Design Elixir plugin loader equivalent
- [ ] Port callback system (`code_puppy/callbacks.py`)
- [ ] Port pack-parallelism plugin

### Phase G: CLI + UI

- [ ] Port interactive loop
- [ ] Port command line / slash commands
- [ ] TUI in Elixir (Owl? Ratatouille?)

### Phase H: Cutover

- [ ] Feature-flag Elixir code paths
- [ ] Gradual rollout per capability
- [ ] Delete Python tree when Elixir is at parity

## Deferred / ideas

- [ ] Replace lefthook with Git-native hooks once ported
- [ ] Phoenix LiveView admin UI for pack orchestration
- [ ] Distributed packs (multi-node Erlang cluster)

## Closed

### bd removal (2026-04-24 — commit `b94b6222`)

- [x] Delete bd tracker from project entirely
- [x] Purge Bloodhound agent
- [x] Rewire pack-leader to git-based coordination
- [x] Clean 1,357 bd-NNN references from 248 files
