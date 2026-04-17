"""Tests for guidance commands in proactive_guidance plugin.

Tests for _handle_custom_command(), _on_custom_help() and related functionality.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


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

    @pytest.mark.parametrize("cmd,expected_state", [
        ("/guidance on", True),
        ("/guidance enable", True),
    ])
    def test_on_commands(self, plugin_module, fresh_state, cmd, expected_state):
        """Test /guidance on and enable commands enable guidance."""
        fresh_state["enabled"] = False
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(cmd, "guidance")
            assert result is True
            assert fresh_state["enabled"] is expected_state
            mock_emit.assert_called_once()
            assert "enabled" in mock_emit.call_args[0][0].lower()

    @pytest.mark.parametrize("cmd,expected_state", [
        ("/guidance off", False),
        ("/guidance disable", False),
    ])
    def test_off_commands(self, plugin_module, fresh_state, cmd, expected_state):
        """Test /guidance off and disable commands disable guidance."""
        fresh_state["enabled"] = True
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(cmd, "guidance")
            assert result is True
            assert fresh_state["enabled"] is expected_state
            mock_emit.assert_called_once()
            assert "disabled" in mock_emit.call_args[0][0].lower()

    @pytest.mark.parametrize("cmd,expected_verbosity", [
        ("/guidance verbosity minimal", "minimal"),
        ("/guidance verbosity normal", "normal"),
        ("/guidance verbosity verbose", "verbose"),
    ])
    def test_verbosity_commands(self, plugin_module, fresh_state, cmd, expected_verbosity):
        """Test /guidance verbosity commands set verbosity correctly."""
        fresh_state["verbosity"] = "normal" if expected_verbosity != "normal" else "minimal"
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = plugin_module._handle_custom_command(cmd, "guidance")
            assert result is True
            assert fresh_state["verbosity"] == expected_verbosity
            mock_emit.assert_called_once()
            assert expected_verbosity in mock_emit.call_args[0][0]

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

    def test_callback_registration_at_module_level(self, plugin_module):
        """Test that callbacks are registered when module is loaded."""
        # Check that register_callback was called for each expected hook
        # by verifying the module has the callback functions
        assert hasattr(plugin_module, "_on_post_tool_call")
        assert hasattr(plugin_module, "_handle_custom_command")
        assert hasattr(plugin_module, "_on_custom_help")
        # These should be callable
        assert callable(plugin_module._on_post_tool_call)
        assert callable(plugin_module._handle_custom_command)
        assert callable(plugin_module._on_custom_help)
