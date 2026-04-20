"""Slash command + policy hook for automatic test execution.

This plugin gives users a simple way to control whether Code Puppy should
automatically run tests as part of agent-driven workflows.

Config (puppy.cfg):
    auto_run_tests = false   # default

Slash command:
    /auto-test status
    /auto-test on
    /auto-test off

Short alias:
    /tests status
    /tests on
    /tests off

When automatic test runs are disabled:
- prompt instructions tell agents not to run tests automatically
- agent-driven test commands are blocked via the pre_tool_call hook
- a completion reminder explains that tests were skipped and can be run manually

Manual shell pass-through (for example ``!pytest`` or ``!mix test``) still works
because it bypasses the agent tool pipeline by design.
"""

from __future__ import annotations

import logging
from pathlib import PurePath
import shlex
from typing import Any

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

_CONFIG_KEY = "auto_run_tests"
_COMMAND_NAMES = {"auto-test", "autotest", "tests"}
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "enable"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", "disable"}

_DIRECT_TEST_COMMANDS = {
    "pytest",
    "py.test",
    "tox",
    "nox",
    "nosetests",
    "rspec",
    "phpunit",
    "ctest",
    "vitest",
    "jest",
}

_RUN_TEST_SUBCOMMANDS = {
    "mix",
    "cargo",
    "go",
    "dotnet",
    "deno",
    "mvn",
    "gradle",
    "gradlew",
    "xcodebuild",
}

_JS_PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
_RUN_WRAPPERS = {"uv", "uvx", "poetry", "pipenv"}


def _get_auto_run_tests_enabled() -> bool:
    """Read auto-test mode from config.

    Defaults to ``False`` so the faster workflow is the out-of-the-box behavior.
    """
    try:
        from code_puppy.config import get_value

        raw = get_value(_CONFIG_KEY)
        if raw is None:
            return False

        normalized = raw.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    except Exception as exc:
        logger.debug("auto_test_control: failed to read config: %s", exc)

    return False


def _set_auto_run_tests_enabled(enabled: bool) -> None:
    """Persist auto-test mode to puppy.cfg."""
    from code_puppy.config import set_value

    set_value(_CONFIG_KEY, "true" if enabled else "false")


def _invalidate_current_agent_prompt() -> None:
    """Invalidate prompt caches so config changes apply immediately."""
    try:
        from code_puppy.agents.agent_manager import get_current_agent

        agent = get_current_agent()
    except Exception:
        return

    if agent is None:
        return

    try:
        if hasattr(agent, "_state") and hasattr(
            agent._state, "invalidate_system_prompt_cache"
        ):
            agent._state.invalidate_system_prompt_cache()
        elif hasattr(agent, "_state") and hasattr(agent._state, "cached_system_prompt"):
            agent._state.cached_system_prompt = None

        if hasattr(agent, "reload_code_generation_agent"):
            agent.reload_code_generation_agent()
    except Exception:
        logger.debug(
            "auto_test_control: prompt cache invalidation failed (non-critical)",
            exc_info=True,
        )


def _is_test_command(command: str) -> bool:
    """Return True when *command* looks like a test runner invocation."""
    if not command or not command.strip():
        return False

    try:
        tokens = [token.lower() for token in shlex.split(command) if token.strip()]
    except ValueError:
        tokens = [token.lower() for token in command.split() if token.strip()]

    if not tokens:
        return False

    head = PurePath(tokens[0]).name

    if head in _DIRECT_TEST_COMMANDS:
        return True

    if head.startswith("python") and len(tokens) >= 3:
        return tokens[1] == "-m" and tokens[2] in {"pytest", "unittest"}

    if head in _RUN_WRAPPERS and len(tokens) >= 3 and tokens[1] == "run":
        return PurePath(tokens[2]).name in _DIRECT_TEST_COMMANDS | {
            "pytest",
            "unittest",
        }

    if head == "bundle" and len(tokens) >= 3:
        return tokens[1] == "exec" and PurePath(tokens[2]).name == "rspec"

    if head in _JS_PACKAGE_MANAGERS:
        if len(tokens) >= 2 and tokens[1] == "test":
            return True
        return len(tokens) >= 3 and tokens[1] == "run" and tokens[2] == "test"

    if head in _RUN_TEST_SUBCOMMANDS and len(tokens) >= 2:
        return tokens[1].startswith("test")

    return False


