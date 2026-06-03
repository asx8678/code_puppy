"""Comprehensive tests for code_puppy/messaging/subagent_console.py.

Targets coverage improvement from 29% to 85%+.
Focuses on:
- AgentState dataclass and its methods
- SubAgentConsoleManager singleton pattern
- Agent registration, update, and unregistration
- Display lifecycle management
- Rendering methods
- Context manager support
- Convenience functions
"""

import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest
from rich.console import Console, Group

from code_puppy.messaging.messages import SubAgentStatusMessage
from code_puppy.messaging.subagent_console import (
    DEFAULT_STYLE,
    STATUS_STYLES,
    AgentState,
    SubAgentConsoleManager,
    get_subagent_console_manager,
)

# =============================================================================
# AgentState Tests
# =============================================================================


class TestAgentStateBasics:
    """Test AgentState dataclass basic functionality."""

    def test_agent_state_creation(self):
        """Test creating an AgentState with required fields."""
        state = AgentState(
            session_id="test-session-123",
            agent_name="test-agent",
            model_name="gpt-4o",
        )
        assert state.session_id == "test-session-123"
        assert state.agent_name == "test-agent"
        assert state.model_name == "gpt-4o"
        assert state.status == "starting"  # Default
        assert state.tool_call_count == 0
        assert state.token_count == 0
        assert state.current_tool is None
        assert state.error_message is None

    def test_agent_state_with_all_fields(self):
        """Test creating AgentState with all fields specified."""
        state = AgentState(
            session_id="sess-456",
            agent_name="code-puppy",
            model_name="claude-3-opus",
            status="running",
            tool_call_count=5,
            token_count=1500,
            current_tool="read_file",
            error_message="some error",
        )
        assert state.status == "running"
        assert state.tool_call_count == 5
        assert state.token_count == 1500
        assert state.current_tool == "read_file"
        assert state.error_message == "some error"


class TestAgentStateElapsedTime:
    """Test AgentState elapsed time methods."""

    def test_elapsed_seconds_returns_positive(self):
        """Test that elapsed_seconds returns a positive float."""
        state = AgentState(
            session_id="test",
            agent_name="agent",
            model_name="model",
        )
        # Give it a tiny moment
        time.sleep(0.01)
        elapsed = state.elapsed_seconds()
        assert isinstance(elapsed, float)
        assert elapsed >= 0.01

    def test_elapsed_seconds_with_fixed_start_time(self):
        """Test elapsed_seconds with a known start time."""
        start = time.time() - 5.0  # 5 seconds ago
        state = AgentState(
            session_id="test",
            agent_name="agent",
            model_name="model",
            start_time=start,
        )
        elapsed = state.elapsed_seconds()
        # Should be approximately 5 seconds (allow some tolerance)
        assert 4.9 <= elapsed <= 6.0

    def test_elapsed_formatted_seconds_only(self):
        """Test elapsed_formatted for durations under 60 seconds."""
        # Set start_time to 30 seconds ago
        start = time.time() - 30.0
        state = AgentState(
            session_id="test",
            agent_name="agent",
            model_name="model",
            start_time=start,
        )
        formatted = state.elapsed_formatted()
        # Should be like "30.0s" or "30.1s"
        assert formatted.endswith("s")
        assert "m" not in formatted
        # Extract number and verify it's around 30
        seconds = float(formatted.rstrip("s"))
        assert 29.5 <= seconds <= 32.0

    def test_elapsed_formatted_with_minutes(self):
        """Test elapsed_formatted for durations over 60 seconds."""
        # Set start_time to 90 seconds ago (1m 30s)
        start = time.time() - 90.0
        state = AgentState(
            session_id="test",
            agent_name="agent",
            model_name="model",
            start_time=start,
        )
        formatted = state.elapsed_formatted()
        # Should be like "1m 30.0s"
        assert "m" in formatted
        assert "s" in formatted
        assert formatted.startswith("1m")

    def test_elapsed_formatted_multiple_minutes(self):
        """Test elapsed_formatted for longer durations."""
        # Set start_time to 185 seconds ago (3m 5s)
        start = time.time() - 185.0
        state = AgentState(
            session_id="test",
            agent_name="agent",
            model_name="model",
            start_time=start,
        )
        formatted = state.elapsed_formatted()
        assert "3m" in formatted

    def test_token_percent_normal(self):
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            token_count=1200,
            token_limit=200000,
        )
        assert state.token_percent() == pytest.approx(0.6)

    def test_token_percent_none_when_no_limit(self):
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            token_count=5,
            token_limit=None,
        )
        assert state.token_percent() is None

    def test_token_percent_none_when_zero_limit(self):
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            token_count=5,
            token_limit=0,
        )
        assert state.token_percent() is None

    def test_token_percent_over_limit(self):
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            token_count=999999,
            token_limit=1000,
        )
        assert state.token_percent() == pytest.approx(99999.9)


