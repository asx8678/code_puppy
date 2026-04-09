"""Register callbacks for the Agent Memory plugin.

Phase 6: Configuration support and /memory slash command.
Adds config integration and CLI commands for managing agent memories.

Features:
- Config-based opt-in activation (enable_agent_memory, default False)
- /memory slash command with subcommands (show, clear, export, help)
- Rich formatted memory display
- JSON export for transparency

Usage:
    /memory              # Show help
    /memory show         # Display current memories
    /memory clear        # Wipe all memories for current agent
    /memory export       # Export memories as JSON

Config keys (puppy.cfg):
    enable_agent_memory = false         # OPT-IN, default off
    memory_debounce_seconds = 30        # Write debounce window
    memory_max_facts = 50               # Max facts per agent
    memory_token_budget = 500           # Token budget for injection
    memory_extraction_model = ""         # Optional model override
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from code_puppy.callbacks import register_callback

if TYPE_CHECKING:
    from code_puppy.plugins.agent_memory.storage import Fact

logger = logging.getLogger(__name__)

# Track if memory is enabled (set during startup)
_memory_enabled = False


def _on_startup() -> None:
    """Initialize the memory plugin on startup.

    Phase 6: Check config and register components only if enabled.
    Only activates when enable_agent_memory = true in puppy.cfg.
    """
    global _memory_enabled

    from code_puppy.plugins.agent_memory.config import is_memory_enabled

    _memory_enabled = is_memory_enabled()

    if _memory_enabled:
        logger.debug(
            "Agent Memory plugin activated (Phase 6: Config + CLI)"
        )
    else:
        logger.debug(
            "Agent Memory plugin loaded but disabled (enable_agent_memory=false)"
        )


def _get_current_agent_name() -> str | None:
    """Get the name of the currently active agent.

    Returns:
        Agent name string, or None if not available
    """
    try:
        from code_puppy.agents import get_current_agent

        agent = get_current_agent()
        return agent.name
    except Exception:
        return None


def _get_storage_for_current_agent():
    """Get FileMemoryStorage for the current agent.

    Returns:
        FileMemoryStorage instance, or None if no agent
    """
    from code_puppy.plugins.agent_memory.storage import FileMemoryStorage

    agent_name = _get_current_agent_name()
    if not agent_name:
        return None
    return FileMemoryStorage(agent_name)


def _memory_help() -> list[tuple[str, str]]:
    """Return help entries for the /memory command.

    Returns:
        List of (command, description) tuples for /help display
    """
    return [
        ("memory", "Manage agent memories 🧠"),
    ]


def _show_memories() -> None:
    """Display current memories for the active agent using Rich formatting."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from code_puppy.messaging import emit_error, emit_info, emit_warning

    agent_name = _get_current_agent_name()
    if not agent_name:
        emit_error("No active agent to show memories for")
        return

    storage = _get_storage_for_current_agent()
    if not storage:
        emit_error("Failed to initialize memory storage")
        return

    facts = storage.load()

    if not facts:
        emit_info(f"📭 No memories stored for [bold]{agent_name}[/bold]")
        return

    # Build rich table
    table = Table(
        title=f"🧠 Memories for {agent_name}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Fact", style="green", min_width=40)
    table.add_column("Confidence", style="cyan", width=12, justify="right")
    table.add_column("Created", style="dim", width=16)

    for idx, fact in enumerate(facts, 1):
        text = fact.get("text", "[invalid fact]")
        confidence = fact.get("confidence", 1.0)
        created_at = fact.get("created_at", "unknown")

        # Format confidence as percentage with color
        conf_str = f"{confidence * 100:.0f}%"
        if confidence >= 0.8:
            conf_style = "[green]"
        elif confidence >= 0.5:
            conf_style = "[yellow]"
        else:
            conf_style = "[red]"

        # Truncate created_at for display
        created_short = created_at[:16] if len(created_at) > 16 else created_at

        table.add_row(
            str(idx),
            text,
            f"{conf_style}{conf_str}[/]",
            created_short,
        )

    # Create summary panel
    total_facts = len(facts)
    avg_confidence = sum(f.get("confidence", 1.0) for f in facts) / total_facts

    summary = Text()
    summary.append(f"Total: {total_facts} facts\n", style="bold")
    summary.append(f"Avg confidence: {avg_confidence * 100:.1f}%", style="dim")

    panel = Panel(
        table,
        title=f"🧠 {agent_name} Memory Bank",
        subtitle=summary,
        border_style="blue",
    )

    console = Console()
    console.print(panel)


