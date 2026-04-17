"""Unix/macOS platform support for scheduler daemon.

# DEPRECATED(bd-62): Use Elixir scheduler. This module is retained for backward compatibility only.
# The Elixir scheduler handles all process management via OTP.

DEPRECATED: Process management is now handled by Elixir/OTP supervision.
"""

import os
import signal


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def terminate_process(pid: int) -> bool:
    """Terminate a process by PID."""
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False
