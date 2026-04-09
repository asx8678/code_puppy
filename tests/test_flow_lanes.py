"""Unit tests for flow_visualizer/lanes.py — pure reducer functions.

Tests the state management logic without any I/O or rendering.
"""

import time
from copy import deepcopy

import pytest

from code_puppy.plugins.flow_visualizer.lanes import (
    FlowLaneState,
    FlowState,
    reduce_agent_start,
    reduce_stream_event,
    reduce_agent_end,
    expire_lanes,
    AGENT_COLORS,
    _get_agent_color,
    _get_session_key,
)


class TestFlowLaneState:
    """Tests for the FlowLaneState dataclass."""

    def test_flow_lane_state_creation(self):
        """Test creating a FlowLaneState with default values."""
        lane = FlowLaneState(
            agent_name="code-puppy",
            model_name="gpt-4",
            session_id="session-123",
        )
        
        assert lane.agent_name == "code-puppy"
        assert lane.model_name == "gpt-4"
        assert lane.session_id == "session-123"
        assert lane.status == "running"
        assert lane.detail == ""
        assert lane.ended_at is None
        assert lane.duration is None
        assert lane.color == "white"
        assert lane.started_at > 0

    def test_flow_lane_state_immutability(self):
        """Test that FlowLaneState is frozen/immutable."""
        lane = FlowLaneState(
            agent_name="test",
            model_name="model",
            session_id="session-1",
        )
        
        # Attempting to modify should raise an error (frozen dataclass)
        with pytest.raises((AttributeError, TypeError)):
            lane.status = "done"


class TestFlowState:
    """Tests for the FlowState class."""

    def test_flow_state_default_creation(self):
        """Test creating a FlowState with default values."""
        state = FlowState()
        
        assert state.lanes == {}
        assert state.enabled is True
        assert state.created_at > 0

    def test_flow_state_copy_creates_independent_copy(self):
        """Test that copy() creates an independent deep copy."""
        lane = FlowLaneState(
            agent_name="test",
            model_name="model",
            session_id="session-1",
        )
        state = FlowState(lanes={"session-1": lane})
        
        # Copy the state
        copied = state.copy()
        
        # Should be equal but independent
        assert copied.lanes["session-1"].agent_name == "test"
        
        # Modifying original should not affect copy
        state.lanes["session-1"] = FlowLaneState(
            agent_name="modified",
            model_name="model",
            session_id="session-1",
        )
        assert copied.lanes["session-1"].agent_name == "test"


class TestGetSessionKey:
    """Tests for the _get_session_key helper."""

    def test_session_id_provided(self):
        """Test that a provided session_id is returned as-is."""
        assert _get_session_key("session-123") == "session-123"

    def test_session_id_none(self):
        """Test that None session_id returns the fallback key."""
        assert _get_session_key(None) == "__default__"


class TestGetAgentColor:
    """Tests for the _get_agent_color helper."""

    def test_exact_agent_match(self):
        """Test exact agent name matches."""
        assert _get_agent_color("turbo-executor") == "white"
        assert _get_agent_color("code-puppy") == "green"
        assert _get_agent_color("bloodhound") == "red"

    def test_partial_agent_match(self):
        """Test partial agent name matching."""
        assert _get_agent_color("turbo-executor-fast") == "white"
        assert _get_agent_color("my-code-puppy-agent") == "green"
        assert _get_agent_color("bloodhound-search") == "red"

    def test_unknown_agent_defaults_to_white(self):
        """Test unknown agent names default to white."""
        assert _get_agent_color("unknown-agent") == "white"
        assert _get_agent_color("custom-tool") == "white"

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        # Note: the actual function does lower() conversion
        assert _get_agent_color("Code-Puppy") == "green"
        assert _get_agent_color("TURBO-EXECUTOR") == "white"


