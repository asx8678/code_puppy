"""Register callbacks for the Agent Memory plugin.

Phase 1: Minimal plugin registration.
Future phases will expand this with:
- Agent lifecycle hooks for automatic memory injection
- Session-based memory consolidation
- Memory retrieval tools for agents
"""

import logging

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _on_startup() -> None:
    """Initialize the memory plugin on startup.

    Currently a no-op for Phase 1. Future phases will:
    - Validate storage directories
    - Clean up old backup files
    - Pre-load frequently accessed memories
    """
    logger.debug("Agent Memory plugin loaded (Phase 1: Storage)")


# Register the startup hook
register_callback("startup", _on_startup)
