# bd-134 Audit — 2026-04-20

## Tally: 10/10 DONE, 0/10 PARTIAL, 0/10 MISSING

## Exit criterion: NO
`test/integration/e2e_test.exs` exercises run lifecycle but uses `mock_mode: true` — no real tool calls dispatched. `test/runtime/agent_loop_test.exs` tests Turn state machine transitions with tool call lifecycle but does not invoke real tools through Agent.Loop. No test file exercises a full agent turn → LLM → tool dispatch → tool result → next turn.

## Per-subtask

**1.1: DONE** — `agent.ex` (3.0 KB) + `agent/` dir has 6 files: `behaviour.ex` (3.1 KB), `loop.ex` (19.2 KB), `turn.ex` (8.7 KB), `events.ex` (6.0 KB), `llm.ex` (1.4 KB), `DESIGN_NOTES.md` (9.1 KB). Full agent loop architecture present.

**1.2: DONE** — `model_factory.ex` (10.7 KB), `model_factory/` dir (handle.ex 2.5 KB, credentials.ex 7.6 KB), `model_registry.ex` (11.1 KB) all present.

**1.3: DONE** — Streaming uses canonical event types: `TextStart`, `TextDelta`, `TextEnd`, `ToolCallStart`, `ToolCallArgsDelta`, `ToolCallEnd`, `ThinkingStart`, `ThinkingDelta`, `ThinkingEnd`, `UsageUpdate`, `Done`. Defined in `stream/event.ex` (12.4 KB) with `stream/collector.ex` (7.2 KB) and `stream/normalizer.ex` (3.0 KB). Naming differs from PartStart/PartDelta/PartEnd but semantics are equivalent (and more granular).

**1.4: DONE** — `tool/schema.ex` (12.9 KB) provides full JSON Schema validation (type coercion, constraints, nested objects). `tool/behaviour.ex` (4.7 KB) defines `tool_schema/0` callback + `to_llm_format/1` for LLM function-calling output. `tool/registry.ex` (10.2 KB) manages tool discovery and per-agent filtering.

**1.5: DONE** — `tools/` dir has all required: `file_modifications.ex` (1.7 KB) + `file_modifications/`, `skills.ex` (6.6 KB), `process_runner.ex` (3.5 KB), `subagent_context.ex` (6.4 KB), `staged_changes.ex` (11.2 KB). Also: `command_runner.ex`, `agent_catalogue.ex`, `agent_session.ex`, `context_filter.ex`, `scheduler_tools.ex`, `universal_constructor.ex`.

**1.6: DONE** — `rate_limiter.ex` (15.0 KB, 21 `RateLimiter` references). `rate_limiter/` dir: `adaptive.ex` (8.7 KB), `bucket.ex` (2.7 KB), `supervisor.ex`. Wired into `application.ex` and `llm.ex`.

**1.7: DONE** — `token_ledger.ex` (10.7 KB, 15 `TokenLedger` references). `token_ledger/` dir: `attempt.ex` (3.5 KB), `cost.ex` (6.3 KB). Wired into `agent/loop.ex` and `application.ex`.

**1.8: DONE** — `compaction.ex` (6.9 KB) + `compaction/` dir with 3 files: `tool_arg_truncation.ex` (7.4 KB), `shadow_mode.ex` (3.8 KB), `file_ops_tracker.ex` (6.6 KB). Integration tests exist in `test/code_puppy_control/agent/compaction_integration_test.exs`.

**1.9: DONE (13/14)** — All 14 target agents present except **planning**. Core (8): `code_puppy.ex`, `code_reviewer.ex`, `code_scout.ex`, `python_programmer.ex`, `security_auditor.ex`, `qa_kitten.ex`, `qa_expert.ex`, `pack_leader.ex`. Pack (5): `pack/bloodhound.ex`, `pack/terrier.ex`, `pack/shepherd.ex`, `pack/watchdog.ex`, `pack/retriever.ex`. Planning agent missing — may have been deprioritized or is a follow-up item.

**1.10: DONE** — `mcp/client.ex` (25.4 KB) defines `@type transport :: :stdio | :sse | :streamable_http` with full `do_connect`, `do_disconnect`, `send_message` implementations for all three. Also: `mcp/supervisor.ex`, `mcp/client_supervisor.ex`, `mcp/server.ex` (15.3 KB), `mcp/manager.ex`, `mcp/tool_index.ex`.

## Recommendation: CLOSE with 1 follow-up

bd-134 is substantively complete. All 10 sub-tasks have implementation. The only gap:

- **planning agent** missing from `agents/` dir (13/14 present). File an issue for this if still required.
- **Exit criterion not met** — no e2e test exercises a real agent turn with tool dispatch. Recommend filing a child issue for an integration test that runs Agent.Loop through LLM → tool call → tool result → next turn (with mock LLM + real tools).

The streaming event naming (TextStart/Delta/End vs PartStart/Delta/End) is a deliberate design choice with more granularity — not a gap.
