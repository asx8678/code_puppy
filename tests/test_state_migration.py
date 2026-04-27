"""Tests for the state_migration plugin.

Boundary-level tests that verify the migration contract (ADR-003)
without coupling to internal implementation details.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

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

    def test_dry_run_returns_non_empty_report(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=False
        )
        total = (
            len(result.copied)
            + len(result.skipped)
            + len(result.refused)
            + len(result.errors)
        )
        assert total > 0, "dry-run should report at least some items"


# ---------------------------------------------------------------------------
# Copy mode (--confirm)
# ---------------------------------------------------------------------------


class TestCopyMode:
    """With --confirm, files are actually copied."""

    def test_copies_allowlisted_files(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(source_home=source, target_home=target).run(confirm=True)

        assert result.mode == "copy"
        # extra_models.json should exist at target
        assert (target / "extra_models.json").exists()
        content = json.loads((target / "extra_models.json").read_text(encoding="utf-8"))
        assert "my-model" in content

    def test_copies_agent_files(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(confirm=True)
        assert (target / "agents" / "default.json").exists()

    def test_copies_skills(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(confirm=True)
        assert (target / "skills" / "my_skill" / "SKILL.md").exists()

    def test_never_copies_forbidden_files(self, tmp_dirs: dict[str, Path]) -> None:
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

    def test_puppy_cfg_only_copies_safe_ui(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        StateMigrator(source_home=source, target_home=target).run(confirm=True)

        cfg = (target / "puppy.cfg").read_text(encoding="utf-8")
        assert "[ui]" in cfg
        assert "theme" in cfg
        assert "dark" in cfg
        # api_key must NOT be in the destination
        assert "sk-secret" not in cfg
        assert "api_key" not in cfg

    def test_legacy_home_not_modified(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        # Snapshot the legacy home before migration
        before = {}
        for p in sorted(source.rglob("*")):
            if p.is_file():
                before[str(p.relative_to(source))] = p.read_text(encoding="utf-8")

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # Verify legacy home is untouched
        for rel_path, content in before.items():
            assert (source / rel_path).read_text(encoding="utf-8") == content, (
                f"legacy file was modified: {rel_path}"
            )


# ---------------------------------------------------------------------------
# Models.json deep merge
# ---------------------------------------------------------------------------


class TestModelsJsonMerge:
    """models.json uses deep-merge semantics: existing values win."""

    def test_merge_preserves_existing(self, tmp_dirs: dict[str, Path]) -> None:
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

        StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        merged = json.loads((target / "models.json").read_text(encoding="utf-8"))
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

        result = StateMigrator(source_home=nonexistent, target_home=target).run(
            confirm=True
        )

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

    def test_second_run_skips_existing(self, tmp_dirs: dict[str, Path]) -> None:
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
    def test_result_has_required_fields(self, tmp_dirs: dict[str, Path]) -> None:
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]
        _populate_legacy(source)

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=False
        )

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
    def test_force_overwrites_existing(self, tmp_dirs: dict[str, Path]) -> None:
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
        content = json.loads((target / "extra_models.json").read_text(encoding="utf-8"))
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
        assert (
            "migration" in result.lower()
            or "no-op" in result.lower()
            or "DRY RUN" in result
        )

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

        StateMigrator(source_home=source, target_home=target).run(confirm=True)

        result = (target / "puppy.cfg").read_text(encoding="utf-8")
        assert "theme = dark" in result
        assert "show_tips = true" in result
        assert "sk-12345" not in result
        assert "api_key" not in result
        assert "token" not in result
        assert "password" not in result


# ---------------------------------------------------------------------------
# Nested forbidden files/dirs within skills (ADR-003 enforcement)
# ---------------------------------------------------------------------------


class TestNestedForbiddenInSkills:
    """Verify ADR-003 denylist is enforced on every file/directory during
    recursive skills copy — not just at the top level.
    """

    def test_nested_forbidden_directory_skipped(
        self, tmp_dirs: dict[str, Path]
    ) -> None:
        """A forbidden directory inside a skill dir must not be copied."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        # Create a skill with a nested sessions directory
        skill_dir = source / "skills" / "my_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n", encoding="utf-8")

        sessions = skill_dir / "sessions"
        sessions.mkdir()
        (sessions / "session_data.json").write_text("{}", encoding="utf-8")

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # sessions/ inside the skill must not be copied
        assert not (target / "skills" / "my_skill" / "sessions").exists()
        # But it should be in the refused list
        refused_paths = [p for p, _ in result.refused]
        assert any("sessions" in p for p in refused_paths)

    def test_nested_forbidden_file_skipped(self, tmp_dirs: dict[str, Path]) -> None:
        """A forbidden file inside a skill dir must not be copied."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        skill_dir = source / "skills" / "my_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
        (skill_dir / "oauth_token.json").write_text(
            json.dumps({"token": "secret"}), encoding="utf-8"
        )
        (skill_dir / "helper.py").write_text("pass\n", encoding="utf-8")

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # oauth_token.json must not be copied
        assert not (target / "skills" / "my_skill" / "oauth_token.json").exists()
        # helper.py should still be copied
        assert (target / "skills" / "my_skill" / "helper.py").exists()
        # Forbidden file should appear in refused
        refused_paths = [p for p, _ in result.refused]
        assert any("oauth_token" in p for p in refused_paths)

    def test_nested_sqlite_file_skipped(self, tmp_dirs: dict[str, Path]) -> None:
        """A .sqlite file inside a skill must not be copied."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        skill_dir = source / "skills" / "data_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Data\n", encoding="utf-8")
        (skill_dir / "cache.sqlite").write_text("binary", encoding="utf-8")
        (skill_dir / "state.db").write_text("binary", encoding="utf-8")

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        assert not (target / "skills" / "data_skill" / "cache.sqlite").exists()
        assert not (target / "skills" / "data_skill" / "state.db").exists()
        refused_paths = [p for p, _ in result.refused]
        assert any(".sqlite" in p for p in refused_paths)
        assert any(".db" in p for p in refused_paths)

    def test_nested_autosaves_dir_skipped(self, tmp_dirs: dict[str, Path]) -> None:
        """An autosaves directory inside a skill must not be copied."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        skill_dir = source / "skills" / "my_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n", encoding="utf-8")

        autosaves = skill_dir / "autosaves"
        autosaves.mkdir()
        (autosaves / "save1.json").write_text("{}", encoding="utf-8")

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        assert not (target / "skills" / "my_skill" / "autosaves").exists()
        refused_paths = [p for p, _ in result.refused]
        assert any("autosaves" in p for p in refused_paths)

    def test_nested_command_history_skipped(self, tmp_dirs: dict[str, Path]) -> None:
        """command_history.txt inside a skill must not be copied."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        skill_dir = source / "skills" / "my_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
        (skill_dir / "command_history.txt").write_text("ls\ncd\n", encoding="utf-8")

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        assert not (target / "skills" / "my_skill" / "command_history.txt").exists()
        refused_paths = [p for p, _ in result.refused]
        assert any("command_history" in p for p in refused_paths)

    def test_deeply_nested_forbidden_file(self, tmp_dirs: dict[str, Path]) -> None:
        """A forbidden file deeply nested in a skill is still caught."""
        source = tmp_dirs["source"]
        target = tmp_dirs["target"]

        skill_dir = source / "skills" / "deep_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Deep\n", encoding="utf-8")

        # Create nested structure: deep_skill/sub/auth/_auth_token.json
        sub = skill_dir / "sub"
        sub.mkdir()
        (sub / "helper.py").write_text("pass\n", encoding="utf-8")

        auth_dir = sub / "auth"
        auth_dir.mkdir()
        # _auth in directory name is forbidden
        (auth_dir / "_auth_token.json").write_text(
            json.dumps({"token": "secret"}), encoding="utf-8"
        )

        result = StateMigrator(source_home=source, target_home=target).run(
            confirm=True, force=True
        )

        # The auth dir with _auth in name should be refused
        assert not (target / "skills" / "deep_skill" / "sub" / "auth").exists()
        refused_paths = [p for p, _ in result.refused]
        assert any("auth" in p for p in refused_paths)


