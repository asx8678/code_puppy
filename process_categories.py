#!/usr/bin/env python3
"""
Process all categories and add serial markers.
"""
import sys
from pathlib import Path

# Add the current directory to import add_serial_markers
sys.path.insert(0, str(Path(__file__).parent))

from add_serial_markers_v2 import process_file

def main():
    # Category 1: PTY/Process Spawning (group: "pty-spawn")
    cat1 = [
        ("tests/integration/test_smoke.py", ["test_version_smoke", "test_help_smoke", "test_interactive_smoke"]),
        ("tests/integration/test_mcp_integration.py", None),  # ALL tests
        ("tests/integration/test_file_operations_integration.py", None),
        ("tests/integration/test_cli_happy_path.py", ["test_interactive_cli_flow"]),
        ("tests/integration/test_cli_autosave_resume.py", None),
        ("tests/integration/test_session_rotation.py", None),
        ("tests/integration/test_real_llm_calls.py", ["test_simple_prompt_response"]),
        ("tests/integration/test_cli_harness_foundations.py", None),
        ("tests/integration/test_network_traffic_monitoring.py", ["test_network_traffic"]),
    ]
    
    # Category 2: Real Subprocess (group: "real-process")
    cat2 = [
        ("tests/integration/test_elixir_stdio_transport.py", None),
        ("tests/tools/test_command_runner_full_coverage.py", ["test_streaming_stdout", "test_failing_command", "test_silent_mode"]),
        # test_command_runner_coverage.py: need to identify which tests spawn real subprocesses.
        # We'll mark all tests for safety.
        ("tests/tools/test_command_runner_coverage.py", None),
    ]
    
    # Category 3: Environment Variable Mutation (group: "env-mutation")
    cat3 = [
        ("tests/test_callbacks_extended.py", ["class:TestCallbacksExtended"]),
        ("tests/test_config_and_storage_edge_cases.py", None),  # around line 311, we'll mark all
        ("tests/plugins/test_tracing_langfuse.py", None),  # fixture, mark all
        ("tests/plugins/test_prompt_store_integration.py", None),
        ("tests/plugins/test_tracing_langsmith.py", None),
        ("tests/plugins/test_ralph_test_plugin.py", None),
        ("tests/plugins/test_tracing_dual.py", None),
        ("tests/integration/test_cli_harness_foundations.py", None),  # lines 73, 129 already covered by ALL
        ("tests/test_callbacks_concurrent.py", None),
        ("tests/test_callback_backlog.py", None),
        ("tests/test_lifecycle_hooks_integration.py", None),
    ]
    
    # Category 4: os.chdir (group: "chdir")
    cat4 = [
        ("tests/test_security_seams.py", ["test_relative_path_to_sensitive_blocked"]),
        ("tests/utils/test_file_mutex.py", ["test_relative_path_resolved"]),
        ("tests/utils/test_path_safety.py", None),  # lines 216, 432
        ("tests/command_line/test_core_commands_full_coverage.py", ["test_cd_valid_dir"]),
    ]
    
    # Category 5: Fixed Port Binding (group: "network")
    cat5 = [
        ("tests/api/test_api_remaining_coverage.py", None),  # around line 17
        ("tests/api/test_main.py", None),  # around line 35
        ("tests/plugins/test_chatgpt_oauth_server.py", None),
        ("tests/plugins/test_chatgpt_oauth_flow.py", None),
        ("tests/plugins/test_oauth_integration.py", None),  # lines 89, 603
        ("tests/plugins/test_claude_code_oauth_coverage.py", None),
        ("tests/plugins/test_chatgpt_oauth_utils.py", None),
    ]
    
    # Category 6: Time-Based (group: "timing")
    cat6 = [
        ("tests/test_messaging_extended.py", ["test_message_listeners", "test_ui_message_timestamps"]),
        ("tests/test_policy_engine.py", None),  # around line 429
        ("tests/test_renderers_extended.py", None),  # lines 673, 687
        ("tests/test_security_seams.py", None),  # lines 207, 243, 249 (already have one test, but we'll mark all)
        ("tests/test_messaging_bus.py", None),  # around line 195
        ("tests/plugins/test_agent_memory_updater.py", None),
    ]
    
    # Category 7: DBOS (group: "dbos")
    cat7 = [
        ("tests/integration/test_dbos_enabled.py", ["test_dbos_initializes_and_creates_db"]),
        ("tests/test_app_runner_lifecycle.py", ["test_dbos_destroy_called_on_shutdown"]),
        ("tests/plugins/test_clean_command.py", None),
    ]
    
    # Category 8: Threading (group: "threading")
    cat8 = [
        ("tests/test_capability_registry.py", None),  # lines 612-651
        ("tests/test_messaging_extended.py", None),  # lines 325-327 (already have some, but we'll mark all)
        ("tests/test_policy_engine.py", None),  # lines 457-461
        ("tests/test_security.py", None),  # lines 288-397
        ("tests/test_security_seams.py", None),  # lines 76-185 (already covered)
    ]
    
    all_categories = [
        ("pty-spawn", cat1),
        ("real-process", cat2),
        ("env-mutation", cat3),
        ("chdir", cat4),
        ("network", cat5),
        ("timing", cat6),
        ("dbos", cat7),
        ("threading", cat8),
    ]
    
    for group, files in all_categories:
        print(f"\n=== Category {group} ===")
        for file_rel, tests in files:
            filepath = Path(file_rel)
            if not filepath.exists():
                print(f"  Skipping {file_rel} (not found)")
                continue
            print(f"  Processing {file_rel}")
            if tests is None:
                process_file(filepath, group, None, mark_all=True)
            else:
                process_file(filepath, group, tests, mark_all=False)
    
    print("\nAll done!")

if __name__ == "__main__":
    main()