class TestAgentStateToStatusMessage:
    """Test AgentState.to_status_message() conversion."""

    def test_to_status_message_basic(self):
        """Test converting AgentState to SubAgentStatusMessage."""
        state = AgentState(
            session_id="sess-abc",
            agent_name="my-agent",
            model_name="gpt-4o-mini",
            status="running",
            tool_call_count=3,
            token_count=500,
        )
        message = state.to_status_message()

        assert isinstance(message, SubAgentStatusMessage)
        assert message.session_id == "sess-abc"
        assert message.agent_name == "my-agent"
        assert message.model_name == "gpt-4o-mini"
        assert message.status == "running"
        assert message.tool_call_count == 3
        assert message.token_count == 500
        assert message.elapsed_seconds >= 0

    def test_to_status_message_with_current_tool(self):
        """Test conversion includes current_tool."""
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            status="tool_calling",
            current_tool="edit_file",
        )
        message = state.to_status_message()
        assert message.current_tool == "edit_file"

    def test_to_status_message_with_error(self):
        """Test conversion includes error_message."""
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            status="error",
            error_message="Something went wrong",
        )
        message = state.to_status_message()
        assert message.error_message == "Something went wrong"
        assert message.status == "error"

    def test_to_status_message_carries_token_fields(self):
        state = AgentState(
            session_id="sess",
            agent_name="agent",
            model_name="model",
            token_count=1200,
            token_limit=200000,
        )
        message = state.to_status_message()
        assert message.token_count == 1200
        assert message.token_limit == 200000
        assert message.token_percent == pytest.approx(0.6)


# =============================================================================
# SubAgentConsoleManager Singleton Tests
# =============================================================================


class TestSubAgentConsoleManagerSingleton:
    """Test the singleton pattern of SubAgentConsoleManager."""

    def setup_method(self):
        """Reset singleton before each test."""
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        """Clean up singleton after each test."""
        SubAgentConsoleManager.reset_instance()

    def test_get_instance_creates_singleton(self):
        """Test that get_instance creates a singleton."""
        instance1 = SubAgentConsoleManager.get_instance()
        instance2 = SubAgentConsoleManager.get_instance()
        assert instance1 is instance2

    def test_get_instance_with_console(self):
        """Test get_instance with a custom console."""
        mock_console = Mock(spec=Console)
        instance = SubAgentConsoleManager.get_instance(console=mock_console)
        assert instance.console is mock_console

    def test_reset_instance_clears_singleton(self):
        """Test that reset_instance clears the singleton."""
        instance1 = SubAgentConsoleManager.get_instance()
        SubAgentConsoleManager.reset_instance()
        instance2 = SubAgentConsoleManager.get_instance()
        assert instance1 is not instance2

    def test_reset_instance_when_none(self):
        """Test reset_instance when no instance exists."""
        # Should not raise
        SubAgentConsoleManager.reset_instance()
        SubAgentConsoleManager.reset_instance()  # Double reset is safe

    def test_direct_init_creates_new_instance(self):
        """Test that direct __init__ creates new instances."""
        manager1 = SubAgentConsoleManager()
        manager2 = SubAgentConsoleManager()
        # Direct init bypasses singleton
        assert manager1 is not manager2

    def test_init_with_custom_console(self):
        """Test __init__ with custom console."""
        mock_console = Mock(spec=Console)
        manager = SubAgentConsoleManager(console=mock_console)
        assert manager.console is mock_console

    def test_init_default_console(self):
        """Test __init__ creates default console."""
        manager = SubAgentConsoleManager()
        assert isinstance(manager.console, Console)