class TestReduceAgentStart:
    """Tests for the reduce_agent_start reducer."""

    def test_creates_new_lane(self):
        """Test that reduce_agent_start creates a new lane."""
        state = FlowState()
        new_state = reduce_agent_start(state, "code-puppy", "gpt-4", "session-1")
        
        assert "session-1" in new_state.lanes
        lane = new_state.lanes["session-1"]
        assert lane.agent_name == "code-puppy"
        assert lane.model_name == "gpt-4"
        assert lane.session_id == "session-1"
        assert lane.status == "running"
        assert lane.color == "green"
        assert lane.started_at > 0

    def test_replaces_existing_lane(self):
        """Test that starting an agent replaces an existing lane with same session."""
        state = FlowState()
        state = reduce_agent_start(state, "old-agent", "old-model", "session-1")
        
        new_state = reduce_agent_start(state, "new-agent", "new-model", "session-1")
        
        assert new_state.lanes["session-1"].agent_name == "new-agent"
        assert new_state.lanes["session-1"].model_name == "new-model"

    def test_handles_none_session_id(self):
        """Test that None session_id uses fallback key."""
        state = FlowState()
        new_state = reduce_agent_start(state, "test-agent", "model", None)
        
        assert "__default__" in new_state.lanes
        assert new_state.lanes["__default__"].agent_name == "test-agent"

    def test_returns_new_state_immutability(self):
        """Test that original state is not modified."""
        state = FlowState()
        original_lanes = state.lanes
        
        new_state = reduce_agent_start(state, "agent", "model", "session-1")
        
        # Original state should be unchanged
        assert state.lanes is original_lanes
        assert "session-1" not in state.lanes
        
        # New state should have the lane
        assert "session-1" in new_state.lanes


