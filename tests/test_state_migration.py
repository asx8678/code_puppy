"""Tests for the state_migration plugin.

Boundary-level tests that verify the migration contract (ADR-003)
without coupling to internal implementation details.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_puppy.plugins.state_migration.migrator import (
    StateMigrator,
)
from code_puppy.plugins.state_migration._adr_predicates import (
    is_allowed,
    is_forbidden,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create temporary source (legacy) and target (elixir) homes."""
    source = tmp_path / "legacy_home"
    target = tmp_path / "elixir_home"
    source.mkdir()
    target.mkdir()
    return {"source": source, "target": target}


def _populate_legacy(source: Path) -> None:
    """Create a realistic legacy home directory for testing."""
    # extra_models.json
    (source / "extra_models.json").write_text(
        json.dumps({"my-model": {"provider": "openai"}}), encoding="utf-8"
    )

    # models.json
    (source / "models.json").write_text(
        json.dumps({"models": [{"id": "gpt-4"}]}), encoding="utf-8"
    )

    # puppy.cfg
    (source / "puppy.cfg").write_text(
        "[ui]\ntheme = dark\nshow_tips = true\n\n[puppy]\nmodel = gpt-5\napi_key = sk-secret\n",
        encoding="utf-8",
    )

    # agents
    agents = source / "agents"
    agents.mkdir()
    (agents / "default.json").write_text(
        json.dumps({"name": "default"}), encoding="utf-8"
    )

    # skills
    skills = source / "skills"
    skill_dir = skills / "my_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# My Skill\n", encoding="utf-8")
    (skill_dir / "helper.py").write_text("pass\n", encoding="utf-8")

    # Forbidden files (should never be copied)
    (source / "oauth_token.json").write_text(
        json.dumps({"token": "secret"}), encoding="utf-8"
    )
    (source / "github_auth.json").write_text(
        json.dumps({"auth": "secret"}), encoding="utf-8"
    )
    (source / "dbos_store.sqlite").write_text("binary_data", encoding="utf-8")
    (source / "command_history.txt").write_text("ls\ncd\n", encoding="utf-8")

    sessions = source / "sessions"
    sessions.mkdir()
    (sessions / "session_1.json").write_text("{}", encoding="utf-8")

    autosaves = source / "autosaves"
    autosaves.mkdir()
    (autosaves / "save1.json").write_text("{}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Allowlist / Denylist predicates (ADR-003 contract)
# ---------------------------------------------------------------------------


class TestAllowlistPredicates:
    """Test the ADR-003 allowlist contract.

    These test the *invariant* (allowlist/denylist semantics), not the
    implementation of the predicate functions.
    """

    @pytest.mark.parametrize(
        "rel_path",
        [
            "extra_models.json",
            "models.json",
            "puppy.cfg",
            "agents/code_puppy.json",
            "agents/custom.json",
            "skills/my_skill/SKILL.md",
            "skills/other/helper.py",
        ],
    )
    def test_allowed_sources(self, rel_path: str) -> None:
        assert is_allowed(rel_path), f"{rel_path} should be allowed"

    @pytest.mark.parametrize(
        "rel_path",
        [
            "oauth_token.json",
            "github_auth.json",
            "my_auth_backup.json",
            "dbos_store.sqlite",
            "cache.db",
            "command_history.txt",
            "autosaves/save1.json",
            "sessions/session_1.json",
            "random_file.txt",
            "README.md",
        ],
    )
    def test_forbidden_or_denied_sources(self, rel_path: str) -> None:
        # These should either be explicitly forbidden or default-denied
        assert not is_allowed(rel_path), f"{rel_path} should NOT be allowed"

    @pytest.mark.parametrize(
        "rel_path",
        [
            "oauth_token.json",
            "github_auth.json",
            "dbos_store.sqlite",
            "cache.db",
            "command_history.txt",
            "autosaves/save1.json",
            "sessions/session_1.json",
        ],
    )
    def test_explicitly_forbidden(self, rel_path: str) -> None:
        assert is_forbidden(rel_path), f"{rel_path} should be forbidden"


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


class TestDryRunMode:
    """Dry-run must produce a report but write ZERO files."""

    def test_dry_run_writes_nothing(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        migrator = StateMigrator(source_home=source, target_home=target)
        result = migrator.run(confirm=False)

        assert result.mode == "dry_run"
        # Target directory should have no migrated files
        # (the target dir itself exists from the fixture, but no content)
        for item in target.iterdir():
            # Only the fixture-created empty dir should be here
            assert not item.is_file(), f"dry-run wrote file: {item}"

    def test_dry_run_returns_non_empty_report(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=False
        )
        total = len(result.copied) + len(result.skipped) + len(
            result.refused
        ) + len(result.errors)
        assert total > 0, "dry-run should report at least some items"


# ---------------------------------------------------------------------------
# Copy mode (--confirm)
# ---------------------------------------------------------------------------


class TestCopyMode:
    """With --confirm, files are actually copied."""

    def test_copies_allowlisted_files(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(
            source_home=source, target_home=target
        ).run(confirm=True)

        assert result.mode == "copy"
        # extra_models.json should exist at target
        assert (target / "extra_models.json").exists()
        content = json.loads(
            (target / "extra_models.json").read_text(encoding="utf-8")
        )
        assert "my-model" in content

    def test_copies_agent_files(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True
        )
        assert (target / "agents" / "default.json").exists()

    def test_copies_skills(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True
        )
        assert (target / "skills" / "my_skill" / "SKILL.md").exists()

    def test_never_copies_forbidden_files(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # None of these should exist at the target
        assert not (target / "oauth_token.json").exists()
        assert not (target / "github_auth.json").exists()
        assert not (target / "dbos_store.sqlite").exists()
        assert not (target / "command_history.txt").exists()
        assert not (target / "sessions").exists()
        assert not (target / "autosaves").exists()

    def test_puppy_cfg_only_copies_safe_ui(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True
        )

        cfg = (target / "puppy.cfg").read_text(encoding="utf-8")
        assert "[ui]" in cfg
        assert "theme" in cfg
        assert "dark" in cfg
        # api_key must NOT be in the destination
        assert "sk-secret" not in cfg
        assert "api_key" not in cfg

    def test_legacy_home_not_modified(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        # Snapshot the legacy home before migration
        before = {}
        for p in sorted(source.rglob("*")):
            if p.is_file():
                before[str(p.relative_to(source))] = p.read_text(
                    encoding="utf-8"
                )

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # Verify legacy home is untouched
        for rel_path, content in before.items():
            assert (source / rel_path).read_text(
                encoding="utf-8"
            ) == content, f"legacy file was modified: {rel_path}"


# ---------------------------------------------------------------------------
# Models.json deep merge
# ---------------------------------------------------------------------------


class TestModelsJsonMerge:
    """models.json uses deep-merge semantics: existing values win."""

    def test_merge_preserves_existing(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        # Legacy: has model "gpt-4"
        (source / "models.json").write_text(
            json.dumps({"models": [{"id": "gpt-4"}], "version": "legacy"}),
            encoding="utf-8",
        )

        # Target: already has model "gpt-5" and a newer version
        (target / "models.json").write_text(
            json.dumps({"models": [{"id": "gpt-5"}], "version": "newer"}),
            encoding="utf-8",
        )

        StateMigrator(
            source_home=source, target_home=target
        ).run(confirm=True, force=True)

        merged = json.loads(
            (target / "models.json").read_text(encoding="utf-8")
        )
        # "newer" version should win (existing preserved)
        assert merged["version"] == "newer"


# ---------------------------------------------------------------------------
# No-op when no legacy home
# ---------------------------------------------------------------------------


class TestNoOp:
    def test_no_op_when_source_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent"
        target = tmp_path / "target"
        target.mkdir()

        result = StateMigrator(
            source_home=nonexistent, target_home=target
        ).run(confirm=True)

        assert result.mode == "no_op"
        assert result.copied == []
        assert result.skipped == []
        assert result.refused == []
        assert result.errors == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running --confirm twice should be safe; second run skips existing."""

    def test_second_run_skips_existing(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        migrator = StateMigrator(source_home=source, target_home=target)

        # First run
        result1 = migrator.run(confirm=True)
        assert len(result1.copied) > 0

        # Second run (without --force)
        result2 = migrator.run(confirm=True)
        # Files should be skipped, not re-copied
        assert len(result2.skipped) > 0


# ---------------------------------------------------------------------------
# Result shape (structural contract)
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_result_has_required_fields(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(
            source_home=source, target_home=target
        ).run(confirm=False)

        assert hasattr(result, "mode")
        assert hasattr(result, "copied")
        assert hasattr(result, "skipped")
        assert hasattr(result, "refused")
        assert hasattr(result, "errors")
        assert result.mode in ("dry_run", "copy", "no_op")


# ---------------------------------------------------------------------------
# --force flag
# ---------------------------------------------------------------------------


class TestForceFlag:
    def test_force_overwrites_existing(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        migrator = StateMigrator(source_home=source, target_home=target)

        # First run
        migrator.run(confirm=True)

        # Modify source to have different content
        (source / "extra_models.json").write_text(
            json.dumps({"updated-model": {"provider": "anthropic"}}),
            encoding="utf-8",
        )

        # Second run with --force should overwrite
        migrator.run(confirm=True, force=True)
        content = json.loads(
            (target / "extra_models.json").read_text(encoding="utf-8")
        )
        assert "updated-model" in content


# ---------------------------------------------------------------------------
# Custom command handler (boundary test)
# ---------------------------------------------------------------------------


class TestCustomCommand:
    """Test the /migrate custom command hook at boundary level."""

    def test_migrate_command_returns_report(self) -> None:
        from code_puppy.plugins.state_migration.register_callbacks import (
            _handle_migrate,
        )

        # /migrate without --confirm should return a string report
        result = _handle_migrate("/migrate", "migrate")
        assert result is not None
        assert isinstance(result, str)
        assert "migration" in result.lower() or "no-op" in result.lower() or "DRY RUN" in result

    def test_migrate_command_ignores_other_commands(self) -> None:
        from code_puppy.plugins.state_migration.register_callbacks import (
            _handle_migrate,
        )

        result = _handle_migrate("/other", "other")
        assert result is None

    def test_migrate_help_returns_entries(self) -> None:
        from code_puppy.plugins.state_migration.register_callbacks import (
            _migrate_help,
        )

        entries = _migrate_help()
        assert len(entries) > 0
        assert any("/migrate" in name for name, _ in entries)


# ---------------------------------------------------------------------------
# Forbidden key filtering in puppy.cfg
# ---------------------------------------------------------------------------


class TestPuppyCfgKeyFiltering:
    """Verify that secret/path keys are stripped from [ui] section."""

    def test_forbidden_keys_stripped(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        cfg = (
            "[ui]\n"
            "theme = dark\n"
            "api_key = sk-12345\n"
            "token = my_token\n"
            "password = hunter2\n"
            "show_tips = true\n"
        )
        (source / "puppy.cfg").write_text(cfg, encoding="utf-8")

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True
        )

        result = (target / "puppy.cfg").read_text(encoding="utf-8")
        assert "theme = dark" in result
        assert "show_tips = true" in result
        assert "sk-12345" not in result
        assert "api_key" not in result
        assert "token" not in result
        assert "password" not in result
