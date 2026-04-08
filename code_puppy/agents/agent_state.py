"""Agent runtime state container for separating mutable state from immutable config.

This module provides the AgentRuntimeState dataclass which encapsulates
all mutable runtime state for an agent instance, enabling clear separation
from immutable configuration.
"""

from dataclasses import dataclass, field
from typing import Any

import pydantic_ai.models


@dataclass
class AgentRuntimeState:
    """Mutable runtime state container for agent instances.

    This dataclass encapsulates all mutable state that changes during
    agent execution, separating it from immutable agent configuration.

    This separation provides:
    1. Clear distinction between config (set at creation) and state (evolves at runtime)
    2. Easier state inspection and debugging
    3. Simpler state serialization for persistence
    4. Prevention of accidental config mutations

    Attributes:
        message_history: List of conversation messages
        compacted_message_hashes: SHA-256 hex digests of summarized messages
        message_history_hashes: Hash set for O(1) duplicate detection
        code_generation_agent: Cached pydantic agent instance
        last_model_name: Track when model changes to invalidate caches
        puppy_rules: Lazy-loaded puppy rules content
        cur_model: Current pydantic-ai Model instance
        mcp_tool_definitions_cache: Tool definitions from MCP servers
        cached_system_prompt: Session-scoped system prompt cache
        cached_tool_defs: Session-scoped tool definitions cache
        delayed_compaction_requested: Flag for delayed compaction
        tool_ids_cache: Per-invocation cache for tool call IDs
        cached_context_overhead: Cached token overhead estimation
        model_name_cache: Per-instance cache for get_model_name()
        resolved_model_components_cache: Cache for model components
        mcp_servers: List of active MCP server connections
        rust_per_message_tokens: Per-message token counts from Rust
    """

    # Message history and tracking
    message_history: list[Any] = field(default_factory=list)
    compacted_message_hashes: set[str] = field(default_factory=set)
    message_history_hashes: set[str] = field(default_factory=set)

    # Agent and model caching
    code_generation_agent: Any = None
    last_model_name: str | None = None
    puppy_rules: str | None = None
    cur_model: pydantic_ai.models.Model | None = None

    # Tool and prompt caching
    mcp_tool_definitions_cache: list[dict[str, Any]] = field(default_factory=list)
    cached_system_prompt: str | None = None
    cached_tool_defs: list[dict[str, Any]] | None = None

    # State flags and temporary caches
    delayed_compaction_requested: bool = False
    tool_ids_cache: Any = None
    cached_context_overhead: int | None = None
    model_name_cache: str | None = None
    resolved_model_components_cache: dict[str, Any] | None = None

    # MCP server connections
    mcp_servers: list[Any] = field(default_factory=list)
    rust_per_message_tokens: list[int] | None = None

    def clear_history(self) -> None:
        """Clear message history and associated hashes."""
        self.message_history = []
        self.compacted_message_hashes.clear()
        self.message_history_hashes.clear()

    def append_message(self, message: Any, message_hash: str) -> None:
        """Append a message and its hash to history."""
        self.message_history.append(message)
        self.message_history_hashes.add(message_hash)

    def extend_history(self, messages: list[Any], message_hashes: list[str]) -> None:
        """Extend history with multiple messages and their hashes."""
        self.message_history.extend(messages)
        self.message_history_hashes.update(message_hashes)

    def invalidate_caches(self) -> None:
        """Invalidate all ephemeral caches. Call when model/tool config changes."""
        self.cached_context_overhead = None
        self.tool_ids_cache = None
        # Note: cached_system_prompt and cached_tool_defs are session-scoped
        # and only invalidated on agent reload, not here.
