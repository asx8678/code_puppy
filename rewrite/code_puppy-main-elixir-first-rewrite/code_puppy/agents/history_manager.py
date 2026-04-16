"""Message history management for agents.

This module handles message history operations including:
- Message history storage and retrieval
- Message hashing and deduplication
- History validation and cleanup
"""

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
)


class MessageHistoryMixin:
    """Mixin providing message history management functionality."""

    def __init__(self):
        self._message_history: list[Any] = []
        self._compacted_message_hashes: set[str] = set()

    def get_message_history(self) -> list[Any]:
        """Get the message history for this agent.

        Returns:
            List of messages in this agent's conversation history.
        """
        return self._message_history

    def set_message_history(self, history: list[Any]) -> None:
        """Set the message history for this agent.

        Args:
            history: List of messages to set as the conversation history.
        """
        self._message_history = history

    def clear_message_history(self) -> None:
        """Clear the message history for this agent."""
        self._message_history = []
        self._compacted_message_hashes.clear()

    def append_to_message_history(self, message: Any) -> None:
        """Append a message to this agent's history.

        Args:
            message: Message to append to the conversation history.
        """
        self._message_history.append(message)

    def extend_message_history(self, history: list[Any]) -> None:
        """Extend this agent's message history with multiple messages.

        Args:
            history: List of messages to append to the conversation history.
        """
        self._message_history.extend(history)

    def get_compacted_message_hashes(self) -> set[str]:
        """Get the set of hashes for messages that have been compacted.

        Returns:
            Set of message hashes that were removed during compaction.
        """
        return self._compacted_message_hashes

    def add_compacted_message_hash(self, message_hash: str) -> None:
        """Add a message hash to the compacted set.

        Args:
            message_hash: Hash of a message that was compacted/summarized.
        """
        self._compacted_message_hashes.add(message_hash)

    def restore_compacted_hashes(self, hashes: list) -> None:
        """Restore compacted hashes from a previous session.

        Args:
            hashes: List of hashes to restore.
        """
        self._compacted_message_hashes.update(hashes)

    def hash_message(self, message: Any) -> int:
        """Hash a message for deduplication.

        Args:
            message: The message to hash.

        Returns:
            Hash value for the message.
        """
        # Build a deterministic string representation
        parts_str = ""
        if hasattr(message, "parts"):
            for part in message.parts:
                if hasattr(part, "content"):
                    parts_str += f"{type(part).__name__}:{part.content}:"
                elif hasattr(part, "tool_name"):
                    parts_str += f"Tool:{part.tool_name}:"
                elif hasattr(part, "tool_calls"):
                    for tc in part.tool_calls:
                        parts_str += f"ToolCall:{tc.tool_name}:"
                else:
                    parts_str += f"{type(part).__name__}:"
        return hash(parts_str)

    def ensure_history_ends_with_request(
        self, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        """Ensure message history ends with a ModelRequest.

        Anthropic API requires the last message to be a ModelRequest (user message).
        If the history ends with a ModelResponse (assistant), we add a placeholder.

        Args:
            messages: The message history to validate.

        Returns:
            Validated message history ending with ModelRequest.
        """
        if not messages:
            return messages

        last_msg = messages[-1]
        if isinstance(last_msg, ModelResponse):
            # Add a placeholder user message to satisfy API requirement
            messages = list(messages)  # Make a copy
            messages.append(ModelRequest(parts=[TextPart(content="(continuing...)")]))
        return messages
