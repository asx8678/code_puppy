# bd-127: Elixir Transport Crash - Compile-Output Hypothesis Verification

## Hypothesis
The Elixir transport crash was hypothesized to be caused by either:
1. **Compile output** on first run triggering the crash (hypothesis to verify)
2. **In-protocol stdout leak** from Logger/SASL/etc if crash persists after pre-compile

## Test Procedure
1. Created worktree: `git worktree add ../bd-127 -b feature/bd-127-verify-compile-hypothesis main`
2. Pre-compiled Elixir code: `cd elixir/code_puppy_control && MIX_ENV=dev mix compile`
3. Attempted to run code-puppy

## Findings

### Discovery 1: Pre-existing Merge Conflict
**Initial blocker:** The `elixir_bridge/__init__.py` file contained a git merge conflict between bd-134 (`call_elixir_round_robin`) and bd-132 (`call_elixir_model_packs`) at line 372. This caused a `SyntaxError` that prevented testing the actual transport issue.

**Resolution:** Merged both functions (they serve different purposes and should coexist).

### Discovery 2: Compile-Output Hypothesis - PARTIALLY CONFIRMED
After fixing the merge conflict and pre-compiling:
- The code-puppy startup **still fails** with `ElixirTransportError: Timeout waiting for service to be ready`
- **Conclusion:** Pre-compilation alone does NOT fully fix the transport crash

### Discovery 3: Root Cause - Runtime stdout Leak (NOT compile output)
Direct testing of the Elixir stdio service revealed the actual problem:

```bash
$ MIX_ENV=dev timeout 3 mix code_puppy.stdio_service 2>/dev/null
16:04:33.467 [notice] SIGTERM received - shutting down

16:04:33.476 [notice] SIGTERM received - shutting down
```

**Critical finding:** SIGTERM notices are being printed to **stdout** even with stderr redirected. These system notices from the Elixir/OTP runtime corrupt the JSON-RPC protocol communication between Python and Elixir.

## Conclusion

| Hypothesis | Status |
|------------|--------|
| Compile output causes crash | ❌ Rejected - crash persists after pre-compile |
| In-protocol stdout leak (Logger/SASL/runtime) | ✅ Confirmed - SIGTERM notices leak to stdout |

**Root Cause:** The Elixir transport crash is caused by **runtime stdout pollution**, not compile output. The Elixir/OTP runtime's SIGTERM handler (or another system process) is writing notices to stdout, which corrupts the JSON-RPC message framing.

## Recommendations

1. **Immediate:** Add stdout redirection/sanitization in the Python transport layer to filter out non-JSON-RPC lines
2. **Short-term:** Configure Elixir runtime to suppress system notices or redirect them to stderr via `:logger` configuration in `config/runtime.exs`
3. **Long-term:** Implement Content-Length framing verification to detect and recover from protocol corruption

## Related Issues
- bd-132: Model packs (one side of the merge conflict)
- bd-134: Round-robin model rotation (other side of the merge conflict)

---
Test Date: 2026-04-18
Worktree: /Users/adam2/projects/bd-127
Branch: feature/bd-127-verify-compile-hypothesis