class TestReduceStreamEvent:
    """Tests for the reduce_stream_event reducer."""

    def test_updates_tool_call_detail(self):
        """Test that tool_call events extract tool name."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        event_data = {"tool_name": "read_file"}
        new_state = reduce_stream_event(state, "tool_call", event_data, "session-1")
        
        assert new_state.lanes["session-1"].detail == "Running read_file"

    def test_updates_tool_call_detail_with_name_field(self):
        """Test that tool_call events work with 'name' field."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        event_data = {"name": "grep"}
        new_state = reduce_stream_event(state, "tool_call", event_data, "session-1")
        
        assert new_state.lanes["session-1"].detail == "Running grep"

    def test_updates_tool_result_detail(self):
        """Test that tool_result events set 'completed' detail."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        new_state = reduce_stream_event(state, "tool_result", {"result": "ok"}, "session-1")
        
        assert new_state.lanes["session-1"].detail == "completed"

    def test_updates_other_event_detail(self):
        """Test that other event types use event_type as detail."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        new_state = reduce_stream_event(state, "token", {"text": "hello"}, "session-1")
        
        assert new_state.lanes["session-1"].detail == "token"

    def test_ignores_missing_lane(self):
        """Test that events for non-existent lanes are ignored."""
        state = FlowState()
        
        new_state = reduce_stream_event(state, "tool_call", {"tool_name": "test"}, "non-existent")
        
        assert "non-existent" not in new_state.lanes
        assert new_state.lanes == {}

    def test_preserves_other_lane_fields(self):
        """Test that updating detail preserves other lane fields."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        original_started_at = state.lanes["session-1"].started_at
        
        new_state = reduce_stream_event(state, "tool_call", {"tool_name": "test"}, "session-1")
        lane = new_state.lanes["session-1"]
        
        assert lane.agent_name == "agent"
        assert lane.model_name == "model"
        assert lane.status == "running"
        assert lane.started_at == original_started_at


class TestReduceAgentEnd:
    """Tests for the reduce_agent_end reducer."""

    def test_marks_lane_done_on_success(self):
        """Test that successful end marks lane as done."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        # Small delay to ensure duration > 0
        time.sleep(0.01)
        
        new_state = reduce_agent_end(state, "agent", "session-1", success=True, error=None)
        lane = new_state.lanes["session-1"]
        
        assert lane.status == "done"
        assert lane.detail == "finished"
        assert lane.ended_at is not None
        assert lane.duration is not None
        assert lane.duration > 0

    def test_marks_lane_failed_on_error(self):
        """Test that failed end marks lane as failed."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        error = Exception("Something went wrong")
        new_state = reduce_agent_end(state, "agent", "session-1", success=False, error=error)
        lane = new_state.lanes["session-1"]
        
        assert lane.status == "failed"
        assert "Something went wrong" in lane.detail
        assert lane.ended_at is not None
        assert lane.duration is not None

    def test_creates_lane_for_end_without_start(self):
        """Test that end events create a lane even if no start was seen."""
        state = FlowState()
        
        new_state = reduce_agent_end(state, "agent", "session-1", success=True, error=None)
        lane = new_state.lanes["session-1"]
        
        assert lane.agent_name == "agent"
        assert lane.model_name == "unknown"
        assert lane.status == "done"
        assert lane.duration == 0.0

    def test_preserves_color_on_end(self):
        """Test that color is preserved when ending a lane."""
        state = FlowState()
        state = reduce_agent_start(state, "code-puppy", "model", "session-1")
        
        new_state = reduce_agent_end(state, "code-puppy", "session-1", success=True, error=None)
        lane = new_state.lanes["session-1"]
        
        assert lane.color == "green"


class TestExpireLanes:
    """Tests for the expire_lanes reducer."""

    def test_removes_old_ended_lanes(self):
        """Test that ended lanes older than ttl are removed."""
        state = FlowState()
        state = reduce_agent_start(state, "agent", "model", "session-1")
        
        # Simulate lane ending 15 seconds ago
        now = time.time()
        state.lanes["session-1"] = FlowLaneState(
            agent_name="agent",
            model_name="model",
            session_id="session-1",
            status="done",
            detail="finished",
            started_at=now - 20,
            ended_at=now - 15,
            duration=5.0,
            color="white",
        )
        
        new_state = expire_lanes(state, now, ttl=10.0)
        
        assert "session-1" not in new_state.lanes

    def test_keeps_recent_ended_lanes(self):
        """Test that ended lanes within ttl are kept."""
        state = FlowState()
        
        now = time.time()
        state.lanes["session-1"] = FlowLaneState(
            agent_name="agent",
            model_name="model",
            session_id="session-1",
            status="done",
            detail="finished",
            started_at=now - 5,
            ended_at=now - 2,
            duration=3.0,
            color="white",
        )
        
        new_state = expire_lanes(state, now, ttl=10.0)
        
        assert "session-1" in new_state.lanes

    def test_keeps_running_lanes(self):
        """Test that running lanes are never removed."""
        state = FlowState()
        now = time.time()
        
        # Create a running lane that started long ago
        state.lanes["session-1"] = FlowLaneState(
            agent_name="agent",
            model_name="model",
            session_id="session-1",
            status="running",
            detail="working",
            started_at=now - 1000,  # Started 1000 seconds ago
            ended_at=None,
            duration=None,
            color="white",
        )
        
        new_state = expire_lanes(state, now, ttl=10.0)
        
        assert "session-1" in new_state.lanes

    def test_only_removes_expired_lanes(self):
        """Test that only expired lanes are removed, others kept."""
        state = FlowState()
        now = time.time()
        
        # Expired lane (ended 20 seconds ago)
        state.lanes["old"] = FlowLaneState(
            agent_name="old-agent",
            model_name="model",
            session_id="old",
            status="done",
            detail="finished",
            started_at=now - 30,
            ended_at=now - 20,
            duration=10.0,
            color="white",
        )
        
        # Fresh lane (ended 2 seconds ago)
        state.lanes["new"] = FlowLaneState(
            agent_name="new-agent",
            model_name="model",
            session_id="new",
            status="done",
            detail="finished",
            started_at=now - 7,
            ended_at=now - 2,
            duration=5.0,
            color="white",
        )
        
        # Running lane
        state.lanes["running"] = FlowLaneState(
            agent_name="running-agent",
            model_name="model",
            session_id="running",
            status="running",
            detail="working",
            started_at=now - 100,
            ended_at=None,
            duration=None,
            color="white",
        )
        
        new_state = expire_lanes(state, now, ttl=10.0)
        
        assert "old" not in new_state.lanes
        assert "new" in new_state.lanes
        assert "running" in new_state.lanes


class TestAgentColors:
    """Tests for the AGENT_COLORS constant."""

    def test_contains_expected_agents(self):
        """Test that AGENT_COLORS contains all expected agent types."""
        expected = {
            "code-puppy",
            "terrier",
            "shepherd",
            "watchdog",
            "retriever",
            "bloodhound",
            "turbo-executor",
        }
        assert set(AGENT_COLORS.keys()) == expected

    def test_color_values_are_valid(self):
        """Test that color values are valid Rich color names."""
        valid_colors = {"green", "blue", "yellow", "magenta", "cyan", "red", "white"}
        for color in AGENT_COLORS.values():
            assert color in valid_colors
