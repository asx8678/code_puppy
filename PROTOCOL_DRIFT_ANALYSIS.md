# Python↔Elixir Bridge Protocol Drift Analysis

## Executive Summary

**Status**: 🔴 **CRITICAL PROTOCOL DRIFT DETECTED**

The Python and Elixir bridge implementations have fundamental incompatibilities that prevent communication. The drift spans method names, event structures, and lifecycle management.

---

## 1. Framing Protocol

| Aspect | Python Implementation | Elixir Implementation | Status |
|--------|----------------------|----------------------|--------|
| **Framing Method** | Content-Length (default) or newline-delimited | Content-Length only | ✅ Compatible |
| **Header Format** | `Content-Length: N\r\n\r\n` | `Content-Length: N\r\n\r\n` | ✅ Identical |
| **JSON Encoding** | Compact (`separators=(',', ':')`) | Compact (`Jason.encode!`) | ✅ Compatible |
| **Backward Compat** | Supports `CODE_PUPPY_BRIDGE_PROTOCOL=newline` | N/A | ⚠️ One-sided |

**Verdict**: ✅ **Framing is compatible**

---

## 2. JSON-RPC Structure

| Aspect | Python Implementation | Elixir Implementation | Status |
|--------|----------------------|----------------------|--------|
| **Protocol Version** | JSON-RPC 2.0 | JSON-RPC 2.0 | ✅ Compatible |
| **Request Format** | `{"jsonrpc": "2.0", "id": ..., "method": ..., "params": {...}}` | Same | ✅ Compatible |
| **Response Format** | `{"jsonrpc": "2.0", "id": ..., "result": {...}}` | Same | ✅ Compatible |
| **Error Format** | `{"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}` | Same | ✅ Compatible |
| **Notification Format** | `{"jsonrpc": "2.0", "method": ..., "params": {...}}` | Same | ✅ Compatible |

**Verdict**: ✅ **JSON-RPC structure is compatible**

---

## 3. Method Names (Requests Elixir→Python)

| Elixir Sends | Python Expects | Status | Notes |
|--------------|----------------|--------|-------|
| `initialize` | `initialize` | ✅ Supported | Python accepts in `from_wire_params` but no handler |
| `run/start` | ❌ Not supported | 🔴 **MISMATCH** | Python has no `run/start` method |
| `run/cancel` | ❌ Not supported | 🔴 **MISMATCH** | Python has no `run/cancel` method |
| `exit` | ❌ Not supported | 🔴 **MISMATCH** | Python has no `exit` method |
| `invoke_agent` | `invoke_agent` | ✅ Supported | Both sides agree |
| `run_shell` | `run_shell` | ✅ Supported | Both sides agree |
| `file_list` | `file_list` | ✅ Supported | Both sides agree |
| `file_read` | `file_read` | ✅ Supported | Both sides agree |
| `file_write` | `file_write` | ✅ Supported | Both sides agree |
| `grep_search` | `grep_search` | ✅ Supported | Both sides agree |
| `get_status` | `get_status` | ✅ Supported | Both sides agree |
| `ping` | `ping` | ✅ Supported | Both sides agree |

**Verdict**: 🔴 **3 methods Elixir sends that Python doesn't support**

---

## 4. Event/Notification Methods (Python→Elixir)

| Python Emits | Elixir Expects | Status | Notes |
|--------------|----------------|--------|-------|
| `event` (generic) | `run.event` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.event" |
| `event` (generic) | `run.status` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.status" |
| `event` (generic) | `run.completed` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.completed" |
| `event` (generic) | `run.failed` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.failed" |
| `event` (generic) | `run.text` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.text" |
| `event` (generic) | `run.tool_result` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.tool_result" |
| `event` (generic) | `run.prompt` | 🔴 **MISMATCH** | Python uses generic "event", Elixir expects "run.prompt" |
| `bridge_ready` | ❌ Not expected | 🔴 **MISMATCH** | Elixir has no handler for bridge lifecycle events |
| `bridge_closing` | ❌ Not expected | 🔴 **MISMATCH** | Elixir has no handler for bridge lifecycle events |

**Verdict**: 🔴 **CRITICAL - Complete event method mismatch**

