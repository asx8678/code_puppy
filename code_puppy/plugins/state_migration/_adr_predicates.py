"""ADR-003 allowlist/denylist predicates and INI helpers.

Extracted from :mod:`code_puppy.plugins.state_migration.migrator` to
keep the core migrator under the 600-line cap.

This module is a **private implementation detail** of the
``state_migration`` plugin — do not import from outside the plugin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ADR-003 Allowlist / Denylist
# ---------------------------------------------------------------------------

ALLOWED_TOP_FILES = frozenset(
    {
        "extra_models.json",
        "models.json",
        "puppy.cfg",
    }
)

ALLOWED_DIRS = frozenset(
    {
        "agents",
        "skills",
    }
)

FORBIDDEN_FILENAME_PARTS = ("oauth", "token", "_auth")
FORBIDDEN_EXTENSIONS = (".sqlite", ".db")
FORBIDDEN_DIRS = frozenset({"autosaves", "sessions"})
FORBIDDEN_EXACT_FILES = frozenset({"command_history.txt"})
FORBIDDEN_KEY_PARTS = (
    "auth",
    "token",
    "api_key",
    "api_secret",
    "secret",
    "password",
    "credential",
    "session_key",
)


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


def _is_forbidden_basename(name: str) -> bool:
    lower = name.lower()
    return any(part in lower for part in FORBIDDEN_FILENAME_PARTS)


def _is_forbidden_extension(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in FORBIDDEN_EXTENSIONS)


def _is_forbidden_dir(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    return any(part in FORBIDDEN_DIRS for part in parts)


def _is_forbidden_exact(name: str) -> bool:
    return name in FORBIDDEN_EXACT_FILES


def is_forbidden(rel_path: str) -> bool:
    """Return True if *rel_path* matches a denial pattern from ADR-003."""
    name = Path(rel_path).name
    return (
        _is_forbidden_basename(name)
        or _is_forbidden_extension(name)
        or _is_forbidden_dir(rel_path)
        or _is_forbidden_exact(name)
    )


def is_allowed(rel_path: str) -> bool:
    """Return True if *rel_path* is on the ADR-003 allowlist.

    The allowlist is default-deny: a file must be explicitly allowed AND
    not match any forbidden pattern.
    """
    if is_forbidden(rel_path):
        return False

    if rel_path in ALLOWED_TOP_FILES:
        return True

    parts = Path(rel_path).parts
    if parts and parts[0] in ALLOWED_DIRS:
        return True

    return False


def forbidden_key(key: str) -> bool:
    """Return True if a config key matches a forbidden pattern."""
    lower = key.lower()
    return any(part in lower for part in FORBIDDEN_KEY_PARTS)


# ---------------------------------------------------------------------------
# INI parsing helpers (lightweight, no external deps)
# ---------------------------------------------------------------------------


def parse_ini(path: Path) -> dict[str, dict[str, str]]:
    """Parse a minimal INI file into ``{section: {key: value}}``."""
    if not path.exists():
        return {}

    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            sections.setdefault(current_section, {})
            continue

        if current_section is None:
            continue

        if "=" in line:
            key, _, value = line.partition("=")
            sections[current_section][key.strip()] = value.strip()

    return sections


def extract_safe_ui(content: str) -> dict[str, str]:
    """Extract only safe ``[ui]`` keys from INI content."""
    ui: dict[str, str] = {}
    in_ui = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        if line.startswith("[") and line.endswith("]"):
            in_ui = line[1:-1].strip() == "ui"
            continue

        if in_ui and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if not forbidden_key(key):
                ui[key] = value.strip()

    return ui


def serialize_ini(config: dict[str, dict[str, str]]) -> str:
    """Serialize an INI config dict back to string."""
    lines: list[str] = []
    for section in sorted(config):
        lines.append(f"[{section}]")
        for key in sorted(config[section]):
            lines.append(f"{key} = {config[section][key]}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any | None:
    """Read and parse a JSON file; return ``None`` on any error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def deep_merge_preserving_existing(
    existing: dict[str, Any],
    legacy: dict[str, Any],
) -> dict[str, Any]:
    """Merge *legacy* into *existing*; existing keys win on conflict."""
    merged = dict(legacy)
    for key, value in existing.items():
        if key in merged:
            if isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key] = deep_merge_preserving_existing(value, merged[key])
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged
