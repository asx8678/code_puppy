"""Skill discovery - scans directories for valid skills."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_puppy.callbacks import get_callbacks, on_register_skills
from code_puppy.config import CACHE_DIR
from code_puppy.plugins.agent_skills.config import get_skill_directories

logger = logging.getLogger(__name__)

_PLUGIN_SKILLS_CACHE_DIR = Path(CACHE_DIR) / "plugin-skills"

# Serializes plugin-skill collection. ``_collect_plugin_skills`` wipes and
# rebuilds the shared cache dir above; without this lock, concurrent
# ``get_model_system_prompt`` dispatches (main agent + subagents on separate
# threads) race on the rmtree/mkdir pair (see _reset_plugin_skills_cache_dir).
_collect_lock = threading.Lock()

# Retries for the wipe+recreate when a race or a stale non-directory is hit.
_RESET_RETRIES = 5


@dataclass
class SkillInfo:
    """Basic skill information from discovery."""

    name: str
    path: Path
    has_skill_md: bool


# Global cache for discovered skills
_skill_cache: list[SkillInfo] | None = None


def get_default_skill_directories() -> list[Path]:
    """Return default directories to scan for skills.

    Returns:
        - ~/.fast_puppy/skills (user skills)
        - ./.fast_puppy/skills (project config skills)
        - ./skills (project skills)
    """
    return [
        Path.home() / ".fast_puppy" / "skills",
        Path.cwd() / ".fast_puppy" / "skills",
        Path.cwd() / "skills",
    ]


def is_valid_skill_directory(path: Path) -> bool:
    """Check if a directory contains a valid SKILL.md file."""
    if not path.is_dir():
        return False

    skill_md_path = path / "SKILL.md"
    return skill_md_path.is_file()


def _sanitize_path_part(value: str) -> str:
    cleaned = (value or "").strip().replace("/", "-").replace("\\", "-")
    return cleaned or "unnamed"


def _render_skill_markdown(entry: dict[str, Any]) -> str:
    if "skill_md" in entry:
        return str(entry["skill_md"])

    if "skill_md_path" in entry:
        return Path(entry["skill_md_path"]).read_text(encoding="utf-8")

    if "frontmatter" in entry and "body" in entry:
        frontmatter = dict(entry["frontmatter"] or {})
        frontmatter.setdefault("name", entry["name"])
        if entry.get("description") and "description" not in frontmatter:
            frontmatter["description"] = entry["description"]
        if entry.get("version") and "version" not in frontmatter:
            frontmatter["version"] = entry["version"]
        if entry.get("author") and "author" not in frontmatter:
            frontmatter["author"] = entry["author"]
        if entry.get("tags") and "tags" not in frontmatter:
            frontmatter["tags"] = entry["tags"]

        lines = ["---"]
        for key, value in frontmatter.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{key}: {value}")
        lines.extend(["---", str(entry["body"])])
        return "\n".join(lines).rstrip() + "\n"

    raise ValueError(
        "Skill entry must define either skill_md_path, skill_md, or frontmatter+body"
    )


def _copy_scripts_dir(source_dir: Path, target_dir: Path) -> None:
    scripts_target = target_dir / "scripts"
    if scripts_target.exists() or scripts_target.is_symlink():
        if scripts_target.is_dir() and not scripts_target.is_symlink():
            shutil.rmtree(scripts_target)
        else:
            scripts_target.unlink()

    try:
        scripts_target.symlink_to(source_dir, target_is_directory=True)
    except OSError:
        shutil.copytree(source_dir, scripts_target)


def _materialize_plugin_skill(
    callback_module: str, callback_name: str, entry: dict[str, Any]
) -> SkillInfo | None:
    skill_name = str(entry.get("name") or "").strip()
    if not skill_name:
        logger.warning(
            "Plugin skill registration from %s.%s missing required 'name'",
            callback_module,
            callback_name,
        )
        return None

    try:
        skill_md = _render_skill_markdown(entry)
    except Exception as exc:
        logger.warning(
            "Failed to render plugin skill %s from %s.%s: %s",
            skill_name,
            callback_module,
            callback_name,
            exc,
        )
        return None

    owner_dir = _PLUGIN_SKILLS_CACHE_DIR / _sanitize_path_part(callback_module)
    skill_dir = owner_dir / _sanitize_path_part(skill_name)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    scripts_dir = entry.get("scripts_dir")
    if scripts_dir:
        source_dir = Path(scripts_dir).expanduser().resolve()
        if source_dir.is_dir():
            _copy_scripts_dir(source_dir, skill_dir)
        else:
            logger.warning(
                "Plugin skill %s from %s.%s provided invalid scripts_dir: %s",
                skill_name,
                callback_module,
                callback_name,
                source_dir,
            )

    return SkillInfo(name=skill_name, path=skill_dir, has_skill_md=True)


def _iter_plugin_skill_registrations() -> Iterable[tuple[str, str, dict[str, Any]]]:
    callbacks = get_callbacks("register_skills")
    results = on_register_skills()

    for callback, result in zip(callbacks, results, strict=True):
        if not result:
            continue
        if not isinstance(result, list):
            logger.warning(
                "register_skills callback %s.%s must return a list, got %s",
                callback.__module__,
                callback.__name__,
                type(result).__name__,
            )
            continue

        for entry in result:
            if not isinstance(entry, dict):
                logger.warning(
                    "register_skills callback %s.%s returned non-dict entry: %r",
                    callback.__module__,
                    callback.__name__,
                    entry,
                )
                continue
            yield callback.__module__, callback.__name__, entry


def _reset_plugin_skills_cache_dir() -> None:
    """Wipe and recreate the plugin-skills cache dir, tolerant of races.

    A bare ``rmtree`` + ``mkdir(parents=True, exist_ok=True)`` is unsafe here:

    * ``shutil.rmtree`` only removes *directories*. If the path is left behind
      as a file or symlink, ``rmtree(ignore_errors=True)`` silently no-ops and
      the following ``mkdir`` raises ``FileExistsError`` on every call.
    * The two calls are not atomic. ``mkdir(exist_ok=True)`` re-checks
      ``is_dir()`` after a failed ``os.mkdir``; if a sibling reset removes the
      directory in that window the check fails and ``FileExistsError`` escapes
      *despite* ``exist_ok=True``. Concurrent ``get_model_system_prompt``
      dispatches hit exactly this.

    Callers hold ``_collect_lock`` to remove the in-process race; this helper
    additionally repairs a stale non-directory and absorbs cross-process races.
    """
    cache = _PLUGIN_SKILLS_CACHE_DIR
    for _ in range(_RESET_RETRIES):
        if cache.is_dir() and not cache.is_symlink():
            shutil.rmtree(cache, ignore_errors=True)
        elif cache.exists() or cache.is_symlink():
            # A stale file or (possibly broken) symlink squatting on the path.
            # Best-effort removal: any failure (vanished, perms, races) falls
            # through to the mkdir + retry below, which is the real correctness.
            try:
                cache.unlink()
            except OSError:
                pass
        try:
            cache.mkdir(parents=True, exist_ok=True)
            return
        except FileExistsError:
            # FileExistsError from mkdir(exist_ok=True) is never a real,
            # persistent failure: it means a sibling/process removed the dir
            # between os.mkdir() and pathlib's is_dir() recheck, or a non-dir
            # reappeared on the path. Both are retriable. Genuine failures
            # (PermissionError, EROFS, ...) are not FileExistsError and
            # propagate straight out of mkdir() above.
            if cache.is_dir() and not cache.is_symlink():
                return
    # Retries exhausted under sustained contention. Don't crash prompt-building
    # over a transient race: skills are materialized with their own
    # mkdir(parents=True) and a missing-but-empty cache dir is harmless.
    if not (cache.is_dir() and not cache.is_symlink()):
        logger.warning(
            "plugin-skills cache dir %s could not be reset cleanly after %d "
            "attempts; continuing best-effort",
            cache,
            _RESET_RETRIES,
        )


def _collect_plugin_skills() -> list[SkillInfo]:
    with _collect_lock:
        _reset_plugin_skills_cache_dir()

        plugin_skills: list[SkillInfo] = []
        seen_names: set[str] = set()

        for callback_module, callback_name, entry in _iter_plugin_skill_registrations():
            skill = _materialize_plugin_skill(callback_module, callback_name, entry)
            if skill is None:
                continue
            if skill.name in seen_names:
                logger.warning(
                    "Skipping duplicate plugin skill registration for '%s' from %s.%s",
                    skill.name,
                    callback_module,
                    callback_name,
                )
                continue
            seen_names.add(skill.name)
            plugin_skills.append(skill)

        return plugin_skills


def discover_skills(directories: list[Path] | None = None) -> list[SkillInfo]:
    """Scan directories for valid skills."""
    global _skill_cache

    if directories is None:
        configured = [Path(d) for d in get_skill_directories()]
        defaults = get_default_skill_directories()
        seen = {p.resolve() for p in configured}
        directories = list(configured)
        for d in defaults:
            if d.resolve() not in seen:
                directories.append(d)

    discovered_skills: list[SkillInfo] = []
    seen_skill_names: set[str] = set()

    for directory in directories:
        if not directory.exists():
            logger.debug(f"Skill directory does not exist: {directory}")
            continue

        if not directory.is_dir():
            logger.warning(f"Skill path is not a directory: {directory}")
            continue

        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue

            has_skill_md = is_valid_skill_directory(skill_dir)
            skill_info = SkillInfo(
                name=skill_dir.name,
                path=skill_dir,
                has_skill_md=has_skill_md,
            )
            discovered_skills.append(skill_info)
            seen_skill_names.add(skill_info.name)

            if has_skill_md:
                logger.debug(
                    "Discovered valid skill: %s at %s", skill_dir.name, skill_dir
                )
            else:
                logger.debug(
                    "Found skill directory without SKILL.md: %s", skill_dir.name
                )

    for plugin_skill in _collect_plugin_skills():
        if plugin_skill.name in seen_skill_names:
            logger.debug(
                "Skipping plugin skill '%s' because a filesystem skill already exists",
                plugin_skill.name,
            )
            continue
        discovered_skills.append(plugin_skill)
        seen_skill_names.add(plugin_skill.name)

    _skill_cache = discovered_skills
    logger.info(
        "Discovered %s skills from %s directories",
        len(discovered_skills),
        len(directories),
    )
    return discovered_skills


def refresh_skill_cache() -> list[SkillInfo]:
    """Force re-discovery of all skills."""
    global _skill_cache
    _skill_cache = None
    return discover_skills()
