"""Flow Visualizer Plugin — Callback Registration.

Registers the flow visualizer with code_puppy's callback hooks:
- startup: Emit info that plugin loaded
- agent_run_start: Track agent start
- stream_event: Update lane detail (throttled)
- agent_run_end: Mark lane done/failed
- custom_command: Handle /flow on|off|status
- custom_command_help: Provide help text
"""

import logging
import sys
import time
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info, emit_success, emit_warning
from code_puppy.plugins.flow_visualizer.lanes import (
    FlowState,
    reduce_agent_start,
    reduce_stream_event,
    reduce_agent_end,
    expire_lanes,
)
from code_puppy.plugins.flow_visualizer.panel import render_flow_panel

logger = logging.getLogger(__name__)

# Module-level FlowState instance
_flow_state = FlowState()

# Rendering state for terminal management
_last_render_lines = 0
_last_render_time = 0.0
_RENDER_THROTTLE_SEC = 0.5  # Min seconds between renders


def _clear_previous_output(lines: int) -> None:
    """Clear previous panel output by moving cursor up and clearing lines."""
    if lines <= 0 or not sys.stdout.isatty():
        return
    # Move up N lines and clear from cursor to end
    sys.stdout.write(f"\033[{lines}A\033[J")
    sys.stdout.flush()


def _safe_render_panel() -> None:
    """Safely render the flow panel with terminal-aware clearing."""
    global _flow_state, _last_render_lines, _last_render_time
    
    if not _flow_state.enabled:
        return
    
    try:
        output = render_flow_panel(_flow_state)
        if not output:
            return
        
        # Count lines in output for next clear
        lines = output.count("\n") + 1
        
        # Clear previous output if we rendered before
        if _last_render_lines > 0:
            _clear_previous_output(_last_render_lines)
        
        # Write new output
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        
        _last_render_lines = lines
        _last_render_time = time.time()
    except Exception as e:
        # Never crash the host app
        logger.debug(f"Flow visualizer render error: {e}")


def _on_startup():
    """Emit info that the flow visualizer loaded."""
    emit_info("🌊 Flow visualizer loaded (use /flow on|off|status)")


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    **kwargs,
) -> None:
    """Track agent start — create a new lane."""
    global _flow_state, _last_render_lines
    
    try:
        # Clear any previous output first
        if _last_render_lines > 0:
            _clear_previous_output(_last_render_lines)
            _last_render_lines = 0
        
        _flow_state = reduce_agent_start(_flow_state, agent_name, model_name, session_id)
        
        # Render initial state
        if _flow_state.enabled:
            _safe_render_panel()
    except Exception as e:
        logger.debug(f"Flow visualizer error in agent_run_start: {e}")


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
    **kwargs,
) -> None:
    """Update lane detail based on stream event (throttled rendering)."""
    global _flow_state, _last_render_time
    
    try:
        _flow_state = reduce_stream_event(
            _flow_state, event_type, event_data, agent_session_id
        )
        
        # Throttled render updates (max once per RENDER_THROTTLE_SEC)
        if _flow_state.enabled:
            now = time.time()
            if now - _last_render_time >= _RENDER_THROTTLE_SEC:
                _safe_render_panel()
            
            # Expire old lanes periodically
            _flow_state = expire_lanes(_flow_state, now, ttl=10.0)
    except Exception as e:
        logger.debug(f"Flow visualizer error in stream_event: {e}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
    **kwargs,
) -> None:
    """Mark lane as done or failed when agent ends."""
    global _flow_state
    
    try:
        _flow_state = reduce_agent_end(_flow_state, agent_name, session_id, success, error)
        
        # Render final state
        if _flow_state.enabled:
            _safe_render_panel()
    except Exception as e:
        logger.debug(f"Flow visualizer error in agent_run_end: {e}")


def _custom_help():
    """Provide help for the /flow command."""
    return [
        ("flow", "Flow state visualizer: /flow on|off|status"),
    ]


def _handle_flow_command(command: str, name: str) -> Any:
    """Handle the /flow slash command.
    
    Usage:
        /flow on      → Enable flow visualizer
        /flow off     → Disable flow visualizer
        /flow status  → Show current flow panel
    """
    global _flow_state
    
    if name != "flow":
        return None
    
    parts = command.strip().split()
    subcommand = parts[1] if len(parts) > 1 else "status"
    
    if subcommand == "on":
        _flow_state.enabled = True
        emit_success("🌊 Flow visualizer enabled")
        # Show current state
        _safe_render_panel()
        return True
    
    if subcommand == "off":
        _flow_state.enabled = False
        emit_info("🌊 Flow visualizer disabled")
        return True
    
    if subcommand == "status":
        if not _flow_state.enabled:
            emit_info("🌊 Flow visualizer is disabled (use /flow on to enable)")
            return True
        
        if not _flow_state.lanes:
            emit_info("🌊 No active agent lanes")
            return True
        
        # Render the panel
        _safe_render_panel()
        return True
    
    # Unknown subcommand - show usage
    emit_warning(f"Unknown /flow command: {subcommand}")
    emit_info("Usage: /flow on | /flow off | /flow status")
    return True


# Register all callbacks at module scope
register_callback("startup", _on_startup)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("stream_event", _on_stream_event)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_flow_command)
