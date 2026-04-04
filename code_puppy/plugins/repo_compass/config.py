from __future__ import annotations

from dataclasses import dataclass

from code_puppy.config import get_value


@dataclass(frozen=True, slots=True)
class RepoCompassConfig:
    enabled: bool = True
    max_files: int = 40
    max_symbols_per_file: int = 8
    max_prompt_chars: int = 2400
    # Condensed mode settings
    condensed_max_files: int = 15
    condensed_max_symbols_per_file: int = 3
    condensed_max_prompt_chars: int = 800


def _get_int(key: str, default: int) -> int:
    raw = get_value(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _get_bool(key: str, default: bool) -> bool:
    raw = get_value(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> RepoCompassConfig:
    return RepoCompassConfig(
        enabled=_get_bool("repo_compass_enabled", True),
        max_files=_get_int("repo_compass_max_files", 40),
        max_symbols_per_file=_get_int("repo_compass_max_symbols_per_file", 8),
        max_prompt_chars=_get_int("repo_compass_max_prompt_chars", 2400),
        condensed_max_files=_get_int("repo_compass_condensed_max_files", 15),
        condensed_max_symbols_per_file=_get_int("repo_compass_condensed_max_symbols_per_file", 3),
        condensed_max_prompt_chars=_get_int("repo_compass_condensed_max_prompt_chars", 800),
    )
