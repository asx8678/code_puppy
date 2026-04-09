"""Flow Visualizer — Rich panel renderer.

This module handles rendering the flow state as a Rich panel.
"""

import os
import time
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from code_puppy.plugins.flow_visualizer.lanes import FlowState, FlowLaneState


def _supports_unicode() -> bool:
    """Check if the terminal supports unicode characters."""
    # Check environment variables commonly set when unicode isn't supported
    if os.environ.get("LANG", "").lower().endswith("ascii"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    # Assume unicode support in most modern terminals
    return True


def _format_duration(duration: Optional[float]) -> str:
    """Format duration as 'X.Ys' for <60s, 'Xm Ys' for >=60s."""
    if duration is None:
        return "—"
    
    if duration < 60:
        return f"{duration:.1f}s"
    
    minutes = int(duration // 60)
    seconds = duration % 60
    return f"{minutes}m {seconds:.0f}s"


def _get_status_emoji(status: str, unicode: bool = True) -> str:
    """Get status indicator (emoji or ASCII fallback)."""
    if unicode:
        return {
            "running": "🔄",
            "done": "✅",
            "failed": "❌",
        }.get(status, "❓")
    else:
        return {
            "running": "[RUN]",
            "done": "[OK]",
            "failed": "[ERR]",
        }.get(status, "[?]")


def _truncate_detail(detail: str, max_length: int = 30) -> str:
    """Truncate detail string to max_length, adding ellipsis if needed."""
    if len(detail) <= max_length:
        return detail
    return detail[: max_length - 3] + "..."


def _render_lane_row(lane: FlowLaneState, unicode: bool = True) -> tuple[str, str, str, str]:
    """Render a single lane as table row components.
    
    Returns:
        Tuple of (agent_name, status, detail, duration) strings
    """
    # Agent name (left-aligned, fixed width conceptually)
    name_str = lane.agent_name[:20]  # Truncate long names
    
    # Status with emoji/text indicator
    status_indicator = _get_status_emoji(lane.status, unicode)
    if unicode:
        status_str = f"[{status_indicator} {lane.status}]"
    else:
        status_str = f"{status_indicator} {lane.status}"
    
    # Detail (current activity)
    detail_str = _truncate_detail(lane.detail) if lane.detail else "—"
    
    # Duration (calculated for running lanes, stored for ended ones)
    if lane.status == "running":
        current_duration = time.time() - lane.started_at
        duration_str = _format_duration(current_duration)
    elif lane.duration is not None:
        duration_str = _format_duration(lane.duration)
    else:
        duration_str = "—"
    
    return name_str, status_str, detail_str, duration_str


def render_flow_panel(flow_state: FlowState) -> Optional[str]:
    """Render the flow state as a Rich panel.
    
    Returns a Rich-renderable string, or None if no active lanes.
    
    Args:
        flow_state: Current FlowState containing all lanes
        
    Returns:
        Rich panel as string, or None if no lanes or disabled
    """
    if not flow_state.enabled:
        return None
    
    if not flow_state.lanes:
        return None
    
    # Check unicode support
    unicode = _supports_unicode()
    
    # Create a table for the lanes
    table = Table(
        show_header=False,
        box=None,
        padding=(0, 1),
        collapse_padding=True,
    )
    
    # Add columns: agent name, status, detail, duration
    table.add_column("agent", style="bold", width=18)
    table.add_column("status", width=15)
    table.add_column("detail", style="italic", min_width=20)
    table.add_column("duration", justify="right", width=8)
    
    # Sort lanes: running first, then by start time
    sorted_lanes = sorted(
        flow_state.lanes.values(),
        key=lambda l: (0 if l.status == "running" else 1, l.started_at),
    )
    
    # Add each lane as a row
    for lane in sorted_lanes:
        name, status, detail, duration = _render_lane_row(lane, unicode)
        
        # Apply color to agent name
        name_text = Text(name, style=lane.color)
        
        # Status with appropriate styling
        if lane.status == "running":
            status_style = "yellow"
        elif lane.status == "done":
            status_style = "green"
        else:  # failed
            status_style = "red"
        status_text = Text(status, style=status_style)
        
        table.add_row(name_text, status_text, detail, duration)
    
    # Create the panel
    title = "🐕 Pack Status" if unicode else "[ Pack Status ]"
    panel = Panel(
        table,
        title=title,
        title_align="left",
        border_style="blue",
        padding=(0, 1),
    )
    
    # Render to string using a console
    console = Console(width=80, force_terminal=True)
    with console.capture() as capture:
        console.print(panel)
    
    return capture.get()
