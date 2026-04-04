"""Clean command plugin — /clean for clearing sessions, history, logs, and caches.

Registers via the ``custom_command`` hook so it lives entirely outside
``code_puppy/command_line/``.  Run ``/clean help`` for usage.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Any

from code_puppy import config
from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_error, emit_info, emit_success, emit_warning

# ---------------------------------------------------------------------------
# Storage location definitions
# ---------------------------------------------------------------------------

# Each category maps to a list of (label, path, kind) tuples.
# kind is "dir" (clean contents) or "file" (unlink).


def _session_targets() -> list[tuple[str, Path, str]]:
    return [
        ("Autosave sessions", Path(config.AUTOSAVE_DIR), "dir"),
        ("Sub-agent sessions", Path(config.DATA_DIR) / "subagent_sessions", "dir"),
        (
            "Terminal sessions",
            Path(config.STATE_DIR) / "terminal_sessions.json",
            "file",
        ),
        ("Session HMAC key", Path(config.DATA_DIR) / ".session_hmac_key", "file"),
        ("Last agent", Path(config.STATE_DIR) / "last_agent.json", "file"),
    ]


def _history_targets() -> list[tuple[str, Path, str]]:
    return [
        ("Command history", Path(config.COMMAND_HISTORY_FILE), "file"),
    ]


def _log_targets() -> list[tuple[str, Path, str]]:
    return [
        ("Error logs", Path(config.STATE_DIR) / "logs", "dir"),
    ]


def _cache_targets() -> list[tuple[str, Path, str]]:
    return [
        ("Browser profiles", Path(config.CACHE_DIR) / "browser_profiles", "dir"),
        ("Browser workflows", Path(config.DATA_DIR) / "browser_workflows", "dir"),
        (
            "Skills cache",
            Path.home() / ".code_puppy" / "cache" / "skills_catalog.json",
            "file",
        ),
        ("API server PID", Path(config.STATE_DIR) / "api_server.pid", "file"),
    ]


def _db_targets() -> list[tuple[str, Path, str]]:
    """DBOS database and its WAL/SHM journal files."""
    db_path = Path(config.DATA_DIR) / "dbos_store.sqlite"
    targets: list[tuple[str, Path, str]] = [
        ("DBOS database", db_path, "file"),
    ]
    # Include WAL/SHM journal files when they exist (status + cleanup)
    for suffix in ("-wal", "-shm"):
        journal = db_path.parent / (db_path.name + suffix)
        if journal.is_file():
            targets.append((f"DBOS journal ({suffix})", journal, "file"))
    return targets


_CATEGORIES: dict[str, Any] = {
    "sessions": ("Sessions", _session_targets),
    "history": ("History", _history_targets),
    "logs": ("Logs", _log_targets),
    "cache": ("Cache", _cache_targets),
    "db": ("Database", _db_targets),
}

# Categories safe to include in "/clean all".
# The "db" category is excluded because deleting the DBOS SQLite database
# while DBOS holds an active connection causes
# ``sqlite3.OperationalError: attempt to write a readonly database``.
# Users must run "/clean db" explicitly (which destroys DBOS first).
_SAFE_CATEGORY_KEYS: list[str] = [k for k in _CATEGORIES if k != "db"]

# ---------------------------------------------------------------------------
# Size / cleanup helpers
# ---------------------------------------------------------------------------

# Disk usage warning thresholds (bytes)
_WARNING_THRESHOLD_MB = 100 * 1024 * 1024  # 100 MB
_CRITICAL_THRESHOLD_MB = 500 * 1024 * 1024  # 500 MB

# Known file extensions for orphan detection
_KNOWN_EXTENSIONS: set[str] = {
    ".json", ".sqlite", ".db", ".log", ".txt", ".cfg", ".pid", 
    ".key", ".wal", ".shm", ".md", ".py", ".html", ".css",
}


def _human_size(nbytes: int) -> str:
    """Format *nbytes* as a human-friendly string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB"):
        nbytes /= 1024.0
        if nbytes < 1024.0 or unit == "GB":
            return f"{nbytes:.1f} {unit}"
    return f"{nbytes:.1f} GB"  # pragma: no cover


def _dir_stats(path: Path) -> tuple[int, int]:
    """Return ``(file_count, total_bytes)`` for a directory tree."""
    if not path.is_dir():
        return 0, 0
    count = 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return count, total


def _file_stats(path: Path) -> tuple[int, int]:
    """Return ``(1, size)`` if file exists, else ``(0, 0)``."""
    if not path.is_file():
        return 0, 0
    try:
        return 1, path.stat().st_size
    except OSError:
        return 0, 0