def _clear_memories() -> None:
    """Clear all memories for the current agent."""
    from code_puppy.messaging import emit_info, emit_success, emit_warning

    agent_name = _get_current_agent_name()
    if not agent_name:
        emit_warning("No active agent to clear memories for")
        return

    storage = _get_storage_for_current_agent()
    if not storage:
        emit_warning("Failed to initialize memory storage")
        return

    count = storage.fact_count()
    if count == 0:
        emit_info(f"📭 No memories to clear for [bold]{agent_name}[/bold]")
        return

    storage.clear()
    emit_success(
        f"🗑️  Cleared {count} memory{'ies' if count != 1 else 'y'} "
        f"for [bold]{agent_name}[/bold]"
    )


def _export_memories() -> None:
    """Export memories as JSON for transparency."""
    import uuid

    from rich.syntax import Syntax

    from code_puppy.messaging import emit_error, emit_info

    agent_name = _get_current_agent_name()
    if not agent_name:
        emit_error("No active agent to export memories for")
        return

    storage = _get_storage_for_current_agent()
    if not storage:
        emit_error("Failed to initialize memory storage")
        return

    facts = storage.load()

    export_data = {
        "agent_name": agent_name,
        "export_timestamp": None,  # Will be filled in
        "fact_count": len(facts),
        "facts": facts,
    }

    # Add timestamp
    from datetime import datetime, timezone

    export_data["export_timestamp"] = datetime.now(timezone.utc).isoformat()

    # Pretty print as JSON with syntax highlighting
    json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)

    emit_info(syntax, message_group=str(uuid.uuid4()))


def _show_memory_help() -> None:
    """Show detailed help for the /memory command."""
    from rich.panel import Panel
    from rich.text import Text

    from code_puppy.messaging import emit_info

    help_text = Text()
    help_text.append("🧠 Agent Memory Commands\n\n", style="bold magenta")

    help_text.append("/memory show", style="bold cyan")
    help_text.append("     Display all stored memories for current agent\n")
    help_text.append("         Shows fact text, confidence score, and creation date\n\n")

    help_text.append("/memory clear", style="bold cyan")
    help_text.append("    Wipe all memories for the current agent\n")
    help_text.append("         This cannot be undone!\n\n")

    help_text.append("/memory export", style="bold cyan")
    help_text.append("   Export memories as formatted JSON\n")
    help_text.append("         Useful for transparency and debugging\n\n")

    help_text.append("Configuration (puppy.cfg):\n", style="bold")
    help_text.append("  enable_agent_memory = false     # OPT-IN, default off\n", style="dim")
    help_text.append("  memory_debounce_seconds = 30    # Write debounce window\n", style="dim")
    help_text.append("  memory_max_facts = 50           # Max facts per agent\n", style="dim")
    help_text.append("  memory_token_budget = 500       # Token budget for injection\n", style="dim")

    panel = Panel(help_text, title="Memory Help", border_style="blue")
    emit_info(panel)


def _handle_memory_command(
    command: str, name: str
) -> Literal[True] | None:
    """Handle /memory slash commands.

    Args:
        command: Full command string (e.g., "/memory show")
        name: Subcommand name (e.g., "show", "clear", "export")

    Returns:
        True if command was handled, None if not a memory command
    """
    from code_puppy.messaging import emit_warning

    # Only handle 'memory' command
    if name != "memory":
        return None

    # Check if memory is enabled
    if not _memory_enabled:
        emit_warning(
            "🧠 Agent memory is disabled. Set enable_agent_memory=true in puppy.cfg to activate."
        )
        return True

    # Parse subcommand
    parts = command.split()
    subcommand = parts[1] if len(parts) > 1 else "help"

    if subcommand == "show":
        _show_memories()
    elif subcommand == "clear":
        _clear_memories()
    elif subcommand == "export":
        _export_memories()
    elif subcommand in ("help", "--help", "-h"):
        _show_memory_help()
    else:
        emit_warning(f"Unknown /memory subcommand: {subcommand}")
        _show_memory_help()

    return True


# Register callbacks
register_callback("startup", _on_startup)
register_callback("custom_command", _handle_memory_command)
register_callback("custom_command_help", _memory_help)
