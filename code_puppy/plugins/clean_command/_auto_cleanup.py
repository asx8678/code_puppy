"""Auto-cleanup functionality for the clean command."""

import configparser
from pathlib import Path
from typing import Any

from code_puppy import config
from code_puppy.messaging import emit_info, emit_success

from ._orphan_detection import _run_orphans


def _load_cleanup_config() -> dict:
    """Load auto-cleanup preferences from puppy.cfg.

    Looks for these keys in [cleanup] section:
    - auto_clean_on_startup: bool (default: false)
    - auto_clean_max_age_days: int (default: 30)
    - auto_clean_categories: comma-separated list (default: cache,logs)

    Returns:
        Dict with keys: enabled, max_age_days, categories
    """
    # Use config.CONFIG_FILE instead of hardcoded path
    cfg_path = Path(config.CONFIG_FILE)
    defaults = {
        "enabled": False,
        "max_age_days": 30,
        "categories": ["cache", "logs"],
    }

    if not cfg_path.is_file():
        return defaults

    try:
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
            defaults["max_age_days"] = int(cleanup.get("auto_clean_max_age_days", "30"))
        except ValueError:
            pass

        # Parse categories - explicit empty string means no categories
        cats_str = cleanup.get("auto_clean_categories")
        if cats_str is not None:
            # If explicitly set (even to empty string), use it
            defaults["categories"] = [
                c.strip() for c in cats_str.split(",") if c.strip()
            ]

    except Exception:
        pass

    return defaults


def _auto_cleanup(
    categories_map: dict[str, Any],
    clean_targets_func: Any,
) -> None:
    """Run auto-cleanup on startup if configured in puppy.cfg.

    Args:
        categories_map: Dictionary mapping category keys to (display_name, target_fn)
        clean_targets_func: Function to clean targets, signature: (targets, dry_run) -> (files, bytes)

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
        if cat in categories_map:
            emit_info(f"  Auto-cleaning {cat}...")
            display_name, target_fn = categories_map[cat]
            targets = target_fn()
            clean_targets_func(targets, dry_run=False)

    # Also clean orphans if requested
    if "orphans" in categories:
        _run_orphans(dry_run=False, auto_clean=True)

    emit_success("Auto-cleanup complete.")
