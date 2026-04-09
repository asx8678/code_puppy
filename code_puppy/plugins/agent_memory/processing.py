"""Signal processing and fact extraction handlers for agent memory.

Handles applying signal-based confidence updates and async fact extraction
from conversation messages. Includes signal safeguards (code-puppy-eed):
- Caps: Maximum number of preference signals per fact
- Decay: Time-based decay so old signals lose influence
- Rate limiting: Prevents rapid-fire preference signal injection
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .core import get_detector, get_extractor, get_config, _get_storage, _get_updater
from .messaging import _extract_user_messages
from .signal_safeguards import get_safeguard_manager
from .signals import SignalType

logger = logging.getLogger(__name__)


def _apply_signal_confidence_updates(
    agent_name: str, messages: list[dict[str, Any]], session_id: str | None
) -> int:
    """Apply confidence adjustments based on detected signals.

    Implements signal safeguards (code-puppy-eed):
    - Caps: Maximum number of preference signals per fact
    - Decay: Time-based decay so old signals lose influence
    - Rate limiting: Prevents rapid-fire preference signal injection

    Args:
        agent_name: Name of the agent
        messages: Conversation messages to analyze
        session_id: Optional session identifier

    Returns:
        Number of facts updated
    """
    detector = get_detector()
    if not detector:
        return 0

    updater = _get_updater(agent_name)
    storage = _get_storage(agent_name)

    # Get safeguard manager for this agent
    config = get_config()
    safeguard_manager = get_safeguard_manager(agent_name, config)

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
        signals = detector.analyze_message(text)

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
                        # Apply signal safeguards for preference signals
                        if signal.signal_type == SignalType.PREFERENCE:
                            allowed, reason = safeguard_manager.can_apply_signal(
                                fact_text, signal, session_id
                            )
                            if not allowed:
                                logger.debug(
                                    f"Blocked preference signal for fact '{fact_text[:50]}...': {reason}"
                                )
                                break  # Skip this signal

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

                            # Record signal application for safeguard tracking
                            if signal.signal_type == SignalType.PREFERENCE:
                                safeguard_manager.record_signal_applied(
                                    fact_text, signal, session_id
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
    extractor = get_extractor()
    config = get_config()

    if not extractor or not config:
        return 0

    if not config.extraction_enabled:
        return 0

    try:
        # Extract facts from conversation
        extracted = await extractor.extract_facts(messages)

        if not extracted:
            return 0

        # Queue facts for storage
        updater = _get_updater(agent_name)

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
