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
- [x] Choose final naming for the Elixir umbrella app (currently `code_puppy_control`) — see [docs/adr/ELIXIR-APP-NAMING.md](docs/adr/ELIXIR-APP-NAMING.md)

### Phase A: Port planning formalization

- [x] Write ADR-004: Python-to-Elixir migration strategy (scope, phases, rollback) — see [docs/adr/ADR-004-python-to-elixir-migration-strategy.md](docs/adr/ADR-004-python-to-elixir-migration-strategy.md)
- [x] Baseline performance harness (tools) — see [docs/benchmarks/README.md](docs/benchmarks/README.md); offline filesystem primitives measured
- [x] Baseline performance harness (LLM latency probe) — credential-gated TTFB probe implemented; requires PUP_ANTHROPIC_API_KEY or PUP_OPENAI_API_KEY; no live baseline numbers committed
- [x] Baseline performance (LLM latency — streaming TTFT/TBT) — streaming probes implemented (credential-gated); live numbers remain operator-local and are not committed; see [docs/benchmarks/llm_latency.md](docs/benchmarks/llm_latency.md)
- [x] Dependency graph of Python modules — see [docs/python_dependency_graph.md](docs/python_dependency_graph.md) — complete: SCC-based topological ordering (dependency-before-importer guaranteed for acyclic edges), relative import semantics fixed, symbol-level deps excluded, self-tests 14/14, reproducible artifacts, semantic sanity verified

### Phase B: Elixir LLM client

- [x] Port `code_puppy/model_factory.py` — provider registry (e0a481dc ProviderRegistry core merge + c2a5738f ModelFactory integration merge; `CodePuppyControl.ModelFactory.ProviderRegistry` backed by Agent; `ModelFactory.provider_module_for_type/1` delegates to `ProviderRegistry.lookup/1`; tests: runtime register/override, `reset_for_test/0`, `list_available/0`, `resolve/1`, malformed non-binary type rejection, provider-map parity — 110 model_factory tests + 29 LLM/parity tests pass)
- [x] Port `code_puppy/messaging/*` — message types and serialization (073335a1, 366101ca, 45cbe34e, 3e67001e; smoke 521/0 across EventBus structured, EventsChannel, messaging, message_core, serializer; Types + Messages facade + split families, WireEvent, Commands, EventBus wire-envelope helpers, EventStore legacy `type` + structured `event_type` filtering)
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
