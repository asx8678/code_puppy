"""Tests for remember_last_agent plugin."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import MagicMock, patch

from code_puppy.plugins.remember_last_agent.register_callbacks import (
    _on_startup,
)

# Module-level import path for storage functions
_MOCK_STORAGE = "code_puppy.plugins.remember_last_agent.register_callbacks"


def _make_mock_agents_module(**attrs: object) -> ModuleType:
    """Create a mock module with the given attributes."""
    mod = ModuleType("code_puppy.agents")
    for name, value in attrs.items():
        setattr(mod, name, value)
    return mod


class TestRememberLastAgentStartup:
    """Tests for the _on_startup restore behavior."""

    @patch(f"{_MOCK_STORAGE}.set_last_agent")
    @patch(f"{_MOCK_STORAGE}.get_last_agent")
    def test_restores_valid_agent(self, mock_get_last, _mock_set_last):
        """Startup restores a valid saved agent."""
        mock_get_last.return_value = "husky"
        mock_agents = _make_mock_agents_module(
            get_available_agents=MagicMock(
                return_value={"husky": "Husky 🐺", "code-puppy": "Code Puppy 🐶"}
            ),
            set_current_agent=MagicMock(),
        )

        with patch.dict("sys.modules", {"code_puppy.agents": mock_agents}):
            _on_startup()

        mock_agents.set_current_agent.assert_called_once_with("husky")

    @patch(f"{_MOCK_STORAGE}.clear_last_agent")
    @patch(f"{_MOCK_STORAGE}.set_last_agent")
    @patch(f"{_MOCK_STORAGE}.get_last_agent")
    def test_clears_stale_agent(self, mock_get_last, _mock_set_last, mock_clear):
        """Startup clears saved agent if it no longer exists."""
        mock_get_last.return_value = "deleted-agent"
        mock_agents = _make_mock_agents_module(
            get_available_agents=MagicMock(
                return_value={"code-puppy": "Code Puppy 🐶"}
            ),
            set_current_agent=MagicMock(),
        )

        with patch.dict("sys.modules", {"code_puppy.agents": mock_agents}):
            _on_startup()

        mock_clear.assert_called_once()

    @patch(f"{_MOCK_STORAGE}.get_last_agent")
    def test_noop_when_no_saved_agent(self, mock_get_last):
        """Startup does nothing if no agent was saved."""
        mock_get_last.return_value = None

        _on_startup()

        # No exception, no crash — that's all we need to verify

    @patch(f"{_MOCK_STORAGE}.set_last_agent")
    @patch(f"{_MOCK_STORAGE}.get_last_agent")
    def test_handles_exception_gracefully(self, mock_get_last, _mock_set_last):
        """Startup catches exceptions without crashing."""
        mock_get_last.return_value = "husky"
        mock_agents = _make_mock_agents_module(
            get_available_agents=MagicMock(return_value={"husky": "Husky 🐺"}),
            set_current_agent=MagicMock(
                side_effect=RuntimeError("agent system not ready")
            ),
        )

        with patch.dict("sys.modules", {"code_puppy.agents": mock_agents}):
            # Should not raise
            _on_startup()
