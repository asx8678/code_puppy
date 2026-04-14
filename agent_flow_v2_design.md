# Agent Flow Visualization V2 — From animation to observability

## The core shift

The current idea is good, but it is still mostly a **live animation of activity**.
A stronger version is a system that treats token movement as a **first-class trace model**.

That means separating three things that are currently blurred together:

1. **Execution graph** — which run/span started, waited, called a tool, delegated, or finished.
2. **Transfer graph** — which payload moved from which producer to which consumer.
3. **Token ledger** — how many tokens were estimated, how many were exact, and when estimates were reconciled.

If those are separate, the UI can show many views from the same data instead of one bespoke graph.

---

## Why the current model plateaus

A single agent-node graph with pulses is useful for demos, but it breaks down on real runs because it cannot answer:

- Who **actually created** the tokens — the parent agent, the child agent, the model, or a tool?
- Which tokens were **input**, **output**, **reasoning**, **tool arguments**, **tool results**, or **history carry-over**?
- Which token counts are **estimated live** versus **exact after provider usage arrives**?
- How much of the input was **system prompt**, **session history**, **retrieved context**, **tool result**, or **subagent response**?
- Where time was spent: model generation, tool wait, queueing, fan-out, retry, or join.

Without that split, the UI can look dynamic while still hiding the important operational truth.

---

## Better mental model

### 1) Node types

Treat the run as a typed multigraph, not a flat agent graph.

Recommended node types:

- `user`
- `agent_run`
- `model_call`
- `tool_call`
- `memory_snapshot`
- `artifact` (file, browser result, terminal output, MCP result)
- `session`

Practical rule:
- an **agent** orchestrates work
- a **model** creates output tokens
- a **tool** returns data
- a **session/history** inflates future prompt size

This is the missing piece behind “who is creating the tokens”.

### 2) Edge types

Represent every meaningful movement as a directed transfer.

Recommended edge types:

- `user_prompt`
- `system_instructions`
- `history_context`
- `retrieved_context`
- `model_input`
- `model_output`
- `tool_args`
- `tool_result`
- `delegate_prompt`
- `delegate_response`
- `artifact_write`
- `artifact_read`
- `memory_append`

### 3) Token classes

Do not use one generic “tokens” number.

Track at least:

- `input_tokens`
- `output_tokens`
- `reasoning_tokens` when available
- `cached_tokens` when available
- `estimated_tokens`
- `billable_tokens`

### 4) Confidence / accounting state

Every live number should be tagged with accounting state:

- `estimated_live`
- `provider_reported_exact`
- `reconciled`
- `unknown`

This lets the UI be honest while still feeling live.

---

## The best visualization is not one visualization

Use one normalized trace stream and render four synchronized views.

### A. Live topology graph
Good for:
- fan-out / fan-in
- delegation chains
- active tool calls
- error hotspots

Rules:
- collapsed mode: `agent_run` nodes only
- expanded mode: split each agent into `agent_run -> model_call -> tool_call`
- show tool nodes only when active or selected

### B. Sequence timeline / waterfall
Good for:
- “what happened when?”
- critical path latency
- idle vs generating vs waiting
- retries and queueing

Rows:
- parent agent
- child agents
- tools
- model calls

Bars:
- running
- waiting on tool
- waiting on subagent
- streaming output

### C. Token Sankey / ledger
Good for:
- “where did the budget go?”
- prompt bloat
- delegation amplification
- tool I/O overhead

Suggested flows:
- user/system/history/retrieval -> model input
- model output -> tool args / child prompt / final answer / memory append
- tool result -> next model input

### D. Replay inspector
Good for:
- debugging one edge or one message
- privacy-aware payload inspection
- comparing estimate vs final usage

On click, show:
- preview / redacted payload
- exact timestamps
- span ids / correlation ids
- token counts by class
- source and destination nodes

---

## The most important new capability: reconciliation

Live streaming cannot be the only source of truth.

A robust system should support this loop:

1. Stream provisional events immediately.
2. Show animated movement using provisional deltas.
3. When the provider returns exact usage, emit reconciliation events.
4. Update the same edge/node totals in place.
5. Mark the run or span as reconciled.

This solves the biggest trust problem in token visualizations: they look precise even when they are not.

---

## What to instrument in Code Puppy

The repo already has the right primitives to build this properly.

### Existing strengths

- callback hooks for agent lifecycle
- callback hooks for tool lifecycle
- streaming part events
- session history replay over WebSocket
- parent/child run context
- existing live graph page

### Missing instrumentation layer

The real gap is **the model boundary**.

Right now the system mostly sees:
- subagent delegation prompt estimates
- stream part deltas
- final usage totals when exposed

To answer “where tokens came from and where they went”, you also want exact capture of:
- model request composition
- model response usage
- tool result payload size / token estimate
- history carried forward into later turns

---

## Recommended architecture for V2

### Layer 1: Trace capture

Emit a normalized event envelope from callbacks and model instrumentation.

Suggested envelope:

```json
{
  "event_id": "uuid",
  "trace_id": "session-or-run-root-id",
  "span_id": "uuid",
  "parent_span_id": "uuid-or-null",
  "run_id": "uuid-or-null",
  "session_id": "string-or-null",
  "event_type": "transfer.chunk",
  "timestamp": "2026-04-14T12:34:56.789Z",
  "node": {
    "kind": "model_call",
    "id": "model-call-123",
    "name": "gpt-5.4"
  },
  "transfer": {
    "kind": "model_output",
    "source_node_id": "model-call-123",
    "target_node_id": "agent-run-456",
    "message_id": "msg-789",
    "token_count": 42,
    "token_class": "output_tokens",
    "accounting": "estimated_live",
    "preview": "partial text..."
  },
  "metrics": {
    "duration_ms": null,
    "cost_usd": null
  }
}
```

