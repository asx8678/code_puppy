# Testing Gap Analysis - Phase 3.2

> **Generated:** 2026-04-07  
> **Scope:** code_puppy test suite audit for coverage gaps, brittle patterns, and security-sensitive test coverage

---

## Executive Summary

The code_puppy project has an **extensive** test suite with **10,396 test functions** across **434 test files** (467 Python files in tests/ directory including 434 test_*.py files). However, significant gaps exist in:

**⚠️ Data Staleness Warning:** The `coverage.json` data is from **2026-02-20** (47+ days old), which affects the validity of 0% coverage claims - some modules may have been tested since then.

1. **Overall measured coverage: 33.1%** (gate is set to 65% - may mask risks)
2. **Core module coverage** - 43+ files have 0% coverage
3. **Brittle test patterns** - Heavy reliance on mocking (9,314+ patch calls) with timing-dependent tests
4. **Security-sensitive paths** - Limited malicious input/attack testing for plugin loader and shell execution
5. **Integration coverage** - Key user flows (MCP handshake, agent run) have thin E2E coverage

**Coverage Gate Note:** The 65% `fail_under` threshold in pyproject.toml may mask risks - zero-coverage files are excluded from coverage.json or are not being exercised by the current test run configuration.

---

## [SEV-HIGH] Major Coverage Gaps

### [SEV-HIGH] API Module (10 files, 0% coverage)
**Module(s):** `code_puppy/api/`

**Issue:** 
- All 10 files in the API module show **0% coverage** in coverage.json:
  - `api/app.py` (67 statements) - FastAPI application factory
  - `api/pty_manager.py` (214 statements) - PTY session management
  - `api/websocket.py` (97 statements) - WebSocket terminal
  - `api/routers/agents.py`, `commands.py`, `config.py`, `sessions.py`

- Test files exist (`tests/api/test_*.py`) but coverage data shows they are not being exercised or coverage is not being recorded properly.

**Recommendation:**
1. Verify coverage configuration in `pyproject.toml` - ensure API tests are included in coverage run
2. Add integration tests for API endpoints using `httpx.AsyncClient` with `ASGITransport`
3. Add PTY-specific tests mocking `asyncio.create_subprocess_exec`

---

### [SEV-HIGH] CLI Runner Completely Untested
**Module(s):** `code_puppy/cli_runner.py` (510 statements, 0% coverage)

**Issue:** 
- The main CLI entry point (`cli_runner.py`) has zero coverage
- Contains critical bootstrapping logic: argument parsing, initial config loading, first-run detection
- Tests exist (`test_cli_runner.py`, `test_cli_runner_coverage.py`) but not reflected in coverage data

**Recommendation:**
1. Fix coverage configuration to properly measure CLI entry points
2. Add E2E tests for CLI boot sequence
3. Test error handling for corrupted/missing config on first run

---

### [SEV-HIGH] Plugin System - Missing Malicious Plugin Tests
**Module(s):** `code_puppy/plugins/__init__.py` (lazy loader), shell safety plugins

**Issue:**
- Plugin loader tests (`test_plugins_init_coverage.py`) exist but only test "happy path"
- No tests for:
  - Malicious plugin with `__import__('os').system('rm -rf /')` in `register_callbacks.py`
  - Plugin with infinite loop in callback registration
  - Plugin that modifies global state unexpectedly
  - Plugin attempting to shadow/override core modules
- User plugins directory (`~/.code_puppy/plugins/`) is treated as **trusted local Python code** per README warning, but no tests verify sandboxing attempts

**Recommendation:**
1. Add tests for plugin loading with malicious/exception-raising code
2. Test plugin isolation (can a plugin corrupt agent state?)
3. Test behavior when plugin hangs during registration
4. Consider adding defense tests for the `shell_safety` plugin when safety level is "low"

---

### [SEV-HIGH] MCP Health Monitor Untested
**Module(s):** `code_puppy/mcp_/health_monitor.py` (222 statements, 0% coverage)

