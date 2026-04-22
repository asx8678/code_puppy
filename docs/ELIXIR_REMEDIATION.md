# Elixir Control Plane Remediation Plan


## Executive Summary

**Current State**: 5.5/10 implementation quality


The Elixir control plane (`elixir/code_puppy_control/`) implements the coordination layer between Python agent workers and the Phoenix/WebSocket frontend. While the architecture is sound, the implementation suffers from protocol drift, OTP anti-patterns, and correctness bugs that must be addressed before the system is production-ready.

**Main Issues**:
1. **Protocol Drift**: The ADR specifies JSON-RPC 2.0 with Content-Length framing, but implementation mixes framing approaches between modules
2. **Critical Correctness Bugs**: Run ID confusion, request tracking race conditions, and atom exhaustion vulnerabilities
3. **OTP Anti-Patterns**: Polling instead of event-driven state machines, insufficient supervision strategies, and unbounded memory growth vectors

**Recommended Path**: **Fix before expand**. The current foundation is too unstable to build upon. The MCP server uses a direct Elixir Port.

---

## Architecture Decision

Based on the hybrid migration ADR and current implementation audit:

| Component | Verdict | Percentage | Rationale |
|-----------|---------|------------|-----------|
| **Python** | Keep | ~25% | Thin shell: CLI, TUI, agent orchestration only |
| **Elixir** | Keep & Expand | ~75% | ALL runtime operations (file ops, parsing, messages, scheduling) |


**Architecture Summary**:
- **Current**: Python + Elixir — Elixir provides full functionality for all accelerated operations
- **Fallback**: Python-only mode available for environments without Elixir (graceful degradation)
- **Standalone**: Python CLI works without Elixir (using pure Python fallbacks)

---

## Critical Bug Fixes (P0)

### 1. Protocol Unification

**Issue ID**: `ELX-001`

**Problem**: The system uses mixed framing approaches:
- `Protocol.frame/1` generates `Content-Length: N\r\n\r\n{json}` (HTTP-style)
- MCP Server Port uses `{:packet, 4}` (4-byte length prefix)
- Python worker port uses no packet framing (raw binary)

This creates confusion and potential message corruption when messages cross boundaries.

**Code Location**:
- `lib/code_puppy_control/protocol.ex` - HTTP-style framing
- `lib/code_puppy_control/mcp/server.ex:264` - Port opened with `{:packet, 4}`
- `lib/code_puppy_control/python_worker/port.ex:88-95` - Raw binary Port

**Fix Approach**: Standardize on **Content-Length framing everywhere**. Remove `{:packet, 4}` from MCP server.

```elixir
```

**Verification**: All messages in protocol integration tests should parse successfully when mixed in a single buffer.

---

### 2. run_id/worker_pid Bug

**Issue ID**: `ELX-002`

**Problem**: In `Run.Manager.start_run/3`, the worker PID is passed to `Port.start_run/2` which expects a `run_id` string:

```elixir
# lib/code_puppy_control/run/manager.ex:55
{:ok, worker_pid} = PythonWorker.Supervisor.start_worker(run_id),
# ...
PythonWorker.Port.start_run(worker_pid, %{  # <-- BUG: should be run_id
  run_id: run_id,
  # ...
})
```

This causes the Port to fail to start because the via_tuple lookup fails (expects `run_id`, gets `PID`).

**Code Location**: `lib/code_puppy_control/run/manager.ex:61`

**Fix Approach**:

```elixir
# FIX - Pass run_id as first argument:
PythonWorker.Port.start_run(run_id, %{
  run_id: run_id,
  session_id: session_id,
  agent_name: agent_name,
  config: config
})
```

**Verification**: E2E test should successfully start a run and receive events.

---

### 3. RequestTracker Race Condition

**Issue ID**: `ELX-003`

**Problem**: In `PythonWorker.Port.handle_call/3` for `{:call, method, params, timeout}`, a race condition exists:

1. Request is sent to Python via `Port.command/2`
2. A Task is spawned to `await_request/3`
3. If Python responds **before** the Task registers with RequestTracker, the response is lost
4. Task times out waiting for a response that already arrived

**Code Location**: `lib/code_puppy_control/python_worker/port.ex:137-152`