def _load_prompt() -> str:
    """Inject prompt instructions describing the current auto-test policy."""
    if _get_auto_run_tests_enabled():
        return (
            "## Automatic Test Execution\n"
            "Automatic test runs are ENABLED for this user. When you make code changes, "
            "run the most relevant tests before you declare the task complete."
        )

    return (
        "## Automatic Test Execution\n"
        "Automatic test runs are DISABLED for this user.\n"
        "- Do not run test commands on your own after making changes.\n"
        "- Finish the coding task without waiting on tests.\n"
        "- At the end, clearly say that tests were not run because `/auto-test off` is active.\n"
        "- The user can run tests manually with `!<command>` or turn auto-tests back on with `/auto-test on`.\n"
        "- If the user wants you to run tests, ask them to enable `/auto-test on` first or to run the command manually."
    )


def _custom_help() -> list[tuple[str, str]]:
    return [
        (
            "auto-test",
            "Control automatic test execution (status|on|off)",
        ),
        ("tests", "Alias for /auto-test (status|on|off)"),
    ]


def _handle_custom_command(command: str, name: str) -> bool | str | None:
    if name not in _COMMAND_NAMES:
        return None

    try:
        from code_puppy.messaging import emit_info, emit_success
    except Exception:
        return True

    command_name = name if name else "auto-test"
    parts = command.strip().split(maxsplit=1)
    subcommand = parts[1].strip().lower() if len(parts) == 2 else "status"

    if subcommand == "status":
        enabled = _get_auto_run_tests_enabled()
        mode = "on" if enabled else "off"
        emit_info(
            "🧪 Automatic test runs: "
            f"{mode}\n"
            "   When off, agents skip test commands and you can still run tests manually with !<command>."
        )
        return True

    if subcommand in _TRUE_VALUES:
        _set_auto_run_tests_enabled(True)
        _invalidate_current_agent_prompt()
        emit_success("✅ Automatic test runs enabled and saved to puppy.cfg")
        return True

    if subcommand in _FALSE_VALUES:
        _set_auto_run_tests_enabled(False)
        _invalidate_current_agent_prompt()
        emit_success(
            "⏸️ Automatic test runs disabled and saved to puppy.cfg. "
            "Use !<command> any time you want to run tests manually."
        )
        return True

    emit_info(
        f"Unknown /{command_name} subcommand: {subcommand!r} (try status|on|off)"
    )
    return True


def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    context: Any = None,
) -> dict[str, Any] | None:
    """Block agent-driven test commands when auto-tests are disabled."""
    del context  # unused

    if tool_name != "agent_run_shell_command":
        return None

    if _get_auto_run_tests_enabled():
        return None

    command = str(tool_args.get("command", ""))
    if not _is_test_command(command):
        return None

    message = (
        "Automatic test runs are disabled (`/auto-test off`). "
        "Skip this test command so development stays fast. "
        "Run tests yourself with !<command> or re-enable agent-driven tests with `/auto-test on`."
    )

    return {
        "blocked": True,
        "reason": message,
        "error_message": message,
    }


def _should_emit_skip_reminder(success: bool, run_context: Any | None) -> bool:
    """Return True when we should remind the user that tests were skipped."""
    if not success:
        return False

    if _get_auto_run_tests_enabled():
        return False

    if run_context is not None and getattr(run_context, "parent_run_id", None):
        return False

    try:
        from code_puppy.workflow_state import get_workflow_state

        state = get_workflow_state()
    except Exception:
        return False

    made_changes = any(
        (
            state.did_generate_code,
            state.did_edit_file,
            state.did_create_file,
            state.did_delete_file,
        )
    )

    return made_changes and not state.did_run_tests


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Any | None = None,
    response_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    run_context: Any | None = None,
    **kwargs: Any,
) -> None:
    """Remind the user that tests were intentionally skipped."""
    del agent_name, model_name, session_id, error, response_text, metadata, kwargs

    if not _should_emit_skip_reminder(success, run_context):
        return

    try:
        from code_puppy.messaging import emit_info

        emit_info(
            "🧪 Automatic test runs are off, so I did not run tests for this task. "
            "If you want to verify now, run them manually with !<command> or turn auto-tests back on with `/auto-test on`."
        )
    except Exception:
        logger.debug("auto_test_control: could not emit skip reminder", exc_info=True)


register_callback("load_prompt", _load_prompt)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_custom_command)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("agent_run_end", _on_agent_run_end)
