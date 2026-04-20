# bd-133 Completion Audit — 2026-04-20

## Summary

**Status: DONE** | **Confidence: HIGH** | **Recommendation: CLOSE**

All three deliverables of bd-133 (Phase 0 — Decision Gates & Prerequisites) are complete with concrete evidence.

---

## 0.1 Pure-Elixir scope + UI target decision

**Status: DONE**

### TUI Library Choice — Owl (decided, implemented, shipping)

- Dep: `mix.exs:59` — `{:owl, "~> 0.11"}` / locked `owl 0.13.0`
- TUI app: `lib/code_puppy_control/tui/app.ex` (8.5 KB) — uses `Owl.LiveScreen`
- TUI renderer: `lib/code_puppy_control/tui/renderer.ex` (19.7 KB) — `owl_puts`, `Owl.Data.tag`
- Widgets: `tui/widgets/model_selector.ex` (owl_select/2), `tui/widgets/session_browser.ex`
- Screens: `tui/screens/chat.ex`, `tui/screens/config.ex`, `tui/screens/help.ex`
- Markdown: `tui/markdown.ex` (8.6 KB), Syntax: `tui/syntax.ex` (14.6 KB)
- REPL: `repl/loop.ex:225-226` — `/tui` command
- No Ratatouille dep found in mix.exs

### LiveView Decision — Explicitly Deferred

- ADR: `docs/decisions/bd-181-liveview-evaluation.md` (2026-04-19)
- Decision: Option B — Defer LiveView to Phase 6+
- Rationale: TUI-first user base, zero demand, Phase 5 large (bd-168)
- Follow-up: bd-209 tracks post-v1 revisit
- Confirmed: No `:phoenix_live_view` in mix.exs

---

## 0.2 MIGRATION_MAP.md

**Status: DONE**

- File: `MIGRATION_MAP.md` — 49 KB, generated 2026-04-18
- 518 Python files mapped, ~145,157 total LOC
- 87 PORTED (~28,400 LOC), 24 IN-PROGRESS (~8,200), 156 TODO, 98 DROP-V1, 67 DEFER, 86 TBD
- 7 phases: bd-134 (Agent Runtime) through bd-140 (Distribution)
- Post-bd-167 state: references Owl TUI (bd-136), 87 PORTED files

### Sample mappings:
1. `callbacks.py` (1400 LOC) → CodePuppyControl.EventBus [PORTED]
2. `base_agent.py` (4040 LOC) → CodePuppyControl.Agent.Behaviour [IN-PROGRESS]
3. `command_runner.py` (2170 LOC) → CodePuppyControl.Tools.CommandRunner [PORTED]
4. `mcp_/manager.py` (1240 LOC) → CodePuppyControl.MCP.Manager [PORTED]
5. `config.py` (2800 LOC) → CodePuppyControl.Config [TODO]
6. `tui/app.py` (1060 LOC) → CodePuppyControl.TUI [DEFER]
7. `session_storage.py` (1060 LOC) → CodePuppyControl.Sessions [PORTED]
8. `interactive_loop.py` (880 LOC) → CodePuppyControl.Agent.Loop [PORTED]
9. `pack_parallelism/` (525 LOC) → CodePuppyControl.Concurrency.Limiter [PORTED]
10. `repo_compass/` (325 LOC) → CodePuppyControl.Indexer.RepoCompass [PORTED]

---

## 0.3 Elixir LLM client baseline

**Status: DONE**

### Provider modules (2,096 LOC total)
- `llm.ex` — 282 LOC (facade, routing, rate limiter integration)
- `llm/provider.ex` — 125 LOC (behaviour: chat, stream_chat, supports_tools?)
- `llm/providers/openai.ex` — 517 LOC (SSE streaming, tool calling)
- `llm/providers/anthropic.ex` — 592 LOC (SSE streaming, tool calling)
- `http_client.ex` — 580 LOC (Finch wrapper, retry, streaming)

### Finch: `mix.exs:53` — `{:finch, "~> 0.18"}`, locked 0.21.0
- Pool: 50 connections, 1/scheduler. `Finch.request/4`, `Finch.stream/5`

### Streaming: Full SSE implementation confirmed
- OpenAI: `parse_sse_chunk/2` handles `data: {...}\n\n` + `[DONE]` terminator
- Anthropic: `parse_anthropic_sse_chunk/2` handles `event:`/`data:` format
- Events: `{:part_start}`, `{:part_delta}`, `{:part_end}`, `{:done}`
- Canonical types: TextDelta, ToolCallStart, ToolCallArgsDelta, ToolCallEnd, Done
- Normalizer bridges provider events to canonical; Collector assembles responses

### Tool calling: Full implementation confirmed
- Tool schema: `provider.ex:33-42` — name/description/parameters
- OpenAI: `format_tool/1`, `parse_tool_calls/1`, streaming `tool_calls` delta
- Anthropic: `maybe_put_tools/2`, `extract_content/1`, content_block streaming
- Both: `supports_tools?/0 -> true`
- Provider map: 13 model types routed to OpenAI or Anthropic

### Confirmed closed issues
- bd-221: Provider parity test (`provider_parity_test.exs:3`)
- bd-222: URL building tests (`openai_test.exs:271`)
- bd-223: Extra headers tests (`anthropic_test.exs:282`, `openai_test.exs:352`)
- bd-224: OTP lifecycle tests (`test/llm/otp_lifecycle_test.exs:3`)
- bd-225: State-machine property tests (`test/llm/state_machine_property_test.exs:3`)
- Git: `4f8afaba` closes bd-221..223, `4cb6420a` closes bd-224..227

### Test coverage: 27 files, 8,545 LOC
- `test/code_puppy_control/llm/` — 5 files (1,292 LOC)
- `test/code_puppy_control/stream/` — 7 files (1,991 LOC)
- `test/llm/` — 15 files (5,262 LOC)

---

## Recommended action

**CLOSE bd-133.** All deliverables complete:
1. Owl TUI chosen (dep + 9 modules), LiveView deferred (ADR bd-181), bd-209 filed
2. MIGRATION_MAP.md: 518 files mapped across 7 phases, 87 PORTED
3. LLM baseline: OpenAI + Anthropic on Finch 0.21.0, SSE streaming, tool calling, 27 test files
