"""Register callbacks for the Agent Memory plugin.

Phases 5 & 6: Full plugin integration with config support and CLI.
Wires together storage, extraction, signal detection, prompt injection,
and CLI commands for end-to-end memory functionality.

Callbacks registered:
- startup: Initialize the memory system (with config-based opt-in)
- shutdown: Flush pending writes
- agent_run_end: Extract facts from conversations, apply signal confidence updates
- get_model_system_prompt: Inject relevant memories into system prompts
- custom_command: Handle /memory show/clear/export/help commands
- custom_command_help: Add /memory to help listing

Features:
- Config-based opt-in activation (enable_agent_memory, default False)
- /memory slash command with subcommands (show, clear, export, help)
- Rich formatted memory display
- JSON export for transparency
- Non-blocking async fact extraction with debounced storage

Config keys (puppy.cfg):
    enable_agent_memory = false         # OPT-IN, default off
    memory_debounce_seconds = 30        # Write debounce window
    memory_max_facts = 50               # Max facts per agent
    memory_token_budget = 500           # Token budget for injection
    memory_extraction_model = ""         # Optional model override
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING, Literal

from code_puppy.callbacks import register_callback
from code_puppy.run_context import get_current_run_context

from .config import load_config, MemoryConfig, is_memory_enabled
from .extraction import FactExtractor
from .signals import SignalDetector, SignalType
from .storage import FileMemoryStorage
from .updater import MemoryUpdater

if TYPE_CHECKING:
    from .storage import Fact

logger = logging.getLogger(__name__)

# Global state (initialized on startup)
_config: MemoryConfig | None = None
_extractor: FactExtractor | None = None
_detector: SignalDetector | None = None

# Per-agent memory components cache
_storage_cache: dict[str, FileMemoryStorage] = {}
_updater_cache: dict[str, MemoryUpdater] = {}

# Track if memory is enabled (set during startup - Phase 6)
_memory_enabled = False


def _get_storage(agent_name: str) -> FileMemoryStorage:
    """Get or create FileMemoryStorage for an agent."""
    if agent_name not in _storage_cache:
        _storage_cache[agent_name] = FileMemoryStorage(agent_name)
    return _storage_cache[agent_name]


def _get_updater(agent_name: str) -> MemoryUpdater:
    """Get or create MemoryUpdater for an agent."""
    if agent_name not in _updater_cache:
        config = _config or load_config()
        storage = _get_storage(agent_name)
        _updater_cache[agent_name] = MemoryUpdater(
            storage, debounce_ms=config.debounce_ms
        )
    return _updater_cache[agent_name]


def _on_startup() -> None:
    """Initialize the memory plugin on startup.

    Phases 5 & 6: Check config (opt-in), and if enabled,
    load configuration and initialize extraction and detection systems.
    """
    global _config, _extractor, _detector, _memory_enabled

    # Phase 6: Check if memory is enabled (OPT-IN)
    _memory_enabled = is_memory_enabled()

    _config = load_config()

    if not _config.enabled:
        logger.debug(
            "Agent Memory plugin loaded but disabled "
            "(set enable_agent_memory=true in puppy.cfg to activate)"
        )
        return

    # Phase 5: Initialize components
    _extractor = FactExtractor(min_confidence=_config.min_confidence)
    _detector = SignalDetector()

    logger.debug(
        "Agent Memory plugin initialized (Phases 5 & 6: Full Integration + Config/CLI) - "
        f"max_facts={_config.max_facts}, token_budget={_config.token_budget}, "
        f"extraction_enabled={_config.extraction_enabled}"
    )


def _on_shutdown() -> None:
    """Flush pending memory writes on shutdown.

    Ensures all debounced facts are persisted before the application exits.
    """
    if not _memory_enabled or (_config and not _config.enabled):
        return

    flushed_count = 0
    for agent_name, updater in _updater_cache.items():
        try:
            items = updater.flush()
            if items:
                flushed_count += len(items)
                logger.debug(f"Flushed {len(items)} pending facts for {agent_name}")
        except Exception as e:
            logger.warning(f"Failed to flush memory for {agent_name}: {e}")

    if flushed_count > 0:
        logger.info(f"Agent Memory: Flushed {flushed_count} pending facts on shutdown")


def _get_conversation_messages(
    agent_name: str, session_id: str | None, metadata: dict | None
) -> list[dict[str, Any]]:
    """Extract conversation messages from run context or metadata.

    Args:
        agent_name: Name of the agent
        session_id: Optional session identifier
        metadata: Optional metadata dict that might contain messages

    Returns:
        List of conversation message dicts with 'role' and 'content'
    """
    # Try to get messages from run context first
    ctx = get_current_run_context()
    if ctx and ctx.metadata:
        messages = ctx.metadata.get("message_history", [])
        if messages:
            return messages

    # Try metadata passed to callback
    if metadata:
        messages = metadata.get("message_history", [])
        if messages:
            return messages

    # Try to get from agent's message history if agent instance available
    try:
        from code_puppy.agents import get_current_agent

        agent = get_current_agent()
        if agent and agent.name == agent_name:
            history = agent.get_message_history()
            if history:
                return _normalize_messages(history)
    except Exception:
        pass

    return []


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


def _normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Normalize various message formats to standard dict format.

    Args:
        messages: Messages in various formats (dicts, pydantic models, etc.)

    Returns:
        List of normalized message dicts with 'role' and 'content'
    """
    normalized: list[dict[str, Any]] = []

    for msg in messages:
        if isinstance(msg, dict):
            # Already a dict, extract standard fields
            normalized.append({
                "role": msg.get("role", "unknown"),
                "content": msg.get("content", str(msg)),
            })
        else:
            # Try to extract from object attributes
            try:
                role = getattr(msg, "role", "unknown")
                content = getattr(msg, "content", str(msg))
                normalized.append({"role": role, "content": content})
            except Exception:
                # Fallback: treat as string content
                normalized.append({"role": "unknown", "content": str(msg)})

    return normalized


