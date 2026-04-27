"""State migration plugin for code_puppy.

Per ADR-003 escape hatch, this plugin provides a one-shot import tool
that copies allowlisted files from the Python pup's home (``~/.code_puppy/``)
to the Elixir pup-ex home (``~/.code_puppy_ex/``).

User-explicit action only — no automatic sync.  Run via ``/migrate`` in
the REPL or as a standalone script.

Safety: all writes go through :func:`code_puppy.config_paths.safe_write`
and :func:`code_puppy.config_paths.safe_mkdir_p` so the isolation guard
is enforced.  The legacy home is never modified.
"""

from code_puppy.plugins.state_migration.migrator import StateMigrator

__all__ = ["StateMigrator"]
