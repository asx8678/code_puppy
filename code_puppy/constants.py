"""Shared constants for Code Puppy."""

from typing import Final

# TUI operations timeout in seconds
# Reduced from 300s (5 min) to 120s (2 min) to provide faster feedback
# when operations hang
TUI_TIMEOUT_SECONDS: Final[int] = 120