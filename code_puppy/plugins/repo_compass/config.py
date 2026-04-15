from dataclasses import dataclass

from code_puppy.config import get_value


@dataclass(frozen=True, slots=True)
class RepoCompassConfig:
    enabled: bool = True
    level: str = "minimal"
    max_files: int = 15
    max_symbols_per_file: int = 3
    max_prompt_chars: int = 1200


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


def _get_str(key: str, default: str) -> str:
    raw = get_value(key)
    if raw is None:
        return default
    return str(raw).strip()


def load_config() -> RepoCompassConfig:
    level = _get_str("repo_compass_level", "minimal")
    if level not in {"full", "minimal", "off"}:
        level = "minimal"
    return RepoCompassConfig(
        enabled=_get_bool("repo_compass_enabled", True),
        level=level,
        max_files=_get_int("repo_compass_max_files", 15),
        max_symbols_per_file=_get_int("repo_compass_max_symbols_per_file", 3),
        max_prompt_chars=_get_int("repo_compass_max_prompt_chars", 1200),
    )