**Current Code (BROKEN)**:
```elixir
def handle_call({:call, method, params, timeout}, from, state) do
  request_id = generate_request_id(state)
  message = Protocol.encode_request(method, params, request_id)
  framed = Protocol.frame(message)

  Port.command(state.port, framed)  # <-- Send FIRST

  # Register AFTER sending - race window here!
  Task.start(fn ->
    case CodePuppyControl.RequestTracker.await_request(request_id, method, timeout) do
      {:ok, result} -> GenServer.reply(from, {:ok, result})
      {:error, reason} -> GenServer.reply(from, {:error, reason})
    end
  end)
  
  {:noreply, %{state | request_counter: state.request_counter + 1}}
end
```

**Fix Approach**: Register the request **before** sending to Python:

```elixir
def handle_call({:call, method, params, timeout}, from, state) do
  request_id = generate_request_id(state)
  
  # Register FIRST to eliminate race window
  CodePuppyControl.RequestTracker.register_request(request_id, from)
  
  # THEN send - any response will find the registered request
  message = Protocol.encode_request(method, params, request_id)
  framed = Protocol.frame(message)
  Port.command(state.port, framed)
  
  # Set timeout timer
  timer_ref = Process.send_after(self(), {:request_timeout, request_id}, timeout)
  
  new_state = %{
    state |
    request_counter: state.request_counter + 1,
    pending_requests: Map.put(state.pending_requests, request_id, %{from: from, timer: timer_ref})
  }
  
  {:noreply, new_state}
end
```

Then in `RequestTracker`, change the API to support registration separate from waiting:

```elixir
@doc """
Register a request for async correlation. Returns immediately.
The caller will be replied to when complete_request/2 is called.
"""
@spec register_request(request_id(), GenServer.from()) :: :ok
def register_request(request_id, from) do
  GenServer.call(__MODULE__, {:register, request_id, from})
end

@impl true
def handle_call({:register, request_id, from}, _from, state) do
  pending = %{
    from: from,
    timestamp: System.monotonic_time(:millisecond)
  }
  
  new_state = %{state | pending: Map.put(state.pending, request_id, pending)}
  {:reply, :ok, new_state}
end
```

**Verification**: Add test where mock Python worker responds immediately (within microseconds) to verify no race.

---

### 4. String.to_atom Security Vulnerability

**Issue ID**: `ELX-004`

**Problem**: User-controlled input is converted to atoms via `String.to_atom/1`. Atoms are not garbage collected, creating a DoS vector where attackers can exhaust the VM atom table (default limit: 1,048,576 atoms).

**Vulnerable Locations**:
- `lib/code_puppy_control/python_worker/port.ex:275` - `String.to_atom(params["status"])`
- `lib/code_puppy_control/run/state.ex:305` - `String.to_atom(status)` in event handling

**Fix Approach**: Use a whitelist pattern instead of dynamic atom creation:

```elixir
# IN port.ex - Replace:
CodePuppyControl.Run.State.set_status(run_id, String.to_atom(params["status"]))

# WITH:
status = parse_status(params["status"])
CodePuppyControl.Run.State.set_status(run_id, status)

defp parse_status("starting"), do: :starting
defp parse_status("running"), do: :running
defp parse_status("completed"), do: :completed
defp parse_status("failed"), do: :failed
defp parse_status("cancelled"), do: :cancelled
defp parse_status(other) do
  Logger.warning("Unknown status: #{inspect(other)}")
  :unknown
end
```

**Verification**: Add property-based test (PropEr/Hypothesis) that random strings never increase atom count:

```elixir
property "status parsing never creates new atoms" do
  forall status <- binary() do
    initial_count = :erlang.system_info(:atom_count)
    parse_status(status)
    :erlang.system_info(:atom_count) == initial_count
  end
end
```

---

### 5. stderr Protocol Corruption

**Issue ID**: `ELX-005`

**Problem**: Python worker Port is opened with `:stderr_to_stdout`, meaning any Python stderr output (logs, warnings, stack traces) will be concatenated with the protocol stream, causing JSON parse failures.

**Code Location**: `lib/code_puppy_control/python_worker/port.ex:88-95`

**Current Code**:
```elixir
port_opts = [
  :binary,
  :use_stdio,
  :exit_status,
  :stderr_to_stdout,  # <-- PROBLEM: stderr corrupts stdout protocol
  args: [script_path, "--run-id", run_id]
]
```

**Fix Approach**: Separate stderr handling:

```elixir
port_opts = [
  :binary,
  :use_stdio,
  :exit_status,
  # REMOVED: :stderr_to_stdout
  {:line, 1024},  # Line-buffered stderr for logging
  args: [script_path, "--run-id", run_id]
]
```

