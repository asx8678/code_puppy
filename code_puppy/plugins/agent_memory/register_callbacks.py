"""Register callbacks for the Agent Memory plugin.

Phase 2: Plugin registration with debounced updater support.
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

    Phase 2: Registers the debounced batch updater infrastructure.
    Future phases will:
    - Validate storage directories
    - Clean up old backup files
    - Pre-load frequently accessed memories
    """
    logger.debug("Agent Memory plugin loaded (Phase 2: Debounced Batch Updater)")


# Register the startup hook
register_callback("startup", _on_startup)
