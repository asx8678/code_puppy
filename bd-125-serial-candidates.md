# Serial-Scan Candidates: Tests Inherently Non-Parallel-Safe

**Date:** 2026-04-18  
**Task:** bd-125  
**Purpose:** Identify tests that CANNOT run in parallel

---

## Summary

Tests classified as non-parallel-safe due to:
- Real process/PTY spawning (pexpect, subprocess.Popen)
- Global state mutation (os.environ, os.chdir)
- Network resource binding (fixed ports)
- Time-based race conditions (time.sleep)

**Total candidates:** ~45 tests across 8 categories
## Category 1: PTY/Process Spawning (pexpect)

Tests that spawn real terminal processes via pexpect.

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/integration/test_smoke.py | test_version_command | Spawns pexpect CLI | high | pty-spawn |
| tests/integration/test_smoke.py | test_help_command | Spawns pexpect CLI | high | pty-spawn |
| tests/integration/test_smoke.py | test_interactive_mode | Spawns interactive CLI | high | pty-spawn |
| tests/integration/test_mcp_integration.py | All tests | Uses cli_harness.spawn() | high | pty-spawn |
| tests/integration/test_file_operations_integration.py | All tests | Uses cli_harness.spawn() | high | pty-spawn |
| tests/integration/test_cli_happy_path.py | test_interactive_cli_flow | Uses cli_harness.spawn() | high | pty-spawn |
| tests/integration/test_cli_autosave_resume.py | All tests | Spawns multiple CLI | high | pty-spawn |
| tests/integration/test_session_rotation.py | All tests | Spawns multiple CLI | high | pty-spawn |
| tests/integration/test_real_llm_calls.py | test_simple_prompt_response | Uses cli_harness.spawn() | high | pty-spawn |
| tests/integration/test_cli_harness_foundations.py | All tests | Tests CLI harness spawning | high | pty-spawn |
| tests/integration/test_network_traffic_monitoring.py | test_network_traffic | Spawns CLI + HTTP proxy | high | pty-spawn |
## Category 2: Real Subprocess Execution

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/integration/test_elixir_stdio_transport.py | All tests | Spawns Elixir stdio service | high | real-process |
| tests/tools/test_command_runner_full_coverage.py | test_streaming_stdout (line 444) | Spawns real subprocess | medium | real-process |
| tests/tools/test_command_runner_full_coverage.py | test_failing_command (line 472) | Spawns real subprocess | medium | real-process |
| tests/tools/test_command_runner_full_coverage.py | test_silent_mode (line 497) | Spawns real subprocess | medium | real-process |
| tests/tools/test_command_runner_coverage.py | Multiple tests (lines 70-204) | Spawns real subprocesses | medium | real-process |

## Category 3: Environment Variable Mutation (without monkeypatch)

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/test_callbacks_extended.py | All class tests | Sets os.environ directly | high | env-mutation |
| tests/test_config_and_storage_edge_cases.py | Line 311 | Direct os.environ[] assignment | medium | env-mutation |
| tests/plugins/test_tracing_langfuse.py | Fixture | Restores os.environ directly | medium | env-mutation |
| tests/plugins/test_prompt_store_integration.py | Line 21 | Sets os.environ directly | medium | env-mutation |
| tests/plugins/test_tracing_langsmith.py | Fixture | Restores os.environ directly | medium | env-mutation |
| tests/plugins/test_ralph_test_plugin.py | Multiple tests | Direct os.environ[] assignment | medium | env-mutation |
| tests/plugins/test_tracing_dual.py | Fixture | Direct os.environ[] mutation | medium | env-mutation |
| tests/integration/test_cli_harness_foundations.py | Lines 73, 129 | Sets env directly | high | env-mutation |
| tests/test_callbacks_concurrent.py | Multiple tests | Direct os.environ[] assignment | medium | env-mutation |
| tests/test_callback_backlog.py | Line 20 | Direct os.environ[] assignment | medium | env-mutation |
| tests/test_lifecycle_hooks_integration.py | Lines 40, 52 | Direct os.environ[] assignment | medium | env-mutation |
## Category 4: Global Directory Changes (os.chdir)

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/test_security_seams.py | test_relative_path_to_sensitive_blocked | os.chdir(home) | medium | chdir |
| tests/utils/test_file_mutex.py | test_relative_path_resolved | os.chdir(tmp_path) | medium | chdir |
| tests/utils/test_path_safety.py | Lines 216, 432 | os.chdir(tmp_path) | medium | chdir |
| tests/command_line/test_core_commands_full_coverage.py | test_cd_valid_dir | os.chdir via command | high | chdir |

