# bd-126: Elixir Transport Crash with Verbose Logging - Findings

## Summary

The Elixir transport crash with verbose logging is caused by Elixir compiler warnings being sent to stdout during the startup phase, which the Python client attempts to parse as JSON and fails.

## Root Cause Analysis

### The Problem

When `PUP_LOG_LEVEL=debug` is set and the Elixir stdio service starts, the Mix compiler outputs parser warnings like:

```
src/rust_parser.yrl:none: warning: conflicts: 42 shift/reduce, 0 reduce/reduce
src/rust_parser.yrl:19:3: warning: terminal symbol where not used
src/python_parser.yrl:none: warning: conflicts: 9 shift/reduce, 0 reduce/reduce
```

These warnings are sent to **stdout** (not stderr) before the Logger configuration takes effect. The Python client then tries to parse these non-JSON lines as JSON-RPC responses, resulting in a `JSONDecodeError`.

### Code Analysis

**Good handling in `_wait_for_ready()` (lines 257-259):**
```python
try:
    response = json.loads(response_line)
    if response.get("id") == ping_id and response.get("result", {}).get("pong"):
        return
except json.JSONDecodeError:
    # Not valid JSON, might be log output
    pass
```

**Problematic handling in `_send_request()` (lines 360-370):**
```python
# Read response (skip empty lines that may be warnings/startup messages)
max_empty_reads = 10
response_line = ""
for _ in range(max_empty_reads):
    line = self._process.stdout.readline()
    if not line:
        raise ElixirTransportError("Empty response from service (process died?)")
    line = line.strip()
    if line:  # Skip empty lines ONLY
        response_line = line
        break

# ... later ...
try:
    response = json.loads(response_line)
except json.JSONDecodeError as e:
    raise ElixirTransportError(f"Invalid JSON response: {e}")
```

The `_send_request` method:
1. Only skips **empty lines** (lines that are `""` after stripping)
2. Does NOT handle **non-JSON lines** that contain compiler warnings
3. Immediately tries to parse the first non-empty line as JSON

## Reproduction Steps

1. Ensure the Elixir code is not compiled (clean build)
2. Run with debug logging enabled:
   ```bash
   PUP_LOG_LEVEL=debug code-puppy
   ```
3. The first request to the Elixir transport will fail with `JSONDecodeError` because it receives compiler warnings instead of JSON

## Captured Output

```
src/rust_parser.yrl:none: warning: conflicts: 42 shift/reduce, 0 reduce/reduce
src/rust_parser.yrl:19:3: warning: terminal symbol where not used
src/python_parser.yrl:none: warning: conflicts: 9 shift/reduce, 0 reduce/reduce
... (more warnings) ...
{"id":1,"jsonrpc":"2.0","result":{"pong":true,"timestamp":"..."}}
```

The first non-empty line Python receives is:
```
src/rust_parser.yrl:none: warning: conflicts: 42 shift/reduce, 0 reduce/reduce
```

Which is NOT valid JSON and causes:
```
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

## Proposed Fix

Modify `_send_request()` to handle non-JSON lines the same way `_wait_for_ready()` does:

```python
# Read response (skip non-JSON lines that may be warnings/startup messages)
max_attempts = 10
for _ in range(max_attempts):
    line = self._process.stdout.readline()
    if not line:
        raise ElixirTransportError("Empty response from service (process died?)")
    
    line = line.strip()
    if not line:
        continue  # Skip empty lines
    
    try:
        response = json.loads(line)
        # Valid JSON found - check ID match
        if response.get("id") != request_id:
            raise ElixirTransportError(f"Response ID mismatch")
        # ... continue processing ...
        return response.get("result", {})
    except json.JSONDecodeError:
        # Not valid JSON, might be log/compiler output - skip and continue
        logger.debug(f"Skipping non-JSON line: {line[:100]}...")
        continue

raise ElixirTransportError("No valid JSON response after max attempts")
```

## Alternative Solutions

1. **Redirect compiler output to stderr in Mix task**: Modify the Mix task to suppress or redirect all pre-startup output
2. **Pre-compile before starting service**: Ensure code is compiled before starting the stdio service
3. **Use Content-Length framing**: Switch to the same framing protocol used in bridge mode (bd-126-fix-approach.md discusses trade-offs)

## Files Affected

- `code_puppy/elixir_transport.py` - `_send_request()` method (lines 340-380)
- `elixir/code_puppy_control/lib/mix/tasks/code_puppy/stdio_service.ex` - Mix task startup

## Test Case

A test should:
1. Clean the Elixir build (`mix clean`)
2. Start the transport with debug logging
3. Send a ping request
4. Verify the request succeeds (no JSONDecodeError)
5. Verify any non-JSON startup lines are logged/silently skipped

## References

- Elixir stdio service: `elixir/code_puppy_control/lib/code_puppy_control/transport/stdio_service.ex`
- Python transport: `code_puppy/elixir_transport.py`
- Mix task: `elixir/code_puppy_control/lib/mix/tasks/code_puppy/stdio_service.ex`
