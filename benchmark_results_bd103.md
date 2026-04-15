# Benchmark Results - bd-103 Protocol Bridge Optimization

## Summary of Changes (bd-103)

### Python Side (`code_puppy/plugins/elixir_bridge/__init__.py`)
1. **Replace polling with threading.Event** - Eliminated 10ms polling floor
2. **Add orjson support** - 5-10x faster JSON serialization/deserialization
3. **Add batch request support** - `call_batch()` for N requests in single frame

### Python Side (`code_puppy/plugins/elixir_bridge/wire_protocol.py`)
1. **orjson integration** - Faster `_serialize_json()` and `_deserialize_json()` functions
2. **`file_read_batch` method** - New batch file read support in `from_wire_params()`

### Elixir Side (`elixir/code_puppy_control/lib/code_puppy_control/protocol.ex`)
1. **`frame_batch/1`** - Frame multiple JSON-RPC messages in single batch
2. **Batch decoding** - `decode()` now handles JSON arrays (batch format)
3. **`validate_batch_jsonrpc/1`** - Validates all messages in a batch

### Elixir Side (`elixir/code_puppy_control/lib/code_puppy_control/python_worker/port.ex`)
1. **`call_batch/3`** - Client API for batch requests
2. **`handle_call({:call_batch, ...})`** - Server-side batch request handling
3. **`handle_incoming_messages/3`** - Handles both single and batch messages

---

## Projected Performance Improvements

| Metric | Before (bd-102) | After (bd-103) | Improvement |
|--------|----------------|----------------|-------------|
| **Req/Resp Latency** | 0.036ms | <0.020ms | 44%+ reduction |
| **Throughput (8 workers)** | 57,828 ops/s | >100,000 ops/s | 73%+ increase |
| **JSON Serialization** | stdlib json | orjson (optional) | 5-10x faster |
| **Response Matching** | 10ms polling | threading.Event | Instant notification |

---

## Key Optimizations Explained

### 1. threading.Event for Response Matching (Biggest Impact)

**Before:**
```python
start_time = time.time()
while time.time() - start_time < timeout:
    with _response_lock:
        slot = _pending_responses.get(request_id)
        if slot and slot["ready"]:
            result = slot["result"]
            error = slot["error"]
            break
    time.sleep(0.01)  # 10ms polling floor - adds 0-10ms latency!
```

**After:**
```python
slot = _ResponseSlot()  # Contains threading.Event
# ...
result, error = slot.wait(timeout)  # Blocks until event.set() or timeout
```

This eliminates the 10ms polling floor, providing instant notification when responses arrive.

### 2. orjson for Faster Serialization

**Before:**
```python
body = json.dumps(message, separators=(",", ":")).encode("utf-8")
```

**After:**
```python
def _serialize_json(data: Any) -> bytes:
    if _HAS_ORJSON:
        return orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY)
    return json.dumps(data, separators=(",", ":")).encode("utf-8")
```

orjson is 5-10x faster than stdlib json for both serialization and deserialization.

### 3. Batch Request Support

**Before:**
```python
# N requests = N separate writes + N separate reads
for method, params in calls:
    result = call_method(method, params)
    results.append(result)
```

**After:**
```python
# N requests = 1 write + N reads (matched by request ID)
results = call_batch([("file_read", {"path": "a.py"}), 
                      ("file_read", {"path": "b.py"})])
```

Reduces IPC overhead by combining N requests into a single write operation.

---

## Usage Examples

### Python: Using orjson (optional)

```bash
pip install orjson
```

The bridge will automatically use orjson if installed, falling back to stdlib json otherwise.

### Python: Batch Requests

```python
from code_puppy.plugins.elixir_bridge import call_batch

# Read multiple files in a single round-trip
results = call_batch([
    ("file_read", {"path": "lib/module_a.ex"}),
    ("file_read", {"path": "lib/module_b.ex"}),
    ("file_read", {"path": "lib/module_c.ex"}),
])
# Returns list of result dicts in same order
```

### Elixir: Batch Requests

```elixir
# Call multiple methods in a single frame
results = CodePuppyControl.PythonWorker.Port.call_batch(
  run_id,
  [
    {"file_read", %{"path" => "a.py"}},
    {"file_list", %{"directory" => "."}},
    {"grep_search", %{"pattern" => "def ", "directory" => "lib/"}}
  ]
)
```

### Elixir: Batch Framing

```elixir
# Frame multiple messages as JSON-RPC batch
framed = Protocol.frame_batch([
  %{"jsonrpc" => "2.0", "id" => 1, "method" => "file_read", "params" => %{"path" => "a.py"}},
  %{"jsonrpc" => "2.0", "id" => 2, "method" => "file_read", "params" => %{"path" => "b.py"}}
])
```

---

## Backwards Compatibility

All changes are **backwards compatible**:

1. **threading.Event** - Internal optimization, no API changes
2. **orjson** - Optional dependency, falls back to stdlib json
3. **Batch format** - JSON-RPC 2.0 standard, single messages still work

---

## Files Modified

- `code_puppy/plugins/elixir_bridge/__init__.py` - Response slot, orjson, batch support
- `code_puppy/plugins/elixir_bridge/wire_protocol.py` - orjson, file_read_batch
- `elixir/code_puppy_control/lib/code_puppy_control/protocol.ex` - Batch framing/decoding
- `elixir/code_puppy_control/lib/code_puppy_control/python_worker/port.ex` - Batch handling

---

## Acceptance Criteria Status

- [x] Replace polling with threading.Event for response matching
- [x] Add batch request support (N requests in single frame)
- [x] Switch to orjson for faster serialization (with fallback)
- [x] Update Elixir port.ex to handle new framing formats
- [ ] Update benchmark suite with new numbers (needs live testing)
- [ ] Req/Resp latency < 0.020ms (needs measurement)
- [ ] Throughput at 8 workers > 100,000 ops/s (needs measurement)

---

## Next Steps

1. Run full benchmark suite with live Elixir/Python workers
2. Install orjson in benchmark environment: `pip install orjson`
3. Compare results against baseline (bd-102 numbers)
4. Update acceptance criteria with measured values
