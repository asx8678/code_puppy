"""Bridge to Rust extension module with Python fallback.

This is the ONLY place where pydantic-ai message objects are converted to
the dict format that Rust expects. The Rust module never touches pydantic-ai
objects directly.
"""

import json
from typing import Any

from code_puppy.utils.binary_token_estimation import (
    estimate_binary_content_tokens as _estimate_binary_tokens_simple,
)

try:
    from pydantic_ai.messages import ModelRequest
except ImportError:
    ModelRequest = None  # type: ignore[misc,assignment]

try:
    from _code_puppy_core import (
        MessageBatch,
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
except (ImportError, SystemError):
    RUST_AVAILABLE = False
    MessageBatch = None  # type: ignore[assignment,misc]

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
except (ImportError, SystemError):
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
            binary_tokens = 0
            for item in content:
                if isinstance(item, str):
                    text_append(item)
                elif hasattr(item, "data"):
                    # BinaryContent: pass metadata for Rust token estimation
                    binary_tokens += _estimate_binary_tokens_simple(item)
            part_dict["content"] = "\n".join(text_parts) if text_parts else None
            if binary_tokens > 0:
                part_dict["binary_token_estimate"] = binary_tokens
        elif hasattr(content, "model_dump_json"):
            # Pydantic model path - try/except for safety
            try:
                part_dict["content_json"] = content.model_dump_json()
            except (TypeError, ValueError):
                part_dict["content"] = repr(content)
        elif isinstance(content, dict):
            part_dict["content_json"] = json.dumps(content)
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


class MessageBatchHandle:
    """Zero-copy wrapper around Rust MessageBatch for batched operations.

    This class serializes pydantic-ai messages ONCE during construction,
    then allows multiple Rust operations without re-serialization.

    Usage:
        batch = MessageBatchHandle(messages)
        result = batch.process(tool_defs, mcp_defs, system_prompt)
        indices = batch.truncation_indices(protected_tokens, has_thinking)
        pruned = batch.prune_and_filter(50000)
    """

    __slots__ = ("_rust_batch", "_py_messages", "_serialized")

    def __init__(self, messages: list) -> None:
        """Create batch from pydantic-ai ModelMessage list.

        Args:
            messages: List of pydantic-ai ModelMessage objects
        """
        self._py_messages = messages
        self._serialized = [serialize_message_for_rust(m) for m in messages]

        if RUST_AVAILABLE:
            self._rust_batch = MessageBatch(self._serialized)
        else:
            self._rust_batch = None

    def __len__(self) -> int:
        return len(self._py_messages)

    @property
    def messages(self) -> list:
        """Access original Python messages."""
        return self._py_messages

    @property
    def serialized(self) -> list[dict]:
        """Access serialized dict form (for legacy code paths)."""
        return self._serialized

    def process(
        self,
        tool_definitions: list,
        mcp_tool_definitions: list,
        system_prompt: str,
    ) -> "ProcessResult":
        """Process messages and cache token counts."""
        if self._rust_batch is not None:
            return self._rust_batch.process(
                tool_definitions, mcp_tool_definitions, system_prompt
            )
        # Fallback: use standalone function
        return process_messages_batch(
            self._serialized, tool_definitions, mcp_tool_definitions, system_prompt
        )

    def prune_and_filter(self, max_tokens_per_message: int = 50000) -> "PruneResult":
        """Prune interrupted tool calls and filter huge messages."""
        if self._rust_batch is not None:
            return self._rust_batch.prune_and_filter(max_tokens_per_message)
        return prune_and_filter(self._serialized, max_tokens_per_message)

    def truncation_indices(
        self, protected_tokens: int, second_has_thinking: bool
    ) -> list[int]:
        """Get indices to keep after truncation."""
        if self._rust_batch is not None:
            return self._rust_batch.truncation_indices(protected_tokens, second_has_thinking)
        # Fallback requires per_message_tokens - not available without process()
        raise RuntimeError("truncation_indices requires process() to be called first")

    def split_for_summarization(self, protected_tokens_limit: int) -> "SplitResult":
        """Split messages for summarization."""
        if self._rust_batch is not None:
            return self._rust_batch.split_for_summarization(protected_tokens_limit)
        raise RuntimeError("split_for_summarization requires Rust batch with process() called")

    def get_per_message_tokens(self) -> list[int] | None:
        """Get cached per-message token counts (None if process() not called)."""
        if self._rust_batch is not None:
            return self._rust_batch.get_per_message_tokens()
        return None

    def get_total_tokens(self) -> int | None:
        """Get cached total token count (None if process() not called)."""
        if self._rust_batch is not None:
            return self._rust_batch.get_total_tokens()
        return None

    def get_message_hashes(self) -> list[int] | None:
        """Get cached message hashes (None if process() not called)."""
        if self._rust_batch is not None:
            return self._rust_batch.get_message_hashes()
        return None


def create_message_batch(messages: list) -> MessageBatchHandle:
    """Factory function for creating MessageBatchHandle.

    Args:
        messages: List of pydantic-ai ModelMessage objects

    Returns:
        MessageBatchHandle wrapping the messages
    """
    return MessageBatchHandle(messages)


__all__ = [
    # Core serialization
    "serialize_message_for_rust",
    "serialize_messages_for_rust",
    # Message batch wrapper
    "MessageBatchHandle",
    "create_message_batch",
    # Rust availability flags
    "RUST_AVAILABLE",
    "is_rust_enabled",
    "set_rust_enabled",
    "get_rust_status",
    # Hashline acceleration
    "HASHLINE_RUST_AVAILABLE",
    "compute_line_hash",
    "format_hashlines",
    "strip_hashline_prefixes",
    "validate_hashline_anchor",
    # Rust types (for type hints)
    "ProcessResult",
    "PruneResult",
    "SplitResult",
    "MessageBatch",
    # Standalone functions (for legacy/fallback use)
    "process_messages_batch",
    "prune_and_filter",
    "truncation_indices",
    "split_for_summarization",
    "serialize_session",
    "deserialize_session",
    "serialize_session_incremental",
]
