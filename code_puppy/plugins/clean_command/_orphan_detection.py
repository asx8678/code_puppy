"""Orphan file detection and cleanup for the clean command."""

import shutil
from pathlib import Path

from code_puppy import config
from code_puppy.messaging import emit_info, emit_success, emit_warning

from ._disk_usage import _human_size

# Known file extensions for orphan detection
_KNOWN_EXTENSIONS: set[str] = {
    ".json",
    ".sqlite",
    ".db",
    ".log",
    ".txt",
    ".cfg",
    ".pid",
    ".key",
    ".wal",
    ".shm",
    ".md",
    ".py",
    ".html",
    ".css",
}

# Known legitimate database files (anything else is orphaned)
_KNOWN_DB_FILES: set[str] = {
    "dbos_store.sqlite",
    "dbos_store.sqlite-shm",
    "dbos_store.sqlite-wal",
}

# Database extensions that require reference checking
_DB_EXTENSIONS: set[str] = {".db", ".sqlite", ".db-shm", ".db-wal", ".sqlite-shm", ".sqlite-wal"}

# Known bad hidden file patterns (specific patterns, not all dotfiles)
_BAD_HIDDEN_PATTERNS: tuple[str, ...] = (
    ".DS_Store",
    ".tmp_",
    ".temp_",
)


def _find_orphans(
    dir_path: Path, known_extensions: set[str] | None = None
) -> list[Path]:
    """Find orphaned files that don't match expected patterns.

    Identifies:
    - Broken symlinks
    - Backup files (ending with '~')
    - Temp files (ending with '.tmp', '.temp')
    - Known bad hidden files (.DS_Store, .tmp_*, .temp_*)
    - Files with unknown extensions

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

            # Backup files
            if name.endswith("~"):
                orphans.append(item)
                continue

            # Temp files (explicit extensions)
            if ext in (".tmp", ".temp"):
                orphans.append(item)
                continue

            # Known bad hidden files (specific patterns only)
            if name.startswith(".") and any(
                name == pattern or name.startswith(pattern)
                for pattern in _BAD_HIDDEN_PATTERNS
            ):
                orphans.append(item)
                continue

            # Database files not in the known list are orphaned
            if ext in _DB_EXTENSIONS or name in _KNOWN_DB_FILES:
                if name not in _KNOWN_DB_FILES:
                    orphans.append(item)
                continue

            # Unknown extensions
            if ext and ext not in known_extensions:
                orphans.append(item)
                continue

    except OSError:
        pass

    return orphans


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

    # Scan XDG directories (use config paths, not hardcoded ~/.code_puppy)
    dirs_to_scan = [
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
            elif orphan.name.endswith("~"):
                orphan_type = "backup file"
            elif orphan.suffix.lower() in (".tmp", ".temp"):
                orphan_type = "temp file"
            elif orphan.name.startswith("."):
                orphan_type = "hidden temp file"
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
        emit_info(
            f"Auto-cleaned {files_removed} orphan files ({_human_size(total_bytes)})"
        )
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


def _count_orphans_in_dirs() -> int:
    """Count total orphans across all XDG directories.

    Returns:
        Total number of orphan files found
    """
    total = 0
    dirs_to_scan = [
        Path(config.CACHE_DIR),
        Path(config.DATA_DIR),
        Path(config.STATE_DIR),
    ]

    for dir_path in dirs_to_scan:
        if dir_path.exists():
            total += len(_find_orphans(dir_path))

    return total
