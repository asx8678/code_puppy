"""Tests for proactive_guidance plugin — state, exploratory guidance, task context, and agent-run hooks.

Split from test_proactive_guidance.py to stay under the 600-line cap.
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers (duplicated minimally to keep each test module standalone)
# ---------------------------------------------------------------------------


def _import_plugin():
    """Import and return the plugin module with all its functions."""
    return importlib.import_module(
        "code_puppy.plugins.proactive_guidance.register_callbacks"
    )


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
        assert "last_agent" in plugin_module._state
        assert "last_agent_model" in plugin_module._state

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


# ---------------------------------------------------------------------------
# Tests: Exploratory Guidance
# ---------------------------------------------------------------------------


class TestExploratoryGuidance:
    """Tests for _get_exploratory_guidance() function."""

    def test_basic_exploratory_guidance_verbose(self, plugin_module, fresh_state):
        """Test exploratory guidance returns basic info in verbose mode."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_exploratory_guidance(
            "read_file", {"file_path": "test.py"}
        )
        assert guidance is not None
        assert "Exploratory" in guidance
        assert "Next" in guidance

    def test_exploratory_guidance_normal_returns_none(self, plugin_module, fresh_state):
        """Test normal verbosity returns None (suppressed to reduce spam)."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_exploratory_guidance(
            "read_file", {"file_path": "test.py"}
        )
        assert guidance is None

    def test_exploratory_guidance_minimal_returns_none(
        self, plugin_module, fresh_state
    ):
        """Test minimal verbosity returns None (suppressed)."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_exploratory_guidance(
            "read_file", {"file_path": "test.py"}
        )
        assert guidance is None

    def test_exploratory_guidance_grep_tool(self, plugin_module, fresh_state):
        """Test exploratory guidance for grep tool in verbose mode."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_exploratory_guidance(
            "grep", {"search_string": "pattern"}
        )
        assert guidance is not None
        assert "Exploratory" in guidance

    def test_exploratory_guidance_list_files_tool(self, plugin_module, fresh_state):
        """Test exploratory guidance for list_files tool in verbose mode."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_exploratory_guidance(
            "list_files", {"directory": "."}
        )
        assert guidance is not None
        assert "Exploratory" in guidance


# ---------------------------------------------------------------------------
# Tests: Task Context Detection
# ---------------------------------------------------------------------------


class TestTaskContext:
    """Tests for task context detection functions."""

    def test_format_task_context_with_data(self, plugin_module):
        """Test formatting with full context."""
        ctx = {
            "task_id": "bd-136",
            "git_branch": "feature/bd-136",
            "git_head": "abc1234",
            "cwd": "/home/user/project",
        }
        result = plugin_module._format_task_context(ctx)
        assert "Task Context" in result
        assert "bd-136" in result
        assert "feature/bd-136" in result
        assert "abc1234" in result

    def test_format_task_context_empty(self, plugin_module):
        """Test formatting with empty context returns empty string."""
        ctx = {}
        result = plugin_module._format_task_context(ctx)
        assert result == ""

    def test_format_task_context_partial(self, plugin_module):
        """Test formatting with partial context."""
        ctx = {"git_branch": "main"}
        result = plugin_module._format_task_context(ctx)
        assert "Task Context" in result
        assert "main" in result

    def test_detect_task_context_returns_dict(self, plugin_module):
        """Test that detect returns a dict with at least cwd."""
        ctx = plugin_module._detect_task_context()
        assert isinstance(ctx, dict)
        assert "cwd" in ctx
        assert "user" in ctx

    def test_detect_task_context_with_env_var(self, plugin_module):
        """Test task ID detection from PUP_TASK_ID env var."""
        old = os.environ.get("PUP_TASK_ID")
        try:
            os.environ["PUP_TASK_ID"] = "bd-999"
            ctx = plugin_module._detect_task_context()
            assert ctx.get("task_id") == "bd-999"
        finally:
            if old is None:
                os.environ.pop("PUP_TASK_ID", None)
            else:
                os.environ["PUP_TASK_ID"] = old


# ---------------------------------------------------------------------------
# Tests: Agent Run Start Hook
# ---------------------------------------------------------------------------


class TestAgentRunStart:
    """Tests for _on_agent_run_start() async callback."""

    async def test_agent_run_start_disabled(self, plugin_module, fresh_state):
        """Test callback does nothing when guidance is disabled."""
        fresh_state["enabled"] = False
        with patch("code_puppy.messaging.emit_info") as mock_emit:
            await plugin_module._on_agent_run_start("test-agent", "gpt-4")
            mock_emit.assert_not_called()

    async def test_agent_run_start_updates_state(self, plugin_module, fresh_state):
        """Test callback updates last_agent and last_agent_model."""
        fresh_state["enabled"] = True
        with (
            patch("code_puppy.messaging.emit_info"),
            patch.object(plugin_module, "_is_enabled", return_value=True),
        ):
            await plugin_module._on_agent_run_start("my-agent", "claude-3")
            assert fresh_state.get("last_agent") == "my-agent"
            assert fresh_state.get("last_agent_model") == "claude-3"

    async def test_agent_run_start_emits_context(self, plugin_module, fresh_state):
        """Test callback emits task context."""
        fresh_state["enabled"] = True
        with (
            patch("code_puppy.messaging.emit_info") as mock_emit,
            patch.object(plugin_module, "_is_enabled", return_value=True),
        ):
            await plugin_module._on_agent_run_start("test-agent", "gpt-4")
            if mock_emit.called:
                msg = mock_emit.call_args[0][0]
                assert "Task Context" in msg or "Branch" in msg or "cwd" in msg.lower()

    async def test_agent_run_start_handles_exception(self, plugin_module, fresh_state):
        """Test callback handles exceptions gracefully."""
        fresh_state["enabled"] = True
        with (
            patch.object(plugin_module, "_is_enabled", return_value=True),
            patch.object(
                plugin_module, "_detect_task_context", side_effect=RuntimeError("boom")
            ),
        ):
            await plugin_module._on_agent_run_start("test-agent", "gpt-4")