Then handle stderr separately in `handle_info`:

```elixir
@impl true
def handle_info({port, {:data, {:eol, line}}}, %{port: port} = state) do
  # This is stderr output - just log it
  Logger.info("[PythonWorker #{state.run_id}] #{line}")
  {:noreply, state}
end

def handle_info({port, {:data, data}}, %{port: port} = state) do
  # This is stdout (binary) - parse as protocol
  new_buffer = state.buffer <> data
  {messages, rest} = Protocol.parse_framed(new_buffer)
  
  for message <- messages do
    handle_message(message, state.run_id)
  end
  
  {:noreply, %{state | buffer: rest}}
end
```

*Note*: Erlang Ports don't support separate stdout/stderr streams directly. Alternative approaches:
1. Python worker writes logs to file instead of stderr
2. Use external wrapper script that redirects stderr
3. Use `Port.open({:spawn, ...})` with shell redirection (less portable)

**Verification**: Protocol should handle 1000 lines of Python logging without parse errors.

---

### 6. MCP Framing Incompatibility

**Issue ID**: `ELX-006`

**Problem**: MCP Server uses `Protocol.frame/1` (Content-Length) but the Port is configured with `{:packet, 4}` (4-byte length prefix). These are incompatible:

- Content-Length: `Content-Length: 47\r\n\r\n{"jsonrpc":"2.0",...}`
- Length-Prefix: `\x00\x00\x00\x2F{"jsonrpc":"2.0",...}` (47 in big-endian)

**Code Location**: `lib/code_puppy_control/mcp/server.ex` lines 264, 292, 312

**Fix Approach**: Remove `{:packet, 4}` and standardize on Content-Length framing:

```elixir
# lib/code_puppy_control/mcp/server.ex:264
port = Port.open({:spawn_executable, executable}, [
  :binary,
  :exit_status,
  # REMOVED: {:packet, 4}
])
```

Ensure the process speaks Content-Length framing on stdin/stdout.

**Verification**: MCP integration tests should pass with mixed message types (requests, notifications, responses).

---

### 7. Run.Supervisor Bypass in Cancel

**Issue ID**: `ELX-007`

**Problem**: In `Run.State.handle_cast({:cancel, ...})`, the state process calls `WorkerSupervisor.terminate_worker/1` directly, bypassing `Run.Manager` which owns the run lifecycle.

**Code Location**: `lib/code_puppy_control/run/state.ex:284-285`

**Current Code**:
```elixir
def handle_cast({:cancel, reason}, state) do
  # ... state updates ...
  
  # Bypasses Run.Manager!
  if state.worker_pid do
    WorkerSupervisor.terminate_worker(state.run_id)
  end
  
  {:noreply, touch(new_state)}
end
```

This breaks supervision boundaries and can leave orphaned processes if the state GenServer crashes after terminating the worker but before completing cleanup.

**Fix Approach**: The state process should NEVER terminate its own worker. Instead, it should monitor the worker and mark itself failed if the worker dies:

```elixir
def handle_cast({:cancel, reason}, state) do
  new_state = %{
    state
    | status: :cancelled,
      completed_at: DateTime.utc_now(),
      error: reason || "cancelled"
  }

  # REMOVED: WorkerSupervisor.terminate_worker(state.run_id)
  # The worker will be terminated by Run.Manager or its own supervisor

  Logger.info("Run #{state.run_id} cancelled: #{inspect(reason)}")
  {:noreply, touch(new_state)}
end
```

The `Run.Manager.cancel_run/2` already handles worker termination:

```elixir
# lib/code_puppy_control/run/manager.ex:73-76
def cancel_run(run_id, reason) do
  case get_run(run_id) do
    {:ok, _} ->
      PythonWorker.Port.cancel_run(run_id)  # Send cancel signal
      Run.State.cancel(run_id, reason)      # Update state
      :ok
    # ...
  end
end
```

**Verification**: Worker termination should only happen in `Run.Manager` or `PythonWorker.Supervisor`, never in `Run.State`.

---

### 8. sys.pid Elixir PID Serialization Bug

**Issue ID**: `ELX-008`

**Problem**: The `init` function in `PythonWorker.Port` includes `elixir_pid` in the initialize notification:

```elixir
def handle_info(:send_initialize, state) do
  message = Protocol.encode_notification("initialize", %{
    "run_id" => state.run_id,
    "elixir_pid" => :erlang.pid_to_list(self())  # <-- "<0.123.0>" format
  })
  # ...
end
```

