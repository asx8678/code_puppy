"""Tests for agent_shortcuts plugin.

Tests for /plan and /pack slash commands that provide quick agent switching.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Import the functions we want to test
from code_puppy.plugins.agent_shortcuts.register_callbacks import (
    PACK_LEADER_AGENT,
    PLANNING_AGENT,
    _get_custom_help,
    _handle_custom_command,
    _handle_pack_command,
    _handle_plan_command,
    _switch_to_agent,
)

_MOCK_PATH = "code_puppy.plugins.agent_shortcuts.register_callbacks"


def _make_mock_agent(name: str, display_name: str, description: str) -> MagicMock:
    """Create a mock agent object."""
    agent = MagicMock()
    agent.name = name
    agent.display_name = display_name
    agent.description = description
    return agent


def _patch_agents_functions(**kwargs):
    """Create mocks for the agents functions.

    Returns a context manager that patches _get_agents_functions to return mocks.
    """
    mocks = {
        "get_available_agents": MagicMock(return_value={}),
        "get_current_agent": MagicMock(return_value=_make_mock_agent("code-puppy", "Code Puppy", "")),
        "set_current_agent": MagicMock(return_value=True),
        "reload_code_generation_agent": MagicMock(),
    }
    mocks.update(kwargs)

    def _mock_get_agents_functions():
        return (
            mocks["get_available_agents"],
            mocks["get_current_agent"],
            mocks["set_current_agent"],
            mocks["reload_code_generation_agent"],
        )

    return patch(f"{_MOCK_PATH}._get_agents_functions", _mock_get_agents_functions), mocks


class TestCustomHelp:
    """Tests for the custom_command_help callback."""

    def test_returns_plan_and_pack_commands(self):
        """Should return help entries for both /plan and /pack."""
        help_entries = _get_custom_help()

        assert len(help_entries) == 2
        names = [entry[0] for entry in help_entries]
        assert "plan" in names
        assert "pack" in names

    def test_plan_description(self):
        """/plan should have appropriate description."""
        help_entries = _get_custom_help()
        plan_entry = next((e for e in help_entries if e[0] == "plan"), None)
        assert plan_entry is not None
        assert "planning" in plan_entry[1].lower()

    def test_pack_description(self):
        """/pack should mention pack agents requirement."""
        help_entries = _get_custom_help()
        pack_entry = next((e for e in help_entries if e[0] == "pack"), None)
        assert pack_entry is not None
        assert "pack-leader" in pack_entry[1].lower() or "pack" in pack_entry[1].lower()


class TestHandleCustomCommandRouting:
    """Tests for command routing."""

    @patch(f"{_MOCK_PATH}._handle_plan_command")
    def test_routes_plan_command(self, mock_plan):
        """Should route /plan to _handle_plan_command."""
        mock_plan.return_value = True
        result = _handle_custom_command("/plan", "plan")
        assert result is True
        mock_plan.assert_called_once()

    @patch(f"{_MOCK_PATH}._handle_pack_command")
    def test_routes_pack_command(self, mock_pack):
        """Should route /pack to _handle_pack_command."""
        mock_pack.return_value = True
        result = _handle_custom_command("/pack", "pack")
        assert result is True
        mock_pack.assert_called_once()

    def test_returns_none_for_unknown_command(self):
        """Should return None for unknown commands."""
        result = _handle_custom_command("/unknown", "unknown")
        assert result is None

    def test_returns_none_for_empty_name(self):
        """Should return None for empty command name."""
        result = _handle_custom_command("/", "")
        assert result is None


class TestSwitchToAgent:
    """Tests for the common agent switching logic."""

    @patch(f"{_MOCK_PATH}.finalize_autosave_session")
    @patch(f"{_MOCK_PATH}.emit_success")
    @patch(f"{_MOCK_PATH}.emit_info")
    def test_switches_to_agent_successfully(
        self, mock_emit_info, mock_emit_success, mock_finalize
    ):
        """Should switch to agent when available and different from current."""
        mock_finalize.return_value = "session-123"

        current_agent = _make_mock_agent("code-puppy", "Code Puppy", "A coding dog")
        new_agent = _make_mock_agent(PLANNING_AGENT, "Planning Agent", "A planner")

        patch_ctx, mocks = _patch_agents_functions(
            get_available_agents=MagicMock(
                return_value={
                    PLANNING_AGENT: "Planning Agent",
                    "code-puppy": "Code Puppy",
                }
            ),
            get_current_agent=MagicMock(side_effect=[current_agent, new_agent]),
            set_current_agent=MagicMock(return_value=True),
        )

        with patch_ctx:
            result = _switch_to_agent(PLANNING_AGENT, "group-1")

        assert result is True
        mocks["set_current_agent"].assert_called_once_with(PLANNING_AGENT)
        mocks["reload_code_generation_agent"].assert_called_once()
        mock_emit_success.assert_called_once()

    @patch(f"{_MOCK_PATH}.emit_error")
    @patch(f"{_MOCK_PATH}.emit_warning")
    def test_shows_error_when_agent_not_available(
        self, mock_emit_warning, mock_emit_error
    ):
        """Should show error when agent is not available."""
        patch_ctx, _ = _patch_agents_functions(
            get_available_agents=MagicMock(return_value={"code-puppy": "Code Puppy"})
        )

        with patch_ctx:
            result = _switch_to_agent(PLANNING_AGENT, "group-1")

        assert result is True
        mock_emit_error.assert_called_once()
        mock_emit_warning.assert_called_once()
        assert PLANNING_AGENT in str(mock_emit_error.call_args)

    @patch(f"{_MOCK_PATH}.emit_info")
    def test_shows_already_using_when_current(self, mock_emit_info):
        """Should show 'already using' message when already on target agent."""
        current_agent = _make_mock_agent(PLANNING_AGENT, "Planning Agent", "A planner")

        patch_ctx, _ = _patch_agents_functions(
            get_available_agents=MagicMock(
                return_value={
                    PLANNING_AGENT: "Planning Agent",
                    "code-puppy": "Code Puppy",
                }
            ),
            get_current_agent=MagicMock(return_value=current_agent),
        )

        with patch_ctx:
            result = _switch_to_agent(PLANNING_AGENT, "group-1")

        assert result is True
        mock_emit_info.assert_called_once()
        assert "already" in str(mock_emit_info.call_args).lower()

    @patch(f"{_MOCK_PATH}.finalize_autosave_session")
    @patch(f"{_MOCK_PATH}.emit_warning")
    def test_shows_warning_when_switch_fails(self, mock_emit_warning, mock_finalize):
        """Should show warning when set_current_agent returns False."""
        mock_finalize.return_value = "session-123"

        current_agent = _make_mock_agent("code-puppy", "Code Puppy", "A coding dog")

        patch_ctx, _ = _patch_agents_functions(
            get_available_agents=MagicMock(
                return_value={
                    PLANNING_AGENT: "Planning Agent",
                    "code-puppy": "Code Puppy",
                }
            ),
            get_current_agent=MagicMock(return_value=current_agent),
            set_current_agent=MagicMock(return_value=False),
        )

        with patch_ctx:
            result = _switch_to_agent(PLANNING_AGENT, "group-1")

        assert result is True
        mock_emit_warning.assert_called_once()
        assert "failed" in str(mock_emit_warning.call_args).lower()


class TestPlanCommand:
    """Tests for /plan command."""

    @patch(f"{_MOCK_PATH}._switch_to_agent")
    def test_calls_switch_to_agent(self, mock_switch):
        """Should call _switch_to_agent with planning-agent."""
        mock_switch.return_value = True
        result = _handle_plan_command()

        assert result is True
        mock_switch.assert_called_once()
        call_args = mock_switch.call_args
        assert call_args[0][0] == PLANNING_AGENT


class TestPackCommand:
    """Tests for /pack command."""

    @patch(f"{_MOCK_PATH}.get_pack_agents_enabled")
    @patch(f"{_MOCK_PATH}.emit_error")
    def test_shows_error_when_pack_agents_disabled(
        self, mock_emit_error, mock_pack_enabled
    ):
        """Should show error when pack agents are disabled."""
        mock_pack_enabled.return_value = False

        result = _handle_pack_command()

        assert result is True
        mock_emit_error.assert_called_once()
        assert "disabled" in str(mock_emit_error.call_args).lower()

    @patch(f"{_MOCK_PATH}.get_pack_agents_enabled")
    @patch(f"{_MOCK_PATH}._switch_to_agent")
    def test_calls_switch_to_agent_when_enabled(self, mock_switch, mock_pack_enabled):
        """Should call _switch_to_agent when pack agents are enabled."""
        mock_pack_enabled.return_value = True
        mock_switch.return_value = True

        result = _handle_pack_command()

        assert result is True
        mock_switch.assert_called_once()
        call_args = mock_switch.call_args
        assert call_args[0][0] == PACK_LEADER_AGENT