# =============================================================================
# Agent Registration Tests
# =============================================================================


class TestAgentRegistration:
    """Test agent registration, update, and unregistration."""

    def setup_method(self):
        """Reset singleton and create fresh manager."""
        SubAgentConsoleManager.reset_instance()
        # Create manager with mocked console to avoid real output
        self.mock_console = Mock(spec=Console)
        self.manager = SubAgentConsoleManager(console=self.mock_console)

    def teardown_method(self):
        """Clean up."""
        SubAgentConsoleManager.reset_instance()

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_register_agent_creates_state(self, mock_start):
        """Test that register_agent creates an AgentState."""
        self.manager.register_agent("sess-1", "agent-one", "gpt-4o")

        state = self.manager.get_agent_state("sess-1")
        assert state is not None
        assert state.session_id == "sess-1"
        assert state.agent_name == "agent-one"
        assert state.model_name == "gpt-4o"
        assert state.status == "starting"

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_register_first_agent_starts_display(self, mock_start):
        """Test that registering first agent starts the display."""
        self.manager.register_agent("sess-1", "agent", "model")
        mock_start.assert_called_once()

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_register_second_agent_no_extra_start(self, mock_start):
        """Test that registering second agent doesn't restart display."""
        self.manager.register_agent("sess-1", "agent1", "model")
        self.manager.register_agent("sess-2", "agent2", "model")
        # Should only be called once for first agent
        assert mock_start.call_count == 1

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_update_agent_modifies_state(self, mock_start):
        """Test that update_agent modifies existing state."""
        self.manager.register_agent("sess-1", "agent", "model")

        self.manager.update_agent(
            "sess-1",
            status="running",
            tool_call_count=5,
            token_count=1000,
            current_tool="grep",
            error_message="test error",
        )

        state = self.manager.get_agent_state("sess-1")
        assert state.status == "running"
        assert state.tool_call_count == 5
        assert state.token_count == 1000
        assert state.current_tool == "grep"
        assert state.error_message == "test error"

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_update_agent_partial_update(self, mock_start):
        """Test partial update only changes specified fields."""
        self.manager.register_agent("sess-1", "agent", "model")
        self.manager.update_agent("sess-1", status="running")

        state = self.manager.get_agent_state("sess-1")
        assert state.status == "running"
        assert state.tool_call_count == 0  # Unchanged

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_update_unknown_agent_silently_ignored(self, mock_start):
        """Test updating unknown agent is silently ignored."""
        # Should not raise
        self.manager.update_agent("nonexistent", status="running")

    @patch.object(SubAgentConsoleManager, "_start_display")
    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_unregister_agent_lingers_in_state(self, mock_stop, mock_start):
        """unregister_agent marks finished and lingers; the update loop prunes later."""
        self.manager.register_agent("sess-1", "agent", "model")
        self.manager.unregister_agent("sess-1")

        # Agent is NOT deleted immediately - it lingers for the update loop to prune.
        state = self.manager.get_agent_state("sess-1")
        assert state is not None
        assert state.status == "completed"
        assert state.completed_at is not None
        # _stop_display is NOT called from unregister_agent - the loop drives stop.
        mock_stop.assert_not_called()

    @patch.object(SubAgentConsoleManager, "_start_display")
    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_unregister_last_agent_does_not_stop_immediately(self, mock_stop, mock_start):
        """unregister_agent does NOT call _stop_display; the update loop does after linger."""
        self.manager.register_agent("sess-1", "agent", "model")
        self.manager.unregister_agent("sess-1")
        # _stop_display is NOT called from unregister_agent anymore.
        mock_stop.assert_not_called()
        # Agent is still present, waiting for the loop to prune after linger.
        state = self.manager.get_agent_state("sess-1")
        assert state is not None
        assert state.completed_at is not None

    @patch.object(SubAgentConsoleManager, "_start_display")
    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_unregister_with_remaining_agents(self, mock_stop, mock_start):
        """Test unregistering when other agents remain doesn't stop display."""
        self.manager.register_agent("sess-1", "agent1", "model")
        self.manager.register_agent("sess-2", "agent2", "model")
        self.manager.unregister_agent("sess-1")

        # Display should not be stopped
        mock_stop.assert_not_called()
        # Second agent should still exist
        assert self.manager.get_agent_state("sess-2") is not None

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_unregister_with_custom_final_status(self, mock_start):
        """unregister_agent with custom final_status lingers so the status is verifiable."""
        self.manager.register_agent("sess-1", "agent", "model")
        self.manager.unregister_agent("sess-1", final_status="error")
        state = self.manager.get_agent_state("sess-1")
        assert state is not None
        assert state.status == "error"
        assert state.completed_at is not None

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_unregister_unknown_agent_silently_ignored(self, mock_start):
        """Test unregistering unknown agent is silently ignored."""
        # Should not raise
        self.manager.unregister_agent("nonexistent")

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_get_agent_state_returns_none_for_unknown(self, mock_start):
        """Test get_agent_state returns None for unknown session."""
        assert self.manager.get_agent_state("unknown") is None

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_get_all_agents_empty(self, mock_start):
        """Test get_all_agents when no agents registered."""
        agents = self.manager.get_all_agents()
        assert agents == []

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_get_all_agents_returns_list(self, mock_start):
        """Test get_all_agents returns list of all agents."""
        self.manager.register_agent("sess-1", "agent1", "model1")
        self.manager.register_agent("sess-2", "agent2", "model2")

        agents = self.manager.get_all_agents()
        assert len(agents) == 2
        session_ids = {a.session_id for a in agents}
        assert session_ids == {"sess-1", "sess-2"}


