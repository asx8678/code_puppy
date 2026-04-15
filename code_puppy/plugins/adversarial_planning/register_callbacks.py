"""Adversarial Planning Plugin - Evidence-first, execution-ready planning.

This plugin implements a multi-agent adversarial planning system that:
1. Gathers evidence from the workspace (Phase 0A)
2. Frames the problem with scope and constraints (Phase 0B)
3. Produces two materially different plans (Phase 1A, 1B)
4. Reviews both plans adversarially (Phase 2A, 2B)
5. Synthesizes the best elements (Phase 4)
6. Stress-tests with red team (Phase 5 - deep mode only)
7. Makes go/no-go decision (Phase 6)
8. Produces execution-ready change sets (Phase 7)

The plugin registers hooks for startup, tools, agents, and commands.
"""

import logging
from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _on_startup() -> None:
    """Called when the plugin is loaded.
    
    Logs plugin initialization and performs any setup needed.
    """
    logger.info("⚔️ Adversarial Planning plugin loaded")
    logger.debug("Plugin: adversarial_planning v0.1.0")


def _register_tools() -> list[dict]:
    """Register adversarial planning specific tools.
    
    Returns:
        List of tool registration dictionaries
    """
    from .tools import get_adversarial_tools
    return get_adversarial_tools()


def _register_agents() -> list[dict]:
    """Register adversarial planning specific agents.
    
    Returns:
        List of agent registration dictionaries
    """
    from .agents import get_adversarial_agents
    
    agents = get_adversarial_agents()
    logger.debug(f"Registering {len(agents)} adversarial planning agents")
    return agents


def _custom_help() -> list[tuple[str, str]]:
    """Provide custom command help entries.
    
    Returns:
        List of (command, description) tuples
    """
    return [
        ("/ap <task>", "Start adversarial planning (auto mode)"),
        ("/ap-standard <task>", "Start adversarial planning (standard mode)"),
        ("/ap-deep <task>", "Start adversarial planning (deep mode)"),
        ("/ap-status", "Show current adversarial plan status"),
        ("/ap-abort", "Abort running adversarial plan"),
    ]


def _handle_command(command: str, name: str) -> str | bool | None:
    """Handle adversarial planning slash commands.
    
    Args:
        command: The full command string
        name: The command name
        
    Returns:
        Response string, True if handled, or None if not recognized
    """
    from .commands import handle_command
    return handle_command(command, name)


def _load_prompt() -> str:
    """Load a brief adversarial planning reference into system prompt.

    Compressed from ~30 lines. Full docs available via /help.
    """
    return (
        "\n\n## ⚔️ Adversarial Planning"
        "\nFor complex tasks (migrations, security, architecture), use `/ap <task>`."
        " See `/ap-status` and `/help` for details."
    )
# =============================================================================
# Register all callbacks
# =============================================================================

# Register plugin lifecycle hooks
register_callback("startup", _on_startup)

# Register tool and agent hooks
register_callback("register_tools", _register_tools)
register_callback("register_agents", _register_agents)

# Register custom command hooks
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_command)

# Register prompt hook
register_callback("load_prompt", _load_prompt)

logger.debug("Adversarial Planning callbacks registered")
