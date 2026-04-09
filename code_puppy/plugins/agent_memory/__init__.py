"""Agent Memory plugin — persists agent knowledge across sessions.

This plugin provides the foundation for the agent memory system,
allowing agents to store and recall facts learned during conversations.

Phase 1: Storage layer (current)
- File-based per-agent storage
- Thread-safe CRUD operations
- Graceful corruption handling
"""

from .storage import FileMemoryStorage

__all__ = ["FileMemoryStorage"]
