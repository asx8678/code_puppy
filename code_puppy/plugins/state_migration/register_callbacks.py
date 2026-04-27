"""Hook registration for the state_migration plugin.

Provides the ``/migrate`` command for one-shot Python→Elixir home
migration per ADR-003 escape hatch.

Registered hooks:
- ``custom_command``: handles ``/migrate`` and ``/migrate --confirm`` / ``/migrate --force``
- ``custom_command_help``: adds help text for ``/migrate``
"""

from __future__ import annotations

import argparse
import logging

from code_puppy.callbacks import register_callback
from code_puppy.plugins.state_migration.migrator import StateMigrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /migrate command handler
# ---------------------------------------------------------------------------


def _handle_migrate(command: str, name: str) -> str | None:
    """Handle the ``/migrate`` custom command.

    Returns a formatted report string, or ``None`` if the command is
    not ``/migrate`` (so other handlers can process it).
    """
    if name != "migrate":
        return None

    # Parse sub-arguments
    parser = argparse.ArgumentParser(
        prog="/migrate",
        description="One-shot state migration: ~/.code_puppy/ → ~/.code_puppy_ex/",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually copy files (default is dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files at destination",
    )

    # Strip the leading "/migrate" and parse the rest
    parts = command.strip().split()
    try:
        args = parser.parse_args(parts[1:])
    except SystemExit:
        return "Usage: /migrate [--confirm] [--force]"

    migrator = StateMigrator()
    result = migrator.run(confirm=args.confirm, force=args.force)

    return _format_report(result)


def _format_report(result: object) -> str:
    """Format a :class:`MigrationResult` into a human-readable report."""
    from code_puppy.plugins.state_migration.migrator import MigrationResult

    if not isinstance(result, MigrationResult):
        return str(result)

    mode_label = {
        "dry_run": "DRY RUN",
        "copy": "COPY",
        "no_op": "NO-OP",
    }.get(result.mode, result.mode.upper())

    lines: list[str] = ["", f"📦 State migration ({mode_label} mode)", "─" * 50]

    if result.mode == "no_op":
        lines.append("  No legacy home to migrate from.")
        lines.append("")
        return "\n".join(lines)

    if result.copied:
        verb = "Would copy" if result.mode == "dry_run" else "Copied"
        lines.append(f"  ✅ {verb}:")
        for path in result.copied:
            lines.append(f"     • {path}")

    if result.skipped:
        lines.append("  ⏭️  Skipped:")
        for path, reason in result.skipped:
            lines.append(f"     • {path} — {reason}")

    if result.refused:
        lines.append("  🚫 Refused (forbidden by ADR-003):")
        for path, reason in result.refused:
            lines.append(f"     • {path} — {reason}")

    if result.errors:
        lines.append("  ❌ Errors:")
        for path, reason in result.errors:
            lines.append(f"     • {path} — {reason}")

    total = (
        len(result.copied)
        + len(result.skipped)
        + len(result.refused)
        + len(result.errors)
    )
    lines.append(
        f"  {total} items: {len(result.copied)} copied, "
        f"{len(result.skipped)} skipped, "
        f"{len(result.refused)} refused, "
        f"{len(result.errors)} errors"
    )

    if result.mode == "dry_run" and total > 0:
        lines.append("")
        lines.append("  Run /migrate --confirm to actually copy files.")

    lines.append("")
    return "\n".join(lines)


def _migrate_help() -> list[tuple[str, str]]:
    """Return help entries for the /migrate command."""
    return [
        (
            "/migrate",
            "One-shot state migration: ~/.code_puppy/ → ~/.code_puppy_ex/ "
            "(ADR-003). Use --confirm to copy, --force to overwrite.",
        )
    ]


# ---------------------------------------------------------------------------
# Register hooks
# ---------------------------------------------------------------------------

register_callback("custom_command", _handle_migrate)
register_callback("custom_command_help", _migrate_help)
