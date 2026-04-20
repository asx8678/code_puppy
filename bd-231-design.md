# bd-231 E2E Test Design — 2026-04-20

## Strategy

**Chosen: Mocked provider modules (MockLLM + MockAgent)** — not Bypass, not real LLM.

- bd-134's exit criterion is "zero Python involvement" — proving the Elixir stack works end-to-end.
- Existing `test/runtime/agent_loop_test.exs` already uses MockLLM + MockAgent — established convention.
- Mocked modules give deterministic control over stream events, enabling precise assertion ordering.
- Real LLM would be flaky/slow; Bypass adds HTTP noise — providers are tested separately.
- Test value: proving `Loop → LLM → Normalizer → Tool.Runner → Registry → Events` wires together with no Python.

## Chosen stack

- **Mock layer:** In-test `MockLLM` module implementing `Agent.LLM` behaviour (`stream_chat/4`). Emits raw `{:part_start}`, `{:part_delta}`, `{:part_end}`, `{:done}` events exactly as OpenAI/Anthropic providers do — exercising the Normalizer path.
- **Tool under test:** `:command_runner` — real registered built-in tool, deterministic with `echo hello`, exercises full `Runner.invoke → Registry.lookup → permission_check → schema validation → invoke` path.
- **Assertions:** EventBus event ordering, final message history structure, no Python port calls.

## Test file structure

```elixir
defmodule CodePuppyControl.Integration.AgentTurnE2ETest do
  use ExUnit.Case, async: false
  @moduletag :integration
  @moduletag timeout: 30_000

  alias CodePuppyControl.Agent.{Loop, Events}
  alias CodePuppyControl.EventBus

  defmodule E2EAgent do
    @behaviour CodePuppyControl.Agent.Behaviour
    def name, do: :e2e_test_agent
    def system_prompt(_ctx), do: "You are a test agent."
    def allowed_tools, do: [:command_runner]
    def model_preference, do: "test-model-e2e"
    def on_tool_result(_name, _result, state), do: {:cont, state}
  end

  defmodule TextOnlyLLM do
    def stream_chat(_messages, _tools, _opts, cb) do
      cb.({:part_start, %{type: :text, index: 0, id: nil}})
      cb.({:part_delta, %{type: :text, index: 0, text: "Hello ", name: nil, arguments: nil}})
      cb.({:part_delta, %{type: :text, index: 0, text: "world!", name: nil, arguments: nil}})
      cb.({:part_end, %{type: :text, index: 0, id: nil, name: nil, arguments: nil}})
      cb.({:done, %{id: "msg-1", model: "test", content: nil, tool_calls: [],
                     finish_reason: "stop", usage: %{prompt_tokens: 5, completion_tokens: 2, total_tokens: 7}}})
      {:ok, %{text: "Hello world!", tool_calls: []}}
    end
  end

  defmodule ToolCallLLM do
    def stream_chat(messages, _tools, _opts, cb) do
      if Enum.any?(messages, fn m -> m[:role] == "tool" end) do
        cb.({:part_start, %{type: :text, index: 0, id: nil}})
        cb.({:part_delta, %{type: :text, index: 0, text: "Command executed!", name: nil, arguments: nil}})
        cb.({:part_end, %{type: :text, index: 0, id: nil, name: nil, arguments: nil}})
        cb.({:done, %{id: "msg-3", model: "test", content: nil, tool_calls: [], finish_reason: "stop", usage: nil}})
        {:ok, %{text: "Command executed!", tool_calls: []}}
      else
        cb.({:part_start, %{type: :tool_call, index: 0, id: "tc-e2e-1"}})
        cb.({:part_delta, %{type: :tool_call, index: 0, text: nil, name: "command_runner", arguments: nil}})
        cb.({:part_delta, %{type: :tool_call, index: 0, text: nil, name: nil, arguments: "{\"command\": \"echo hello\"}"}})
        cb.({:part_end, %{type: :tool_call, index: 0, id: "tc-e2e-1", name: "command_runner", arguments: "{\"command\": \"echo hello\"}"}})
        cb.({:done, %{id: "msg-2", model: "test", content: nil,
                       tool_calls: [%{id: "tc-e2e-1", name: "command_runner", arguments: %{"command" => "echo hello"}}],
                       finish_reason: "tool_calls", usage: nil}})
        {:ok, %{text: nil, tool_calls: [%{id: "tc-e2e-1", name: "command_runner", arguments: %{"command" => "echo hello"}}]}}
      end
    end
  end

  setup do
    EventBus.subscribe_global()
    on_exit(fn -> EventBus.unsubscribe_global() end)
    :ok
  end
  # ... test blocks below ...
end
```

## Test cases

### 1. Simple text-only turn
Start Loop with `TextOnlyLLM`, max_turns: 1. Call `run_until_done(pid, 10_000)`.
- Assert `state.completed == true`, `state.turn_number == 1`
- Assert EventBus: `agent_turn_started`, `agent_llm_stream` (x2), `agent_turn_ended(:done)`, `agent_run_completed`
- Assert message_count increased (assistant message appended)

### 2. Tool-call turn (single tool)
Start Loop with `ToolCallLLM`, max_turns: 5. Call `run_until_done(pid, 15_000)`.
- Assert `state.completed == true`, `state.turn_number == 2`
- Assert EventBus sequence:
  - `agent_turn_started` → `agent_tool_call_start(command_runner, %{"command" => "echo hello"})` → `agent_tool_call_end({:ok, %{stdout: "hello\n", ...}})` → `agent_turn_ended` (turn 1)
  - `agent_turn_started` → `agent_llm_stream("Command executed!")` → `agent_turn_ended(:done)` (turn 2)
  - `agent_run_completed`
- Assert final messages: user → assistant(nil) → tool result → assistant("Command executed!")

### 3. (Optional) Multi-turn: max_turns boundary
3 text-only turns with a counting MockLLM. Assert exactly 3 turns and completion at boundary.

## Files to create

- `test/integration/agent_turn_e2e_test.exs`

## Files to read (not modify)

- `lib/agent/{loop,turn,behaviour,llm,events}.ex` — core agent loop plumbing
- `lib/stream/{normalizer,event,collector}.ex` — stream event pipeline
- `lib/tool/{runner,registry,behaviour}.ex` — tool dispatch
- `lib/tools/command_runner.ex` — the tool under test
- `lib/llm/providers/openai.ex` — reference for event emission format
- `test/runtime/agent_loop_test.exs` — existing MockAgent/MockLLM pattern
- `test/test_helper.exs` — ExUnit config (:integration excluded by default)

## Risks

- **Timing:** `run_until_done` is synchronous, mock LLM is instant — zero timing risk.
- **Registry not started:** Built-in tools auto-register on init. Verify with `Registry.registered?(:command_runner)` in setup.
- **Mock maintenance:** ~20 lines in-test. Normalizer handles format drift.
- **CommandRunner validator:** `echo hello` may be blocked. Pre-check allowlist; fallback to trivial pure tool.
- **Event ordering:** Collect all events into list, then assert ordering (don't use interleaved `assert_receive`).

## Effort estimate

**~2-3 hours**
- 30 min: Create file + mock modules + setup
- 45 min: Test 1 (text-only)
- 45 min: Test 2 (tool-call) — debug CommandRunner
- 30 min: Test 3 (multi-turn) optional
- 15 min: Run + verify
- 15 min: Polish