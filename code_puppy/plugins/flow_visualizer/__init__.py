"""Flow Visualizer Plugin — Live pack status panel for code_puppy.

A pure-observer plugin that displays active agent lanes in a Rich panel.
Does not block or modify any events.

Exports:
    - FlowLaneState: Dataclass for individual lane state
    - FlowState: Class managing all lanes
    - render_flow_panel: Function to render the Rich panel
"""

from code_puppy.plugins.flow_visualizer.lanes import (
    FlowLaneState,
    FlowState,
    reduce_agent_start,
    reduce_stream_event,
    reduce_agent_end,
    expire_lanes,
    AGENT_COLORS,
)
from code_puppy.plugins.flow_visualizer.panel import render_flow_panel

__all__ = [
    "FlowLaneState",
    "FlowState",
    "reduce_agent_start",
    "reduce_stream_event",
    "reduce_agent_end",
    "expire_lanes",
    "AGENT_COLORS",
    "render_flow_panel",
]
