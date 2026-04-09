"""Agent Memory plugin — persists agent knowledge across sessions.

This plugin provides the foundation for the agent memory system,
allowing agents to store and recall facts learned during conversations.

Phase 1: Storage layer
- File-based per-agent storage
- Thread-safe CRUD operations
- Graceful corruption handling

Phase 2: Debounced batch updater (current)
- Batched writes with configurable debounce window
- Automatic deduplication by fact text
- Immediate operations for reinforce/remove (bypass debounce)
- Graceful flush on shutdown
"""

from .storage import FileMemoryStorage, Fact
from .updater import MemoryUpdater, DEFAULT_DEBOUNCE_MS

__all__ = [
    "FileMemoryStorage",
    "MemoryUpdater",
    "Fact",
    "DEFAULT_DEBOUNCE_MS",
]