### Layer 2: Normalization

Build one reducer that turns raw callback data into:

- spans (`agent_run`, `model_call`, `tool_call`)
- transfers (`delegate_prompt`, `model_output`, `tool_result`, etc.)
- usage reports (`estimated`, `exact`, `reconciled`)

This prevents UI code from knowing about every callback shape.

### Layer 3: Persistence

Do not rely only on WebSocket live state.

Persist the normalized trace so you can:
- reconnect cleanly
- replay a run later
- compare runs
- compute aggregates after the fact
- debug failures that happened before the UI was opened

Good enough first step:
- append NDJSON per session/run

Better step:
- lightweight SQLite trace store keyed by `trace_id`, `span_id`, `message_id`

### Layer 4: Presentation

Keep the browser state derived from the normalized events only.

The UI should never infer semantics directly from raw stream callbacks.

---

## Specific implementation hooks in this repo

### 1) `callbacks.on_agent_run_start` / `callbacks.on_agent_run_end`
Use for:
- `agent_run` span start/end
- parent/child relationships
- final status and duration

### 2) `callbacks.on_pre_tool_call` / `callbacks.on_post_tool_call`
Use for:
- `tool_call` span start/end
- tool arg/result edges
- duration and success

### 3) `callbacks.on_stream_event`
Use for:
- provisional token deltas
- live status changes
- thinking / generating / tool-building states

### 4) model instrumentation boundary
This is where V2 gets much better.

Capture:
- exact model request messages
- exact provider usage when available
- model input/output separation
- reasoning token fields when available

### 5) session history save/load
Use for:
- history growth metrics
- per-session carry-over cost
- replay and lineage

---

## The biggest conceptual upgrade: model calls should be explicit nodes

Today an agent node often absorbs model behavior.
That makes the animation simple but the semantics fuzzy.

A stronger representation is:

```text
User -> AgentRun -> ModelCall -> AgentRun -> ToolCall -> AgentRun -> ChildAgentRun
```

This yields much clearer answers:

- **Who created the response tokens?** The `ModelCall` node.
- **Who forwarded them to a child?** The `AgentRun` node.
- **Who consumed tool results?** The next `ModelCall` node.
- **Why did prompt size grow?** History and tool results feeding later `ModelCall` input.

---

## What “tokens moving” should really mean

There are at least five different kinds of movement:

1. **Prompt assembly**
   - system prompt
   - user prompt
   - retrieved context
   - history
   - tool results

2. **Model generation**
   - streaming output tokens
   - thinking/reasoning tokens when available

3. **Tool invocation**
   - tool argument construction
   - tool result return

4. **Agent delegation**
   - parent -> child prompt
   - child -> parent response

5. **Session carry-over**
   - prior messages that get re-used later

If the UI can switch between these movement classes, it becomes a diagnostic tool instead of a demo.

---

## Metrics worth surfacing

### Efficiency
- delegation amplification ratio = total child input tokens / parent final output tokens
- context carry-over ratio = history tokens / fresh task tokens
- tool overhead ratio = tool arg + tool result tokens / final answer tokens

### Latency
- time to first token
- time to last token
- tool wait time
- critical path duration
- join wait after fan-out

### Reliability
- retries per tool or model
- failed spans per run
- abandoned child runs
- queue wait / backpressure events

### Cost and budget
- estimated vs exact token drift
- billable token total by model
- cost by agent
- cost by tool-driven branch

---

## UX ideas that make the graph more useful

### Expand / collapse depth
- Level 0: only root + child agents
- Level 1: show model nodes
- Level 2: show tools and artifacts

### Honest uncertainty
Use visual encoding for confidence:
- solid = exact
- dashed = estimated
- striped = partially reconciled

### Hover behavior
On edge hover show:
- source -> destination
- token class
- estimated vs exact
- preview / redacted payload
- duration / time window

### Time scrubber
- live mode while running
- replay mode after run ends
- pause, step, speed-up

### Diff mode
Compare two runs:
- which branch cost more
- where prompt size exploded
- which tool caused slowdown

---

## Privacy and safety guardrails

This kind of observability can leak sensitive prompts and tool arguments if it is too literal.

Recommended controls:

- redaction policy per edge type
- payload previews truncated by default
- opt-in full payload inspection
- hash / fingerprint mode for sensitive content
- explicit marking of public vs sensitive tool outputs

---

## A pragmatic rollout plan

### Phase 1 — make the current graph trustworthy
- add accounting state: estimated vs exact
- add reconciliation events
- make model nodes explicit in the reducer
- persist normalized events for replay

### Phase 2 — show real information flow
- add tool result edges
- add history/context source breakdown
- add timeline view
- add per-agent token and latency rollups

### Phase 3 — make it operationally valuable
- Sankey budget view
- compare-runs diff
- outlier detection (loops, huge context carry-over, retry storms)
- export traces for external observability tools

---

## If I were improving the repo next

I would prioritize these four concrete changes:

1. **Introduce a normalized trace event schema**
   - stop making the browser infer semantics from raw callback payloads

2. **Capture exact model request/response spans**
   - this is the missing source of truth for token provenance

3. **Add reconciliation events**
   - live estimates first, exact counts later

4. **Add a second UI mode: timeline**
   - graphs show topology, timelines show truth

That combination turns the feature from “cool live graph” into “real agent observability”.