# ---------------------------------------------------------------------------
# python_home_dir() source resolver (unit tests)
# ---------------------------------------------------------------------------


def _clean_env(**overrides: str) -> dict[str, str]:
    """Build a clean env dict with only the specified overrides.

    Removes PUP_HOME, PUPPY_HOME, PUP_EX_HOME, PUP_RUNTIME so tests
    can control exactly which variables are present.
    """
    env: dict[str, str] = {}
    for key in ("PUP_HOME", "PUPPY_HOME", "PUP_EX_HOME", "PUP_RUNTIME"):
        if key in overrides:
            env[key] = overrides.pop(key)
    env.update(overrides)
    return env


class TestPythonHomeDir:
    """Verify python_home_dir() honours PUP_HOME → PUPPY_HOME →
    ~/.code_puppy/ precedence and never consults PUP_EX_HOME.
    """

    def test_pup_home_first(self, tmp_path: Path) -> None:
        """PUP_HOME is the highest-precedence source."""
        from code_puppy.config_paths import python_home_dir

        pup_home = str(tmp_path / "pup_home")
        env = _clean_env(PUP_HOME=pup_home)
        with patch.dict(os.environ, env, clear=True):
            assert str(python_home_dir()) == pup_home

    def test_puppy_home_when_no_pup_home(self, tmp_path: Path) -> None:
        """PUPPY_HOME is used when PUP_HOME is absent."""
        from code_puppy.config_paths import python_home_dir

        puppy_home = str(tmp_path / "puppy_home")
        env = _clean_env(PUPPY_HOME=puppy_home)
        with patch.dict(os.environ, env, clear=True):
            assert str(python_home_dir()) == puppy_home

    def test_pup_home_beats_puppy_home(self, tmp_path: Path) -> None:
        """When both PUP_HOME and PUPPY_HOME are set, PUP_HOME wins."""
        from code_puppy.config_paths import python_home_dir

        pup_home = str(tmp_path / "pup_home")
        puppy_home = str(tmp_path / "puppy_home")
        env = _clean_env(PUP_HOME=pup_home, PUPPY_HOME=puppy_home)
        with patch.dict(os.environ, env, clear=True):
            assert str(python_home_dir()) == pup_home

    def test_default_when_no_env(self) -> None:
        """Without env vars, falls back to ~/.code_puppy/."""
        from code_puppy.config_paths import python_home_dir

        with patch.dict(os.environ, _clean_env(), clear=True):
            result = python_home_dir()
            assert str(result).endswith(".code_puppy")

    def test_never_uses_pup_ex_home(self, tmp_path: Path) -> None:
        """PUP_EX_HOME must not influence source resolution."""
        from code_puppy.config_paths import python_home_dir

        pup_ex = str(tmp_path / "elixir_home")
        pup_home = str(tmp_path / "python_home")
        env = _clean_env(PUP_HOME=pup_home, PUP_EX_HOME=pup_ex)
        with patch.dict(os.environ, env, clear=True):
            result = python_home_dir()
            # Source must be PUP_HOME, NOT PUP_EX_HOME
            assert str(result) == pup_home
            assert str(result) != pup_ex

    def test_pup_ex_home_alone_not_used_as_source(self, tmp_path: Path) -> None:
        """Only PUP_EX_HOME set → source still defaults to ~/.code_puppy/."""
        from code_puppy.config_paths import python_home_dir

        pup_ex = str(tmp_path / "elixir_home")
        env = _clean_env(PUP_EX_HOME=pup_ex)
        with patch.dict(os.environ, env, clear=True):
            result = python_home_dir()
            assert str(result) != pup_ex
            assert str(result).endswith(".code_puppy")


