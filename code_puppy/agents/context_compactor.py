"""Context compaction and token management for agents.

This module handles:
- Token estimation and counting
- Context compaction and summarization
- Protected token management
- Message filtering and truncation
"""

import logging
from typing import Any, Dict, List

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from rich.text import Text

from code_puppy.config import (
    get_model_context_length,
)
from code_puppy.messaging import emit_info, emit_warning

logger = logging.getLogger(__name__)


class ContextCompactorMixin:
    """Mixin providing context compaction and token management functionality."""

    def __init__(self):
        self._delayed_compaction_requested: bool = False
        # Cache for MCP tool definitions (for token estimation)
        self._mcp_tool_definitions_cache: List[Dict[str, Any]] = []

    def estimate_token_count(self, text: str) -> int:
        """Estimate the number of tokens in a text string.

        Uses a rough heuristic of ~4 characters per token.

        Args:
            text: The text to estimate tokens for.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0
        return max(1, len(text) // 4)

    def estimate_tokens_for_message(self, message: ModelMessage) -> int:
        """Estimate the token count for a single message.

        Args:
            message: The message to estimate.

        Returns:
            Estimated token count for the message.
        """
        total = 0
        if hasattr(message, "parts"):
            for part in message.parts:
                if hasattr(part, "content") and isinstance(part.content, str):
                    total += self.estimate_token_count(part.content)
        return total

    def estimate_context_overhead_tokens(self) -> int:
        """Estimate the token overhead from context (system prompt, tools, MCP).

        This includes:
        - System prompt tokens
        - Tool definition tokens
        - MCP tool definition tokens

        Returns:
            Estimated token count for context overhead.
        """
        total = 0

        # System prompt
        try:
            system_prompt = self.get_full_system_prompt()
            total += self.estimate_token_count(system_prompt)
        except Exception:
            pass

        # Regular tool definitions
        try:
            tool_defs = self._get_cached_tool_defs()
            if tool_defs:
                for tool in tool_defs:
                    tool_str = str(tool)
                    total += self.estimate_token_count(tool_str)
        except Exception:
            pass

        # MCP tool definitions
        try:
            mcp_tool_defs = getattr(self, "_mcp_tool_definitions_cache", [])
            if mcp_tool_defs:
                for tool in mcp_tool_defs:
                    tool_str = str(tool)
                    total += self.estimate_token_count(tool_str)
        except Exception:
            pass

        return total

    def _get_cached_tool_defs(self) -> List[Dict[str, Any]]:
        """Get cached tool definitions.

        Returns:
            List of tool definitions.
        """
        return getattr(self, "_cached_tool_defs", None) or []

    def request_delayed_compaction(self) -> None:
        """Request that compaction be delayed until a safe point.

        This is called when we want to compact but there are pending tool calls.
        """
        self._delayed_compaction_requested = True

    def should_attempt_delayed_compaction(self) -> bool:
        """Check if delayed compaction should be attempted.

        Returns:
            True if compaction was requested and should be attempted now.
        """
        if self._delayed_compaction_requested:
            self._delayed_compaction_requested = False
            return True
        return False

    def get_model_context_length(self) -> int:
        """Get the context length for the current model.

        Returns:
            Model context length in tokens.
        """
        try:
            model_name = self.get_model_name()
            if model_name:
                return get_model_context_length()
        except Exception:
            pass
        return 128000  # Default

    def filter_huge_messages(
        self, messages: List[ModelMessage], max_tokens: int = 8000
    ) -> List[ModelMessage]:
        """Filter out extremely large messages that exceed token limits.

        Args:
            messages: List of messages to filter.
            max_tokens: Maximum tokens allowed per message.

        Returns:
            Filtered messages with huge ones replaced with placeholders.
        """
        result = []
        for msg in messages:
            msg_tokens = self.estimate_tokens_for_message(msg)
            if msg_tokens > max_tokens:
                # Replace with a summary placeholder
                if isinstance(msg, ModelRequest):
                    result.append(
                        ModelRequest(
                            parts=[
                                TextPart(
                                    content=f"[Large message ({msg_tokens} tokens) - content omitted]"
                                )
                            ]
                        )
                    )
                elif isinstance(msg, ModelResponse):
                    result.append(
                        ModelResponse(
                            parts=[
                                TextPart(
                                    content=f"[Large response ({msg_tokens} tokens) - content omitted]"
                                )
                            ]
                        )
                    )
                else:
                    result.append(msg)
                emit_warning(
                    f"Filtered huge message ({msg_tokens} tokens) to prevent context overflow"
                )
            else:
                result.append(msg)
        return result

    def has_pending_tool_calls(self, messages: List[ModelMessage]) -> bool:
        """Check if there are pending tool calls in the message history.

        Args:
            messages: Message history to check.

        Returns:
            True if there are unfulfilled tool calls.
        """
        pending_calls = set()
        returned_tools = set()

        for msg in messages:
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        pending_calls.add(part.tool_call_id)
            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        returned_tools.add(part.tool_call_id)

        return bool(pending_calls - returned_tools)

    def get_pending_tool_call_count(self, messages: List[ModelMessage]) -> int:
        """Count the number of pending tool calls.

        Args:
            messages: Message history to check.

        Returns:
            Number of unfulfilled tool calls.
        """
        pending_calls = set()
        returned_tools = set()

        for msg in messages:
            if isinstance(msg, ModelResponse):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        pending_calls.add(part.tool_call_id)
            elif isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        returned_tools.add(part.tool_call_id)

        return len(pending_calls - returned_tools)

    def prune_interrupted_tool_calls(
        self, messages: List[ModelMessage]
    ) -> List[ModelMessage]:
        """Remove incomplete tool call/return sequences.

        When an agent is interrupted mid-stream, there may be partial
        tool calls that will never complete. This removes those.

        Args:
            messages: Message history to clean.

        Returns:
            Cleaned message history.
        """
        result = []
        pending_calls: Dict[str, ToolCallPart] = {}

        for msg in messages:
            if isinstance(msg, ModelResponse):
                new_parts = []
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        pending_calls[part.tool_call_id] = part
                        new_parts.append(part)
                    else:
                        new_parts.append(part)
                if new_parts:
                    result.append(ModelResponse(parts=new_parts))
            elif isinstance(msg, ModelRequest):
                new_parts = []
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        # Check if this returns a pending call
                        if part.tool_call_id in pending_calls:
                            del pending_calls[part.tool_call_id]
                            new_parts.append(part)
                    else:
                        new_parts.append(part)
                if new_parts:
                    result.append(ModelRequest(parts=new_parts))
            else:
                result.append(msg)

        return result

    def truncation(
        self,
        ctx: Any,
        messages: List[ModelMessage],
        total_tokens: int,
        max_tokens: int,
    ) -> List[ModelMessage]:
        """Truncate messages to fit within token limits.

        This is called when compaction is disabled or fails.
        Simply removes oldest messages until under limit.

        Args:
            ctx: Run context.
            messages: Messages to truncate.
            total_tokens: Current total token count.
            max_tokens: Maximum allowed tokens.

        Returns:
            Truncated messages.
        """
        if total_tokens <= max_tokens:
            return messages

        # Calculate how many tokens we need to remove
        tokens_to_remove = total_tokens - max_tokens
        tokens_removed = 0
        messages_to_remove = 0

        # Remove oldest messages first
        for msg in messages:
            msg_tokens = self.estimate_tokens_for_message(msg)
            tokens_removed += msg_tokens
            messages_to_remove += 1
            if tokens_removed >= tokens_to_remove:
                break

        # Keep at least 2 messages (system + last user)
        if len(messages) - messages_to_remove < 2:
            messages_to_remove = max(0, len(messages) - 2)

        result = messages[messages_to_remove:]
        emit_info(
            Text.from_markup(
                f"[yellow]Truncated {messages_to_remove} messages ({tokens_removed} tokens) to fit context[/yellow]"
            )
        )
        return result