# =============================================================================
# Display Management Tests
# =============================================================================


class TestDisplayManagement:
    """Test display lifecycle management."""

    def setup_method(self):
        """Reset singleton."""
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        """Clean up."""
        SubAgentConsoleManager.reset_instance()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_start_display_creates_live(self, mock_live_class):
        """Test that _start_display creates a Live instance."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        mock_console = Mock(spec=Console)
        manager = SubAgentConsoleManager(console=mock_console)
        manager._start_display()

        # Verify Live was created with correct params
        mock_live_class.assert_called_once()
        mock_live.start.assert_called_once()

        # Clean up
        manager._stop_display()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_start_display_idempotent(self, mock_live_class):
        """Test that calling _start_display twice doesn't create duplicate."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        # Register an agent so the update loop doesn't self-stop between calls.
        manager.register_agent("sess-1", "agent", "model")
        manager._start_display()
        manager._start_display()  # Second call should be no-op

        # Should only be called once
        assert mock_live_class.call_count == 1

        manager._stop_display()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_stop_display_stops_live(self, mock_live_class):
        """Test that _stop_display stops the Live instance."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        manager._start_display()
        manager._stop_display()

        mock_live.stop.assert_called_once()
        assert manager._live is None

    def test_stop_display_when_not_started(self):
        """Test _stop_display when display was never started."""
        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        # Should not raise
        manager._stop_display()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_stop_display_handles_live_exception(self, mock_live_class):
        """Test _stop_display handles exceptions gracefully."""
        mock_live = MagicMock()
        mock_live.stop.side_effect = Exception("Stop failed")
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        manager._start_display()

        # Should not raise
        manager._stop_display()
        assert manager._live is None


class TestUpdateLoop:
    """Test the background update loop."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_update_loop_runs_until_stopped(self, mock_live_class):
        """Test that update loop runs and can be stopped."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        # Register an agent so the loop doesn't self-stop.
        manager.register_agent("sess-1", "agent", "model")
        manager._start_display()

        # Wait long enough for at least one 2-FPS tick (loop sleeps 0.5s).
        time.sleep(0.6)

        # Verify update was called at least once
        assert mock_live.update.call_count >= 1

        manager._stop_display()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_update_loop_handles_render_exception(self, mock_live_class):
        """Test update loop continues despite render exceptions."""
        mock_live = MagicMock()
        mock_live.update.side_effect = Exception("Render failed")
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        # Register an agent so the loop doesn't self-stop.
        manager.register_agent("sess-1", "agent", "model")
        manager._start_display()

        # Wait long enough for at least one 2-FPS tick.
        time.sleep(0.6)

        # Should still be running (didn't crash)
        assert manager._update_thread is not None

        manager._stop_display()


# =============================================================================
# Rendering Tests
# =============================================================================


class TestUpdateLoopPruning:
    """Test the update loop prunes expired finished rows after the linger window."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    @patch("code_puppy.messaging.subagent_console.Live")
    def test_update_loop_prunes_lingered_agent(self, mock_live_class):
        """Update loop removes an agent whose completed_at is older than LINGER_SECONDS."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        # Speed up the test by using a very short linger window.
        manager._LINGER_SECONDS = 0.1
        manager.register_agent("sess-1", "agent", "model")
        manager.unregister_agent("sess-1")

        # Agent lingers immediately after unregister.
        assert manager.get_agent_state("sess-1") is not None

        # Start the loop and wait long enough for one tick (0.5s) to pass
        # and for completed_at (now) to exceed the short linger window.
        manager._start_display()
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if manager.get_agent_state("sess-1") is None:
                    break
                time.sleep(0.1)
        finally:
            manager._stop_display()

        # After the linger window, the agent is pruned.
        assert manager.get_agent_state("sess-1") is None



class TestRendering:
    """Test rendering methods."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()
        self.manager = SubAgentConsoleManager(console=Mock(spec=Console))

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    def test_render_display_empty(self):
        """Test _render_display with no agents."""
        result = self.manager._render_display()
        assert isinstance(result, Group)

    @patch.object(SubAgentConsoleManager, "_start_display")
    def test_render_display_with_agents(self, mock_start):
        """Test _render_display with registered agents."""
        self.manager.register_agent("sess-1", "agent1", "model1")
        self.manager.register_agent("sess-2", "agent2", "model2")

        result = self.manager._render_display()
        assert isinstance(result, Group)

    def _render_to_text(self, rendered):
        """Helper: render a Rich renderable to plain text for assertions."""
        import io
        from rich.console import Console as _Console
        buf = io.StringIO()
        console = _Console(file=buf, width=200, force_terminal=False, no_color=True)
        console.print(rendered)
        return buf.getvalue()

    def test_render_display_compact_with_token_limit(self):
        """Compact render shows the 'Active sub-agents' panel with token context cell."""
        self.manager.register_agent(
            "sess-1", "code-puppy", "gpt-4o",
            token_count=1200, token_limit=200000,
        )
        text = self._render_to_text(self.manager._render_display())
        assert "Active sub-agents" in text
        assert "1,200/200,000" in text
        assert "0.6% used" in text

    def test_render_display_compact_without_token_limit(self):
        """Compact render falls back to plain 'Tokens: N' when token_limit is None."""
        self.manager.register_agent(
            "sess-1", "code-puppy", "gpt-4o",
            token_count=5000, token_limit=None,
        )
        text = self._render_to_text(self.manager._render_display())
        assert "Active sub-agents" in text
        assert "Tokens: 5,000" in text
        # Should NOT show the percent-used form when no limit
        assert "% used" not in text

    def test_render_display_compact_with_current_tool(self):
        """Compact render includes the current tool cell when set."""
        self.manager.register_agent("sess-1", "code-puppy", "gpt-4o")
        self.manager.update_agent("sess-1", current_tool="read_file")
        text = self._render_to_text(self.manager._render_display())
        assert "tool: read_file" in text

    def test_render_display_compact_all_statuses(self):
        """Compact render handles every defined status without error."""
        for status in [
            "starting",
            "running",
            "thinking",
            "tool_calling",
            "completed",
            "error",
        ]:
            self.manager.register_agent(
                f"sess-{status}", "test-agent", "gpt-4o",
            )
            self.manager.update_agent(f"sess-{status}", status=status)
        text = self._render_to_text(self.manager._render_display())
        assert "Active sub-agents" in text

    def test_render_display_compact_unknown_status(self):
        """Compact render falls back to DEFAULT_STYLE for unknown statuses."""
        self.manager.register_agent("sess-1", "test-agent", "gpt-4o")
        self.manager.update_agent("sess-1", status="unknown_status")
        text = self._render_to_text(self.manager._render_display())
        assert "Active sub-agents" in text
        # The unknown status string is still rendered (no crash).
        assert "unknown_status" in text


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestContextManager:
    """Test context manager support."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_context_manager_enter_returns_self(self, mock_stop):
        """Test __enter__ returns the manager instance."""
        manager = SubAgentConsoleManager(console=Mock(spec=Console))

        with manager as ctx:
            assert ctx is manager

    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_context_manager_exit_stops_display(self, mock_stop):
        """Test __exit__ calls _stop_display."""
        manager = SubAgentConsoleManager(console=Mock(spec=Console))

        with manager:
            pass

        mock_stop.assert_called_once()

    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_context_manager_exit_on_exception(self, mock_stop):
        """Test __exit__ is called even on exception."""
        manager = SubAgentConsoleManager(console=Mock(spec=Console))

        with pytest.raises(ValueError):
            with manager:
                raise ValueError("Test error")

        mock_stop.assert_called_once()


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunction:
    """Test get_subagent_console_manager convenience function."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    def test_get_subagent_console_manager_returns_singleton(self):
        """Test that get_subagent_console_manager returns singleton."""
        manager1 = get_subagent_console_manager()
        manager2 = get_subagent_console_manager()
        assert manager1 is manager2

    def test_get_subagent_console_manager_with_console(self):
        """Test get_subagent_console_manager with custom console."""
        mock_console = Mock(spec=Console)
        manager = get_subagent_console_manager(console=mock_console)
        assert manager.console is mock_console

    def test_get_subagent_console_manager_returns_correct_type(self):
        """Test return type is SubAgentConsoleManager."""
        manager = get_subagent_console_manager()
        assert isinstance(manager, SubAgentConsoleManager)


