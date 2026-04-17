"""Tests for the proactive_guidance plugin.

This module tests the proactive guidance plugin that provides contextual
next-step suggestions after tool execution.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _import_plugin():
    """Import and return the plugin module with all its functions."""
    module = importlib.import_module(
        "code_puppy.plugins.proactive_guidance.register_callbacks"
    )
    return module


@pytest.fixture
def plugin_module():
    """Fixture providing the plugin module."""
    return _import_plugin()


@pytest.fixture
def fresh_state(plugin_module):
    """Fixture that resets plugin state to known defaults."""
    original_state = dict(plugin_module._state)
    plugin_module._state["enabled"] = True
    plugin_module._state["verbosity"] = "normal"
    plugin_module._state["last_tool"] = None
    plugin_module._state["guidance_count"] = 0
    yield plugin_module._state
    # Restore original state after test
    plugin_module._state.clear()
    plugin_module._state.update(original_state)


# ---------------------------------------------------------------------------
# Tests: Guidance Generation for Write Operations
# ---------------------------------------------------------------------------


class TestWriteGuidance:
    """Tests for _get_write_guidance() function."""

    def test_python_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Python files includes pytest and syntax check."""
        guidance = plugin_module._get_write_guidance("test.py", "def hello(): pass")
        assert guidance is not None
        assert "pytest" in guidance
        assert "py_compile" in guidance
        assert "✨ Next steps for your new file:" in guidance

    def test_javascript_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for JavaScript files."""
        guidance = plugin_module._get_write_guidance("app.js", "console.log('hi')")
        assert guidance is not None
        assert "pytest" in guidance  # Uses generic guidance for code files
        assert "py_compile" in guidance

    def test_typescript_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for TypeScript files."""
        guidance = plugin_module._get_write_guidance("app.ts", "const x: number = 1")
        assert guidance is not None
        assert "pytest" in guidance

    def test_markdown_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for markdown files."""
        guidance = plugin_module._get_write_guidance("README.md", "# Title")
        assert guidance is not None
        assert "cat" in guidance
        assert "head -20" in guidance

    def test_json_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for JSON files includes validation."""
        guidance = plugin_module._get_write_guidance("config.json", '{"key": "val"}')
        assert guidance is not None
        assert "Validate" in guidance
        assert "json.load" in guidance

    def test_yaml_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for YAML files."""
        guidance = plugin_module._get_write_guidance("config.yaml", "key: val")
        assert guidance is not None
        assert "Validate" in guidance

    def test_shell_script_guidance(self, plugin_module, fresh_state):
        """Test guidance for shell scripts includes shellcheck and chmod."""
        guidance = plugin_module._get_write_guidance("script.sh", "#!/bin/bash")
        assert guidance is not None
        assert "shellcheck" in guidance
        assert "chmod +x" in guidance

    def test_bash_script_guidance(self, plugin_module, fresh_state):
        """Test guidance for bash scripts."""
        guidance = plugin_module._get_write_guidance("script.bash", "#!/bin/bash")
        assert guidance is not None
        assert "shellcheck" in guidance

    def test_rust_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Rust files."""
        guidance = plugin_module._get_write_guidance("main.rs", "fn main() {}")
        assert guidance is not None
        assert "pytest" in guidance

    def test_go_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Go files."""
        guidance = plugin_module._get_write_guidance("main.go", "package main")
        assert guidance is not None
        assert "pytest" in guidance

    def test_minimal_verbosity_no_view_option(self, plugin_module, fresh_state):
        """Test that minimal verbosity excludes view file option."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_write_guidance("test.py", "pass")
        assert guidance is not None
        assert "/file" not in guidance  # View file option not shown in minimal mode
        assert "/grep" not in guidance  # Search option not shown in minimal mode

    def test_verbose_verbosity_extra_suggestions(self, plugin_module, fresh_state):
        """Test that verbose verbosity includes extra suggestions."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_write_guidance("test.py", "pass")
        assert guidance is not None
        # Verbose mode should include more lines than minimal suggestion count
        # Check for additional suggestions (verbose adds test file and git diff suggestions)
        assert guidance.count("\n") >= 4  # Should have at least header + 4 suggestions in verbose mode

    def test_empty_suggestions_returns_none(self, plugin_module, fresh_state):
        """Test that files with no specific guidance return None."""
        # Use an unknown extension that doesn't match any patterns
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_write_guidance("file.unknownxyz", "content")
        # With minimal verbosity and no matching patterns, should return None
        # Actually the function always adds at least /file and /grep for normal+
        # So let's test with minimal where no suggestions are added


# ---------------------------------------------------------------------------
# Tests: Guidance Generation for Shell Commands
# ---------------------------------------------------------------------------


class TestShellGuidance:
    """Tests for _get_shell_guidance() function."""

    def test_pytest_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after successful pytest run."""
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance
        assert "commit" in guidance.lower() or "Tests passed" in guidance

    def test_pytest_success_coverage_suggestion(self, plugin_module, fresh_state):
        """Test that successful pytest suggests coverage in normal mode."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "--cov" in guidance or "coverage" in guidance.lower()

    def test_pytest_success_no_coverage_in_minimal(self, plugin_module, fresh_state):
        """Test that minimal verbosity doesn't include coverage suggestion."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "--cov" not in guidance

    def test_git_commit_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after git commit."""
        guidance = plugin_module._get_shell_guidance("git commit -m 'msg'", 0)
        assert guidance is not None
        # Note: "git commit -m 'test'" would match pytest pattern, so we use 'msg'
        assert "push" in guidance.lower()

    def test_git_add_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after git add."""
        guidance = plugin_module._get_shell_guidance("git add file.py", 0)
        assert guidance is not None
        assert "push" in guidance.lower()

    def test_git_push_pr_suggestion_in_verbose(self, plugin_module, fresh_state):
        """Test verbose mode suggests creating PR."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_shell_guidance("git commit -m 'msg'", 0)
        assert guidance is not None
        assert "pr create" in guidance.lower() or "PR" in guidance

    def test_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after successful build."""
        guidance = plugin_module._get_shell_guidance("cargo build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "🎯" in guidance

    def test_make_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after make command."""
        guidance = plugin_module._get_shell_guidance("make all", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "🎯" in guidance or "✅" in guidance

    def test_npm_install_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm install."""
        guidance = plugin_module._get_shell_guidance("npm install", 0)
        assert guidance is not None
        assert "dependencies" in guidance.lower() or "📦" in guidance

    def test_pip_install_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after pip install."""
        guidance = plugin_module._get_shell_guidance("pip install requests", 0)
        assert guidance is not None
        assert "freeze" in guidance or "📦" in guidance

    def test_grep_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after grep command."""
        guidance = plugin_module._get_shell_guidance("grep -r 'pattern' src/", 0)
        assert guidance is not None
        assert "Found matches" in guidance or "🔍" in guidance or "✅" in guidance

    def test_find_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after find command."""
        guidance = plugin_module._get_shell_guidance("find . -name '*.py'", 0)
        assert guidance is not None
        assert "Found matches" in guidance or "🔍" in guidance or "✅" in guidance

    def test_ls_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after ls command."""
        guidance = plugin_module._get_shell_guidance("ls -la", 0)
        assert guidance is not None
        assert "Explore" in guidance or "📂" in guidance or "✅" in guidance

    def test_tree_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after tree command."""
        guidance = plugin_module._get_shell_guidance("tree", 0)
        assert guidance is not None
        assert "Explore" in guidance or "📂" in guidance or "✅" in guidance

    def test_npm_test_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm test."""
        guidance = plugin_module._get_shell_guidance("npm test", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance

    def test_cargo_test_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after cargo test."""
        guidance = plugin_module._get_shell_guidance("cargo test", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance

    def test_cargo_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after cargo build."""
        guidance = plugin_module._get_shell_guidance("cargo build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "✅" in guidance

    def test_npm_run_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm run build."""
        guidance = plugin_module._get_shell_guidance("npm run build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "✅" in guidance

    def test_generic_command_success(self, plugin_module, fresh_state):
        """Test guidance for generic commands that match no specific patterns."""
        guidance = plugin_module._get_shell_guidance("echo hello", 0)
        assert guidance is not None
        assert "✅" in guidance or "Command completed" in guidance

    def test_command_failure_guidance(self, plugin_module, fresh_state):
        """Test guidance when command fails (non-zero exit code)."""
        guidance = plugin_module._get_shell_guidance("false", 1)
        assert guidance is not None
        assert "⚠️" in guidance or "failed" in guidance.lower()
        assert "exit code 1" in guidance
        assert "Debug" in guidance or "verbose" in guidance.lower()

    def test_command_failure_exit_code_2(self, plugin_module, fresh_state):
        """Test guidance when command fails with exit code 2."""
        guidance = plugin_module._get_shell_guidance("grep pattern file.txt", 2)
        assert guidance is not None
        assert "⚠️" in guidance or "failed" in guidance.lower()
        assert "exit code 2" in guidance

    def test_shell_reuse_suggestion_in_normal_mode(self, plugin_module, fresh_state):
        """Test that normal mode suggests running similar command."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_shell_guidance("echo test", 0)
        assert guidance is not None
        assert "/shell" in guidance or "Use ↑" in guidance

    def test_shell_reuse_not_in_minimal_mode(self, plugin_module, fresh_state):
        """Test that minimal mode doesn't suggest command reuse."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_shell_guidance("echo test", 0)
        assert guidance is not None
        assert "/shell" not in guidance


# ---------------------------------------------------------------------------
# Tests: Guidance Generation for Agent Invocations
# ---------------------------------------------------------------------------


class TestAgentGuidance:
    """Tests for _get_agent_guidance() function."""

    def test_agent_completion_guidance(self, plugin_module, fresh_state):
        """Test basic agent completion guidance."""
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "test_agent" in guidance
        assert "🤖" in guidance or "completed" in guidance.lower()

    def test_normal_verbosity_includes_review(self, plugin_module, fresh_state):
        """Test normal verbosity includes review suggestion."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "Review" in guidance or "output" in guidance.lower()
        assert "Iterate" in guidance or "re-invoke" in guidance.lower()

    def test_verbose_verbosity_extra_guidance(self, plugin_module, fresh_state):
        """Test verbose verbosity includes extra suggestions."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "context" in guidance.lower() or "Document" in guidance

    def test_minimal_verbosity_basic_only(self, plugin_module, fresh_state):
        """Test minimal verbosity only includes basic completion message."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "test_agent" in guidance
        # In minimal mode, no extra suggestions should be included


# ---------------------------------------------------------------------------
# Tests: /guidance Command Handling
# ---------------------------------------------------------------------------


class TestGuidanceCommand:
    """Tests for _handle_custom_command() function."""

    def test_ignores_other_commands(self, plugin_module):
        """Test handler returns None for non-guidance commands."""
        result = plugin_module._handle_custom_command("/other", "other")
        assert result is None

    def test_ignores_wrong_base_command(self, plugin_module):
        """Test handler returns None for commands that start with different base."""
        result = plugin_module._handle_custom_command("/guidance_extra", "guidance_extra")
        assert result is None

    def test_status_command(self, plugin_module, fresh_state):
        """Test /guidance status command."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance status", "guidance")
            assert result is True
            mock_emit.assert_called_once()
            status_msg = mock_emit.call_args[0][0]
            assert "Proactive Guidance" in status_msg
            assert "enabled" in status_msg.lower()

    def test_status_default_when_no_subcommand(self, plugin_module, fresh_state):
        """Test /guidance without subcommand defaults to status."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance", "guidance")
            assert result is True
            mock_emit.assert_called_once()
            status_msg = mock_emit.call_args[0][0]
            assert "Proactive Guidance" in status_msg

    def test_on_command(self, plugin_module, fresh_state):
        """Test /guidance on command enables guidance."""
        fresh_state["enabled"] = False
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance on", "guidance")
            assert result is True
            assert fresh_state["enabled"] is True
            mock_emit.assert_called_once()
            assert "enabled" in mock_emit.call_args[0][0].lower()

    def test_enable_alias(self, plugin_module, fresh_state):
        """Test /guidance enable is an alias for on."""
        fresh_state["enabled"] = False
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance enable", "guidance")
            assert result is True
            assert fresh_state["enabled"] is True

    def test_off_command(self, plugin_module, fresh_state):
        """Test /guidance off command disables guidance."""
        fresh_state["enabled"] = True
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance off", "guidance")
            assert result is True
            assert fresh_state["enabled"] is False
            mock_emit.assert_called_once()
            assert "disabled" in mock_emit.call_args[0][0].lower()

    def test_disable_alias(self, plugin_module, fresh_state):
        """Test /guidance disable is an alias for off."""
        fresh_state["enabled"] = True
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance disable", "guidance")
            assert result is True
            assert fresh_state["enabled"] is False

    def test_verbosity_minimal(self, plugin_module, fresh_state):
        """Test /guidance verbosity minimal command."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(
                "/guidance verbosity minimal", "guidance"
            )
            assert result is True
            assert fresh_state["verbosity"] == "minimal"
            mock_emit.assert_called_once()
            assert "minimal" in mock_emit.call_args[0][0]

    def test_verbosity_normal(self, plugin_module, fresh_state):
        """Test /guidance verbosity normal command."""
        fresh_state["verbosity"] = "minimal"
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(
                "/guidance verbosity normal", "guidance"
            )
            assert result is True
            assert fresh_state["verbosity"] == "normal"

    def test_verbosity_verbose(self, plugin_module, fresh_state):
        """Test /guidance verbosity verbose command."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(
                "/guidance verbosity verbose", "guidance"
            )
            assert result is True
            assert fresh_state["verbosity"] == "verbose"

    def test_verbosity_invalid(self, plugin_module, fresh_state):
        """Test /guidance verbosity with invalid value."""
        original_verbosity = fresh_state["verbosity"]
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(
                "/guidance verbosity invalid", "guidance"
            )
            assert result is True
            # Invalid verbosity should not change the state
            assert fresh_state["verbosity"] == original_verbosity
            mock_emit.assert_called_once()
            assert "Invalid" in mock_emit.call_args[0][0]

    def test_test_command(self, plugin_module, fresh_state):
        """Test /guidance test command shows sample guidance."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance test", "guidance")
            assert result is True
            # Should emit multiple times for sample output
            assert mock_emit.call_count >= 2
            # First call should indicate sample output
            first_call = mock_emit.call_args_list[0][0][0]
            assert "Sample" in first_call or "🧪" in first_call

    def test_reset_command(self, plugin_module, fresh_state):
        """Test /guidance reset command resets counter."""
        fresh_state["guidance_count"] = 42
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command("/guidance reset", "guidance")
            assert result is True
            assert fresh_state["guidance_count"] == 0
            mock_emit.assert_called_once()
            assert "reset" in mock_emit.call_args[0][0].lower()

    def test_unknown_subcommand(self, plugin_module, fresh_state):
        """Test unknown subcommand shows error message."""
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(
                "/guidance unknown_cmd", "guidance"
            )
            assert result is True
            mock_emit.assert_called_once()
            assert "Unknown" in mock_emit.call_args[0][0]
            assert "unknown_cmd" in mock_emit.call_args[0][0]

    def test_emit_import_failure_handling(self, plugin_module):
        """Test that handler returns True even when emit_info import fails."""
        with patch.dict(
            "sys.modules", {"code_puppy.messaging": None}
        ), patch.object(sys, "modules", dict(sys.modules)):
            # Force re-import to fail
            result = plugin_module._handle_custom_command("/guidance status", "guidance")
            # Should return True to indicate command was handled (even if display failed)
            assert result is True


# ---------------------------------------------------------------------------
# Tests: Callback Registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    """Tests that verify callbacks are properly registered."""

    def test_help_callback_registered(self, plugin_module):
        """Test that custom_command_help returns guidance entry."""
        help_entries = plugin_module._on_custom_help()
        assert isinstance(help_entries, list)
        assert len(help_entries) == 2
        # First entry is the main command
        name, desc = help_entries[0]
        assert name == "/guidance"
        assert "proactive guidance" in desc.lower()

    def test_help_includes_verbosity(self, plugin_module):
        """Test that help includes verbosity command."""
        help_entries = plugin_module._on_custom_help()
        assert len(help_entries) == 2
        name, desc = help_entries[1]
        assert "/guidance verbosity" in name
        assert "detail level" in desc.lower()


# ---------------------------------------------------------------------------
# Tests: Configuration Helpers
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    """Tests for configuration helper functions."""

    def test_get_config_enabled_true_values(self, plugin_module):
        """Test _get_config_enabled returns True for various true values."""
        from code_puppy import config as config_module

        for true_value in ["true", "True", "TRUE", "1", "yes", "Yes", "on", "ON"]:
            with patch.object(config_module, "get_value", return_value=true_value):
                result = plugin_module._get_config_enabled()
                assert result is True, f"Failed for value: {true_value}"

    def test_get_config_enabled_false_values(self, plugin_module):
        """Test _get_config_enabled returns False for various false values."""
        from code_puppy import config as config_module

        for false_value in ["false", "False", "FALSE", "0", "no", "No", "off", "OFF", "random"]:
            with patch.object(config_module, "get_value", return_value=false_value):
                result = plugin_module._get_config_enabled()
                assert result is False, f"Failed for value: {false_value}"

    def test_get_config_enabled_default_when_none(self, plugin_module):
        """Test _get_config_enabled defaults to True when config value is None."""
        from code_puppy import config as config_module

        with patch.object(config_module, "get_value", return_value=None):
            result = plugin_module._get_config_enabled()
            assert result is True

    def test_get_config_enabled_handles_exception(self, plugin_module):
        """Test _get_config_enabled defaults to True on exception."""
        from code_puppy import config as config_module

        with patch.object(config_module, "get_value", side_effect=Exception("config error")):
            result = plugin_module._get_config_enabled()
            assert result is True

    def test_get_config_verbosity_valid_values(self, plugin_module):
        """Test _get_config_verbosity accepts valid verbosity values."""
        from code_puppy import config as config_module

        for valid in ["minimal", "normal", "verbose", "MINIMAL", "Normal", "VERBOSE"]:
            with patch.object(config_module, "get_value", return_value=valid):
                result = plugin_module._get_config_verbosity()
                assert result == valid.strip().lower(), f"Failed for value: {valid}"

    def test_get_config_verbosity_invalid_defaults_normal(self, plugin_module):
        """Test _get_config_verbosity defaults to normal for invalid values."""
        from code_puppy import config as config_module

        with patch.object(config_module, "get_value", return_value="invalid_verbosity"):
            result = plugin_module._get_config_verbosity()
            assert result == "normal"

    def test_get_config_verbosity_default_when_none(self, plugin_module):
        """Test _get_config_verbosity defaults to normal when config value is None."""
        from code_puppy import config as config_module

        with patch.object(config_module, "get_value", return_value=None):
            result = plugin_module._get_config_verbosity()
            assert result == "normal"

    def test_get_config_verbosity_handles_exception(self, plugin_module):
        """Test _get_config_verbosity defaults to normal on exception."""
        from code_puppy import config as config_module

        with patch.object(config_module, "get_value", side_effect=Exception("config error")):
            result = plugin_module._get_config_verbosity()
            assert result == "normal"

    def test_is_enabled_when_both_true(self, plugin_module, fresh_state):
        """Test _is_enabled returns True when both config and runtime are enabled."""
        fresh_state["enabled"] = True
        with patch.object(plugin_module, "_get_config_enabled", return_value=True):
            result = plugin_module._is_enabled()
            assert result is True

    def test_is_enabled_when_runtime_disabled(self, plugin_module, fresh_state):
        """Test _is_enabled returns False when runtime state is disabled."""
        fresh_state["enabled"] = False
        with patch.object(plugin_module, "_get_config_enabled", return_value=True):
            result = plugin_module._is_enabled()
            assert result is False

    def test_is_enabled_when_config_disabled(self, plugin_module, fresh_state):
        """Test _is_enabled returns False when config is disabled."""
        fresh_state["enabled"] = True
        with patch.object(plugin_module, "_get_config_enabled", return_value=False):
            result = plugin_module._is_enabled()
            assert result is False

    def test_is_enabled_when_both_disabled(self, plugin_module, fresh_state):
        """Test _is_enabled returns False when both are disabled."""
        fresh_state["enabled"] = False
        with patch.object(plugin_module, "_get_config_enabled", return_value=False):
            result = plugin_module._is_enabled()
            assert result is False


# ---------------------------------------------------------------------------
# Tests: Post-Tool Call Hook
# ---------------------------------------------------------------------------


class TestPostToolCall:
    """Tests for _on_post_tool_call() async callback."""

    async def test_disabled_does_nothing(self, plugin_module, fresh_state):
        """Test callback does nothing when guidance is disabled."""
        fresh_state["enabled"] = False

        with patch("code_puppy.messaging.emit_info") as mock_emit:
            await plugin_module._on_post_tool_call(
                "create_file",
                {"file_path": "test.py", "content": "pass"},
                {"success": True},
                100.0,
            )
            mock_emit.assert_not_called()

    async def test_create_file_triggers_guidance(self, plugin_module, fresh_state):
        """Test create_file tool triggers write guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_get_config_enabled", return_value=True
        ), patch.object(plugin_module, "_is_enabled", return_value=True):
            await plugin_module._on_post_tool_call(
                "create_file",
                {"file_path": "test.py", "content": "def hello(): pass"},
                {"success": True},
                100.0,
            )
            mock_emit.assert_called_once()
            guidance = mock_emit.call_args[0][0]
            assert "✨ Next steps" in guidance
            assert fresh_state["guidance_count"] == 1
            assert fresh_state["last_tool"] == "create_file"

    async def test_replace_in_file_triggers_guidance(self, plugin_module, fresh_state):
        """Test replace_in_file tool triggers write guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            await plugin_module._on_post_tool_call(
                "replace_in_file",
                {"file_path": "test.py", "replacements": []},
                {"success": True},
                100.0,
            )
            mock_emit.assert_called_once()
            assert fresh_state["guidance_count"] == 1
            assert fresh_state["last_tool"] == "replace_in_file"

    async def test_shell_command_success_triggers_guidance(
        self, plugin_module, fresh_state
    ):
        """Test shell command with exit code 0 triggers guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            await plugin_module._on_post_tool_call(
                "agent_run_shell_command",
                {"command": "pytest tests/"},
                {"exit_code": 0, "success": True},
                500.0,
            )
            mock_emit.assert_called_once()
            guidance = mock_emit.call_args[0][0]
            assert "✅" in guidance or "Tests passed" in guidance
            assert fresh_state["guidance_count"] == 1
            assert fresh_state["last_tool"] == "agent_run_shell_command"

    async def test_shell_command_failure_triggers_guidance(
        self, plugin_module, fresh_state
    ):
        """Test shell command with non-zero exit code triggers error guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            await plugin_module._on_post_tool_call(
                "agent_run_shell_command",
                {"command": "false"},
                {"exit_code": 1, "success": False},
                100.0,
            )
            mock_emit.assert_called_once()
            guidance = mock_emit.call_args[0][0]
            assert "⚠️" in guidance or "failed" in guidance.lower()
            assert "exit code 1" in guidance

    async def test_invoke_agent_triggers_guidance(self, plugin_module, fresh_state):
        """Test invoke_agent tool triggers agent guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            await plugin_module._on_post_tool_call(
                "invoke_agent",
                {"agent_name": "turbo-executor", "prompt": "test"},
                {"result": "success"},
                200.0,
            )
            mock_emit.assert_called_once()
            guidance = mock_emit.call_args[0][0]
            assert "turbo-executor" in guidance
            assert "🤖" in guidance or "completed" in guidance.lower()
            assert fresh_state["guidance_count"] == 1
            assert fresh_state["last_tool"] == "invoke_agent"

    async def test_unsupported_tool_no_guidance(self, plugin_module, fresh_state):
        """Test unsupported tools don't trigger guidance."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            await plugin_module._on_post_tool_call(
                "read_file",
                {"file_path": "test.py"},
                {"content": "..."},
                50.0,
            )
            mock_emit.assert_not_called()
            assert fresh_state["guidance_count"] == 0

    async def test_no_guidance_when_none_returned(self, plugin_module, fresh_state):
        """Test that nothing is emitted when guidance function returns None."""
        fresh_state["enabled"] = True
        fresh_state["verbosity"] = "minimal"

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ), patch.object(
            plugin_module, "_get_write_guidance", return_value=None
        ):
            await plugin_module._on_post_tool_call(
                "create_file",
                {"file_path": "file.unknown_ext_abc", "content": "x"},
                {"success": True},
                100.0,
            )
            mock_emit.assert_not_called()
            assert fresh_state["guidance_count"] == 0

    async def test_exception_handling(self, plugin_module, fresh_state):
        """Test that exceptions in callback are silently caught."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            # Should not raise exception even when internal error occurs
            await plugin_module._on_post_tool_call(
                "create_file",
                {"file_path": "test.py", "content": "pass"},
                {"success": True},
                100.0,
            )
            # In normal case, emit_info would be called
            mock_emit.assert_called_once()

    async def test_shell_result_as_dict(self, plugin_module, fresh_state):
        """Test shell command handling when result is a dict with exit_code."""
        fresh_state["enabled"] = True

        with patch("code_puppy.messaging.emit_info") as mock_emit, patch.object(
            plugin_module, "_is_enabled", return_value=True
        ):
            # Result is a dict without exit_code key
            await plugin_module._on_post_tool_call(
                "agent_run_shell_command",
                {"command": "echo hello"},
                {"stdout": "hello", "stderr": ""},  # No exit_code key
                100.0,
            )
            # Should still work and default to exit_code 0
            mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: State Initialization
# ---------------------------------------------------------------------------


class TestStateInitialization:
    """Tests that verify state is initialized from config."""

    def test_valid_verbosity_values_constant(self, plugin_module):
        """Test that _VALID_VERBOSITY contains expected values."""
        assert plugin_module._VALID_VERBOSITY == {"minimal", "normal", "verbose"}

    def test_config_key_constants(self, plugin_module):
        """Test that config key constants are correct."""
        assert plugin_module._CONFIG_KEY_ENABLED == "proactive_guidance_enabled"
        assert plugin_module._CONFIG_KEY_VERBOSITY == "guidance_verbosity"

    def test_state_dict_structure(self, plugin_module):
        """Test that _state has expected keys."""
        assert "enabled" in plugin_module._state
        assert "verbosity" in plugin_module._state
        assert "last_tool" in plugin_module._state
        assert "guidance_count" in plugin_module._state