## Category 5: Network Resource Binding (Fixed Ports)

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/api/test_api_remaining_coverage.py | Line 17 | main(port=9999) fixed port | high | network |
| tests/api/test_main.py | Line 35 | main(port=9999) fixed port | high | network |
| tests/plugins/test_chatgpt_oauth_server.py | All tests | Uses port 1455 | high | network |
| tests/plugins/test_chatgpt_oauth_flow.py | All tests | Uses port 1455 | high | network |
| tests/plugins/test_oauth_integration.py | Lines 89, 603 | OAuth server tests | high | network |
| tests/plugins/test_claude_code_oauth_coverage.py | Multiple tests | localhost:19000 | medium | network |
| tests/plugins/test_chatgpt_oauth_utils.py | Multiple tests | localhost:1455 | medium | network |
## Category 6: Time-Based Race Conditions

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/test_messaging_extended.py | test_message_listeners (line 225) | time.sleep(0.1) | medium | timing |
| tests/test_messaging_extended.py | test_ui_message_timestamps (line 330) | time.sleep(0.1) | medium | timing |
| tests/test_policy_engine.py | Line 429 | time.sleep(0.05) | medium | timing |
| tests/test_renderers_extended.py | Lines 673, 687 | time.sleep() | medium | timing |
| tests/test_security_seams.py | Lines 207, 243, 249 | time.sleep() in threads | medium | timing |
| tests/test_messaging_bus.py | Line 195 | time.sleep(0.01) | medium | timing |
| tests/plugins/test_agent_memory_updater.py | Multiple lines | Multiple time.sleep() | medium | timing |

## Category 7: DBOS Integration Tests

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/integration/test_dbos_enabled.py | test_dbos_initializes_and_creates_db | Spawns CLI with DBOS | high | dbos |
| tests/test_app_runner_lifecycle.py | test_dbos_destroy_called_on_shutdown | Mocks DBOS | low | dbos |
| tests/plugins/test_clean_command.py | Multiple tests | Tests DBOS SQLite cleanup | medium | dbos |

## Category 8: Threading Without Proper Isolation

| Test File | Test Name | Reason | Confidence | Group |
|-----------|-----------|--------|------------|-------|
| tests/test_capability_registry.py | Lines 612-651 | Spawns 20 threads | medium | threading |
| tests/test_messaging_extended.py | Lines 325-327 | Spawns producer thread | medium | threading |
| tests/test_policy_engine.py | Lines 457-461 | Spawns 5 racer threads | medium | threading |
| tests/test_security.py | Lines 288-397 | Multiple tests with 10+ threads | medium | threading |
| tests/test_security_seams.py | Lines 76-185 | Multiple tests with 5-20 threads | medium | threading |
## Recommended Serial Groups

For pytest-xdist parallel execution, group these tests:

### High-Priority Serial Groups

1. **integration-cli** - All tests in tests/integration/ using cli_harness or spawned_cli
2. **oauth-server** - Already marked with @pytest.mark.xdist_group("oauth-server")
3. **api-fixed-port** - Tests binding to port 9999
4. **elixir-stdio** - Elixir stdio transport tests

### Medium-Priority Serial Groups

1. **env-mutation-callbacks** - Tests directly mutating PUP_DISABLE_CALLBACK_PLUGIN_LOADING
2. **threading-stress** - Tests spawning multiple threads for stress testing

## Notes

- Tests with @pytest.mark.skip(reason="Flaky") are excluded
- The isolate_config_between_tests fixture handles config isolation well
- Most os.chdir tests have proper try/finally cleanup
- time.sleep() usage can cause flakiness under parallel load
- Dynamic port binding (port=0) is safe; only fixed ports are problematic

---

Report generated by Code Scout (bd-125)