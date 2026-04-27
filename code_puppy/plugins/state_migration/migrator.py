"""Core migration logic: Python home → Elixir home (ADR-003 escape hatch).

Reads from the Python pup's canonical home and writes to the Elixir
pup-ex home.  The migration is:

- **One-shot**: designed to be run once; idempotent on re-run.
- **Explicit-only**: never triggered automatically.
- **Copy-only**: the legacy home is never modified or deleted.
- **Guarded**: all writes go through ``config_paths.safe_*`` wrappers.

The allowlist is defined by ADR-003 and mirrors the Elixir-side
``CodePuppyControl.Config.Importer`` logic.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from code_puppy.config_paths import (
    legacy_home_dir,
    safe_mkdir_p,
    safe_write,
)
from code_puppy.plugins.state_migration._adr_predicates import (
    deep_merge_preserving_existing,
    extract_safe_ui,
    is_allowed,
    is_forbidden,
    parse_ini,
    read_json,
    serialize_ini,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MigrationResult:
    """Structured result from a migration run."""

    mode: str  # "dry_run" | "copy" | "no_op"
    copied: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core migrator
# ---------------------------------------------------------------------------


class StateMigrator:
    """One-shot state migrator: Python home → Elixir home.

    Parameters
    ----------
    source_home:
        Path to the Python pup's home (defaults to ``legacy_home_dir()``).
    target_home:
        Path to the Elixir pup-ex home (defaults to ``home_dir()`` when
        ``PUP_EX_HOME`` is set, otherwise ``~/.code_puppy_ex/``).
    """

    def __init__(
        self,
        source_home: Path | str | None = None,
        target_home: Path | str | None = None,
    ) -> None:
        self.source_home = Path(source_home) if source_home else legacy_home_dir()
        if target_home:
            self.target_home = Path(target_home)
        else:
            pup_ex = os.environ.get("PUP_EX_HOME")
            if pup_ex:
                self.target_home = Path(pup_ex).expanduser().resolve()
            else:
                self.target_home = Path.home() / ".code_puppy_ex"

    # ── Public API ────────────────────────────────────────────────────────

    def run(
        self,
        *,
        confirm: bool = False,
        force: bool = False,
    ) -> MigrationResult:
        """Execute the migration.

        Parameters
        ----------
        confirm:
            Actually copy files.  Without this, runs in dry-run mode.
        force:
            Overwrite existing files at the destination.

        Returns
        -------
        MigrationResult
            Structured report of what was / would be copied.
        """
        if not self.source_home.is_dir():
            return MigrationResult(mode="no_op")

        mode = "copy" if confirm else "dry_run"
        result = MigrationResult(mode=mode)

        # Phase 1: scan for forbidden files
        result = self._scan_for_forbidden(result)

        # Phase 2: import allowlisted items
        result = self._import_extra_models(result, mode, force)
        result = self._import_models_json(result, mode, force)
        result = self._import_puppy_cfg(result, mode, force)
        result = self._import_agents(result, mode, force)
        result = self._import_skills(result, mode, force)

        return result

    # ── Scan phase ───────────────────────────────────────────────────────

    def _scan_for_forbidden(self, result: MigrationResult) -> MigrationResult:
        for rel_path in self._walk_dir(self.source_home, ""):
            if is_forbidden(rel_path):
                full = str(self.source_home / rel_path)
                result.refused.append((full, "forbidden by ADR-003 allowlist"))
        return result

    # ── Import phases ────────────────────────────────────────────────────

    def _import_extra_models(
        self,
        result: MigrationResult,
        mode: str,
        force: bool,
    ) -> MigrationResult:
        src = self.source_home / "extra_models.json"
        dst = self.target_home / "extra_models.json"
        return self._import_single_file(
            src, dst, "extra_models.json", mode, force, result
        )

    def _import_models_json(
        self,
        result: MigrationResult,
        mode: str,
        force: bool,
    ) -> MigrationResult:
        src = self.source_home / "models.json"
        dst = self.target_home / "models.json"

        if not src.exists():
            return result

        legacy_data = read_json(src)
        if legacy_data is None:
            return result

        existing_data = read_json(dst) if dst.exists() else {}
        if existing_data is None:
            existing_data = {}

        # Deep merge: existing values win (never overwrite newer state)
        merged = deep_merge_preserving_existing(existing_data, legacy_data)
        merged_json = json.dumps(merged, indent=2, sort_keys=True)

        if not force and dst.exists():
            result.skipped.append(
                (str(dst), "already exists; use --force to overwrite")
            )
            return result

        return self._maybe_write(dst, merged_json, mode, result)

    def _import_puppy_cfg(
        self,
        result: MigrationResult,
        mode: str,
        force: bool,
    ) -> MigrationResult:
        src = self.source_home / "puppy.cfg"
        dst = self.target_home / "puppy.cfg"

        if not src.exists():
            return result

        try:
            content = src.read_text(encoding="utf-8")
        except Exception as exc:
            result.errors.append(("puppy.cfg", str(exc)))
            return result

        # Extract only [ui] section; reject keys with secrets/paths
        safe_ui = extract_safe_ui(content)

        if not safe_ui:
            return result

        # Build destination config, merging safe [ui] keys
        existing_cfg = parse_ini(dst) if dst.exists() else {}
        existing_ui = existing_cfg.get("ui", {})

        if not force and existing_ui == safe_ui:
            result.skipped.append((str(dst), "ui section already matches"))
            return result

        if not force and existing_ui and dst.exists():
            result.skipped.append(
                (str(dst), "already exists; use --force to overwrite")
            )
            return result

        merged_config = {**existing_cfg, "ui": {**existing_ui, **safe_ui}}
        serialized = serialize_ini(merged_config)

        return self._maybe_write(dst, serialized, mode, result)

    def _import_agents(
        self,
        result: MigrationResult,
        mode: str,
        force: bool,
    ) -> MigrationResult:
        src_dir = self.source_home / "agents"
        dst_dir = self.target_home / "agents"

        if not src_dir.is_dir():
            return result

        return self._import_directory(
            src_dir, dst_dir, ".json", "agents", mode, force, result
        )

    def _import_skills(
        self,
        result: MigrationResult,
        mode: str,
        force: bool,
    ) -> MigrationResult:
        src_dir = self.source_home / "skills"
        dst_dir = self.target_home / "skills"

        if not src_dir.is_dir():
            return result

        try:
            entries = sorted(src_dir.iterdir())
        except OSError as exc:
            result.errors.append(("skills/", str(exc)))
            return result

        for entry in entries:
            if not entry.is_dir():
                continue

            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue

            dst_sub = dst_dir / entry.name
            result = self._copy_directory_tree(entry, dst_sub, mode, force, result)

        return result

    # ── File helpers ─────────────────────────────────────────────────────

    def _import_single_file(
        self,
        src: Path,
        dst: Path,
        label: str,
        mode: str,
        force: bool,
        result: MigrationResult,
    ) -> MigrationResult:
        if not src.exists():
            return result

        if not is_allowed(label):
            # Already handled by scan_for_forbidden
            return result

        try:
            content = src.read_text(encoding="utf-8")
        except Exception as exc:
            result.errors.append((label, str(exc)))
            return result

        if not force and dst.exists():
            result.skipped.append(
                (str(dst), "already exists; use --force to overwrite")
            )
            return result

        return self._maybe_write(dst, content, mode, result)

    def _import_directory(
        self,
        src_dir: Path,
        dst_dir: Path,
        ext_filter: str,
        prefix: str,
        mode: str,
        force: bool,
        result: MigrationResult,
    ) -> MigrationResult:
        try:
            entries = sorted(src_dir.iterdir())
        except OSError as exc:
            result.errors.append((f"{prefix}/", str(exc)))
            return result

        for entry in entries:
            if not entry.is_file() or entry.suffix != ext_filter:
                continue

            rel_path = f"{prefix}/{entry.name}"

            if not is_allowed(rel_path):
                continue

            dst_path = dst_dir / entry.name

            if not force and dst_path.exists():
                result.skipped.append((str(dst_path), "already exists"))
                continue

            try:
                content = entry.read_text(encoding="utf-8")
            except Exception as exc:
                result.errors.append((entry.name, str(exc)))
                continue

            result = self._maybe_write(dst_path, content, mode, result)

        return result

    def _copy_directory_tree(
        self,
        src_dir: Path,
        dst_dir: Path,
        mode: str,
        force: bool,
        result: MigrationResult,
    ) -> MigrationResult:
        if not force and dst_dir.is_dir():
            result.skipped.append(
                (str(dst_dir), "already exists; use --force to overwrite")
            )
            return result

        copied, errors, refused = self._walk_and_copy(src_dir, dst_dir, mode, force)

        result.copied.extend(copied)
        result.errors.extend(errors)
        result.refused.extend(refused)
        return result

    def _walk_and_copy(
        self,
        src_dir: Path,
        dst_dir: Path,
        mode: str,
        force: bool,
    ) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]:
        copied: list[str] = []
        errors: list[tuple[str, str]] = []
        refused: list[tuple[str, str]] = []

        try:
            entries = sorted(src_dir.iterdir())
        except OSError as exc:
            errors.append((str(src_dir), str(exc)))
            return copied, errors, refused

        for entry in entries:
            dst_path = dst_dir / entry.name

            if entry.is_dir():
                # ADR-003: skip forbidden subdirectories
                if is_forbidden(entry.name):
                    refused.append((str(entry), "forbidden directory by ADR-003"))
                    continue

                sub_copied, sub_errors, sub_refused = self._walk_and_copy(
                    entry, dst_path, mode, force
                )
                copied.extend(sub_copied)
                errors.extend(sub_errors)
                refused.extend(sub_refused)
            elif entry.is_file():
                # ADR-003: skip forbidden files
                if is_forbidden(entry.name):
                    refused.append((str(entry), "forbidden file by ADR-003"))
                    continue

                if not force and dst_path.exists():
                    continue

                try:
                    content = entry.read_text(encoding="utf-8")
                except Exception as exc:
                    errors.append((entry.name, str(exc)))
                    continue

                write_result = self._safe_maybe_write(dst_path, content, mode)
                if write_result == "ok":
                    copied.append(str(dst_path))
                elif write_result is not None:
                    errors.append((str(dst_path), write_result))

        return copied, errors, refused

    # ── Write helpers ────────────────────────────────────────────────────

    def _maybe_write(
        self,
        dst: Path,
        content: str,
        mode: str,
        result: MigrationResult,
    ) -> MigrationResult:
        """Write (or dry-run) a file and update the result."""
        if mode == "dry_run":
            result.copied.append(str(dst))
            return result

        # mode == "copy"
        write_err = self._safe_maybe_write(dst, content, mode)
        if write_err == "ok":
            result.copied.append(str(dst))
        elif write_err is not None:
            result.errors.append((str(dst), write_err))

        return result

    def _safe_maybe_write(self, dst: Path, content: str, mode: str) -> str | None:
        """Perform a guarded write.  Returns ``"ok"`` on success, ``None``
        on dry-run, or an error string on failure.
        """
        if mode == "dry_run":
            return None

        try:
            safe_mkdir_p(str(dst.parent))
            safe_write(str(dst), content)
            return "ok"
        except Exception as exc:
            return str(exc)

    # ── Directory walking ────────────────────────────────────────────────

    @staticmethod
    def _walk_dir(root: Path, prefix: str) -> list[str]:
        """Recursively walk *root*, yielding relative paths."""
        results: list[str] = []
        current = root / prefix if prefix else root

        try:
            entries = sorted(current.iterdir())
        except OSError:
            return results

        for entry in entries:
            rel = f"{prefix}/{entry.name}" if prefix else entry.name

            if entry.is_dir():
                results.extend(StateMigrator._walk_dir(root, rel))
            elif entry.is_file():
                results.append(rel)

        return results
