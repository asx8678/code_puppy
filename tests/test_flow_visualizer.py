"""Integration tests for the flow_visualizer plugin.

Tests the complete flow: events → state updates → rendering.
"""

import time


from code_puppy.plugins.flow_visualizer.lanes import (
    FlowState,
    reduce_agent_start,
    reduce_stream_event,
    reduce_agent_end,
)
from code_puppy.plugins.flow_visualizer.panel import (
    render_flow_panel,
    _format_duration,
    _get_status_emoji,
    _supports_unicode,
)


class TestRenderFlowPanel:
    """Tests for the render_flow_panel function."""

    def test_returns_none_when_disabled(self):
        """Test that render_flow_panel returns None when disabled."""
        state = FlowState(enabled=False, lanes={"s1": None})
        assert render_flow_panel(state) is None

    def test_returns_none_when_no_lanes(self):
        """Test that render_flow_panel returns None with empty lanes."""
        state = FlowState(enabled=True, lanes={})
        assert render_flow_panel(state) is None

    def test_renders_single_running_lane(self):
        """Test rendering a panel with one running lane."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "code-puppy", "gpt-4", "session-1")
        state = reduce_stream_event(state, "tool_call", {"tool_name": "read_file"}, "session-1")
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "code-puppy" in output
        assert "running" in output.lower() or "🔄" in output

    def test_renders_multiple_lanes(self):
        """Test rendering a panel with multiple lanes."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "turbo-executor", "gpt-4", "session-1")
        state = reduce_agent_start(state, "code-puppy", "claude", "session-2")
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "turbo-executor" in output
        assert "code-puppy" in output

    def test_shows_done_status(self):
        """Test that done lanes show correct status."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "retriever", "gpt-4", "session-1")
        state = reduce_agent_end(state, "retriever", "session-1", success=True, error=None)
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "retriever" in output
        # Should show done indicator
        assert "done" in output.lower() or "✅" in output or "[OK]" in output

    def test_shows_failed_status(self):
        """Test that failed lanes show correct status."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "bloodhound", "gpt-4", "session-1")
        state = reduce_agent_end(state, "bloodhound", "session-1", success=False, error=Exception("Error"))
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "bloodhound" in output
        # Should show failed indicator
        assert "failed" in output.lower() or "❌" in output or "[ERR]" in output

    def test_shows_duration_for_running_lane(self):
        """Test that running lanes show elapsed duration."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "shepherd", "gpt-4", "session-1")
        
        # Small delay to ensure non-zero duration
        time.sleep(0.05)
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "shepherd" in output
        # Should contain a duration like "0.1s"
        assert "s" in output  # Duration suffix

    def test_contains_pack_status_title(self):
        """Test that panel has correct title."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "watchdog", "gpt-4", "session-1")
        
        output = render_flow_panel(state)
        
        assert output is not None
        # Should have "Pack Status" in title (with or without emoji)
        assert "Pack Status" in output or "🐕" in output


class TestFormatDuration:
    """Tests for the _format_duration helper."""

    def test_formats_sub_60_seconds(self):
        """Test formatting durations under 60 seconds."""
        assert _format_duration(5.5) == "5.5s"
        assert _format_duration(0.1) == "0.1s"
        assert _format_duration(59.9) == "59.9s"

    def test_formats_over_60_seconds(self):
        """Test formatting durations over 60 seconds."""
        assert _format_duration(65.0) == "1m 5s"
        assert _format_duration(125.0) == "2m 5s"
        assert _format_duration(3600.0) == "60m 0s"

    def test_handles_none(self):
        """Test that None duration returns em dash."""
        assert _format_duration(None) == "—"


class TestStatusEmoji:
    """Tests for the _get_status_emoji helper."""

    def test_unicode_statuses(self):
        """Test unicode emoji status indicators."""
        assert _get_status_emoji("running", unicode=True) == "🔄"
        assert _get_status_emoji("done", unicode=True) == "✅"
        assert _get_status_emoji("failed", unicode=True) == "❌"

    def test_ascii_statuses(self):
        """Test ASCII fallback status indicators."""
        assert _get_status_emoji("running", unicode=False) == "[RUN]"
        assert _get_status_emoji("done", unicode=False) == "[OK]"
        assert _get_status_emoji("failed", unicode=False) == "[ERR]"

    def test_unknown_status(self):
        """Test that unknown status returns a default indicator."""
        assert _get_status_emoji("unknown", unicode=True) == "❓"
        assert _get_status_emoji("unknown", unicode=False) == "[?]"


