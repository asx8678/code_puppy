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

Phase 4: Signal detection
- Correction/reinforcement/preference pattern detection
- Regex-based analysis of user messages
- Configurable confidence deltas per signal type
"""

from .signals import (
    CORRECTION_DELTA,
    PREFERENCE_DELTA,
    REINFORCEMENT_DELTA,
    Signal,
    SignalDetector,
    SignalType,
    detect_signals,
    has_correction,
    has_preference,
    has_reinforcement,
)
from .storage import FileMemoryStorage, Fact
from .updater import MemoryUpdater, DEFAULT_DEBOUNCE_MS

__all__ = [
    "CORRECTION_DELTA",
    "DEFAULT_DEBOUNCE_MS",
    "Fact",
    "FileMemoryStorage",
    "MemoryUpdater",
    "PREFERENCE_DELTA",
    "REINFORCEMENT_DELTA",
    "Signal",
    "SignalDetector",
    "SignalType",
    "detect_signals",
    "has_correction",
    "has_preference",
    "has_reinforcement",
]
