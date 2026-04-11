"""Git Auto Commit (GAC) Plugin - BLK1 Spike.

This plugin proves that a `/commit` slash command can safely orchestrate
async git commands through Code Puppy's centralized shell security boundary.

Success Criteria:
- `/commit` command registers and can execute `git status` through security
- Tests pass proving the sync→async shell bridge works
- Clear documentation of what works and what doesn't

This is a SPIKE - minimal implementation focused on proving the architecture.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__: list[str] = []
