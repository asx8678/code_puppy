# Python↔Elixir Protocol Comparison Table

## Quick Reference - Critical Mismatches

| Category | Python Implementation | Elixir Implementation | Status |
|----------|----------------------|----------------------|--------|
| **Framing** | Content-Length or newline | Content-Length only | ✅ Compatible |
| **JSON-RPC** | 2.0 standard | 2.0 standard | ✅ Compatible |

---

## Methods (Elixir → Python Requests)

| Elixir Sends | Python Handles | Status | Impact |
|--------------|----------------|--------|--------|
| `initialize` | ❌ No handler | 🔴 Missing | Worker won't initialize properly |
| `run/start` | ❌ Not supported | 🔴 **CRITICAL** | Cannot start runs |
| `run/cancel` | ❌ Not supported | 🔴 **CRITICAL** | Cannot cancel runs |
| `exit` | ❌ Not supported | 🔴 **CRITICAL** | Cannot shutdown gracefully |
| `invoke_agent` | ✅ Yes | ✅ Works | Core functionality works |
| `run_shell` | ✅ Yes | ✅ Works | Shell commands work |
| `file_list` | ✅ Yes | ✅ Works | File listing works |
| `file_read` | ✅ Yes | ✅ Works | File reading works |
| `file_write` | ✅ Yes | ✅ Works | File writing works |
| `grep_search` | ✅ Yes | ✅ Works | Search works |
| `get_status` | ✅ Yes | ✅ Works | Status checks work |
| `ping` | ✅ Yes | ✅ Works | Health checks work |

**Summary**: 3 critical methods missing, 8 basic methods work

---

## Events (Python → Elixir Notifications)

| Python Emits | Elixir Expects | Status | Impact |
|--------------|----------------|--------|--------|
| `event` (generic) | `run.event` | 🔴 **WRONG NAME** | Events ignored |
| `event` (generic) | `run.status` | 🔴 **WRONG NAME** | Status not updated |
| `event` (generic) | `run.completed` | 🔴 **WRONG NAME** | Runs never complete |
| `event` (generic) | `run.failed` | 🔴 **WRONG NAME** | Failures not reported |
| `event` (generic) | `run.text` | 🔴 **WRONG NAME** | Text not streamed |
| `event` (generic) | `run.tool_result` | 🔴 **WRONG NAME** | Tool results lost |
| `event` (generic) | `run.prompt` | 🔴 **WRONG NAME** | Prompts not forwarded |
| `bridge_ready` | ❌ Not expected | 🔴 **UNKNOWN** | Lifecycle not handled |
| `bridge_closing` | ❌ Not expected | 🔴 **UNKNOWN** | Lifecycle not handled |

**Summary**: 100% event method mismatch - NO events will be processed by Elixir

---

## Event Structure (Params Format)

### Python Sends:
```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "event_type": "tool_output",
    "run_id": "run-123",
    "session_id": "sess-456",
    "timestamp": 1713123456789,
    "payload": {"command": "ls", "output": "..."}
  }
}
```

### Elixir Expects:
```json
{
  "jsonrpc": "2.0",
  "method": "run.tool_result",
  "params": {
    "run_id": "run-123",
    "session_id": "sess-456",
    "tool_name": "shell",
    "result": {"output": "..."}
  }
}
```

### Key Differences:

| Aspect | Python | Elixir | Issue |
|--------|--------|--------|-------|
| Method name | `"event"` | `"run.tool_result"` | Different |
| Event type location | `params.event_type` | In method name | Different |
| Data structure | Nested in `payload` | Flat in `params` | Different |
| Timestamp | Required | Optional | Different |
| Required fields | `event_type` | Varies by method | Different |

**Summary**: Structure incompatible even if method names matched

---

## Lifecycle Events

| Python Emits | Elixir Handles | Status |
|--------------|----------------|--------|
| `bridge_ready` | ❌ No | 🔴 Not implemented |
| `bridge_closing` | ❌ No | 🔴 Not implemented |

| Elixir Sends | Python Handles | Status |
|--------------|----------------|--------|
| `initialize` | ❌ No | 🔴 Not implemented |
| `run/start` | ❌ No | 🔴 Not implemented |
| `run/cancel` | ❌ No | 🔴 Not implemented |
| `exit` | ❌ No | 🔴 Not implemented |

**Summary**: Lifecycle completely disconnected

---

## Test Mock vs Reality

| Component | Test Mock Does | Real Implementation Does | Match? |
|-----------|----------------|-------------------------|--------|
| Python worker | Emits `run.status` | Emits `event` | ❌ **NO** |
| Python worker | Emits `run.completed` | Emits `event` | ❌ **NO** |
| Python worker | Emits `run.text` | Emits `event` | ❌ **NO** |

**Summary**: Tests use mocks that don't match real implementation

---

## Event Type Mapping

| Python Event Type | Python Method | Elixir Method | Status |
|-------------------|---------------|---------------|--------|
| `tool_output` | `event` | `run.tool_result` | 🔴 Mismatch |
| `agent_response` | `event` | `run.text` | 🔴 Mismatch |
| `tool_call` | `event` | `run.event` | 🔴 Mismatch |
| `status_change` | `event` | `run.status` | 🔴 Mismatch |
| `error` | `event` | `run.failed` | 🔴 Mismatch |
| `prompt_request` | `event` | `run.prompt` | 🔴 Mismatch |
| `run_complete` | `event` | `run.completed` | 🔴 Mismatch |

**Summary**: 0% event type compatibility

---

## Severity Matrix

| Issue | Severity | Blocks | Scope |
|-------|----------|--------|-------|
| Event method mismatch | 🔴 CRITICAL | All events | 100% of event flow |
| Missing run lifecycle | 🔴 CRITICAL | Run management | Core functionality |
| Structure mismatch | 🔴 CRITICAL | All events | Data parsing |
| Test mock mismatch | 🟡 HIGH | Testing | Quality assurance |
| Lifecycle events | 🟡 HIGH | Bridge management | Operations |

**Overall**: 🔴 **CRITICAL - BRIDGE NON-FUNCTIONAL**

---

## What Actually Works

✅ **Working**:
- Basic file operations (list, read, write)
- Shell command execution
- Agent invocation
- Grep/search
- Status checks
- Ping/health checks
- Content-Length framing
- JSON-RPC 2.0 structure

❌ **Broken**:
- All event streaming
- Run lifecycle management
- Status updates
- Progress reporting
- Tool result forwarding
- Text streaming
- Prompt handling
- Graceful shutdown

**Bottom Line**: Basic tool execution works, but all run management and event streaming is broken.

---

## Fix Priority

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Event method names | Medium | Unblocks all events |
| P0 | Run lifecycle handlers | Medium | Unblocks run management |
| P1 | Event structure alignment | Low | Ensures data parses |
| P2 | Test mock alignment | Low | Ensures tests valid |
| P3 | Lifecycle events | Low | Better operations |

**Estimated Fix Effort**: 2-3 days for complete resolution

---

## Recommended Approach

**Option B: Make Elixir accept Python's format** (recommended)

Why:
- Python's generic event model is more flexible
- Less Python refactoring (fewer users affected)
- Can add specific method routing in Elixir
- Preserves Python's current architecture

Changes needed:
1. Add generic `"event"` handler in Elixir port.ex
2. Map `event_type` to appropriate actions
3. Add lifecycle event handlers
4. Extract data from nested payload

---

**Generated**: 2026-04-14  
**Confidence**: 100%  
**Action Required**: Immediate protocol reconciliation
