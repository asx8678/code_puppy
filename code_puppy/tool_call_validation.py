"""Sanitize malformed tool-call parts from pydantic-ai message history.

Provider-side validation (e.g. OpenAI) rejects tool calls whose ``function.arguments``
field is not a JSON object.  Malformed history — caused by hallucinated tool names,
list-valued args, or corrupted session data — causes 400 errors that replay on every
attempt. This module removes or repairs such parts before they reach the provider.

Conservative rules:
  - Only **repair** string args that parse as valid JSON objects.
  - Never invent positional→keyword mappings for list args.
  - Unrecoverable tool-call parts are removed along with their matching tool-return
    parts (same ``tool_call_id``).
  - Empty messages after pruning are dropped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

logger = logging.getLogger(__name__)


def _normalize_args(args: Any) -> dict[str, Any] | str | None:
    """Try to produce a valid args value for a ToolCallPart.

    Returns a dict (preferred), a valid-JSON-object string, or ``None``
    if the args cannot be salvaged.
    """
    # Already a dict — the happy path.
    if isinstance(args, dict):
        return args

    # None / empty → treat as empty dict so the provider sees ``{}``.
    if args is None:
        return {}

    # String args: try to parse as JSON.
    if isinstance(args, str):
        stripped = args.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            # Not valid JSON at all.
            return None
        if isinstance(parsed, dict):
            return parsed
        # Valid JSON but not an object (e.g. a list, scalar).
        return None

    # Any other type (list, tuple, int, float, bool, …) — unrecoverable.
    return None


def sanitize_serialized_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize serialized message dicts before pydantic model validation.

    This is used for session history loaded from msgpack where malformed tool-call
    args may prevent ``ModelMessagesTypeAdapter.validate_python`` from succeeding.
    """
    if not messages:
        return messages

    bad_tool_call_ids: set[str] = set()

    # Phase 1: sanitize tool-call args and collect bad IDs.
    phase1: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            phase1.append(message)
            continue

        parts = message.get("parts")
        if not isinstance(parts, list):
            phase1.append(message)
            continue

        new_parts: list[Any] = []
        for part in parts:
            if not isinstance(part, dict) or part.get("part_kind") != "tool-call":
                new_parts.append(part)
                continue

            normalized = _normalize_args(part.get("args"))
            if normalized is None:
                tcid = part.get("tool_call_id")
                if isinstance(tcid, str) and tcid:
                    bad_tool_call_ids.add(tcid)
                continue

            part = dict(part)
            part["args"] = normalized
            new_parts.append(part)

        if new_parts:
            new_message = dict(message)
            new_message["parts"] = new_parts
            phase1.append(new_message)

    if not bad_tool_call_ids:
        return phase1

    # Phase 2: remove tool-return parts tied to bad call IDs.
    cleaned: list[dict[str, Any]] = []
    for message in phase1:
        if not isinstance(message, dict):
            cleaned.append(message)
            continue

        parts = message.get("parts")
        if not isinstance(parts, list):
            cleaned.append(message)
            continue

        new_parts = []
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("part_kind") == "tool-return"
                and part.get("tool_call_id") in bad_tool_call_ids
            ):
                continue
            new_parts.append(part)

        if new_parts:
            new_message = dict(message)
            new_message["parts"] = new_parts
            cleaned.append(new_message)

    return cleaned


def sanitize_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Return a cleaned copy of *messages* with malformed tool-call parts removed.

    Steps:
      1. Walk every message and inspect ``ToolCallPart`` args.
      2. If args can be normalized to a dict / valid-JSON-object string, fix in place.
      3. If args are unrecoverable, collect the ``tool_call_id`` for removal.
      4. Remove matching ``ToolReturnPart`` entries that reference a bad ``tool_call_id``.
      5. Drop messages that become empty after pruning.
    """
    if not messages:
        return messages

    # Phase 1: identify bad tool_call_ids and fix repairable args.
    bad_tool_call_ids: set[str] = set()
    fixed_count = 0

    # We'll rebuild parts lists; track which messages need rebuilding.
    rebuilt_messages: list[ModelMessage] = []

    for msg in messages:
        if not isinstance(msg, (ModelRequest, ModelResponse)):
            rebuilt_messages.append(msg)
            continue

        parts_changed = False
        new_parts: list[Any] = []

        for part in msg.parts:
            if not isinstance(part, ToolCallPart):
                new_parts.append(part)
                continue

            normalized = _normalize_args(part.args)

            if normalized is None:
                # Unrecoverable — mark for removal.
                bad_tool_call_ids.add(part.tool_call_id)
                parts_changed = True
                fixed_count += 1
                logger.debug(
                    "Removing malformed tool-call part: tool=%r args=%r id=%s",
                    part.tool_name,
                    part.args,
                    part.tool_call_id,
                )
                continue

            if normalized != part.args:
                # Args were repaired.
                part = replace(part, args=normalized)
                parts_changed = True
                fixed_count += 1
                logger.debug(
                    "Repaired tool-call args: tool=%r id=%s",
                    part.tool_name,
                    part.tool_call_id,
                )

            new_parts.append(part)

        if not parts_changed:
            rebuilt_messages.append(msg)
            continue

        # Rebuild the message with cleaned parts.
        if not new_parts:
            # Message is now empty — drop it entirely.
            logger.debug("Dropping empty message after sanitization")
            fixed_count += 1
            continue

        rebuilt_messages.append(replace(msg, parts=new_parts))

    if not bad_tool_call_ids:
        # No tool-return cleanup needed — but we may have repaired args.
        if fixed_count:
            logger.info(
                "tool_call_validation: repaired %d tool-call arg(s)", fixed_count
            )
        return rebuilt_messages

    # Phase 2: remove ToolReturnParts referencing bad tool_call_ids.
    final_messages: list[ModelMessage] = []
    for msg in rebuilt_messages:
        if not isinstance(msg, (ModelRequest, ModelResponse)):
            final_messages.append(msg)
            continue

        has_bad_returns = False
        new_parts: list[Any] = []
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and getattr(part, "tool_call_id", None) in bad_tool_call_ids
            ):
                has_bad_returns = True
                fixed_count += 1
                logger.debug(
                    "Removing orphaned tool-return: tool=%r id=%s",
                    part.tool_name,
                    part.tool_call_id,
                )
                continue
            new_parts.append(part)

        if not has_bad_returns:
            final_messages.append(msg)
            continue

        if not new_parts:
            # Message is now empty — drop it entirely.
            logger.debug("Dropping empty message after sanitization")
            continue

        # Rebuild with remaining parts.
        final_messages.append(replace(msg, parts=new_parts))

    if fixed_count:
        logger.info(
            "tool_call_validation: cleaned %d malformed part(s) from message history",
            fixed_count,
        )

    return final_messages
