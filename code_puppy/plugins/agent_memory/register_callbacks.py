"""Register callbacks for the Agent Memory plugin.

Phase 5: Full plugin integration - wires together storage, extraction,
signal detection, and prompt injection for end-to-end memory functionality.

Callbacks registered:
- startup: Initialize the memory system
- shutdown: Flush pending writes
- agent_run_end: Extract facts from conversations, apply signal confidence updates
- get_model_system_prompt: Inject relevant memories into system prompts
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from code_puppy.callbacks import register_callback
from code_puppy.run_context import get_current_run_context

from .config import load_config, MemoryConfig
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

    Loads configuration and initializes the extraction and detection systems.
    """
    global _config, _extractor, _detector

    _config = load_config()

    if not _config.enabled:
        logger.debug("Agent Memory plugin disabled by configuration")
        return

    # Initialize components
    _extractor = FactExtractor(min_confidence=_config.min_confidence)
    _detector = SignalDetector()

    logger.debug(
        "Agent Memory plugin initialized (Phase 5: Full Integration) - "
        f"max_facts={_config.max_facts}, token_budget={_config.token_budget}, "
        f"extraction_enabled={_config.extraction_enabled}"
    )


def _on_shutdown() -> None:
    """Flush pending memory writes on shutdown.

    Ensures all debounced facts are persisted before the application exits.
    """
    if _config and not _config.enabled:
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
    if _config and not _config.enabled:
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
    if _config and not _config.enabled:
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


# Register callbacks
register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("get_model_system_prompt", _on_load_prompt)