def _extract_user_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter messages to only include user messages.

    Args:
        messages: All conversation messages

    Returns:
        List of user messages only
    """
    return [m for m in messages if m.get("role") in ("user", "human", "input")]


def _apply_signal_confidence_updates(
    agent_name: str, messages: list[dict[str, Any]], session_id: str | None
) -> int:
    """Apply confidence adjustments based on detected signals.

    Args:
        agent_name: Name of the agent
        messages: Conversation messages to analyze
        session_id: Optional session identifier

    Returns:
        Number of facts updated
    """
    if not _detector:
        return 0

    updater = _get_updater(agent_name)
    storage = _get_storage(agent_name)

    updated_count = 0
    user_messages = _extract_user_messages(messages)

    # Load existing facts for matching
    existing_facts = storage.get_facts(min_confidence=0.0)
    fact_texts = {f.get("text", ""): f for f in existing_facts}

    for msg in user_messages:
        text = msg.get("content", "")
        if not text:
            continue

        # Detect signals in this message
        signals = _detector.analyze_message(text)

        for signal in signals:
            # Try to match signal with existing facts
            # Simple approach: check if any fact text appears in the message
            for fact_text, fact in fact_texts.items():
                if fact_text and len(fact_text) > 10:
                    # Check for semantic similarity (simple substring for now)
                    fact_lower = fact_text.lower()
                    msg_lower = text.lower()

                    # If fact appears in message and signal is relevant
                    if fact_lower in msg_lower or msg_lower in fact_lower:
                        # Apply confidence delta
                        current_conf = fact.get("confidence", 0.5)
                        new_conf = max(
                            0.0, min(1.0, current_conf + signal.confidence_delta)
                        )

                        if new_conf != current_conf:
                            storage.update_fact(fact_text, {
                                "confidence": new_conf,
                                "last_reinforced": signal.matched_text,
                            })
                            updated_count += 1
                            logger.debug(
                                f"Updated confidence for fact '{fact_text[:50]}...' "
                                f"({current_conf:.2f} -> {new_conf:.2f}) via {signal.signal_type.name}"
                            )

                        # If reinforcement signal, also update last_reinforced
                        if signal.signal_type == SignalType.REINFORCEMENT:
                            updater.reinforce_fact(fact_text, session_id)

                        break  # Only update one fact per signal

    return updated_count


async def _async_extract_and_store_facts(
    agent_name: str,
    messages: list[dict[str, Any]],
    session_id: str | None,
) -> int:
    """Async extraction and storage of facts.

    Args:
        agent_name: Name of the agent
        messages: Conversation messages to extract from
        session_id: Optional session identifier

    Returns:
        Number of facts extracted and queued
    """
    if not _extractor or not _config:
        return 0

    if not _config.extraction_enabled:
        return 0

    try:
        # Extract facts from conversation
        extracted = await _extractor.extract_facts(messages)

        if not extracted:
            return 0

        # Queue facts for storage
        updater = _get_updater(agent_name)
        from datetime import datetime, timezone

        for fact in extracted:
            fact_dict: dict[str, Any] = {
                "text": fact.text,
                "confidence": fact.confidence,
                "source_session": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            updater.add_fact(fact_dict)

        logger.debug(
            f"Queued {len(extracted)} facts for extraction from {agent_name} session"
        )
        return len(extracted)

    except Exception as e:
        logger.error(f"Fact extraction failed for {agent_name}: {e}")
        return 0


def _schedule_fact_extraction(
    agent_name: str,
    messages: list[dict[str, Any]],
    session_id: str | None,
) -> None:
    """Schedule async fact extraction (non-blocking).

    Args:
        agent_name: Name of the agent
        messages: Conversation messages
        session_id: Optional session identifier
    """
    try:
        # Try to get existing event loop
        loop = asyncio.get_running_loop()
        # Create task for async extraction
        loop.create_task(
            _async_extract_and_store_facts(agent_name, messages, session_id)
        )
    except RuntimeError:
        # No running loop - use async_utils to run in thread pool
        try:
            from code_puppy.async_utils import run_async_sync

            run_async_sync(
                _async_extract_and_store_facts(agent_name, messages, session_id)
            )
        except Exception as e:
            logger.debug(f"Could not schedule fact extraction: {e}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
    **kwargs: Any,
) -> None:
    """Handle agent run end - extract facts and apply signal confidence updates.

    This callback:
    1. Gets conversation messages from the run context
    2. Runs SignalDetector on user messages to detect corrections/reinforcements
    3. Applies signal confidence deltas to existing facts in storage
    4. Schedules async fact extraction via FactExtractor (non-blocking)
    5. Queues extracted facts via MemoryUpdater (debounced)

    Args:
        agent_name: Name of the agent that finished
        model_name: Name of the model used
        session_id: Optional session identifier
        success: Whether the run completed successfully
        error: Exception if the run failed
        response_text: Final response from the agent
        metadata: Additional context data
    """
    if not _memory_enabled or (_config and not _config.enabled):
        return

    # Only process successful runs with actual conversation
    if not success:
        return

    try:
        # Get conversation messages
        messages = _get_conversation_messages(agent_name, session_id, metadata)

        if not messages:
            logger.debug(f"No conversation messages found for {agent_name}")
            return

        # Step 1: Apply signal-based confidence updates
        signal_updates = _apply_signal_confidence_updates(
            agent_name, messages, session_id
        )

        if signal_updates > 0:
            logger.debug(f"Applied {signal_updates} signal-based confidence updates")

        # Step 2: Schedule async fact extraction (non-blocking)
        _schedule_fact_extraction(agent_name, messages, session_id)

    except Exception as e:
        # Fail gracefully - memory should never break agent operation
        logger.debug(f"Memory processing failed for {agent_name}: {e}")


def _format_memory_section(
    facts: list[Fact],
    max_facts: int,
    token_budget: int,
) -> str | None:
    """Format facts into a memory section for prompt injection.

    Args:
        facts: List of facts to format
        max_facts: Maximum number of facts to include
        token_budget: Maximum tokens for the section

    Returns:
        Formatted memory section string, or None if no facts fit
    """
    if not facts:
        return None

    # Sort by confidence (highest first)
    sorted_facts = sorted(
        facts,
        key=lambda f: f.get("confidence", 0.0),
        reverse=True,
    )

    # Rough token estimation: ~4 chars per token
    chars_per_token = 4
    max_chars = token_budget * chars_per_token

    lines = ["## Memory"]
    current_chars = len(lines[0]) + 1  # +1 for newline

    for fact in sorted_facts[:max_facts]:
        text = fact.get("text", "").strip()
        confidence = fact.get("confidence", 0.5)

        if not text:
            continue

        line = f"- {text} (confidence: {confidence:.1f})"
        line_chars = len(line) + 1  # +1 for newline

        if current_chars + line_chars > max_chars:
            break

        lines.append(line)
        current_chars += line_chars

    if len(lines) == 1:  # Only header, no facts
        return None

    return "\n".join(lines)


def _on_load_prompt(
    model_name: str,
    default_system_prompt: str,
    user_prompt: str,
) -> dict[str, Any] | None:
    """Inject relevant memories into the system prompt.

    Loads top facts for the current agent (sorted by confidence) and
    injects them into the system prompt within the configured token budget.

    Args:
        model_name: Name of the model being used
        default_system_prompt: The default system prompt
        user_prompt: The user's prompt

    Returns:
        Dict with enhanced prompt if memories found, None otherwise
    """
    if not _memory_enabled or (_config and not _config.enabled):
        return None

    try:
        # Get current agent name from context
        agent_name = None
        ctx = get_current_run_context()
        if ctx:
            agent_name = ctx.component_name

        if not agent_name:
            # Try to get from agent manager
            try:
                from code_puppy.agents import get_current_agent

                agent = get_current_agent()
                if agent:
                    agent_name = agent.name
            except Exception:
                pass

        if not agent_name:
            return None

        # Load configuration
        config = _config or load_config()

        # Get facts for this agent
        storage = _get_storage(agent_name)
        facts = storage.get_facts(min_confidence=config.min_confidence)

        if not facts:
            return None

        # Format memory section
        memory_section = _format_memory_section(
            facts,
            max_facts=config.max_facts,
            token_budget=config.token_budget,
        )

        if not memory_section:
            return None

        # Inject into prompt
        enhanced_prompt = f"{default_system_prompt}\n\n{memory_section}"

        return {
            "instructions": enhanced_prompt,
            "user_prompt": user_prompt,
            "handled": False,  # Allow other plugins to also modify
        }

    except Exception as e:
        logger.debug(f"Memory prompt injection failed: {e}")
        return None


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
register_callback("shutdown", _on_shutdown)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("get_model_system_prompt", _on_load_prompt)
register_callback("custom_command", _handle_memory_command)
register_callback("custom_command_help", _memory_help)
