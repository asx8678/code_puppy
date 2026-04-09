"""Agent Memory plugin — persists agent knowledge across sessions.

This plugin provides the foundation for the agent memory system,
allowing agents to store and recall facts learned during conversations.

Phase 1: Storage layer
- File-based per-agent storage
- Thread-safe CRUD operations
- Graceful corruption handling

Phase 2: Debounced batch updater
- Batched writes with configurable debounce window
- Automatic deduplication by fact text
- Immediate operations for reinforce/remove (bypass debounce)
- Graceful flush on shutdown

Phase 6: Configuration and CLI
- Config-based opt-in activation
- /memory slash command with subcommands
- Rich formatted memory display
- JSON export for transparency
"""

from .config import MemoryConfig, get_config, is_memory_enabled
from .storage import FileMemoryStorage, Fact
from .updater import MemoryUpdater, DEFAULT_DEBOUNCE_MS

__all__ = [
    "DEFAULT_DEBOUNCE_MS",
    "Fact",
    "FileMemoryStorage",
    "MemoryConfig",
    "MemoryUpdater",
    "get_config",
    "is_memory_enabled",
]
