"""Unit tests for agent_shortcuts plugin."""

from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.agent_shortcuts.register_callbacks import (
    _custom_help,
    _handle_custom_command,
    _SHORTCUTS,
    _HELP_ENTRIES,
    _switch_agent,
)


class TestHandleCustomCommand:
    """Test cases for _handle_custom_command function."""

    def test_unknown_command_returns_none(self) -> None:
        """Unknown command name should return None."""
        result = _handle_custom_command("/foo", "foo")
        assert result is None

    def test_empty_name_returns_none(self) -> None:
        """Empty command name should return None."""
        result = _handle_custom_command("/", "")
        assert result is None

    @pytest.mark.parametrize("command,name,target", [
        ("/plan", "plan", "planning-agent"),
        ("/planning", "planning", "planning-agent"),
        ("/lead", "lead", "pack-leader"),
        ("/pack", "pack", "pack-leader"),
    ])
    def test_shortcuts_map_to_correct_agent(
        self, command: str, name: str, target: str
    ) -> None:
        """Each shortcut should map to the correct agent name."""
        # Verify the mapping in _SHORTCUTS dict
        assert _SHORTCUTS[name] == target

        # Verify the handler calls _switch_agent with correct target
        with patch(
            "code_puppy.plugins.agent_shortcuts.register_callbacks._switch_agent"
        ) as mock_switch:
            mock_switch.return_value = True
            result = _handle_custom_command(command, name)
            assert result is True
            mock_switch.assert_called_once_with(target, invoked_as=name)


class TestSwitchAgent:
    """Test cases for _switch_agent function."""

    def test_set_current_agent_false_emits_warning(self) -> None:
        """When set_current_agent returns False, emit warning but still return True."""
        # Patch the actual modules where the imports come from (lazy imports inside function)
        with patch(
            "code_puppy.agents.agent_manager.get_current_agent"
        ) as mock_get_current, patch(
            "code_puppy.agents.agent_manager.set_current_agent"
        ) as mock_set_current, patch(
            "code_puppy.config.finalize_autosave_session"
        ) as mock_finalize, patch(
            "code_puppy.messaging.emit_warning"
        ) as mock_emit_warning, patch(
            "code_puppy.messaging.emit_success"
        ) as mock_emit_success, patch(
            "code_puppy.messaging.emit_info"
        ):
            # Setup mocks
            mock_agent = MagicMock()
            mock_agent.name = "different-agent"
            mock_agent.display_name = "Different Agent"
            mock_get_current.return_value = mock_agent
            mock_set_current.return_value = False
            mock_finalize.return_value = "test-session-id"

            result = _switch_agent("pack-leader", invoked_as="lead")

            # Should still return True (don't crash)
            assert result is True
            # Should have emitted a warning
            mock_emit_warning.assert_called_once()
            warning_msg = mock_emit_warning.call_args[0][0]
            assert "pack-leader" in warning_msg
            assert "failed" in warning_msg.lower() or "preserved" in warning_msg.lower()

    def test_import_failure_returns_true(self) -> None:
        """Import failures should return True and never crash."""
        # The code does: from code_puppy.messaging import ...
        # We need to patch the builtin __import__ to fail for code_puppy modules
        original_import = __builtins__["__import__"]

        def failing_import(name, *args, **kwargs):
            if name.startswith("code_puppy"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=failing_import):
            result = _switch_agent("pack-leader", invoked_as="lead")
            # Should still return True (never crash)
            assert result is True


class TestCustomHelp:
    """Test cases for _custom_help function."""

    def test_custom_help_returns_plan_and_leader_only(self) -> None:
        """Help should only show 'plan' and 'lead' entries (aliases hidden)."""
        result = _custom_help()

        # Should return exactly 2 entries
        assert len(result) == 2

        # Should contain plan and lead, not planning or pack
        commands = [entry[0] for entry in result]
        assert "plan" in commands
        assert "lead" in commands
        assert "planning" not in commands
        assert "pack" not in commands

        # Verify the exact structure matches _HELP_ENTRIES
        assert result == _HELP_ENTRIES