The Python side may try to parse this as an integer PID (Unix process ID), causing confusion. The Elixir PID format (`<0.N.0>`) is not a valid integer.

**Fix Approach**: Either remove or clarify the field:

```elixir
def handle_info(:send_initialize, state) do
  message = Protocol.encode_notification("initialize", %{
    "run_id" => state.run_id,
    # Option 1: Remove (Python shouldn't need it)
    # Option 2: Use string to avoid confusion:
    "elixir_node_pid" => inspect(self())  # "#PID<0.123.0>"
  })
  # ...
end
```

**Verification**: Python worker should not attempt to use `elixir_pid` as a Unix PID for signaling.

---

## OTP Pattern Fixes (P1)

### MCP.Server Rewrite

**Issue**: Current MCP.Server has health check logic mixed with business logic, uses polling instead of reacting to events, and has complex quarantine logic that should be handled at a higher level.

**Fix**: Refactor into a proper state machine:

```elixir
defmodule CodePuppyControl.MCP.Server do
  use GenServer, restart: :temporary  # Don't auto-restart crashed servers
  
  # State machine states
  @states [:starting, :healthy, :degraded, :quarantined, :stopped]
  
  # ...
  
  @impl true
  def init(opts) do
    # ... setup ...
    
    # Start in :starting, transition on first successful response
    state = %__MODULE__{
      server_id: server_id,
      status: :starting,
      # ...
    }
    
    # Send initial ping to check health
    send(self(), :check_health)
    {:ok, state}
  end
  
  @impl true
  def handle_info(:check_health, state) do
    case do_ping(state) do
      :ok -> 
        {:noreply, %{state | status: :healthy, error_count: 0}}
      {:error, reason} ->
        new_state = handle_health_failure(state, reason)
        {:noreply, new_state}
    end
  end
  
  defp handle_health_failure(%{status: :starting} = state, reason) do
    # Failed on first health check - crash and let supervisor decide
    {:stop, {:startup_failed, reason}, state}
  end
  
  defp handle_health_failure(%{error_count: count} = state, reason) when count >= 2 do
    # Too many failures - quarantine
    quarantine_until = DateTime.add(DateTime.utc_now(), quarantine_duration(count), :second)
    schedule_health_check(quarantine_until)
    %{state | status: :quarantined, quarantine_until: quarantine_until}
  end
  
  defp handle_health_failure(state, reason) do
    # Single failure - mark degraded
    %{state | status: :degraded, error_count: state.error_count + 1}
  end
end
```

### Run.Manager Event-Driven

**Issue**: `Run.Manager.await_run/3` uses polling with `Process.sleep/1` instead of subscribing to PubSub events.

**Fix**: Replace polling with event subscription:

```elixir
def await_run(run_id, timeout_ms \\ 30_000) do
  # Subscribe to run events
  Phoenix.PubSub.subscribe(CodePuppyControl.PubSub, "run:#{run_id}")
  
  start_time = System.monotonic_time(:millisecond)
  
  try do
    do_await_run(run_id, start_time, timeout_ms)
  after
    Phoenix.PubSub.unsubscribe(CodePuppyControl.PubSub, "run:#{run_id}")
  end
end

defp do_await_run(run_id, start_time, timeout_ms) do
  receive do
    {:run_event, %{"type" => "completed"} = event} ->
      {:ok, Map.get(event, "result", %{})}
      
    {:run_event, %{"type" => "failed", "error" => error}} ->
      {:error, error}
      
    {:run_event, %{"type" => "cancelled"}} ->
      {:ok, :cancelled}
      
  after
    timeout_ms ->
      elapsed = System.monotonic_time(:millisecond) - start_time
      if elapsed >= timeout_ms do
        {:timeout, get_run(run_id)}
      else
        # Still waiting, recurse with remaining time
        do_await_run(run_id, start_time, timeout_ms - elapsed)
      end
  end
end
```

### Unbounded History Caps

**Issue**: `Run.State.request_history` and `events` lists grow without bounds for long-running sessions.

**Fix**: Add circular buffer with max size:

```elixir
defstruct [
  # ... existing fields ...
  request_history: [],
  events: [],
  max_history_size: 10_000  # Configurable
]

@impl true
def handle_cast({:record_request, request}, state) do
  entry = %{
    type: :request,
    timestamp: DateTime.utc_now(),
    data: request
  }
  
  # Keep only last N entries
  new_history = 
    [entry | state.request_history]
    |> Enum.take(state.max_history_size)
  
  {:noreply, %{state | request_history: new_history}}
end
```