def _target_stats(targets: list[tuple[str, Path, str]]) -> tuple[int, int]:
    """Aggregate file count and byte total across all targets."""
    count = 0
    total = 0
    for _label, path, kind in targets:
        if kind == "dir":
            c, t = _dir_stats(path)
        else:
            c, t = _file_stats(path)
        count += c
        total += t
    return count, total


def _clean_dir(path: Path, dry_run: bool) -> tuple[int, int]:
    """Remove **contents** of *path* (not the dir itself).

    Returns ``(files_removed, bytes_freed)``.
    """
    if not path.is_dir():
        return 0, 0
    count, total = _dir_stats(path)
    if dry_run or count == 0:
        return count, total
    try:
        shutil.rmtree(path)
    except OSError as exc:
        emit_warning(f"  ⚠️  Could not fully clean {path}: {exc}")
    finally:
        path.mkdir(parents=True, exist_ok=True)
    return count, total


def _clean_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Remove a single file.  Returns ``(1, size)`` or ``(0, 0)``."""
    if not path.is_file():
        return 0, 0
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if dry_run:
        return 1, size
    try:
        path.unlink()
    except OSError as exc:
        emit_warning(f"  ⚠️  Could not remove {path}: {exc}")
        return 0, 0
    return 1, size


def _clean_targets(
    targets: list[tuple[str, Path, str]], dry_run: bool
) -> tuple[int, int]:
    """Clean all targets in a list, emitting per-target output.

    Returns ``(total_files, total_bytes)`` across all targets.
    """
    total_files = 0
    total_bytes = 0
    for label, path, kind in targets:
        if kind == "dir":
            c, b = _clean_dir(path, dry_run)
        else:
            c, b = _clean_file(path, dry_run)
        if c:
            prefix = "Would remove" if dry_run else "Removed"
            emit_info(
                f"  🗑️  {prefix} {label}: {c} file{'s' if c != 1 else ''}, {_human_size(b)}"
            )
        total_files += c
        total_bytes += b
    return total_files, total_bytes


def _check_disk_usage(path: Path) -> tuple[int, str | None]:
    """Check disk usage for a path and return warning if thresholds exceeded.

    Args:
        path: The path to check (file or directory)

    Returns:
        Tuple of (bytes_used, warning_message_or_none).
        Warning is shown for > 100MB, critical warning for > 500MB.
    """
    if path.is_dir():
        count, total = _dir_stats(path)
    elif path.is_file():
        count, total = _file_stats(path)
    else:
        return 0, None

    if total == 0:
        return 0, None

    warning = None
    if total > _CRITICAL_THRESHOLD_MB:
        warning = f"🔴 CRITICAL: {_human_size(total)} - very large!"
    elif total > _WARNING_THRESHOLD_MB:
        warning = f"🟡 Warning: {_human_size(total)} - consider cleaning"

    return total, warning


def _find_orphans(dir_path: Path, known_extensions: set[str] | None = None) -> list[Path]:
    """Find orphaned files that don't match expected patterns.

    Identifies:
    - Files with unknown extensions
    - Temporary files (starting with '.' or ending with '~', '.tmp', '.temp')
    - Broken symlinks

    Args:
        dir_path: Directory to scan
        known_extensions: Set of known extensions (defaults to _KNOWN_EXTENSIONS)

    Returns:
        List of orphaned file paths
    """
    if known_extensions is None:
        known_extensions = _KNOWN_EXTENSIONS

    orphans: list[Path] = []

    if not dir_path.is_dir():
        return orphans

    try:
        for item in dir_path.rglob("*"):
            # Check for broken symlinks
            if item.is_symlink() and not item.exists():
                orphans.append(item)
                continue

            if not item.is_file():
                continue

            name = item.name
            ext = item.suffix.lower()

            # Temp file patterns
            if name.startswith(".") or name.endswith("~"):
                orphans.append(item)
                continue

            if name.endswith(".tmp") or name.endswith(".temp"):
                orphans.append(item)
                continue

            # Unknown extensions
            if ext and ext not in known_extensions:
                orphans.append(item)
                continue

    except OSError:
        pass

    return orphans


def _load_cleanup_config() -> dict:
    """Load auto-cleanup preferences from puppy.cfg.

    Looks for these keys in [cleanup] section:
    - auto_clean_on_startup: bool (default: false)
    - auto_clean_max_age_days: int (default: 30)
    - auto_clean_categories: comma-separated list (default: cache,logs)

    Returns:
        Dict with keys: enabled, max_age_days, categories
    """
    cfg_path = Path.home() / ".code_puppy" / "puppy.cfg"
    defaults = {
        "enabled": False,
        "max_age_days": 30,
        "categories": ["cache", "logs"],
    }

    if not cfg_path.is_file():
        return defaults

    try:
        import configparser
        parser = configparser.ConfigParser()
        parser.read(cfg_path)

        if "cleanup" not in parser.sections():
            return defaults

        cleanup = parser["cleanup"]

        # Parse enabled
        enabled_str = cleanup.get("auto_clean_on_startup", "false").lower()
        defaults["enabled"] = enabled_str in ("true", "1", "yes", "on")

        # Parse max age
        try:
            defaults["max_age_days"] = int(
                cleanup.get("auto_clean_max_age_days", "30")
            )
        except ValueError:
            pass

        # Parse categories
        cats_str = cleanup.get("auto_clean_categories", "cache,logs")
        if cats_str:
            defaults["categories"] = [
                c.strip() for c in cats_str.split(",") if c.strip()
            ]

    except Exception:
        pass

    return defaults


def _get_last_modified(path: Path) -> str | None:
    """Get the last modified timestamp for a path as a human-readable string.

    Args:
        path: The path to check

    Returns:
        Human-readable timestamp string, or None if path doesn't exist
    """
    if not path.exists():
        return None

    try:
        mtime = path.stat().st_mtime
        # Format as relative time if within last 24 hours, else as date
        age_seconds = time.time() - mtime
        if age_seconds < 86400:  # 24 hours
            hours = int(age_seconds / 3600)
            if hours < 1:
                mins = int(age_seconds / 60)
                return f"{mins}m ago"
            return f"{hours}h ago"
        else:
            return time.strftime("%Y-%m-%d", time.localtime(mtime))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# DBOS-safe database cleanup
# ---------------------------------------------------------------------------


def _destroy_dbos() -> bool:
    """Attempt to gracefully shut down DBOS.  Returns True on success."""
    try:
        from dbos import DBOS

        DBOS.destroy()
        return True
    except Exception:
        return False


def _clean_db(dry_run: bool) -> tuple[int, int]:
    """Clean the DBOS database with safety handling.

    Unlike other categories, the ``db`` category must destroy the active DBOS
    connection **before** deleting the underlying SQLite file.  Deleting while
    DBOS holds an open connection causes
    ``sqlite3.OperationalError: attempt to write a readonly database``.

    Returns ``(total_files, total_bytes)``.
    """
    if not dry_run:
        if _destroy_dbos():
            emit_info("  🔌 DBOS connection closed")
        else:
            emit_warning(
                "  ⚠️  Could not close DBOS connection — database may still be locked"
            )

    _, target_fn = _CATEGORIES["db"]
    targets = target_fn()
    total_files, total_bytes = _clean_targets(targets, dry_run)

    if not dry_run and total_files > 0:
        emit_warning("  ⚠️  Please restart Code Puppy for DBOS to reinitialize.")

    return total_files, total_bytes


def _run_orphans(dry_run: bool = False, auto_clean: bool = False) -> None:
    """Find and optionally clean orphan files.

    Args:
        dry_run: If True, only list orphans without removing
        auto_clean: If True, automatically clean orphans (for auto-cleanup)
    """
    if dry_run and not auto_clean:
        emit_info("🔍 Scanning for orphan files...\n")
    elif not auto_clean:
        emit_info("🧹 Cleaning orphan files...\n")

    all_orphans: list[tuple[Path, str]] = []

    # Scan main code_puppy directories
    base_dir = Path.home() / ".code_puppy"

    dirs_to_scan = [
        (base_dir, "Root directory"),
        (Path(config.CACHE_DIR), "Cache directory"),
        (Path(config.DATA_DIR), "Data directory"),
        (Path(config.STATE_DIR), "State directory"),
    ]

    for dir_path, label in dirs_to_scan:
        if not dir_path.exists():
            continue

        orphans = _find_orphans(dir_path)
        for orphan in orphans:
            # Determine type
            if orphan.is_symlink():
                orphan_type = "broken symlink"
            elif orphan.name.startswith("."):
                orphan_type = "hidden file"
            elif orphan.name.endswith("~"):
                orphan_type = "backup file"
            elif orphan.suffix.lower() in (".tmp", ".temp"):
                orphan_type = "temp file"
            else:
                orphan_type = "unknown extension"

            all_orphans.append((orphan, orphan_type))

    if not all_orphans:
        if not auto_clean:
            emit_info("\n✨ No orphan files found!")
        return

    if not auto_clean:
        emit_info(f"Found {len(all_orphans)} orphan file(s):\n")

    total_bytes = 0
    files_removed = 0

    for orphan_path, orphan_type in all_orphans:
        try:
            size = orphan_path.stat().st_size if orphan_path.is_file() else 0
        except OSError:
            size = 0

        if not auto_clean:
            emit_info(f"  📄 {orphan_path.name} ({orphan_type})")

        if dry_run:
            total_bytes += size
            files_removed += 1
        else:
            try:
                if orphan_path.is_dir():
                    shutil.rmtree(orphan_path)
                else:
                    orphan_path.unlink()
                files_removed += 1
                total_bytes += size
                if not auto_clean:
                    emit_info(f"     ✓ Removed ({_human_size(size)})")
            except OSError as exc:
                if not auto_clean:
                    emit_warning(f"     ⚠️ Could not remove: {exc}")

    if auto_clean:
        emit_info(f"Auto-cleaned {files_removed} orphan files ({_human_size(total_bytes)})")
    elif dry_run:
        emit_info(
            f"\n📋 Would remove {files_removed} orphan file{'s' if files_removed != 1 else ''}"
            f" ({_human_size(total_bytes)})"
        )
    else:
        emit_success(
            f"\n✅ Removed {files_removed} orphan file{'s' if files_removed != 1 else ''}"
            f" ({_human_size(total_bytes)})"
        )


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _show_help() -> None:
    """Print help text for /clean."""
    emit_info("🧹 /clean — Clean Code Puppy session data, logs, and caches\n")
    emit_info("Usage:")
    emit_info("  /clean help              Show this help message")
    emit_info("  /clean status            Show detailed disk usage per category")
    emit_info(
        "  /clean all               Clean everything except db (sessions, history, logs, cache)"
    )
    emit_info(
        "  /clean sessions          Clean autosave + sub-agent + terminal sessions"
    )
    emit_info("  /clean history           Clean command history")
    emit_info("  /clean logs              Clean error logs")
    emit_info(
        "  /clean cache             Clean browser profiles, workflows, skills cache"
    )
    emit_info(
        "  /clean db                Clean DBOS state database (⚠️ requires restart)"
    )
    emit_info("  /clean orphans           Find and clean orphaned/temp files")
    emit_info("")
    emit_info("Options:")
    emit_info(
        "  --dry-run                Preview what would be cleaned without deleting"
    )
    emit_info("")
    emit_info("Examples:")
    emit_info("  /clean sessions --dry-run")
    emit_info("  /clean --dry-run all")
    emit_info("  /clean orphans           Remove orphan files")
    emit_info("  /clean --dry-run orphans Preview orphan files to be removed")
    emit_info("")
    emit_info("⚠️  Config files (puppy.cfg, mcp_servers.json, models, OAuth tokens)")
    emit_info("   are never touched.")
    emit_info("💡 /clean all excludes db — use /clean db explicitly (needs restart).")
    emit_info("")
    emit_info("🤖 Auto-cleanup Configuration (puppy.cfg):")
    emit_info("   [cleanup]")
    emit_info("   auto_clean_on_startup = false")
    emit_info("   auto_clean_max_age_days = 30")
    emit_info("   auto_clean_categories = cache,logs")


def _show_status() -> None:
    """Print detailed disk usage per category with warnings and timestamps."""
    emit_info("📊 Code Puppy Storage Status\n")

    grand_files = 0
    grand_bytes = 0
    warnings: list[tuple[str, str]] = []

    for key, (display_name, target_fn) in _CATEGORIES.items():
        targets = target_fn()
        count, total = _target_stats(targets)
        grand_files += count
        grand_bytes += total

        # Check for disk usage warnings
        for _label, path, kind in targets:
            if kind == "dir":
                _, warning = _check_disk_usage(path)
                if warning:
                    warnings.append((f"{display_name}", warning))

        count_str = f"{count} file{'s' if count != 1 else ''}"
        size_str = _human_size(total)

        # Get last modified for first target (if directory)
        first_target = targets[0] if targets else None
        last_mod = None
        if first_target:
            _label, path, kind = first_target
            if kind == "dir":
                last_mod = _get_last_modified(path)
            elif kind == "file" and path.exists():
                last_mod = _get_last_modified(path)

        mod_str = f" (modified: {last_mod})" if last_mod else ""
        emit_info(f"  {display_name:<20s} {count_str:>12s}  {size_str:>10s}{mod_str}")

        # Show individual target details if more than one target
        if len(targets) > 1:
            for label, path, kind in targets:
                if kind == "dir":
                    c, t = _dir_stats(path)
                else:
                    c, t = _file_stats(path)
                if c > 0:
                    detail_count = f"{c} file{'s' if c != 1 else ''}"
                    emit_info(
                        f"    • {label:<30s} {detail_count:>10s}  {_human_size(t):>10s}"
                    )

    emit_info("  " + "─" * 44)
    emit_info(
        f"  {'Total':<20s} {grand_files:>6d} file{'s' if grand_files != 1 else '':5s} {_human_size(grand_bytes):>10s}"
    )

    # Display warnings section
    if warnings:
        emit_info("\n⚠️  Warnings:")
        for category, warning in warnings:
            emit_info(f"   {category}: {warning}")

    # Show orphan count
    base_dir = Path.home() / ".code_puppy"
    orphan_count = len(_find_orphans(base_dir)) if base_dir.exists() else 0
    if orphan_count > 0:
        emit_info(f"\n🔍 Found {orphan_count} orphan file(s). Run '/clean orphans' to remove.")

    emit_info("\n💡 Run '/clean help' for available commands.")


def _run_clean(categories: list[str], dry_run: bool) -> None:
    """Execute a clean across the given category keys."""
    if dry_run:
        emit_info("🔍 Dry run — nothing will be deleted\n")
    else:
        emit_info("🧹 Cleaning Code Puppy data...\n")

    grand_files = 0
    grand_bytes = 0
    for key in categories:
        if key == "db":
            # db category requires special DBOS-safe handling
            files, nbytes = _clean_db(dry_run)
        else:
            display_name, target_fn = _CATEGORIES[key]
            targets = target_fn()
            files, nbytes = _clean_targets(targets, dry_run)
        grand_files += files
        grand_bytes += nbytes

    if grand_files == 0:
        emit_info("\n✨ Nothing to clean — already squeaky clean!")
    elif dry_run:
        emit_info(
            f"\n📋 Would clean {grand_files} file{'s' if grand_files != 1 else ''}"
            f" ({_human_size(grand_bytes)})"
        )
    else:
        emit_success(
            f"\n✅ Cleaned {grand_files} file{'s' if grand_files != 1 else ''}"
            f" ({_human_size(grand_bytes)})"
        )


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

_VALID_SUBCMDS = {"help", "status", "all", "sessions", "history", "logs", "cache", "db", "orphans"}


def _handle_clean_command(command: str, name: str) -> bool | None:
    """Handle ``/clean`` and its subcommands.

    Returns ``True`` when the command was handled, ``None`` otherwise.
    """
    if name != "clean":
        return None

    # Parse arguments after "/clean"
    parts = command.split()[1:]  # drop "/clean" itself

    # Detect --dry-run anywhere in args
    dry_run = "--dry-run" in parts
    args = [a for a in parts if a != "--dry-run"]

    subcmd = args[0] if args else "help"

    try:
        if subcmd == "help":
            _show_help()
        elif subcmd == "status":
            _show_status()
        elif subcmd == "all":
            _run_clean(_SAFE_CATEGORY_KEYS, dry_run)
        elif subcmd == "orphans":
            _run_orphans(dry_run)
        elif subcmd in _CATEGORIES:
            _run_clean([subcmd], dry_run)
        else:
            emit_warning(f"Unknown subcommand: {subcmd}")
            _show_help()
    except Exception as exc:
        emit_error(f"Clean command failed: {exc}")

    return True


def _auto_cleanup() -> None:
    """Run auto-cleanup on startup if configured in puppy.cfg.

    Reads cleanup preferences from puppy.cfg [cleanup] section and
    automatically cleans configured categories if auto_clean_on_startup
    is enabled.
    """
    cfg = _load_cleanup_config()

    if not cfg.get("enabled", False):
        return

    categories = cfg.get("categories", [])
    if not categories:
        return

    emit_info("🤖 Auto-cleanup enabled — checking storage...")

    # Clean configured categories
    for cat in categories:
        if cat in _CATEGORIES:
            emit_info(f"  Auto-cleaning {cat}...")
            display_name, target_fn = _CATEGORIES[cat]
            targets = target_fn()
            _clean_targets(targets, dry_run=False)

    # Also clean orphans if requested
    if "orphans" in categories:
        _run_orphans(dry_run=False, auto_clean=True)

    emit_success("Auto-cleanup complete.")


# ---------------------------------------------------------------------------
# Help callback
# ---------------------------------------------------------------------------


def _custom_help() -> list[tuple[str, str]]:
    return [("clean", "Clean sessions, history, logs, and cache data")]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_callback("custom_command", _handle_clean_command)
register_callback("custom_command_help", _custom_help)
register_callback("startup", _auto_cleanup)
