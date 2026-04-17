"""Entry point for running scheduler daemon directly.

# DEPRECATED(bd-62): Use Elixir scheduler. This module is retained for backward compatibility only.
# The Elixir scheduler is started automatically with the application supervision tree.

Usage: python -m code_puppy.scheduler

DEPRECATED: The scheduler daemon is now managed by Elixir.
"""

from code_puppy.scheduler.daemon import start_daemon

if __name__ == "__main__":
    start_daemon(foreground=True)
