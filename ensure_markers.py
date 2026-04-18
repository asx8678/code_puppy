#!/usr/bin/env python3
"""
Ensure all required tests have serial and xdist_group markers.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import the processing function
sys.path.insert(0, str(Path(__file__).parent))
from add_serial_markers_v2 import process_file

# Mapping from file to (group, test_names_or_None)
# Generated from the categories, deduplicated by file (first occurrence wins)
FILE_MAP: Dict[str, Tuple[str, Optional[List[str]]]] = {
    # Category 1: PTY/Process Spawning (group: "pty-spawn")
    "tests/integration/test_smoke.py": ("pty-spawn", ["test_version_smoke", "test_help_smoke", "test_interactive_smoke"]),
    "tests/integration/test_mcp_integration.py": ("pty-spawn", None),
    "tests/integration/test_file_operations_integration.py": ("pty-spawn", None),
    "tests/integration/test_cli_happy_path.py": ("pty-spawn", ["test_cli_happy_path_interactive_flow"]),  # actual name
    "tests/integration/test_cli_autosave_resume.py": ("pty-spawn", None),
    "tests/integration/test_session_rotation.py": ("pty-spawn", None),
    "tests/integration/test_real_llm_calls.py": ("pty-spawn", None),  # test name unknown, mark all
    "tests/integration/test_cli_harness_foundations.py": ("pty-spawn", None),
    "tests/integration/test_network_traffic_monitoring.py": ("pty-spawn", None),  # test name unknown
    # Category 2: Real Subprocess (group: "real-process")
    "tests/integration/test_elixir_stdio_transport.py": ("real-process", None),
    "tests/tools/test_command_runner_full_coverage.py": ("real-process", None),  # specific tests unknown
    "tests/tools/test_command_runner_coverage.py": ("real-process", None),
    # Category 3: Environment Variable Mutation (group: "env-mutation")
    "tests/test_callbacks_extended.py": ("env-mutation", ["class:TestCallbacksExtended"]),
    "tests/test_config_and_storage_edge_cases.py": ("env-mutation", None),
    "tests/plugins/test_tracing_langfuse.py": ("env-mutation", None),
    "tests/plugins/test_prompt_store_integration.py": ("env-mutation", None),
    "tests/plugins/test_tracing_langsmith.py": ("env-mutation", None),
    "tests/plugins/test_ralph_test_plugin.py": ("env-mutation", None),
    "tests/plugins/test_tracing_dual.py": ("env-mutation", None),
    "tests/test_callbacks_concurrent.py": ("env-mutation", None),
    "tests/test_callback_backlog.py": ("env-mutation", None),
    "tests/test_lifecycle_hooks_integration.py": ("env-mutation", None),
    # Category 4: os.chdir (group: "chdir")
    "tests/test_security_seams.py": ("chdir", None),  # multiple tests, mark all
    "tests/utils/test_file_mutex.py": ("chdir", None),
    "tests/utils/test_path_safety.py": ("chdir", None),
    "tests/command_line/test_core_commands_full_coverage.py": ("chdir", None),
    # Category 5: Fixed Port Binding (group: "network")
    "tests/api/test_api_remaining_coverage.py": ("network", None),
    "tests/api/test_main.py": ("network", None),
    "tests/plugins/test_chatgpt_oauth_server.py": ("network", None),
    "tests/plugins/test_chatgpt_oauth_flow.py": ("network", None),
    "tests/plugins/test_oauth_integration.py": ("network", None),
    "tests/plugins/test_claude_code_oauth_coverage.py": ("network", None),
    "tests/plugins/test_chatgpt_oauth_utils.py": ("network", None),
    # Category 6: Time-Based (group: "timing")
    "tests/test_messaging_extended.py": ("timing", None),
    "tests/test_policy_engine.py": ("timing", None),
    "tests/test_renderers_extended.py": ("timing", None),
    "tests/test_messaging_bus.py": ("timing", None),
    "tests/plugins/test_agent_memory_updater.py": ("timing", None),
    # Category 7: DBOS (group: "dbos")
    "tests/integration/test_dbos_enabled.py": ("dbos", ["test_dbos_initializes_and_creates_db"]),
    "tests/test_app_runner_lifecycle.py": ("dbos", None),
    "tests/plugins/test_clean_command.py": ("dbos", None),
    # Category 8: Threading (group: "threading")
    "tests/test_capability_registry.py": ("threading", None),
    "tests/test_security.py": ("threading", None),
}

def file_has_serial_marker(filepath: Path) -> bool:
    """Check if file contains @pytest.mark.serial."""
    try:
        with open(filepath, "r") as f:
            content = f.read()
        return "@pytest.mark.serial" in content
    except FileNotFoundError:
        return False

def main():
    for file_rel, (group, tests) in FILE_MAP.items():
        filepath = Path(file_rel)
        if not filepath.exists():
            print(f"SKIP: {file_rel} not found")
            continue
        if file_has_serial_marker(filepath):
            print(f"OK: {file_rel} already has serial marker")
            # Ensure xdist_group exists with correct group? We'll trust existing.
            continue
        print(f"ADDING markers to {file_rel} (group={group})")
        process_file(filepath, group, tests, mark_all=(tests is None))
    print("\nDone.")

if __name__ == "__main__":
    main()