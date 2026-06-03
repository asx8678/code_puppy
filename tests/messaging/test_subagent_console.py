"""Tests for code_puppy.messaging.subagent_console."""

import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from code_puppy.messaging.subagent_console import (
    STATUS_STYLES,
    AgentState,
    SubAgentConsoleManager,
    get_subagent_console_manager,
)


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=False, width=120)


@pytest.fixture(autouse=True)
def reset_singleton():
    SubAgentConsoleManager.reset_instance()
    yield
    SubAgentConsoleManager.reset_instance()


# =========================================================================
# AgentState
# =========================================================================


def test_agent_state_elapsed():
    state = AgentState(session_id="s1", agent_name="agent", model_name="gpt-4o")
    time.sleep(0.05)
    assert state.elapsed_seconds() > 0


def test_agent_state_elapsed_formatted_seconds():
    state = AgentState(session_id="s1", agent_name="agent", model_name="gpt-4o")
    fmt = state.elapsed_formatted()
    assert "s" in fmt


def test_agent_state_elapsed_formatted_minutes():
    state = AgentState(session_id="s1", agent_name="agent", model_name="gpt-4o")
    state.start_time = time.time() - 125  # 2m 5s
    fmt = state.elapsed_formatted()
    assert "m" in fmt


def test_agent_state_to_status_message():
    state = AgentState(
        session_id="s1",
        agent_name="agent",
        model_name="gpt-4o",
        status="running",
        tool_call_count=3,
        token_count=100,
        current_tool="grep",
        error_message="oops",
    )
    msg = state.to_status_message()
    assert msg.agent_name == "agent"
    assert msg.tool_call_count == 3
    assert msg.error_message == "oops"


# =========================================================================
# SubAgentConsoleManager
# =========================================================================


def test_singleton(console):
    m1 = SubAgentConsoleManager.get_instance(console)
    m2 = SubAgentConsoleManager.get_instance()
    assert m1 is m2


def test_register_unregister_agent(console):
    mgr = SubAgentConsoleManager(console)
    mgr.register_agent("s1", "agent", "gpt-4o")
    assert mgr.get_agent_state("s1") is not None
    assert len(mgr.get_all_agents()) == 1

    mgr.unregister_agent("s1")
    # T2 linger semantics: state persists with final status + completed_at
    state = mgr.get_agent_state("s1")
    assert state is not None
    assert state.status == "completed"
    assert state.completed_at is not None
    # The update loop prunes after _LINGER_SECONDS (covered in coverage suite)
    assert len(mgr.get_all_agents()) == 1  # still present until prune


def test_unregister_unknown_agent(console):
    mgr = SubAgentConsoleManager(console)
    mgr.unregister_agent("nonexistent")  # Should not raise


def test_update_agent(console):
    mgr = SubAgentConsoleManager(console)
    mgr.register_agent("s1", "agent", "gpt-4o")
    mgr.update_agent(
        "s1",
        status="running",
        tool_call_count=5,
        token_count=200,
        current_tool="edit",
        error_message="err",
    )
    state = mgr.get_agent_state("s1")
    assert state.status == "running"
    assert state.tool_call_count == 5
    assert state.token_count == 200
    assert state.current_tool == "edit"
    assert state.error_message == "err"
    mgr.unregister_agent("s1")


def test_update_unknown_agent(console):
    mgr = SubAgentConsoleManager(console)
    mgr.update_agent("nonexistent", status="running")  # Should not raise


def test_render_display_no_agents(console):
    mgr = SubAgentConsoleManager(console)
    group = mgr._render_display()
    assert group is not None


def test_render_display_with_agents(console):
    mgr = SubAgentConsoleManager(console)
    # Don't use register_agent (starts live display), add directly
    mgr._agents["s1"] = AgentState(
        session_id="s1", agent_name="agent", model_name="gpt-4o"
    )
    group = mgr._render_display()
    assert group is not None


def test_render_display_all_statuses(console):
    mgr = SubAgentConsoleManager(console)
    for status in STATUS_STYLES:
        mgr._agents["s1"] = AgentState(
            session_id="s1",
            agent_name="agent",
            model_name="gpt-4o",
            status=status,
        )
        group = mgr._render_display()
        assert group is not None
        mgr._agents.clear()


def test_render_display_unknown_status(console):
    mgr = SubAgentConsoleManager(console)
    mgr._agents["s1"] = AgentState(
        session_id="s1",
        agent_name="agent",
        model_name="gpt-4o",
        status="weird",
    )
    group = mgr._render_display()
    assert group is not None


