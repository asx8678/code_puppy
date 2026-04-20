"""Tests for the auto_test_control plugin."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest

from code_puppy.run_context import RunContext
from code_puppy.workflow_state import WorkflowFlag, reset_workflow_state, set_flag


@pytest.fixture(autouse=True)
def _reset_workflow_state() -> None:
    reset_workflow_state()
    yield
    reset_workflow_state()


def _import_plugin():
    mod_name = "code_puppy.plugins.auto_test_control.register_callbacks"
    sys.modules.pop(mod_name, None)
    with patch("code_puppy.callbacks.register_callback"):
        return importlib.import_module(mod_name)


class TestConfigHelpers:
    def test_defaults_to_off_when_config_missing(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value=None):
            assert mod._get_auto_run_tests_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", "enabled"])
    def test_true_values_enable_auto_tests(self, value: str) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value=value):
            assert mod._get_auto_run_tests_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "wat"])
    def test_false_and_invalid_values_disable_auto_tests(self, value: str) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value=value):
            assert mod._get_auto_run_tests_enabled() is False

    def test_setter_persists_boolean_value(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.set_value") as set_value:
            mod._set_auto_run_tests_enabled(True)
            set_value.assert_called_once_with(mod._CONFIG_KEY, "true")


class TestPromptInjection:
    def test_load_prompt_describes_disabled_mode(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_get_auto_run_tests_enabled", return_value=False):
            prompt = mod._load_prompt()

        assert "Automatic test runs are DISABLED" in prompt
        assert "Do not run test commands" in prompt
        assert "/auto-test on" in prompt

    def test_load_prompt_describes_enabled_mode(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_get_auto_run_tests_enabled", return_value=True):
            prompt = mod._load_prompt()

        assert "Automatic test runs are ENABLED" in prompt
        assert "run the most relevant tests" in prompt


class TestCommandDetection:
    @pytest.mark.parametrize(
        "command",
        [
            "pytest tests/",
            "python -m pytest tests/test_plugin.py",
            "uv run pytest -q",
            "mix test",
            "cargo test",
            "npm test -- --silent",
            "pnpm test",
            "go test ./...",
            "bundle exec rspec spec/models/user_spec.rb",
            "./gradlew test",
        ],
    )
    def test_detects_test_commands(self, command: str) -> None:
        mod = _import_plugin()
        assert mod._is_test_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "npm run build",
            "ruff check .",
            "echo contest",
            "cat pytest.ini",
        ],
    )
    def test_ignores_non_test_commands(self, command: str) -> None:
        mod = _import_plugin()
        assert mod._is_test_command(command) is False


class TestPreToolCall:
    def test_blocks_agent_test_commands_when_disabled(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_get_auto_run_tests_enabled", return_value=False):
            result = mod._on_pre_tool_call(
                "agent_run_shell_command",
                {"command": "pytest tests/"},
            )

        assert result is not None
        assert result["blocked"] is True
        assert "/auto-test off" in result["reason"]

    def test_allows_non_test_shell_commands_when_disabled(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_get_auto_run_tests_enabled", return_value=False):
            result = mod._on_pre_tool_call(
                "agent_run_shell_command",
                {"command": "git status"},
            )

        assert result is None

    def test_allows_test_commands_when_enabled(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_get_auto_run_tests_enabled", return_value=True):
            result = mod._on_pre_tool_call(
                "agent_run_shell_command",
                {"command": "pytest tests/"},
            )

        assert result is None

    def test_ignores_other_tools(self) -> None:
        mod = _import_plugin()
        result = mod._on_pre_tool_call("read_file", {"file_path": "README.md"})
        assert result is None


class TestCustomCommand:
    def test_unknown_command_returns_none(self) -> None:
        mod = _import_plugin()
        assert mod._handle_custom_command("/notify status", "notify") is None

    @pytest.mark.parametrize(
        ("command", "name"),
        [("/auto-test", "auto-test"), ("/tests", "tests")],
    )
    def test_status_reports_current_mode(self, command: str, name: str) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_info") as emit_info,
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
        ):
            result = mod._handle_custom_command(command, name)

        assert result is True
        assert "off" in emit_info.call_args[0][0]

    @pytest.mark.parametrize(
        ("command", "name"),
        [("/auto-test on", "auto-test"), ("/tests on", "tests")],
    )
    def test_on_persists_and_invalidates_prompt_cache(
        self, command: str, name: str
    ) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_success") as emit_success,
            patch.object(mod, "_set_auto_run_tests_enabled") as set_enabled,
            patch.object(mod, "_invalidate_current_agent_prompt") as invalidate,
        ):
            result = mod._handle_custom_command(command, name)

        assert result is True
        set_enabled.assert_called_once_with(True)
        invalidate.assert_called_once_with()
        assert "enabled" in emit_success.call_args[0][0].lower()

    @pytest.mark.parametrize(
        ("command", "name"),
        [("/auto-test off", "auto-test"), ("/tests off", "tests")],
    )
    def test_off_persists_and_invalidates_prompt_cache(
        self, command: str, name: str
    ) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_success") as emit_success,
            patch.object(mod, "_set_auto_run_tests_enabled") as set_enabled,
            patch.object(mod, "_invalidate_current_agent_prompt") as invalidate,
        ):
            result = mod._handle_custom_command(command, name)

        assert result is True
        set_enabled.assert_called_once_with(False)
        invalidate.assert_called_once_with()
        assert "disabled" in emit_success.call_args[0][0].lower()

    def test_unknown_subcommand_shows_usage(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.messaging.emit_info") as emit_info:
            result = mod._handle_custom_command("/auto-test maybe", "auto-test")

        assert result is True
        assert "status|on|off" in emit_info.call_args[0][0]


class TestAgentRunEndReminder:
    def test_emits_reminder_when_changes_made_without_tests(self) -> None:
        mod = _import_plugin()
        set_flag(WorkflowFlag.DID_GENERATE_CODE)
        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end("code-puppy", "model", success=True, run_context=ctx)

        emit_info.assert_called_once()
        assert "did not run tests" in emit_info.call_args[0][0]

    def test_no_reminder_when_tests_were_run(self) -> None:
        mod = _import_plugin()
        set_flag(WorkflowFlag.DID_GENERATE_CODE)
        set_flag(WorkflowFlag.DID_RUN_TESTS)
        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end("code-puppy", "model", success=True, run_context=ctx)

        emit_info.assert_not_called()

    def test_no_reminder_without_code_changes(self) -> None:
        mod = _import_plugin()
        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end("code-puppy", "model", success=True, run_context=ctx)

        emit_info.assert_not_called()

    def test_no_reminder_for_child_runs(self) -> None:
        mod = _import_plugin()
        set_flag(WorkflowFlag.DID_GENERATE_CODE)
        parent = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )
        child = RunContext.create_child(parent, "tool", "agent_run_shell_command")

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end(
                "code-puppy", "model", success=True, run_context=child
            )

        emit_info.assert_not_called()

    def test_no_reminder_when_run_failed(self) -> None:
        mod = _import_plugin()
        set_flag(WorkflowFlag.DID_GENERATE_CODE)
        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=False),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end("code-puppy", "model", success=False, run_context=ctx)

        emit_info.assert_not_called()

    def test_no_reminder_when_auto_tests_enabled(self) -> None:
        mod = _import_plugin()
        set_flag(WorkflowFlag.DID_GENERATE_CODE)
        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="code-puppy"
        )

        with (
            patch.object(mod, "_get_auto_run_tests_enabled", return_value=True),
            patch("code_puppy.messaging.emit_info") as emit_info,
        ):
            mod._on_agent_run_end("code-puppy", "model", success=True, run_context=ctx)

        emit_info.assert_not_called()


class TestHelp:
    def test_help_lists_auto_test_command(self) -> None:
        mod = _import_plugin()
        entries = dict(mod._custom_help())
        assert (
            entries["auto-test"] == "Control automatic test execution (status|on|off)"
        )
        assert entries["tests"] == "Alias for /auto-test (status|on|off)"
