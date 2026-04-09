"""Flow Visualizer — Pure state management module.

This module contains pure reducer functions for managing flow lane state.
All functions are side-effect free and return new state objects.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, Optional


# Color mapping for different agent types
AGENT_COLORS: dict[str, str] = {
    "code-puppy": "green",
    "terrier": "blue",
    "shepherd": "yellow",
    "watchdog": "magenta",
    "retriever": "cyan",
    "bloodhound": "red",
    "turbo-executor": "white",
}


def _get_agent_color(agent_name: str) -> str:
    """Get color for an agent based on its name.
    
    Returns a color from AGENT_COLORS if the agent name matches or contains
    a known agent type, otherwise returns 'white'.
    """
    agent_lower = agent_name.lower()
    
    # Exact match
    if agent_lower in AGENT_COLORS:
        return AGENT_COLORS[agent_lower]
    
    # Partial match (e.g., "turbo-executor-fast" matches "turbo-executor")
    for name, color in AGENT_COLORS.items():
        if name in agent_lower:
            return color
    
    return "white"


@dataclass(frozen=True)
class FlowLaneState:
    """State for a single agent lane.
    
    This is an immutable dataclass representing the current status
    of an agent in the flow visualization.
    """
    agent_name: str
    model_name: str
    session_id: Optional[str]
    status: str = "running"  # "running", "done", "failed"
    detail: str = ""  # Current activity description
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    duration: Optional[float] = None
    color: str = "white"


@dataclass
class FlowState:
    """Manager for all flow lanes.
    
    Contains a dictionary of FlowLaneState objects keyed by session_id,
    and configuration for the visualizer.
    """
    lanes: dict[str, FlowLaneState] = field(default_factory=dict)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def copy(self) -> FlowState:
        """Create a deep copy of this state."""
        new_state = FlowState(
            lanes=deepcopy(self.lanes),
            enabled=self.enabled,
            created_at=self.created_at,
        )
        return new_state


def _get_session_key(session_id: Optional[str]) -> str:
    """Get a valid dict key from session_id, handling None."""
    return session_id if session_id is not None else "__default__"


def reduce_agent_start(
    state: FlowState,
    agent_name: str,
    model_name: str,
    session_id: Optional[str],
) -> FlowState:
    """Create a new lane when an agent starts.
    
    Args:
        state: Current FlowState
        agent_name: Name of the agent starting
        model_name: Name of the model being used
        session_id: Optional session identifier
        
    Returns:
        New FlowState with the added lane
    """
    new_state = state.copy()
    key = _get_session_key(session_id)
    
    new_state.lanes[key] = FlowLaneState(
        agent_name=agent_name,
        model_name=model_name,
        session_id=session_id,
        status="running",
        detail="starting...",
        started_at=time.time(),
        ended_at=None,
        duration=None,
        color=_get_agent_color(agent_name),
    )
    
    return new_state


def reduce_stream_event(
    state: FlowState,
    event_type: str,
    event_data: Optional[object],
    session_id: Optional[str],
) -> FlowState:
    """Update lane detail based on stream event.
    
    Extracts relevant detail information:
    - For "tool_call" events: shows the tool name
    - For "tool_result" events: shows "completed"
    - For other events: shows the event_type
    
    Args:
        state: Current FlowState
        event_type: Type of the streaming event
        event_data: Data associated with the event
        session_id: Optional session identifier
        
    Returns:
        New FlowState with updated lane detail
    """
    new_state = state.copy()
    key = _get_session_key(session_id)
    
    if key not in new_state.lanes:
        # Lane doesn't exist, ignore event
        return new_state
    
    lane = new_state.lanes[key]
    
    # Extract detail based on event type
    if event_type == "tool_call":
        # Try to extract tool name from event_data
        tool_name = "unknown tool"
        if isinstance(event_data, dict):
            if "tool_name" in event_data:
                tool_name = str(event_data["tool_name"])
            elif "name" in event_data:
                tool_name = str(event_data["name"])
        detail = f"Running {tool_name}"
    elif event_type == "tool_result":
        detail = "completed"
    else:
        detail = event_type
    
    # Update the lane with new detail
    new_state.lanes[key] = FlowLaneState(
        agent_name=lane.agent_name,
        model_name=lane.model_name,
        session_id=lane.session_id,
        status=lane.status,
        detail=detail,
        started_at=lane.started_at,
        ended_at=lane.ended_at,
        duration=lane.duration,
        color=lane.color,
    )
    
    return new_state


def reduce_agent_end(
    state: FlowState,
    agent_name: str,
    session_id: Optional[str],
    success: bool,
    error: Optional[Exception],
) -> FlowState:
    """Mark a lane as done or failed when an agent ends.
    
    Args:
        state: Current FlowState
        agent_name: Name of the agent that finished
        session_id: Optional session identifier
        success: Whether the run completed successfully
        error: Exception if the run failed
        
    Returns:
        New FlowState with the lane marked as done/failed
    """
    new_state = state.copy()
    key = _get_session_key(session_id)
    
    if key not in new_state.lanes:
        # Lane doesn't exist, create a brief one for the end event
        ended_at = time.time()
        new_state.lanes[key] = FlowLaneState(
            agent_name=agent_name,
            model_name="unknown",
            session_id=session_id,
            status="done" if success else "failed",
            detail="finished" if success else str(error) if error else "failed",
            started_at=ended_at,  # Started and ended at same time
            ended_at=ended_at,
            duration=0.0,
            color=_get_agent_color(agent_name),
        )
        return new_state
    
    lane = new_state.lanes[key]
    ended_at = time.time()
    duration = ended_at - lane.started_at
    
    new_state.lanes[key] = FlowLaneState(
        agent_name=lane.agent_name,
        model_name=lane.model_name,
        session_id=lane.session_id,
        status="done" if success else "failed",
        detail="finished" if success else str(error) if error else "failed",
        started_at=lane.started_at,
        ended_at=ended_at,
        duration=duration,
        color=lane.color,
    )
    
    return new_state


def expire_lanes(
    state: FlowState,
    now: float,
    ttl: float = 10.0,
) -> FlowState:
    """Remove lanes that have been ended for longer than ttl seconds.
    
    Args:
        state: Current FlowState
        now: Current time.time() value
        ttl: Time-to-live in seconds for ended lanes (default 10.0)
        
    Returns:
        New FlowState with expired lanes removed
    """
    new_state = state.copy()
    
    keys_to_remove = []
    for key, lane in new_state.lanes.items():
        if lane.ended_at is not None:
            age_after_end = now - lane.ended_at
            if age_after_end > ttl:
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del new_state.lanes[key]
    
    return new_state
