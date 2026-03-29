"""Bridge to Rust extension module with Python fallback.

This is the ONLY place where pydantic-ai message objects are converted to
the dict format that Rust expects. The Rust module never touches pydantic-ai
objects directly.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from _code_puppy_core import (
        ProcessResult,
        PruneResult,
        SplitResult,
        deserialize_session,
        process_messages_batch,
        prune_and_filter,
        serialize_session,
        serialize_session_incremental,
        split_for_summarization,
        truncation_indices,
    )

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

    # Provide type stubs so downstream code can reference them
    ProcessResult = None  # type: ignore[assignment,misc]
    PruneResult = None  # type: ignore[assignment,misc]
    SplitResult = None  # type: ignore[assignment,misc]
    process_messages_batch = None  # type: ignore[assignment]
    prune_and_filter = None  # type: ignore[assignment]
    truncation_indices = None  # type: ignore[assignment]
    split_for_summarization = None  # type: ignore[assignment]
    serialize_session = None  # type: ignore[assignment]
    deserialize_session = None  # type: ignore[assignment]
    serialize_session_incremental = None  # type: ignore[assignment]


def serialize_message_for_rust(message: Any) -> dict:
    """Convert a pydantic-ai ModelMessage to the dict format expected by Rust.

    This is the ONLY place where pydantic-ai message objects are converted
    to dicts. The Rust module never touches pydantic-ai objects directly.
    """
    from pydantic_ai.messages import ModelRequest

    kind = "request" if isinstance(message, ModelRequest) else "response"
    role = getattr(message, "role", None)
    instructions = getattr(message, "instructions", None)

    parts: list[dict] = []
    for part in getattr(message, "parts", []):
        part_dict: dict[str, Any] = {
            "part_kind": getattr(part, "part_kind", str(type(part).__name__)),
            "content": None,
            "content_json": None,
            "tool_call_id": getattr(part, "tool_call_id", None),
            "tool_name": getattr(part, "tool_name", None),
            "args": str(getattr(part, "args", "")) if hasattr(part, "args") else None,
        }

        content = getattr(part, "content", None)
        if content is None:
            pass
        elif isinstance(content, str):
            part_dict["content"] = content
        elif isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                # Skip BinaryContent for token estimation
            part_dict["content"] = "\n".join(text_parts) if text_parts else None
        else:
            # Dicts, Pydantic models, other — serialize to JSON string
            try:
                if hasattr(content, "model_dump"):
                    part_dict["content_json"] = json.dumps(
                        content.model_dump(), sort_keys=True
                    )
                elif isinstance(content, dict):
                    part_dict["content_json"] = json.dumps(content, sort_keys=True)
                else:
                    part_dict["content"] = repr(content)
            except (TypeError, ValueError):
                part_dict["content"] = repr(content)

        parts.append(part_dict)

    return {
        "kind": kind,
        "role": role,
        "instructions": instructions,
        "parts": parts,
    }


def serialize_messages_for_rust(messages: list) -> list[dict]:
    """Batch convert messages for Rust consumption."""
    return [serialize_message_for_rust(m) for m in messages]
