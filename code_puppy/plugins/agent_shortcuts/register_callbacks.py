"""Agent shortcuts plugin - provides /plan and /leader slash commands.

This plugin adds convenient shortcuts for quickly switching to commonly used agents:
- /plan → switches to planning-agent
- /leader → switches to pack-leader
"""

from __future__ import annotations

import uuid

from code_puppy.callbacks import register_callback
from code_puppy.config import finalize_autosave_session, get_pack_agents_enabled
from code_puppy.messaging import emit_error, emit_info, emit_success, emit_warning

# Agent names for shortcuts
PLANNING_AGENT = "planning-agent"
PACK_LEADER_AGENT = "pack-leader"


def _get_agents_functions():
    """Lazy import agents functions to avoid circular imports and allow patching."""
    from code_puppy.agents import (
        get_available_agents,
        get_current_agent,
        set_current_agent,
    )
    from code_puppy.agents.base_agent import reload_code_generation_agent

    return get_available_agents, get_current_agent, set_current_agent, reload_code_generation_agent


def _get_custom_help() -> list[tuple[str, str]]:
    """Return help entries for custom commands."""
    return [
        ("plan", "Switch to the planning agent"),
        ("leader", "Switch to the pack-leader agent (requires pack agents enabled)"),
    ]


def _switch_to_agent(agent_name: str, group_id: str) -> bool:
    """Common agent switching logic.

    Args:
        agent_name: Name of the agent to switch to
        group_id: Message group ID for consistent output

    Returns:
        True if handled (success or handled error)
    """
    get_available_agents, get_current_agent, set_current_agent, reload_code_generation_agent = _get_agents_functions()

    available_agents = get_available_agents()

    # Check if agent is available
    if agent_name not in available_agents:
        emit_error(f"Agent '{agent_name}' not found", message_group=group_id)
        emit_warning(
            f"Available agents: {', '.join(available_agents.keys())}",
            message_group=group_id,
        )
        return True

    current_agent = get_current_agent()
    if current_agent.name == agent_name:
        emit_info(
            f"Already using agent: {current_agent.display_name}",
            message_group=group_id,
        )
        return True

    # Switch to the agent
    new_session_id = finalize_autosave_session()
    if not set_current_agent(agent_name):
        emit_warning(
            "Agent switch failed after autosave rotation. Your context was preserved.",
            message_group=group_id,
        )
        return True

    # Reload the agent
    reload_code_generation_agent()

    new_agent = get_current_agent()
    emit_success(
        f"Switched to agent: {new_agent.display_name}",
        message_group=group_id,
    )
    emit_info(f"{new_agent.description}", message_group=group_id)
    emit_info(
        f"Auto-save session rotated to: {new_session_id}",
        message_group=group_id,
    )
    return True


def _handle_plan_command() -> bool:
    """Handle /plan command - switch to planning-agent."""
    group_id = str(uuid.uuid4())
    return _switch_to_agent(PLANNING_AGENT, group_id)


def _handle_leader_command() -> bool:
    """Handle /leader command - switch to pack-leader."""
    group_id = str(uuid.uuid4())

    # Check if pack agents are enabled
    if not get_pack_agents_enabled():
        emit_error(
            "Pack agents are disabled. Enable them with /config set enable_pack_agents true",
            message_group=group_id,
        )
        return True

    return _switch_to_agent(PACK_LEADER_AGENT, group_id)


def _handle_custom_command(command: str, name: str) -> bool | None:
    """Handle custom slash commands.

    Args:
        command: The full command string
        name: The command name (without the /)

    Returns:
        True if handled, None if not our command
    """
    if not name:
        return None

    if name == "plan":
        return _handle_plan_command()

    if name == "leader":
        return _handle_leader_command()

    return None


# Register callbacks
register_callback("custom_command_help", _get_custom_help)
register_callback("custom_command", _handle_custom_command)
