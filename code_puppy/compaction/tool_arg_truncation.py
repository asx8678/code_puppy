"""Pre-summarization optimization: truncate large tool call args in older messages.

This is a cheap pass that often reclaims significant tokens without needing an
LLM call for full summarization. Targets write_file/edit_file tool calls where
the 'content' arg can be huge.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Sequence

# pydantic-ai imports
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
)

logger = logging.getLogger(__name__)

# Tool names whose args are commonly large (content, old_string, new_string)
_TARGET_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "replace_in_file",
    "create_file",
    "apply_patch",
})

# Keys within a tool call's args that should be truncated if oversized
_TARGET_KEYS: frozenset[str] = frozenset({
    "content",
    "new_content",
    "old_string",
    "new_string",
    "patch",
    "text",
})

DEFAULT_MAX_ARG_LENGTH = 500  # chars
DEFAULT_TRUNCATION_TEXT = " ...(argument truncated during compaction)"


def truncate_tool_arg(
    value: Any,
    max_length: int = DEFAULT_MAX_ARG_LENGTH,
    truncation_text: str = DEFAULT_TRUNCATION_TEXT,
) -> tuple[Any, bool]:
    """Truncate a single arg value if it's a string and too long.

    Args:
        value: The argument value to potentially truncate
        max_length: Maximum length before truncation
        truncation_text: Text to append after truncation

    Returns:
        (new_value, was_modified)
    """
    if not isinstance(value, str):
        return value, False
    if len(value) <= max_length:
        return value, False
    return value[:max_length] + truncation_text, True


def truncate_tool_call_args(
    tool_name: str,
    args: dict[str, Any],
    *,
    max_length: int = DEFAULT_MAX_ARG_LENGTH,
    truncation_text: str = DEFAULT_TRUNCATION_TEXT,
    target_tools: frozenset[str] = _TARGET_TOOLS,
    target_keys: frozenset[str] = _TARGET_KEYS,
) -> tuple[dict[str, Any], bool]:
    """Truncate target keys in a tool call's args if it's a target tool.

    Args:
        tool_name: Name of the tool being called
        args: The arguments dict for the tool call
        max_length: Maximum length before truncation
        truncation_text: Text to append after truncation
        target_tools: Set of tool names to target for truncation
        target_keys: Set of argument keys to target for truncation

    Returns:
        (new_args_dict, was_modified)
    """
    if tool_name not in target_tools:
        return args, False

    new_args: dict[str, Any] = {}
    any_modified = False
    for key, value in args.items():
        if key in target_keys:
            new_value, modified = truncate_tool_arg(value, max_length, truncation_text)
            new_args[key] = new_value
            any_modified = any_modified or modified
        else:
            new_args[key] = value
    return new_args, any_modified


def _truncate_message_tool_calls(
    msg: ModelMessage,
    max_length: int,
) -> ModelMessage:
    """Return a new message with tool call args truncated, or the original if unchanged.

    Handles pydantic-ai's ModelResponse (which contains ToolCallPart) and
    ModelRequest (which can contain ToolCallPart when being re-sent).

    Args:
        msg: The message to process
        max_length: Maximum characters per target argument

    Returns:
        New message with truncated args, or original if no changes needed
    """
    # Only ModelResponse and ModelRequest can contain tool calls
    if not isinstance(msg, (ModelResponse, ModelRequest)):
        return msg

    parts = getattr(msg, "parts", None)
    if not parts:
        return msg

    new_parts = []
    any_modified = False

    for part in parts:
        if isinstance(part, ToolCallPart):
            tool_name = getattr(part, "tool_name", "")
            args = getattr(part, "args", {}) or {}

            new_args, modified = truncate_tool_call_args(
                tool_name, args, max_length=max_length
            )

            if modified:
                # Create new ToolCallPart with truncated args, preserving all fields
                # Use dataclasses.replace to ensure all fields are preserved (code_puppy-lg9)
                new_part = dataclasses.replace(part, args=new_args)
                new_parts.append(new_part)
                any_modified = True
            else:
                new_parts.append(part)
        else:
            new_parts.append(part)

    if not any_modified:
        return msg

    # Create new message with truncated parts
    if isinstance(msg, ModelResponse):
        return ModelResponse(parts=new_parts)
    elif isinstance(msg, ModelRequest):
        return ModelRequest(parts=new_parts)

    # Fallback: should not reach here given isinstance check above
    return msg


def pretruncate_messages(
    messages: Sequence[ModelMessage],
    *,
    keep_recent: int = 10,
    max_length: int = DEFAULT_MAX_ARG_LENGTH,
) -> tuple[list[ModelMessage], int]:
    """Pre-truncate tool call args in messages older than the `keep_recent` most recent.

    This is an OPTIONAL cheap pass to run BEFORE full summarization. It tries to
    reclaim tokens without an LLM call.

    Args:
        messages: Full message history (pydantic-ai messages)
        keep_recent: Don't touch the last N messages (they're active context)
        max_length: Max characters allowed per target arg before truncation

    Returns:
        (modified_messages, truncation_count) — modified_messages is a new list;
        the original is not mutated.
    """
    if len(messages) <= keep_recent:
        return list(messages), 0

    # Messages older than the keep window are candidates for truncation
    if keep_recent > 0:
        older = list(messages[:-keep_recent])
        recent = list(messages[-keep_recent:])
    else:
        older = list(messages)
        recent = []

    truncation_count = 0
    modified_older: list[ModelMessage] = []

    for msg in older:
        new_msg = _truncate_message_tool_calls(msg, max_length)
        if new_msg is not msg:
            truncation_count += 1
        modified_older.append(new_msg)

    return modified_older + recent, truncation_count