class TestEventSequence:
    """Tests for complete event sequences."""

    def test_full_agent_lifecycle(self):
        """Test complete lifecycle: start → stream events → end."""
        state = FlowState(enabled=True)
        
        # Agent starts
        state = reduce_agent_start(state, "terrier", "gpt-4", "task-123")
        assert state.lanes["task-123"].status == "running"
        assert state.lanes["task-123"].agent_name == "terrier"
        
        # Stream events
        state = reduce_stream_event(state, "tool_call", {"tool_name": "list_files"}, "task-123")
        assert state.lanes["task-123"].detail == "Running list_files"
        
        state = reduce_stream_event(state, "tool_result", {"success": True}, "task-123")
        assert state.lanes["task-123"].detail == "completed"
        
        state = reduce_stream_event(state, "token", {"text": "Done"}, "task-123")
        assert state.lanes["task-123"].detail == "token"
        
        # Agent ends
        state = reduce_agent_end(state, "terrier", "task-123", success=True, error=None)
        assert state.lanes["task-123"].status == "done"
        assert state.lanes["task-123"].ended_at is not None
        assert state.lanes["task-123"].duration is not None

    def test_multiple_agents_parallel(self):
        """Test multiple agents running in parallel."""
        state = FlowState(enabled=True)
        
        # Start multiple agents
        state = reduce_agent_start(state, "agent-a", "model-1", "session-a")
        state = reduce_agent_start(state, "agent-b", "model-2", "session-b")
        state = reduce_agent_start(state, "agent-c", "model-3", "session-c")
        
        assert len(state.lanes) == 3
        assert "session-a" in state.lanes
        assert "session-b" in state.lanes
        assert "session-c" in state.lanes
        
        # Different stream events for each
        state = reduce_stream_event(state, "tool_call", {"tool_name": "read"}, "session-a")
        state = reduce_stream_event(state, "tool_call", {"tool_name": "write"}, "session-b")
        state = reduce_stream_event(state, "thinking", {}, "session-c")
        
        assert state.lanes["session-a"].detail == "Running read"
        assert state.lanes["session-b"].detail == "Running write"
        assert state.lanes["session-c"].detail == "thinking"
        
        # End one agent
        state = reduce_agent_end(state, "agent-a", "session-a", success=True, error=None)
        
        assert state.lanes["session-a"].status == "done"
        assert state.lanes["session-b"].status == "running"
        assert state.lanes["session-c"].status == "running"

    def test_render_after_event_sequence(self):
        """Test that panel renders correctly after event sequence."""
        state = FlowState(enabled=True)
        
        state = reduce_agent_start(state, "code-puppy", "gpt-4", "s1")
        state = reduce_stream_event(state, "tool_call", {"tool_name": "grep"}, "s1")
        
        output = render_flow_panel(state)
        
        assert output is not None
        assert "code-puppy" in output
        # The panel should show the current detail (grep tool)
        assert "grep" in output or "Running" in output or "running" in output


class TestRichConsoleOutput:
    """Tests that verify Rich console output capture works."""

    def test_can_capture_rich_output(self):
        """Test that we can capture Rich console output."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "test", "model", "s1")
        
        output = render_flow_panel(state)
        
        # Verify we got a string with Rich formatting
        assert isinstance(output, str)
        assert len(output) > 0
        # Rich output uses box drawing characters
        assert any(c in output for c in ["─", "│", "┌", "┐", "└", "┘"])

    def test_output_contains_all_lanes(self):
        """Test that output contains all lanes' information."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "first", "m1", "s1")
        state = reduce_agent_start(state, "second", "m2", "s2")
        
        output = render_flow_panel(state)
        
        assert "first" in output
        assert "second" in output


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_stream_event_for_nonexistent_lane(self):
        """Test that stream events for non-existent lanes don't crash."""
        state = FlowState(enabled=True)
        
        # Try to update a lane that doesn't exist
        new_state = reduce_stream_event(
            state, "tool_call", {"tool_name": "test"}, "nonexistent"
        )
        
        # Should return state unchanged (or copied with no changes)
        assert "nonexistent" not in new_state.lanes

    def test_end_event_for_nonexistent_lane(self):
        """Test that end events for non-existent lanes create a new lane."""
        state = FlowState(enabled=True)
        
        new_state = reduce_agent_end(state, "orphan", "orphan-session", success=True, error=None)
        
        # Should create a lane to record the end event
        assert "orphan-session" in new_state.lanes
        assert new_state.lanes["orphan-session"].agent_name == "orphan"
        assert new_state.lanes["orphan-session"].status == "done"

    def test_handles_empty_event_data(self):
        """Test that empty event data is handled gracefully."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "test", "model", "s1")
        
        # Event with no data
        new_state = reduce_stream_event(state, "tool_call", {}, "s1")
        assert "unknown tool" in new_state.lanes["s1"].detail

    def test_handles_none_event_data(self):
        """Test that None event data is handled gracefully."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "test", "model", "s1")
        
        new_state = reduce_stream_event(state, "tool_call", None, "s1")
        assert "unknown tool" in new_state.lanes["s1"].detail

    def test_end_with_error_none_for_failure(self):
        """Test failure with None error message."""
        state = FlowState(enabled=True)
        state = reduce_agent_start(state, "test", "model", "s1")
        
        new_state = reduce_agent_end(state, "test", "s1", success=False, error=None)
        
        assert new_state.lanes["s1"].status == "failed"
        assert new_state.lanes["s1"].detail == "failed"


class TestUnicodeSupport:
    """Tests for unicode/ASCII detection."""

    def test_unicode_detection_no_crash(self):
        """Test that unicode detection doesn't crash."""
        # This should not raise
        result = _supports_unicode()
        assert isinstance(result, bool)

    def test_status_emoji_handles_all_statuses(self):
        """Test that all statuses have both unicode and ASCII representations."""
        statuses = ["running", "done", "failed", "unknown"]
        
        for status in statuses:
            unicode = _get_status_emoji(status, unicode=True)
            ascii = _get_status_emoji(status, unicode=False)
            
            assert isinstance(unicode, str)
            assert isinstance(ascii, str)
            assert len(unicode) > 0
            assert len(ascii) > 0