# =============================================================================
# Status Styles Tests
# =============================================================================


class TestStatusStyles:
    """Test STATUS_STYLES and DEFAULT_STYLE constants."""

    def test_status_styles_contains_all_statuses(self):
        """Test STATUS_STYLES has all expected statuses."""
        expected_statuses = {
            "starting",
            "running",
            "thinking",
            "tool_calling",
            "completed",
            "error",
        }
        assert set(STATUS_STYLES.keys()) == expected_statuses

    def test_status_styles_have_required_keys(self):
        """Test each status style has required keys."""
        required_keys = {"color", "spinner", "emoji"}
        for status, style in STATUS_STYLES.items():
            assert set(style.keys()) == required_keys, f"Status {status} missing keys"

    def test_default_style_has_required_keys(self):
        """Test DEFAULT_STYLE has required keys."""
        required_keys = {"color", "spinner", "emoji"}
        assert set(DEFAULT_STYLE.keys()) == required_keys

    def test_completed_and_error_have_no_spinner(self):
        """Test completed and error statuses have no spinner."""
        assert STATUS_STYLES["completed"]["spinner"] is None
        assert STATUS_STYLES["error"]["spinner"] is None


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Test thread safety of SubAgentConsoleManager."""

    def setup_method(self):
        SubAgentConsoleManager.reset_instance()

    def teardown_method(self):
        SubAgentConsoleManager.reset_instance()

    @patch.object(SubAgentConsoleManager, "_start_display")
    @patch.object(SubAgentConsoleManager, "_stop_display")
    def test_concurrent_registration(self, mock_stop, mock_start):
        """Test concurrent agent registration is thread-safe."""
        manager = SubAgentConsoleManager(console=Mock(spec=Console))
        errors = []

        def register_agent(i):
            try:
                manager.register_agent(f"sess-{i}", f"agent-{i}", "model")
                manager.update_agent(f"sess-{i}", status="running")
                manager.unregister_agent(f"sess-{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_agent, args=(i,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_singleton_thread_safety(self):
        """Test get_instance is thread-safe."""
        instances = []

        def get_instance():
            inst = SubAgentConsoleManager.get_instance()
            instances.append(inst)

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All instances should be the same object
        assert all(inst is instances[0] for inst in instances)