---

## 5. Event Structure (Params Format)

### Python Wire Event Format (what Python sends):
```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "event_type": "tool_output",
    "run_id": "run-abc123",
    "session_id": "session-xyz789",
    "timestamp": 1713123456789,
    "payload": {
      "command": "ls",
      "output": "..."
    }
  }
}
```

### Elixir Expected Format (what Elixir expects):
```json
{
  "jsonrpc": "2.0",
  "method": "run.tool_result",
  "params": {
    "run_id": "run-abc123",
    "session_id": "session-xyz789",
    "tool_name": "shell",
    "result": {...},
    "tool_call_id": "..."
  }
}
```

### Key Differences:

| Field | Python Format | Elixir Format | Issue |
|-------|---------------|---------------|-------|
| **Method Name** | `"event"` (generic) | `"run.*"` (specific) | Method name mismatch |
| **Event Type** | `params.event_type` | Implicit in method name | Different semantics |
| **Payload Structure** | `params.payload` (nested) | `params` (flat) | Structure mismatch |
| **Required Fields** | `event_type`, `timestamp` | Varies by method | Different validation |

**Verdict**: 🔴 **CRITICAL - Incompatible event structures**

---

## 6. Complete Event Type Mapping

### Events Python Emits (via `stream_event` callback):

| Python Event Type | Python Method | Elixir Expected Method | Status |
|-------------------|---------------|------------------------|--------|
| `tool_output` | `event` | `run.tool_result` | 🔴 Mismatch |
| `agent_response` | `event` | `run.text` | 🔴 Mismatch |
| `tool_call` | `event` | `run.event` | 🔴 Mismatch |
| `status_change` | `event` | `run.status` | 🔴 Mismatch |
| `error` | `event` | `run.failed` | 🔴 Mismatch |
| `prompt_request` | `event` | `run.prompt` | 🔴 Mismatch |
| `run_complete` | `event` | `run.completed` | 🔴 Mismatch |

### Events Elixir Handles (from `port.ex` `handle_message`):

| Elixir Method | Elixir Action | Python Sends | Status |
|---------------|---------------|--------------|--------|
| `run.event` | Store + broadcast | ❌ No | 🔴 Missing |
| `run.status` | Update run state + broadcast | ❌ No | 🔴 Missing |
| `run.completed` | Complete run + broadcast | ❌ No | 🔴 Missing |
| `run.failed` | Fail run + broadcast | ❌ No | 🔴 Missing |
| `run.text` | Store + broadcast | ❌ No | 🔴 Missing |
| `run.tool_result` | Store + broadcast | ❌ No | 🔴 Missing |
| `run.prompt` | Store + broadcast | ❌ No | 🔴 Missing |

**Verdict**: 🔴 **Zero event method overlap**

---

## 7. Lifecycle Management

### Python Emits:
1. `bridge_ready` - When bridge initializes
2. `bridge_closing` - Before shutdown

### Elixir Sends:
1. `initialize` - To initialize Python worker
2. `run/start` - To start a run
3. `run/cancel` - To cancel a run
4. `exit` - To shutdown worker

### Elixir Expects Python to Emit:
1. `run.status` - Status updates
2. `run.completed` - Run completion
3. `run.failed` - Run failure

**Verdict**: 🔴 **Completely different lifecycle models**

---

## 8. Missing Functionality

### Python Bridge Missing (Elixir expects):

1. ❌ `run/start` method handler
2. ❌ `run/cancel` method handler  
3. ❌ `exit` method handler
4. ❌ `run.event` event emission
5. ❌ `run.status` event emission
6. ❌ `run.completed` event emission
7. ❌ `run.failed` event emission
8. ❌ `run.text` event emission
9. ❌ `run.tool_result` event emission
10. ❌ `run.prompt` event emission

### Elixir Bridge Missing (Python emits):

1. ❌ `bridge_ready` notification handler
2. ❌ `bridge_closing` notification handler

---

## 9. Evidence from Documentation

From `docs/ELIXIR_REMEDIATION.md`:

> **Protocol Drift**: The ADR specifies JSON-RPC 2.0 with Content-Length framing, but implementation mixes framing approaches between modules