**Issue:**
- Critical infrastructure for MCP server health monitoring has zero coverage
- Contains failure detection, circuit breaker integration, restart logic
- No tests verify health check behavior or failure cascades

**Recommendation:**
1. Add unit tests for health check logic with mocked MCP servers
2. Test circuit breaker state transitions
3. Test restart/recovery behavior

---

## [SEV-MEDIUM] Coverage Gaps in Key Modules

### [SEV-MEDIUM] ChatGPT Codex Client Untested
**Module(s):** `code_puppy/chatgpt_codex_client.py` (155 statements, 0% coverage)

**Issue:**
- OAuth-based client for ChatGPT Codex has no test coverage
- Contains JWT handling, token refresh, API request logic
- Security-sensitive paths (token storage, refresh) untested

**Recommendation:**
1. Add tests mirroring the pattern from `test_claude_cache_client.py`
2. Test JWT age detection and refresh triggers
3. Test Cloudflare error detection patterns

---

### [SEV-MEDIUM] Terminal Utils and Status Display Untested
**Module(s):**
- `code_puppy/terminal_utils.py` (177 statements, 0%)
- `code_puppy/status_display.py` (113 statements, 0%)

**Issue:**
- Terminal detection, size queries, ANSI handling untested
- Status display formatting (used by all agents) untested
- Rich console output formatting (no coverage)

**Recommendation:**
1. Add tests mocking `shutil.get_terminal_size`, `os.environ`
2. Test ANSI escape sequence generation
3. Test status display with various message types

---

### [SEV-MEDIUM] Gemini Integration Untested
**Module(s):**
- `code_puppy/gemini_code_assist.py` (176 statements, 0%)
- `code_puppy/gemini_model.py` (375 statements, 0%)

**Issue:**
- Tests exist in `tests/test_gemini_code_assist.py` but coverage shows 0%
- Model request building, response parsing untested per coverage data
- Safety settings, tool handling not verified

**Recommendation:**
1. Verify test execution for Gemini tests
2. Add tests for model request/response schemas
3. Test tool return serialization (suspected fragile area)

---

### [SEV-MEDIUM] Scheduler Subsystem Weak Coverage
**Module(s):** `code_puppy/scheduler/`

**Issue:**
- `daemon.py` (160 statements, 0%), `config.py` (86 statements, 0%)
- Tests exist but may not run in CI (platform-specific?)
- Cross-platform daemon management (Windows vs Unix) has limited verification

**Recommendation:**
1. Ensure scheduler tests run on all platforms in CI
2. Add mocked tests for daemon lifecycle (start, stop, status)
3. Test cross-platform path handling

---

## [SEV-MEDIUM] Brittle Test Patterns

### [SEV-MEDIUM] Excessive Mocking - 9,314+ patch() calls
**Pattern:** Unit tests mock internal implementation details rather than testing behavior

**Evidence:**
- `grep -r "patch(" tests/ | wc -l` = 9,314
- `grep -r "MagicMock" tests/ | wc -l` = 3,476
- Tests for session storage, TUI, and plugins have heavy mocking of internal state

**Example from test_plugins_init_coverage.py:**
```python
with patch("code_puppy.plugins.importlib.import_module") as mock_import:
    mock_import.return_value = MagicMock()
    result = loader()
```

**Issue:**
- Tests verify that mocks were called, not that behavior is correct
- Refactoring internal implementation breaks tests even when behavior is preserved
- Tests don't catch integration failures between real components

**Recommendation:**
1. Prioritize integration tests over heavily-mocked unit tests for complex flows
2. Use `pytest` fixtures for real object setup where feasible
3. Review tests with >5 patch decorators for refactoring to behavioral tests

---

### [SEV-MEDIUM] Timing-Dependent Tests - 426+ sleep calls
**Pattern:** Tests use `time.sleep()` and `asyncio.sleep()` for synchronization