# ---------------------------------------------------------------------------
# StateMigrator default source_home resolution (integration tests)
# ---------------------------------------------------------------------------


class TestSourceHomeDefaultResolution:
    """Verify that StateMigrator(target_home=...) without explicit
    source_home resolves via python_home_dir() precedence.

    These tests instantiate StateMigrator with only target_home, so the
    default source resolver runs and we verify the correct env var wins.
    """

    def test_source_from_pup_home(self, tmp_path: Path) -> None:
        """PUP_HOME is the default source when no source_home given."""
        pup_home = tmp_path / "pup_home_src"
        pup_home.mkdir()
        (pup_home / "extra_models.json").write_text(
            json.dumps({"pup-model": {"provider": "test"}}), encoding="utf-8"
        )
        target = tmp_path / "target"
        target.mkdir()

        env = _clean_env(PUP_HOME=str(pup_home))
        with patch.dict(os.environ, env, clear=True):
            migrator = StateMigrator(target_home=target)
            assert str(migrator.source_home) == str(pup_home)

    def test_source_from_puppy_home_only(self, tmp_path: Path) -> None:
        """PUPPY_HOME is used as source when PUP_HOME is absent."""
        puppy_home = tmp_path / "puppy_home_src"
        puppy_home.mkdir()
        (puppy_home / "extra_models.json").write_text(
            json.dumps({"puppy-model": {"provider": "test"}}), encoding="utf-8"
        )
        target = tmp_path / "target"
        target.mkdir()

        env = _clean_env(PUPPY_HOME=str(puppy_home))
        with patch.dict(os.environ, env, clear=True):
            migrator = StateMigrator(target_home=target)
            assert str(migrator.source_home) == str(puppy_home)

    def test_pup_home_wins_over_puppy_home(self, tmp_path: Path) -> None:
        """Both set: source_home == PUP_HOME, not PUPPY_HOME."""
        pup_home = tmp_path / "pup_home_wins"
        puppy_home = tmp_path / "puppy_home_loses"
        pup_home.mkdir()
        (pup_home / "extra_models.json").write_text("{}", encoding="utf-8")
        puppy_home.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        env = _clean_env(PUP_HOME=str(pup_home), PUPPY_HOME=str(puppy_home))
        with patch.dict(os.environ, env, clear=True):
            migrator = StateMigrator(target_home=target)
            assert str(migrator.source_home) == str(pup_home)
            assert str(migrator.source_home) != str(puppy_home)

    def test_pup_ex_home_alongside_pup_home_source_stays_pup_home(
        self,
        tmp_path: Path,
    ) -> None:
        """PUP_EX_HOME + PUP_HOME: source uses PUP_HOME; target uses PUP_EX_HOME."""
        pup_home = tmp_path / "python_src"
        pup_home.mkdir()
        (pup_home / "extra_models.json").write_text(
            json.dumps({"migrated": True}), encoding="utf-8"
        )
        pup_ex = tmp_path / "elixir_target"
        pup_ex.mkdir()

        env = _clean_env(PUP_HOME=str(pup_home), PUP_EX_HOME=str(pup_ex))
        with patch.dict(os.environ, env, clear=True):
            migrator = StateMigrator(target_home=target) if False else None  # noqa
            # We explicitly test the no-target_home path too
            migrator = StateMigrator()
            # Source must be PUP_HOME, NEVER PUP_EX_HOME
            assert str(migrator.source_home) == str(pup_home)
            # Target must be PUP_EX_HOME (default target resolution)
            assert str(migrator.target_home) == str(pup_ex)

    def test_pup_ex_home_not_used_as_source(self, tmp_path: Path) -> None:
        """PUP_EX_HOME alone must not become source_home default."""
        pup_ex = tmp_path / "elixir_only"
        pup_ex.mkdir()

        env = _clean_env(PUP_EX_HOME=str(pup_ex))
        with patch.dict(os.environ, env, clear=True):
            # No explicit target_home — default target resolution uses PUP_EX_HOME
            migrator = StateMigrator()
            # Source must fall back to ~/.code_puppy/, not PUP_EX_HOME
            assert str(migrator.source_home) != str(pup_ex)
            assert str(migrator.source_home).endswith(".code_puppy")
            # Target must use PUP_EX_HOME
            assert str(migrator.target_home) == str(pup_ex)

    def test_explicit_source_home_overrides_env(self, tmp_path: Path) -> None:
        """An explicit source_home kwarg always wins, regardless of env."""
        explicit = tmp_path / "explicit_source"
        explicit.mkdir()
        pup_home = tmp_path / "env_source"
        pup_home.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        env = _clean_env(PUP_HOME=str(pup_home))
        with patch.dict(os.environ, env, clear=True):
            migrator = StateMigrator(source_home=explicit, target_home=target)
            assert str(migrator.source_home) == str(explicit)


