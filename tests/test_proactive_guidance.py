"""Tests for the proactive_guidance plugin.

This module tests the proactive guidance plugin that provides contextual
next-step suggestions after tool execution.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

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

        for false_value in [
            "false",
            "False",
            "FALSE",
            "0",
            "no",
            "No",
            "off",
            "OFF",
            "random",
        ]:
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

        with patch.object(
            config_module, "get_value", side_effect=Exception("config error")
        ):
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

        with patch.object(
            config_module, "get_value", side_effect=Exception("config error")
        ):
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_get_config_enabled", return_value=True),
            patch.object(plugin_module, "_is_enabled", return_value=True),
        ):
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
            patch.object(plugin_module, "_get_write_guidance", return_value=None),
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

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
        ):
            # Force an exception to be raised during guidance emission
            mock_emit.side_effect = RuntimeError("Simulated emit error")
            # Should not raise exception - the callback should catch and swallow it
            try:
                await plugin_module._on_post_tool_call(
                    "create_file",
                    {"file_path": "test.py", "content": "pass"},
                    {"success": True},
                    100.0,
                )
                # If we reach here, exception was caught as expected
                exception_swallowed = True
            except RuntimeError:
                # If exception propagates, test fails
                exception_swallowed = False

            assert exception_swallowed, (
                "Exception should have been caught and swallowed"
            )
            # Verify that emit was attempted before the exception
            assert mock_emit.call_count >= 1

    async def test_shell_result_as_dict(self, plugin_module, fresh_state):
        """Test shell command handling when result is a dict with exit_code."""
        fresh_state["enabled"] = True

        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
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

    def test_import_time_state_initialization(self, plugin_module):
        """Test that state is initialized at module import time."""
        # The _state dict should already exist and have expected structure
        # This verifies that the module-level initialization code ran at import
        assert isinstance(plugin_module._state, dict)
        # All expected keys should be present with valid values
        assert plugin_module._state["enabled"] in (True, False)
        assert plugin_module._state["verbosity"] in plugin_module._VALID_VERBOSITY
        assert plugin_module._state["last_tool"] is None or isinstance(
            plugin_module._state["last_tool"], str
        )
        assert isinstance(plugin_module._state["guidance_count"], int)
        assert plugin_module._state["guidance_count"] >= 0