**Evidence:**
- `grep -r "time\.sleep\|asyncio\.sleep" tests/ | wc -l` = 426+
- Tests in `test_mcp_integration.py` use `time.sleep(3)` for "agent reload"
- Circuit breaker tests use `await asyncio.sleep(0.3)` for state transitions
- Bridge E2E tests have multiple 0.3s - 1.0s delays

**Issue:**
- Tests are slow (426 × 0.1s avg = 42s of pure sleep)
- Flaky on slow CI runners (timeouts in `test_mcp_integration.py` already handle this)
- Don't actually verify conditions - just "hope" things are ready

**Example from test_mcp_integration.py:**
```python
time.sleep(10)  # Reduced timeout for LLM response
```

**Recommendation:**
1. Replace sleeps with deterministic synchronization (events, condition variables)
2. Use `asyncio.wait_for()` with timeouts instead of blind sleeps
3. Add `pytest.mark.slow` for timing-dependent tests to exclude from fast test runs

---

### [SEV-MEDIUM] Implementation Detail Testing
**Pattern:** Tests verify internal state rather than public behavior

**Evidence:**
- `test_session_storage_coverage.py` tests `_LAZY_PLUGIN_REGISTRY` directly
- Many tests access `module._private_variable` patterns
- Tests in `test_command_runner_core.py` manipulate `_RUNNING_PROCESSES` global

**Issue:**
- Tests break when implementation changes
- Encourages preserving bad implementation to avoid test rewrites
- Gives false confidence - internal state may be corrupt while tests pass

**Recommendation:**
1. Test through public APIs only where possible
2. Use dependency injection to avoid testing global state
3. Mark state-testing tests with warning comments about brittleness

---

## [SEV-MEDIUM] Integration Coverage Gaps

### [SEV-MEDIUM] Agent Run Flow - Missing Integration Test
**Flow:** `agent_manager.run()` → `base_agent.run()` → tool execution → callback handling

**Issue:**
- No end-to-end test of a complete agent conversation
- Integration tests exist (`tests/integration/`) but limited:
  - `test_cli_happy_path.py` - basic startup only
  - `test_file_operations_integration.py` - only file tools
  - No test for multi-turn conversation with tool calls

**Recommendation:**
1. Add mocked LLM integration test that simulates:
   - User prompt → agent
   - Agent requests tool call
   - Tool executes and returns
   - Agent generates response
2. Test with real LLM calls behind `RUN_EVALS` flag (evals infrastructure exists)

---

### [SEV-MEDIUM] Session Save/Restore Gaps
**Module(s):** `code_puppy/session_storage.py`, `code_puppy/tools/agent_tools.py`

**Issue:**
- Session storage tests (`test_session_storage_coverage.py`) focus on interactive restore
- Missing tests for:
  - Corrupted session file handling
  - Session migration (format changes)
  - Concurrent session access
  - Session storage with encryption (if enabled)

**Recommendation:**
1. Add property-based tests (hypothesis) for session data corruption scenarios
2. Test concurrent read/write of session files
3. Verify graceful degradation when session file is corrupted

---

### [SEV-MEDIUM] Tool Call Integration Limited
**Module(s):** `code_puppy/tools/command_runner.py`, file operations

**Issue:**
- `test_file_operations_integration.py` covers basic file operations
- Missing integration tests for:
  - Shell command with timeout/cancellation
  - Concurrent tool calls from multiple agents
  - Tool failures cascading to agent error handling

**Recommendation:**
1. Add integration test for shell command timeout
2. Test concurrent file operations from subagents
3. Test tool execution during agent shutdown

---

## [SEV-LOW] Security Test Coverage

### [SEV-LOW] JWT/Token Handling Tests Present but Scattered
**Module(s):** OAuth plugins, Claude cache client

**Status:** PARTIALLY ADDRESSED
- `test_claude_cache_client.py` has comprehensive JWT age detection tests
- OAuth plugins have token storage tests in various files
- 14 OAuth-related test files exist

