"""Configuration module for the agent memory plugin.

This module provides convenient access to memory-related configuration
from puppy.cfg, with proper defaults and validation.

Config keys (in puppy.cfg):
    enable_agent_memory = false         # OPT-IN, default off
    memory_debounce_seconds = 30        # Write debounce window (1-300)
    memory_max_facts = 50               # Max facts per agent (1-1000)
    memory_token_budget = 500           # Token budget for injection (100-2000)
    memory_extraction_model = ""        # Optional model override (empty = default)

Example usage:
    >>> from code_puppy.plugins.agent_memory.config import get_config
    >>> config = get_config()
    >>> if config.enabled:
    ...     print(f"Debouncing for {config.debounce_seconds}s")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


@dataclass(frozen=True)
class MemoryConfig:
    """Immutable configuration container for agent memory settings.

    Attributes:
        enabled: Whether agent memory is enabled (default: False)
        debounce_seconds: Write debounce window in seconds (default: 30)
        max_facts: Maximum facts to store per agent (default: 50)
        token_budget: Token budget for memory injection (default: 500)
        extraction_model: Optional model override for extraction (default: None)
    """

    enabled: bool = False
    debounce_seconds: int = 30
    max_facts: int = 50
    token_budget: int = 500
    extraction_model: Optional[str] = None


def get_config() -> MemoryConfig:
    """Load and return the current memory configuration.

    Reads all memory-related config keys from puppy.cfg with
    appropriate defaults. This function is lightweight and can
    be called frequently - underlying config reads are cached.

    Returns:
        MemoryConfig with current settings

    Example:
        >>> config = get_config()
        >>> if config.enabled:
        ...     updater = MemoryUpdater(storage, config.debounce_seconds * 1000)
    """
    # Import here to avoid circular imports at module load time
    from code_puppy.config import (
        get_enable_agent_memory,
        get_memory_debounce_seconds,
        get_memory_extraction_model,
        get_memory_max_facts,
        get_memory_token_budget,
    )

    return MemoryConfig(
        enabled=get_enable_agent_memory(),
        debounce_seconds=get_memory_debounce_seconds(),
        max_facts=get_memory_max_facts(),
        token_budget=get_memory_token_budget(),
        extraction_model=get_memory_extraction_model(),
    )


def is_memory_enabled() -> bool:
    """Quick check if agent memory is enabled.

    This is a convenience function for checks that don't need
    the full configuration object.

    Returns:
        True if enable_agent_memory is set to a truthy value

    Example:
        >>> if is_memory_enabled():
        ...     initialize_memory_system()
    """
    from code_puppy.config import get_enable_agent_memory

    return get_enable_agent_memory()


__all__ = [
    "MemoryConfig",
    "get_config",
    "is_memory_enabled",
]
