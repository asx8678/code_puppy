"""Register callbacks for the Remember Last Agent plugin.

Hooks into agent_reload to save the last selected agent.
"""

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

from .storage import set_last_agent, clear_last_agent


def _on_agent_reload(agent_id: str, agent_name: str) -> None:
    """Save the agent name whenever an agent is selected.
    
    Args:
        agent_id: The unique ID of the agent instance.
        agent_name: The name of the agent (e.g., "code-puppy").
    """
    if agent_name:
        set_last_agent(agent_name)


def _handle_last_agent_command(command: str, name: str) -> bool | None:
    """Handle /last-agent command.
    
    Commands:
        /last-agent clear  - Clear the saved last agent
        /last-agent show   - Show the saved last agent
    
    Returns:
        True if handled, None otherwise.
    """
    if name != "last-agent":
        return None
    
    from .storage import get_last_agent
    
    parts = command.split()[1:]  # drop "/last-agent" itself
    subcmd = parts[0] if parts else "show"
    
    if subcmd == "clear":
        clear_last_agent()
        emit_info("🐾 Last agent cleared. Will use default on next startup.")
        return True
    elif subcmd == "show":
        last_agent = get_last_agent()
        if last_agent:
            emit_info(f"🐾 Last selected agent: {last_agent}")
        else:
            emit_info("🐾 No last agent saved. Will use default on startup.")
        return True
    else:
        emit_info(f"Unknown subcommand: {subcmd}")
        emit_info("Usage: /last-agent [show|clear]")
        return True


def _custom_help() -> list[tuple[str, str]]:
    """Return help entry for /last-agent command."""
    return [("last-agent", "Show or clear the last selected agent")]


# Register callbacks
register_callback("agent_reload", _on_agent_reload)
register_callback("custom_command", _handle_last_agent_command)
register_callback("custom_command_help", _custom_help)
