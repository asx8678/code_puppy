"""Bridge to Rust extension module with Python fallback.

This is the ONLY place where pydantic-ai message objects are converted to
the dict format that Rust expects. The Rust module never touches pydantic-ai
objects directly.
"""

import json
from typing import Any

try:
    from pydantic_ai.messages import ModelRequest
except ImportError:
    ModelRequest = None  # type: ignore[misc,assignment]

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


# --- Hashline acceleration --------------------------------------------------
try:
    from _code_puppy_core import (
        compute_line_hash,
        format_hashlines,
        strip_hashline_prefixes,
        validate_hashline_anchor,
    )

    HASHLINE_RUST_AVAILABLE = True
except ImportError:
    HASHLINE_RUST_AVAILABLE = False
    compute_line_hash = None  # type: ignore[assignment]
    format_hashlines = None  # type: ignore[assignment]
    strip_hashline_prefixes = None  # type: ignore[assignment]
    validate_hashline_anchor = None  # type: ignore[assignment]
# ---------------------------------------------------------------------------


# --- Fast Puppy toggle ---------------------------------------------------
# When True (default), Rust acceleration is used at runtime if the module
# is installed.  /fast_puppy disable flips this to False so every call
# falls through to the Python path — no restart needed.
_rust_user_enabled: bool = True


def is_rust_enabled() -> bool:
    """Check if Rust acceleration is both available AND enabled by the user."""
    return RUST_AVAILABLE and _rust_user_enabled


def set_rust_enabled(enabled: bool) -> None:
    """Toggle Rust acceleration on or off at runtime."""
    global _rust_user_enabled
    _rust_user_enabled = enabled


def get_rust_status() -> dict:
    """Return diagnostic info for /fast_puppy status."""
    return {
        "installed": RUST_AVAILABLE,
        "enabled": _rust_user_enabled,
        "active": is_rust_enabled(),
    }


# --------------------------------------------------------------------------


def serialize_message_for_rust(message: Any) -> dict:
    """Convert a pydantic-ai ModelMessage to the dict format expected by Rust.

    This is the ONLY place where pydantic-ai message objects are converted
    to dicts. The Rust module never touches pydantic-ai objects directly.

    OPTIMIZED: Reduced getattr() calls by using direct attribute access
    and local variable caching where type is known.
    """
    kind = "request" if isinstance(message, ModelRequest) else "response"

    # OPTIMIZATION: Cache message attributes to avoid repeated lookups
    # These are optional attributes, so getattr with default is appropriate
    msg_role = getattr(message, "role", None)
    msg_instructions = getattr(message, "instructions", None)
    # Use or [] to avoid repeated None checks in the loop
    msg_parts = getattr(message, "parts", None) or []

    # Pre-allocate parts list and bind append method for speed
    parts: list[dict] = []
    parts_append = parts.append

    for part in msg_parts:
        # part_kind is usually present, but use getattr with fallback
        part_kind = getattr(part, "part_kind", None)
        if part_kind is None:
            part_kind = type(part).__name__

        # Use getattr with default for safe attribute access
        content = getattr(part, "content", None)
        tool_call_id = getattr(part, "tool_call_id", None)
        tool_name = getattr(part, "tool_name", None)
        args = getattr(part, "args", None)

        # Build part dict with cached values
        part_dict: dict[str, Any] = {
            "part_kind": part_kind,
            "content": None,
            "content_json": None,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args": json.dumps(args, separators=(',', ':')) if args is not None else None,
        }

        # Handle content serialization - using local 'content' avoids re-lookup
        if content is None:
            pass
        elif isinstance(content, str):
            part_dict["content"] = content
        elif isinstance(content, list):
            # OPTIMIZATION: Local append binding for text extraction loop
            text_parts: list[str] = []
            text_append = text_parts.append
            for item in content:
                if isinstance(item, str):
                    text_append(item)
            part_dict["content"] = "\n".join(text_parts) if text_parts else None
        elif hasattr(content, "model_dump_json"):
            # Pydantic model path - try/except for safety
            try:
                part_dict["content_json"] = content.model_dump_json(sort_keys=True)
            except (TypeError, ValueError):
                part_dict["content"] = repr(content)
        elif isinstance(content, dict):
            part_dict["content_json"] = json.dumps(content, sort_keys=True)
        else:
            part_dict["content"] = repr(content)

        parts_append(part_dict)

    return {
        "kind": kind,
        "role": msg_role,
        "instructions": msg_instructions,
        "parts": parts,
    }


def serialize_messages_for_rust(messages: list) -> list[dict]:
    """Batch convert messages for Rust consumption."""
    return [serialize_message_for_rust(m) for m in messages]
