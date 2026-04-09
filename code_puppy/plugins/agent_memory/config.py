"""Configuration module for agent memory plugin.

Provides typed access to memory-related configuration settings
with sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

from code_puppy.config import get_value


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    """Configuration for the agent memory system.

    Attributes:
        enabled: Whether memory system is enabled
        max_facts: Maximum facts to inject into prompts
        token_budget: Max tokens for memory section in prompts
        min_confidence: Minimum confidence threshold for facts
        debounce_ms: Debounce window for batching writes
        extraction_enabled: Whether LLM fact extraction is enabled
    """

    enabled: bool = True
    max_facts: int = 10
    token_budget: int = 800
    min_confidence: float = 0.5
    debounce_ms: int = 30000
    extraction_enabled: bool = True


def _get_int(key: str, default: int) -> int:
    """Get integer config value with fallback."""
    raw = get_value(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _get_bool(key: str, default: bool) -> bool:
    """Get boolean config value with fallback."""
    raw = get_value(key)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    # Truthy values
    if value in {"1", "true", "yes", "on", "enabled"}:
        return True
    # Falsy values
    if value in {"0", "false", "no", "off", "disabled", ""}:
        return False
    # For any other value, check if it looks truthy
    return value and value not in {"0", "false", "no", "off", "disabled", "none", "null"}


def _get_float(key: str, default: float) -> float:
    """Get float config value with fallback."""
    raw = get_value(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def load_config() -> MemoryConfig:
    """Load memory configuration from config system.

    Returns:
        MemoryConfig with loaded values or defaults
    """
    return MemoryConfig(
        enabled=_get_bool("memory_enabled", True),
        max_facts=_get_int("memory_max_facts", 10),
        token_budget=_get_int("memory_token_budget", 800),
        min_confidence=_get_float("memory_min_confidence", 0.5),
        debounce_ms=_get_int("memory_debounce_ms", 30000),
        extraction_enabled=_get_bool("memory_extraction_enabled", True),
    )