Also add this to `EventStore` if not already present (it has `@max_events_per_session 1000` - verify this is enforced).

---

## Migration Roadmap

### Phase 1: Protocol Stabilization (Week 1)

**Goals**: Fix critical bugs, unify protocol implementation

**Tasks**:
1. Fix `ELX-001` - Remove `{:packet, 4}` from MCP server
2. Fix `ELX-002` - Pass `run_id` instead of `worker_pid`
3. Fix `ELX-004` - Replace all `String.to_atom` with whitelist functions
4. Add protocol conformance test suite

**Success Criteria**: 
- All protocol integration tests pass
- No atom leakage in property tests

### Phase 2: Correctness Fixes (Week 2)

**Goals**: Fix race conditions and security issues

**Tasks**:
1. Fix `ELX-003` - Refactor RequestTracker to register-before-send
2. Fix `ELX-005` - Separate stderr from protocol stream
3. Fix `ELX-007` - Remove worker termination from Run.State
4. Fix `ELX-008` - Fix PID serialization

**Success Criteria**:
- Race condition test passes (1000 rapid requests)
- No stderr corruption in load test
- Clean process tree after run cancellation

### Phase 3: OTP Pattern Cleanup (Week 3)

**Goals**: Implement proper OTP patterns

**Tasks**:
1. Rewrite MCP.Server as state machine
2. Convert Run.Manager.await_run to event-driven
3. Add history caps to Run.State
4. Add comprehensive metrics/logging

**Success Criteria**:
- No polling loops
- Bounded memory usage
- Proper state machine visualization possible

### True Interop Tests

**Current Problem**: Tests use `MockPythonWorker` which doesn't test actual Port communication.

**Required Tests**:

```elixir
defmodule CodePuppyControl.TrueInteropTest do
  use ExUnit.Case
  
  @moduledoc """
  Tests actual Python worker spawn and communication.
  Requires Python environment with code_puppy installed.
  """
  
  @tag :integration
  @tag :requires_python
  test "start python worker and exchange messages" do
    # Spawn real Python worker
    {:ok, worker_pid} = PythonWorker.Supervisor.start_worker("test-run-#{System.unique_integer()}")
    
    # Send initialize
    :ok = PythonWorker.Port.send_initialize(worker_pid)
    
    # Wait for response
    assert_receive {:python_notification, %{"method" => "initialize_ack"}}, 5000
    
    # Clean up
    PythonWorker.Supervisor.terminate_worker("test-run-#{System.unique_integer()}")
  end
  
  @tag :integration
  @tag :requires_python
  test "handles python crash gracefully" do
    {:ok, worker_pid} = PythonWorker.Supervisor.start_worker("crash-test")
    
    # Send kill signal via special method
    PythonWorker.Port.call("crash-test", "sys.exit", %{"code" => 1})
    
    # Verify Elixir detects exit
    assert_receive {:DOWN, _ref, :process, ^worker_pid, {:port_exit, 1}}, 5000
  end
end
```

### Protocol Conformance Tests

Test all message types per ADR-001:

| Message Type | Direction | Test |
|--------------|-----------|------|
| `initialize` | E→P | Worker receives and responds |
| `run.start` | E→P | Run begins, status updates |
| `run.cancel` | E→P | Run terminates gracefully |
| `run.status` | P→E | Elixir stores authoritative status |
| `run.event` | P→E | PubSub broadcast in order |
| `run.completed` | P→E | Run state updated, worker cleaned up |
| `run.failed` | P→E | Error propagated, worker restarted |

### Load Testing for Race Conditions

```elixir
defmodule CodePuppyControl.RaceConditionTest do
  use ExUnit.Case
  
  @tag :stress
  @tag :slow
  test "1000 concurrent requests all resolve correctly" do
    {:ok, _} = RequestTracker.start_link()
    
    # Fire 1000 concurrent requests
    tasks = for i <- 1..1000 do
      Task.async(fn ->
        request_id = "req-#{i}"
        # Mock worker responds immediately
        spawn(fn ->
          Process.sleep(:rand.uniform(10))  # Random delay 0-10ms
          RequestTracker.complete_request(request_id, %{"index" => i})
        end)
        
        # This should always succeed if no race
        assert {:ok, %{"index" => ^i}} = 
          RequestTracker.await_request(request_id, "test", 5000)
      end)
    end
    
    # All should complete successfully
    results = Task.await_many(tasks, 10_000)
    assert Enum.all?(results, &match?(:ok, &1))
  end
end
```

