"""Agent identity and prompt management.

This module contains identity-related functionality for agents including:
- Agent name, display_name, description properties
- System prompt generation
- Identity prompt generation
- Available agents listing
"""

import uuid
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from code_puppy.config import get_default_agent


class AgentIdentityMixin(ABC):
    """Mixin providing identity-related functionality for agents."""

    def __init__(self):
        self.id = str(uuid.uuid4())

    def get_identity(self) -> str:
        """Get a unique identity for this agent instance.

        Returns:
            A string like 'python-programmer-a3f2b1' combining name + short UUID.
        """
        return f"{self.name}-{self.id[:6]}"

    def get_identity_prompt(self) -> str:
        """Get the identity prompt suffix to embed in system prompts.

        Returns:
            A string instructing the agent about its identity for task ownership.
        """
        return (
            f"\n\nYour ID is `{self.get_identity()}`. "
            "Use this for any tasks which require identifying yourself "
            "such as claiming task ownership or coordination with other agents."
        )

    def get_full_system_prompt(self) -> str:
        """Get the complete system prompt with identity automatically appended.

        This wraps get_system_prompt() and appends the agent's identity,
        so subclasses don't need to worry about it.

        Returns:
            The full system prompt including identity information.
        """
        return self.get_system_prompt() + self.get_identity_prompt()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the agent."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for the agent."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of what this agent does."""
        pass

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        pass

    @abstractmethod
    def get_available_tools(self) -> List[str]:
        """Get list of tool names that this agent should have access to.

        Returns:
            List of tool names to register for this agent.
        """
        pass

    def get_tools_config(self) -> Optional[Dict[str, Any]]:
        """Get tool configuration for this agent.

        Returns:
            Dict with tool configuration, or None to use default tools.
        """
        return None

    def get_user_prompt(self) -> Optional[str]:
        """Get custom user prompt for this agent.

        Returns:
            Custom prompt string, or None to use default.
        """
        return None


def get_default_agent_name() -> str:
    """Get the name of the default agent.

    Returns:
        The default agent name from config.
    """
    return get_default_agent()