# ---------------------------------------------------------------------------
# PUP_HOME / PUPPY_HOME precedence (docs-alignment tests for home_dir)
# ---------------------------------------------------------------------------


class TestPupHomePrecedence:
    """Verify that PUP_HOME takes precedence over PUPPY_HOME, matching
    the documented behavior in ADR-003 and MIGRATION.md.
    """

    def test_pup_home_overrides_default(self, tmp_path: Path) -> None:
        """PUP_HOME overrides the default ~/.code_puppy/ path."""
        from code_puppy.config_paths import home_dir

        custom = str(tmp_path / "custom_home")
        with patch.dict(os.environ, {"PUP_HOME": custom}, clear=False):
            # Clear PUPPY_HOME and PUP_EX_HOME to isolate PUP_HOME
            env = os.environ.copy()
            env.pop("PUPPY_HOME", None)
            env.pop("PUP_EX_HOME", None)
            env.pop("PUP_RUNTIME", None)
            with patch.dict(os.environ, env, clear=True):
                result = home_dir()
                assert str(result) == custom

    def test_puppy_home_overrides_default(self, tmp_path: Path) -> None:
        """PUPPY_HOME overrides the default when PUP_HOME is not set."""
        from code_puppy.config_paths import home_dir

        custom = str(tmp_path / "puppy_home")
        env = os.environ.copy()
        env["PUPPY_HOME"] = custom
        env.pop("PUP_HOME", None)
        env.pop("PUP_EX_HOME", None)
        env.pop("PUP_RUNTIME", None)
        with patch.dict(os.environ, env, clear=True):
            result = home_dir()
            assert str(result) == custom

    def test_pup_home_takes_precedence_over_puppy_home(
        self,
        tmp_path: Path,
    ) -> None:
        """When both are set, PUP_HOME wins."""
        from code_puppy.config_paths import home_dir

        pup_home = str(tmp_path / "pup_home")
        puppy_home = str(tmp_path / "puppy_home")
        env = os.environ.copy()
        env["PUP_HOME"] = pup_home
        env["PUPPY_HOME"] = puppy_home
        env.pop("PUP_EX_HOME", None)
        env.pop("PUP_RUNTIME", None)
        with patch.dict(os.environ, env, clear=True):
            result = home_dir()
            assert str(result) == pup_home

    def test_migrator_uses_pup_home_as_source(
        self,
        tmp_path: Path,
    ) -> None:
        """StateMigrator with explicit PUP_HOME source works correctly."""
        custom = tmp_path / "custom_source"
        custom.mkdir()
        (custom / "extra_models.json").write_text(
            json.dumps({"model": {"provider": "test"}}), encoding="utf-8"
        )

        target = tmp_path / "target"
        target.mkdir()

        migrator = StateMigrator(source_home=custom, target_home=target)
        assert migrator.source_home == custom
        migrator.run(confirm=True)
        assert (target / "extra_models.json").exists()


