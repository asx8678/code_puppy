"""Platform abstraction for daemon management.

# DEPRECATED: Use Elixir scheduler. This module is retained for backward compatibility only.
# The Elixir scheduler handles all process management.

Provides a unified interface for daemon operations across Windows, Linux, and macOS.

DEPRECATED: Process management is now handled by Elixir/OTP supervision.
"""

import sys

if sys.platform == "win32":
    from code_puppy.scheduler.platform_win import is_process_running, terminate_process
else:
    from code_puppy.scheduler.platform_unix import is_process_running, terminate_process

__all__ = ["is_process_running", "terminate_process"]