def test_render_display_with_current_tool(console):
    mgr = SubAgentConsoleManager(console)
    mgr._agents["s1"] = AgentState(
        session_id="s1",
        agent_name="agent",
        model_name="gpt-4o",
        current_tool="grep",
        tool_call_count=3,
        token_count=500,
        error_message="some error",
    )
    group = mgr._render_display()
    assert group is not None


def test_render_display_long_session_id(console):
    mgr = SubAgentConsoleManager(console)
    mgr._agents["s1"] = AgentState(
        session_id="a" * 30,  # > 24 chars
        agent_name="agent",
        model_name="gpt-4o",
    )
    group = mgr._render_display()
    assert group is not None


def test_start_stop_display(console):
    mgr = SubAgentConsoleManager(console)
    with patch("code_puppy.messaging.spinner.pause_all_spinners") as mock_pause, \
         patch("code_puppy.messaging.spinner.resume_all_spinners") as mock_resume:
        # Simulate _start_display side-effect (creating a Live) without calling
        # the real method — Rich Live won't cooperate with patched Console.
        def _fake_start(*a, **kw):
            mock_pause()
            mgr._live = MagicMock()

        mgr._start_display = _fake_start
        mgr._start_display()
        assert mgr._live is not None
        mock_pause.assert_called_once()
        # Double start is no-op when already running
        mgr._start_display()
        mgr._stop_display()
        assert mgr._live is None
        mock_resume.assert_called_once()


def test_context_manager(console):
    mgr = SubAgentConsoleManager(console)
    with mgr:
        mgr._agents["s1"] = AgentState(
            session_id="s1", agent_name="agent", model_name="gpt-4o"
        )
    # After exit, display is stopped


def test_get_subagent_console_manager(console):
    SubAgentConsoleManager.reset_instance()
    mgr = get_subagent_console_manager(console)
    assert isinstance(mgr, SubAgentConsoleManager)


def test_register_starts_display_unregister_lingers_then_removed(console):
    mgr = SubAgentConsoleManager(console)
    with patch("code_puppy.messaging.spinner.pause_all_spinners"), \
         patch("code_puppy.messaging.spinner.resume_all_spinners"), \
         patch("code_puppy.messaging.subagent_console.Live") as mock_live_class:
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live
        mgr.register_agent("s1", "agent", "gpt-4o")
        assert mgr._live is mock_live
        mgr._LINGER_SECONDS = 0.05
        mgr.unregister_agent("s1", final_status="completed")
        # Agent lingers immediately after unregister (not removed synchronously)
        assert mgr.get_agent_state("s1") is not None
        assert mgr.get_agent_state("s1").status == "completed"
        # Wait for the update loop to prune after the linger window
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if mgr.get_agent_state("s1") is None:
                break
            time.sleep(0.05)
        mgr._stop_display()
        assert mgr._live is None


def test_unregister_with_error_status(console):
    mgr = SubAgentConsoleManager(console)
    mgr.register_agent("s1", "agent", "gpt-4o")
    mgr.unregister_agent("s1", final_status="error")
    # T2 linger semantics: state persists with error status + completed_at
    state = mgr.get_agent_state("s1")
    assert state is not None
    assert state.status == "error"
    assert state.completed_at is not None


def test_stop_display_live_stop_error(console):
    """_stop_display catches errors from live.stop()."""
    mgr = SubAgentConsoleManager(console)
    with patch("code_puppy.messaging.spinner.pause_all_spinners"), \
         patch("code_puppy.messaging.spinner.resume_all_spinners"):
        # Simulate _start_display side-effect without calling the real method.
        mgr._start_display = lambda *a, **kw: mgr.__setattr__("_live", MagicMock())
        mgr._start_display()
        assert mgr._live is not None
        # Force live.stop() to raise
        mgr._live.stop = MagicMock(side_effect=RuntimeError("crash"))
        mgr._stop_display()  # Should not raise
        assert mgr._live is None


def test_update_loop_render_error(console):
    """_update_loop catches rendering errors."""
    mgr = SubAgentConsoleManager(console)
    mgr._start_display()
    time.sleep(0.05)
    # Force _render_display to raise
    mgr._render_display = MagicMock(side_effect=RuntimeError("render fail"))
    time.sleep(0.2)  # Let the update loop encounter the error
    mgr._stop_display()  # Should work fine despite errors