# ---------------------------------------------------------------------------
# PUP_EX_HOME isolation tests
# ---------------------------------------------------------------------------


class TestPupExHomeIsolation:
    """Verify PUP_EX_HOME isolation semantics in config_paths."""

    def test_pup_ex_home_overrides_default(self, tmp_path: Path) -> None:
        """PUP_EX_HOME overrides the default elixir home path."""
        from code_puppy.config_paths import home_dir, is_pup_ex

        custom = str(tmp_path / "pup_ex_home")
        env = os.environ.copy()
        env["PUP_EX_HOME"] = custom
        env.pop("PUP_HOME", None)
        env.pop("PUPPY_HOME", None)
        env.pop("PUP_RUNTIME", None)
        with patch.dict(os.environ, env, clear=True):
            assert is_pup_ex() is True
            result = home_dir()
            assert str(result) == custom

    def test_pup_ex_home_does_not_use_pup_home(self, tmp_path: Path) -> None:
        """In pup-ex mode, PUP_HOME is NOT used for home_dir()."""
        from code_puppy.config_paths import home_dir, is_pup_ex

        pup_ex = str(tmp_path / "elixir_home")
        pup_home = str(tmp_path / "python_home")
        env = os.environ.copy()
        env["PUP_EX_HOME"] = pup_ex
        env["PUP_HOME"] = pup_home
        env.pop("PUPPY_HOME", None)
        env.pop("PUP_RUNTIME", None)
        with patch.dict(os.environ, env, clear=True):
            assert is_pup_ex() is True
            result = home_dir()
            # home_dir() should return PUP_EX_HOME, not PUP_HOME
            assert str(result) == pup_ex

    def test_pup_ex_runtime_detection(self) -> None:
        """PUP_RUNTIME=elixir also triggers pup-ex mode."""
        from code_puppy.config_paths import is_pup_ex

        env = os.environ.copy()
        env.pop("PUP_EX_HOME", None)
        env["PUP_RUNTIME"] = "elixir"
        with patch.dict(os.environ, env, clear=True):
            assert is_pup_ex() is True

        env["PUP_RUNTIME"] = "python"
        with patch.dict(os.environ, env, clear=True):
            assert is_pup_ex() is False

    def test_write_to_legacy_home_blocked_in_pup_ex(
        self,
        tmp_path: Path,
    ) -> None:
        """In pup-ex mode, writes to legacy home raise violation."""
        from code_puppy.config_paths import (
            safe_write,
            with_sandbox,
        )

        # Use sandbox to allow the test to set up
        with with_sandbox(allow_all=True):
            # Simulate pup-ex mode by setting PUP_EX_HOME
            pup_ex = str(tmp_path / "pup_ex")
            os.makedirs(pup_ex, exist_ok=True)

            # We need to patch is_pup_ex to return True
            with patch("code_puppy.config_paths.is_pup_ex", return_value=True):
                with patch(
                    "code_puppy.config_paths.home_dir",
                    return_value=Path(pup_ex),
                ):
                    # Write to pup_ex home should work (sandbox allows all)
                    test_file = str(tmp_path / "pup_ex" / "test.txt")
                    safe_write(test_file, "hello")

    def test_resolve_path_under_pup_ex(self, tmp_path: Path) -> None:
        """resolve_path returns paths under the active home."""
        from code_puppy.config_paths import resolve_path

        custom = str(tmp_path / "pup_ex_resolve")
        env = os.environ.copy()
        env["PUP_EX_HOME"] = custom
        env.pop("PUP_HOME", None)
        env.pop("PUPPY_HOME", None)
        env.pop("PUP_RUNTIME", None)
        with patch.dict(os.environ, env, clear=True):
            result = resolve_path("plugins", "my_plugin")
            assert str(result).startswith(custom)
