"""Flow Visualizer — Rich panel renderer.

This module handles rendering the flow state as a Rich panel.
"""

import os
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from code_puppy.plugins.flow_visualizer.lanes import FlowState, FlowLaneState


def _is_terminal_color_supported() -> bool:
    """Check if terminal supports ANSI colors."""
    # Disable colors if NO_COLOR is set (respect user preference)
    if os.environ.get("NO_COLOR"):
        return False
    # Check if output is a tty
    if not sys.stdout.isatty():
        return False
    # Check TERM environment variable
    term = os.environ.get("TERM", "")
    if term == "dumb":
        return False
    # Assume color support for most modern terminals
    return True


def _format_duration(duration: float | None) -> str:
    """Format duration as 'X.Ys' for <60s, 'Xm Ys' for >=60s."""
    if duration is None:
        return "-"
    
    if duration < 60:
        return f"{duration:.1f}s"
    
    minutes = int(duration // 60)
    seconds = duration % 60
    return f"{minutes}m {seconds:.0f}s"


def _get_status_indicator(status: str) -> str:
    """Get compact status indicator."""
    return {
        "running": "◐",
        "done": "✓",
        "failed": "✗",
    }.get(status, "?")


def _truncate_detail(detail: str, max_length: int = 28) -> str:
    """Truncate detail string to max_length, adding ellipsis if needed."""
    if len(detail) <= max_length:
        return detail
    return detail[: max_length - 3] + "..."


def _render_lane_row(lane: FlowLaneState) -> tuple[str, str, str, str]:
    """Render a single lane as table row components.
    
    Returns:
        Tuple of (agent_name, status, detail, duration) strings
    """
    # Agent name (compact)
    name_str = lane.agent_name[:18]
    
    # Compact status indicator
    indicator = _get_status_indicator(lane.status)
    status_str = f"{indicator} {lane.status[:7]}"  # truncate 'running' to 'running'
    
    # Detail (current activity)
    detail_str = _truncate_detail(lane.detail) if lane.detail else "-"
    
    # Duration
    if lane.status == "running":
        current_duration = time.time() - lane.started_at
        duration_str = _format_duration(current_duration)
    elif lane.duration is not None:
        duration_str = _format_duration(lane.duration)
    else:
        duration_str = "-"
    
    return name_str, status_str, detail_str, duration_str


def render_flow_panel(flow_state: FlowState) -> str | None:
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
    
    # Check color support
    color_supported = _is_terminal_color_supported()
    
    # Sort lanes: running first, then by start time
    sorted_lanes = sorted(
        flow_state.lanes.values(),
        key=lambda lane: (0 if lane.status == "running" else 1, lane.started_at),
    )
    
    # Build compact table
    table = Table(
        show_header=False,
        box=None,
        padding=(0, 1),
        collapse_padding=True,
    )
    
    table.add_column("agent", style="bold", width=16)
    table.add_column("status", width=10)
    table.add_column("detail", style="italic", min_width=20, max_width=28)
    table.add_column("time", justify="right", width=7)
    
    for lane in sorted_lanes:
        name, status, detail, duration = _render_lane_row(lane)
        
        # Apply color styling
        if color_supported:
            name_text = Text(name, style=lane.color)
            status_style = {"running": "yellow", "done": "green", "failed": "red"}.get(lane.status, "white")
            status_text = Text(status, style=status_style)
        else:
            # No color fallback
            name_text = Text(name)
            status_text = Text(status)
        
        table.add_row(name_text, status_text, detail, duration)
    
    # Create panel
    title = "🐕 Pack Status"
    panel = Panel(
        table,
        title=title,
        title_align="left",
        border_style="blue",
        padding=(0, 1),
    )
    
    # Render to plain string with ANSI codes
    if color_supported:
        # Use a console that outputs ANSI codes properly
        console = Console(
            width=78,
            force_terminal=True,
            color_system="standard",
            legacy_windows=False,
        )
    else:
        # No color mode
        console = Console(width=78, force_terminal=False, no_color=True)
    
    with console.capture() as capture:
        console.print(panel)
    
    return capture.get()