**Gaps:**
- No tests for token leakage (logs, error messages, process lists)
- No tests for expired token handling in concurrent requests
- No tests for token refresh failures (network down, auth revoked)

**Recommendation:**
1. Add test verifying tokens don't appear in logs or exceptions
2. Test concurrent refresh scenario (multiple threads, one refresh needed)
3. Test graceful degradation when refresh fails

---

### [SEV-LOW] Shell Command Injection Tests Limited
**Module(s):** `code_puppy/tools/command_runner.py`

**Issue:**
- Shell execution tests focus on process management
- Limited tests for command injection scenarios
- `shell_safety` plugin exists but has 0% coverage

**Recommendation:**
1. Add tests for command injection attempts via tool parameters
2. Verify shell_safety plugin correctly blocks dangerous commands
3. Test behavior with shell metacharacters in filenames

---

## [SEV-LOW] Test Organization Issues

### [SEV-LOW] Test File Fragmentation
**Issue:**
- Single modules have 5+ test files (e.g., `test_base_agent_*.py` × 10+ files)
- Makes it hard to find tests for specific functionality
- Suggests test organization by "coverage run" rather than by feature

**Recommendation:**
1. Consolidate test files by feature domain
2. Use pytest markers for coverage categories instead of separate files
3. Document test organization in `tests/README.md`

---

### [SEV-LOW] Coverage Data Quality Issues
**Issue:**
- coverage.json shows 0% for many modules that have test files
- Either tests not being run, or coverage not being recorded
- Data is from 2026-02-20 (47+ days old) - consider regenerating for current analysis

**Recommendation:**
1. Regenerate coverage with fresh test run
2. Verify coverage configuration includes all source files
3. Check for import-time side effects that prevent coverage measurement

---

## Recommendations by Priority

### Immediate (This Sprint)
1. **Fix coverage measurement** - Verify why tests exist but show 0% coverage
2. **Add plugin loader security tests** - Test malicious plugin scenarios
3. **Add MCP health monitor tests** - Critical infrastructure gap

### Short Term (Next 2 Sprints)
1. **Reduce brittle patterns** - Convert 20+ most timing-dependent tests to event-based
2. **Add API integration tests** - At minimum, test all router endpoints
3. **Consolidate fragmented test files** - Reduce cognitive load

### Medium Term (Next Quarter)
1. **Add end-to-end agent flow tests** - Full conversation with tool calls
2. **Add chaos tests for session storage** - Corruption, concurrent access
3. **Improve mocking strategy** - Reduce 9,314 patch calls by 30%

---

## Metrics Summary

| Metric | Value | Assessment |
|--------|-------|------------|
| Test Functions | 10,396 | Good volume |
| Test Files | 434 test_*.py (467 total .py in tests/) | High fragmentation |
| Overall Coverage | 33.1% (gate: 65%) | Below gate |
| patch() Calls | 9,314 | Excessive mocking |
| MagicMock References | 3,476 | Heavy reliance on mocks |
| sleep Calls | 426+ | Timing-dependent |
| Zero Coverage Files | 43+ ( stmt > 10) | Major gaps |
| Files <50% Coverage | 40 | Needs attention |
| Integration Test Files | 12 | Too few for app size |
| Coverage Data Date | 2026-02-20 (47+ days old) | Stale data |

---

## Appendix: Completely Untested Core Modules (>100 statements)

| Module | Statements | Risk Level |
|--------|------------|------------|
| `cli_runner.py` | 510 | CRITICAL |
| `api/pty_manager.py` | 214 | HIGH |
| `mcp_/health_monitor.py` | 222 | HIGH |
| `api/websocket.py` | 97 | MEDIUM |
| `chatgpt_codex_client.py` | 155 | MEDIUM |
| `gemini_code_assist.py` | 176 | MEDIUM |
| `gemini_model.py` | 375 | MEDIUM |
| `terminal_utils.py` | 177 | LOW |
| `status_display.py` | 113 | LOW |