---

## Success Criteria

Before the Elixir control plane can be considered "stable":

| Criteria | Verification |
|----------|--------------|
| **All P0 issues resolved** | Checklist audit of ELX-001 through ELX-008 |
| **One canonical protocol** | All modules use `Protocol.frame/1` and `Protocol.parse_framed/1` |
| **Real end-to-end tests passing** | `@tag :requires_python` tests pass in CI |
| **Clean `bd ready` output** | No high-priority beads issues related to Elixir |
| **Memory bounded** | 1000 runs don't exhaust atom table or heap |
| **Clean shutdown** | `Application.stop(:code_puppy_control)` terminates all children cleanly |
| **Crash recovery** | Worker crash restarts run, no orphan processes |

---

## Code Repository Structure

Post-remediation, the Elixir directory should be organized as:

```
elixir/code_puppy_control/
├── lib/
│   ├── code_puppy_control/
│   │   ├── application.ex      # OTP application callback
│   │   ├── protocol.ex         # JSON-RPC framing (canonical)
│   │   ├── event_bus.ex        # PubSub wrappers
│   │   ├── event_store.ex      # ETS-based event storage
│   │   ├── request_tracker.ex  # Async request correlation
│   │   ├── run/
│   │   │   ├── manager.ex      # High-level API (P0 fixes)
│   │   │   ├── state.ex        # Per-run state machine (P1 fixes)
│   │   │   ├── supervisor.ex   # DynamicSupervisor
│   │   │   └── registry.ex     # run_id → pid lookup
│   │   ├── python_worker/
│   │   │   ├── port.ex         # Port owner (P0 fixes)
│   │   │   └── supervisor.ex   # Worker supervision
│   │   └── mcp/
│   │       ├── server.ex       # State machine (P1 rewrite)
│   │       ├── supervisor.ex
│   │       └── manager.ex      # Optional: pool MCP servers
│   └── code_puppy_control_web/  # Phoenix channels/controllers
├── test/
│   ├── unit/                    # Fast, isolated tests
│   ├── integration/             # Component interaction tests
│   └── interop/                 # Real Python worker tests (@tag :requires_python)
└── priv/
    └── python_worker.py         # Python side of the bridge (if shipped with)
```

---

## Appendices

### A: Anti-Pattern Reference

| Anti-Pattern | Location | Fix |
|--------------|----------|-----|
| Dynamic atom creation | `port.ex:275`, `state.ex:305` | Whitelist function |
| Polling loops | `manager.ex:156-176` | PubSub subscription |
| GenServer terminating other processes | `state.ex:284-285` | Supervisor hierarchy |
| Race-prone request tracking | `port.ex:137-152` | Register-before-send |
| Mixed framing approaches | `mcp/server.ex:264` | Standardize on Content-Length |
| Unbounded list growth | `state.ex` history fields | Circular buffer |

### B: Testing Commands

```bash
# Run all tests except interop
cd elixir/code_puppy_control
mix test --exclude requires_python

# Run integration tests only
mix test --include integration --exclude requires_python

# Run stress tests
mix test --include stress --timeout 120000

# Run with real Python (requires code_puppy Python package installed)
mix test --include requires_python

# Check for atom leaks
mix run -e "
  initial = :erlang.system_info(:atom_count)
  for i <- 1..10000 do
    CodePuppyControl.Protocol.parse_status(\"random_#{i}\")
  end
  final = :erlang.system_info(:atom_count)
  IO.puts(\"Atoms created: #{final - initial}\")  # Should be 0
"
```

### C: Monitoring Checklist

In production, monitor these metrics:

```elixir
# Atoms (should be stable)
:erlang.system_info(:atom_count)
:erlang.system_info(:atom_limit)

# ETS tables (EventStore)
length(:ets.all())
:ets.info(:event_store, :size)

# Process counts
Process.count()
DynamicSupervisor.count_children(CodePuppyControl.Run.Supervisor)
DynamicSupervisor.count_children(CodePuppyControl.PythonWorker.Supervisor)

# Pending requests
CodePuppyControl.RequestTracker.stats()
```

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-14  
**Owner**: Code Puppy Architecture Team  
**Status**: DRAFT - Pending review