This confirms the protocol drift is a known issue, but the analysis shows it's **much worse than framing** - it's a complete semantic mismatch.

---

## 10. Test Evidence

From `elixir/code_puppy_control/test/support/mock_python_worker_script.py`:

```python
# Line 155: Python mock sends run.status
send_notification("run.status", {...})

# Line 165: Python mock sends run.status  
send_notification("run.status", {...})

# Line 176: Python mock sends run.completed
send_notification("run.completed", {...})
```

**Analysis**: The test mock uses Elixir's expected method names (`run.status`, `run.completed`), but the **actual Python bridge** uses generic `"event"` method. This means:
- Tests may pass (using mock)
- Real integration will fail (using actual bridge)

---

## 11. Severity Assessment

| Issue | Severity | Impact |
|-------|----------|--------|
| Event method name mismatch | 🔴 **CRITICAL** | No events processed by Elixir |
| Missing run lifecycle handlers | 🔴 **CRITICAL** | Cannot start/cancel/stop runs |
| Event structure mismatch | 🔴 **CRITICAL** | Even if methods matched, params differ |
| Missing event types | 🔴 **CRITICAL** | No text, tool results, prompts forwarded |
| Lifecycle event mismatch | 🟡 **HIGH** | Bridge ready/closing not handled |

**Overall Severity**: 🔴 **CRITICAL - BRIDGE IS NON-FUNCTIONAL**

---

## 12. Root Causes

1. **Independent Development**: Python and Elixir bridges developed without shared protocol spec
2. **Generic vs Specific**: Python uses generic `"event"` method, Elixir expects specific methods
3. **Missing Middleware**: No translation layer between the two implementations
4. **Test Mock Mismatch**: Test mocks don't match actual implementation
5. **Documentation Gap**: Protocol spec not enforced or validated

---

## 13. Recommended Fixes

### Option A: Make Python Emit Elixir's Expected Format

**Changes Required**:
1. Add `run/start`, `run/cancel`, `exit` method handlers to Python
2. Change `_on_stream_event` to emit specific methods instead of generic `"event"`
3. Map Python event types to Elixir method names
4. Flatten payload structure (remove nested `payload` field)

**Pros**: 
- Minimal Elixir changes
- Follows Elixir's more specific event model

**Cons**:
- Significant Python refactoring
- Breaks Python's current generic event model

### Option B: Make Elixir Accept Python's Format

**Changes Required**:
1. Add handler for generic `"event"` method in Elixir port.ex
2. Map `params.event_type` to appropriate Elixir actions
3. Add handlers for `bridge_ready`, `bridge_closing` lifecycle events
4. Extract data from nested `payload` field

**Pros**:
- Minimal Python changes
- Preserves Python's generic event model

**Cons**:
- Significant Elixir refactoring
- Less specific event handling in Elixir

### Option C: Add Protocol Translation Layer

**Changes Required**:
1. Create middleware component that translates between protocols
2. Python emits to translation layer
3. Translation layer reformats and forwards to Elixir

**Pros**:
- Neither side needs major changes
- Can evolve independently

**Cons**:
- Additional complexity
- Another component to maintain

---

## 14. Immediate Action Items

1. **STOP** assuming Python↔Elixir bridge works
2. **CREATE** shared protocol specification document
3. **CHOOSE** one of the three fix options above
4. **IMPLEMENT** chosen option with integration tests
5. **VALIDATE** with end-to-end tests (not just mocks)
6. **DOCUMENT** protocol contract for future development

---

## 15. Verification Checklist

After fixes, verify:

- [ ] Python emits `run.status` events (not generic `event`)
- [ ] Python emits `run.completed` events
- [ ] Python emits `run.text` events
- [ ] Python emits `run.tool_result` events
- [ ] Python handles `run/start` method
- [ ] Python handles `run/cancel` method
- [ ] Python handles `exit` method
- [ ] Elixir receives and processes all event types
- [ ] E2E tests pass with real bridge (not mock)
- [ ] Protocol spec document created and agreed upon

---

**Generated**: 2026-04-14  
**Status**: 🔴 CRITICAL - IMMEDIATE ACTION REQUIRED  
**Confidence**: 100% (based on source code analysis)
