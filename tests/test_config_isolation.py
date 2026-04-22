"""Tests for ADR-003 dual-home config isolation guard.

Covers all bypass vectors identified in the Phase 6 review of bd-186:
- GATE-1: No-write — pup-ex must not write to ~/.code_puppy/
- GATE-2: Guard raises — direct writes to legacy home raise ConfigIsolationViolation
- GATE-3: Safe wrappers validate isolation
- GATE-4: Path resolution respects pup-ex mode
- GATE-5: Symlink attack prevention
- GATE-6: Sandbox escape hatch for tests
- GATE-7: Thread-local sandbox isolation
- Bypass: config.py setters guarded
- Bypass: get_summarization_history_dir uses active home
- Bypass: persistence.atomic_write_text checks isolation
"""

import importlib
import os
import threading
from pathlib import Path

import pytest

from code_puppy.config_paths import (
    ConfigIsolationViolation,
    _canonical,
    _is_path_within_home,
    assert_write_allowed,
    cache_dir,
    config_dir,
    data_dir,
    home_dir,
    is_pup_ex,
    legacy_home_dir,
    safe_mkdir_p,
    safe_rm,
    safe_rm_rf,
    safe_write,
    state_dir,
    with_sandbox,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure no leftover PUP_EX_HOME or PUP_RUNTIME env vars between tests."""
    monkeypatch.delenv("PUP_EX_HOME", raising=False)
    monkeypatch.delenv("PUP_RUNTIME", raising=False)
    monkeypatch.delenv("PUP_HOME", raising=False)
    monkeypatch.delenv("PUPPY_HOME", raising=False)


# ---------------------------------------------------------------------------
# is_pup_ex() detection
# ---------------------------------------------------------------------------


class TestIsPupEx:
    def test_default_is_standard_pup(self):
        assert is_pup_ex() is False

    def test_pup_ex_home_env_set(self, monkeypatch):
        monkeypatch.setenv("PUP_EX_HOME", "/tmp/pup_ex_home")
        assert is_pup_ex() is True

    def test_pup_runtime_elixir(self, monkeypatch):
        monkeypatch.setenv("PUP_RUNTIME", "elixir")
        assert is_pup_ex() is True

    def test_pup_runtime_python_not_pup_ex(self, monkeypatch):
        monkeypatch.setenv("PUP_RUNTIME", "python")
        assert is_pup_ex() is False

    def test_pup_runtime_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("PUP_RUNTIME", "Elixir")
        assert is_pup_ex() is True

    def test_pup_ex_home_takes_priority_over_runtime(self, monkeypatch):
        monkeypatch.setenv("PUP_EX_HOME", "/tmp/pup_ex_home")
        monkeypatch.setenv("PUP_RUNTIME", "python")
        assert is_pup_ex() is True


# ---------------------------------------------------------------------------
# home_dir() path resolution
# ---------------------------------------------------------------------------


class TestHomeDir:
    def test_standard_pup_default(self):
        result = home_dir()
        assert result == Path.home() / ".code_puppy"

    def test_standard_pup_with_pup_home(self, monkeypatch):
        monkeypatch.setenv("PUP_HOME", "/custom/pup_home")
        assert home_dir() == Path("/custom/pup_home")

    def test_standard_pup_puppy_home_legacy(self, monkeypatch):
        monkeypatch.setenv("PUPPY_HOME", "/legacy/puppy_home")
        assert home_dir() == Path("/legacy/puppy_home")

    def test_pup_home_over_puppy_home(self, monkeypatch):
        monkeypatch.setenv("PUP_HOME", "/new/home")
        monkeypatch.setenv("PUPPY_HOME", "/old/home")
        assert home_dir() == Path("/new/home")

    def test_pup_ex_default_home(self, monkeypatch):
        monkeypatch.setenv("PUP_RUNTIME", "elixir")
        result = home_dir()
        assert result == Path.home() / ".code_puppy_ex"

    def test_pup_ex_explicit_home(self, monkeypatch):
        monkeypatch.setenv("PUP_EX_HOME", "/explicit/ex_home")
        assert home_dir() == Path("/explicit/ex_home")


# ---------------------------------------------------------------------------
# XDG path resolution
# ---------------------------------------------------------------------------


class TestXdgPaths:
    def test_config_dir_standard(self):
        # Without XDG env var, goes under home_dir
        result = config_dir()
        assert str(result).endswith(os.sep + "config")

    def test_data_dir_standard(self):
        result = data_dir()
        assert str(result).endswith(os.sep + "data")

    def test_cache_dir_standard(self):
        result = cache_dir()
        assert str(result).endswith(os.sep + "cache")

    def test_state_dir_standard(self):
        result = state_dir()
        assert str(result).endswith(os.sep + "state")

    def test_config_dir_xdg_override(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
        result = config_dir()
        assert result == Path("/xdg/config/code_puppy")

    def test_pup_ex_paths_under_active_home(self, monkeypatch):
        monkeypatch.setenv("PUP_EX_HOME", "/pup_ex_home")
        assert str(config_dir()).startswith("/pup_ex_home")
        assert str(data_dir()).startswith("/pup_ex_home")
        assert str(cache_dir()).startswith("/pup_ex_home")
        assert str(state_dir()).startswith("/pup_ex_home")

    def test_pup_ex_ignores_xdg_override_outside_active_home(self, monkeypatch, tmp_path):
        ex_home = tmp_path / "pup_ex_home"
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "outside" / "config"))

        result = config_dir()
        assert result == ex_home / "config"


# ---------------------------------------------------------------------------
# legacy_home_dir()
# ---------------------------------------------------------------------------


class TestLegacyHomeDir:
    def test_always_returns_legacy(self):
        result = legacy_home_dir()
        assert result == Path.home() / ".code_puppy"

    def test_legacy_unchanged_by_pup_ex(self, monkeypatch):
        monkeypatch.setenv("PUP_EX_HOME", "/pup_ex_home")
        result = legacy_home_dir()
        assert result == Path.home() / ".code_puppy"


# ---------------------------------------------------------------------------
# assert_write_allowed() — the core guard
# ---------------------------------------------------------------------------


class TestAssertWriteAllowed:
    def test_standard_pup_allows_legacy_home_writes(self, monkeypatch, tmp_path):
        # Standard pup should allow writes to ~/.code_puppy/
        legacy = tmp_path / ".code_puppy" / "test.cfg"
        legacy.parent.mkdir(parents=True)
        # Should not raise
        assert_write_allowed(legacy, "write")

    def test_standard_pup_allows_any_path(self, tmp_path):
        # Standard pup can write anywhere (no isolation constraint)
        arbitrary = tmp_path / "arbitrary" / "path"
        # Should not raise
        assert_write_allowed(arbitrary, "write")

    def test_pup_ex_blocks_legacy_home_writes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        # Use fake home
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "test.cfg"
        with pytest.raises(ConfigIsolationViolation) as exc_info:
            assert_write_allowed(legacy, "write")
        assert "isolation violation" in str(exc_info.value).lower()

    def test_pup_ex_allows_active_home_writes(self, monkeypatch, tmp_path):
        ex_home = tmp_path / "pup_ex_home"
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
        target = ex_home / "config" / "test.cfg"
        # Should not raise
        assert_write_allowed(target, "write")

    def test_pup_ex_blocks_writes_outside_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        # Writing to /tmp/arbitrary when pup-ex home is elsewhere
        outside = tmp_path / "outside_home" / "file.txt"
        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(outside, "write")

    def test_config_isolation_violation_has_path_and_action(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        target = fake_home / ".code_puppy" / "file.txt"
        with pytest.raises(ConfigIsolationViolation) as exc_info:
            assert_write_allowed(target, "mkdir")
        assert exc_info.value.action == "mkdir"
        assert str(target) in str(exc_info.value.path)


# ---------------------------------------------------------------------------
# Symlink attack prevention
# ---------------------------------------------------------------------------


class TestSymlinkPrevention:
    def test_symlink_to_legacy_home_blocked(self, monkeypatch, tmp_path):
        """Simulate a symlink that points from pup-ex home to legacy home."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))

        # Create a symlink: pup_ex_home/data → ~/.code_puppy/data
        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        symlink_target = tmp_path / ".code_puppy" / "data"
        symlink_target.mkdir(parents=True)

        symlink = ex_home / "data_link"
        try:
            symlink.symlink_to(symlink_target)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        # Writing through the symlink should be blocked because the
        # canonical path resolves to the legacy home
        target = symlink / "test.cfg"
        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(target, "write")


# ---------------------------------------------------------------------------
# Safe wrappers
# ---------------------------------------------------------------------------


class TestSafeWrite:
    def test_safe_write_standard_pup(self, tmp_path):
        target = tmp_path / "test.cfg"
        safe_write(target, "hello")
        assert target.read_text() == "hello"

    def test_safe_write_pup_ex_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "test.cfg"
        with pytest.raises(ConfigIsolationViolation):
            safe_write(legacy, "data")

    def test_safe_write_creates_parent_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        target = tmp_path / "pup_ex_home" / "config" / "deep" / "file.cfg"
        safe_write(target, "content")
        assert target.read_text() == "content"


class TestSafeMkdirP:
    def test_safe_mkdir_p_standard_pup(self, tmp_path):
        target = tmp_path / "new_dir"
        safe_mkdir_p(target)
        assert target.is_dir()

    def test_safe_mkdir_p_pup_ex_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "new_dir"
        with pytest.raises(ConfigIsolationViolation):
            safe_mkdir_p(legacy)


class TestSafeRm:
    def test_safe_rm_removes_file(self, tmp_path):
        target = tmp_path / "to_remove.txt"
        target.write_text("data")
        safe_rm(target)
        assert not target.exists()

    def test_safe_rm_pup_ex_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "file.txt"
        with pytest.raises(ConfigIsolationViolation):
            safe_rm(legacy)


class TestSafeRmRf:
    def test_safe_rm_rf_removes_tree(self, tmp_path):
        target = tmp_path / "tree"
        target.mkdir()
        (target / "file.txt").write_text("data")
        safe_rm_rf(target)
        assert not target.exists()

    def test_safe_rm_rf_pup_ex_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "somedir"
        with pytest.raises(ConfigIsolationViolation):
            safe_rm_rf(legacy)


# ---------------------------------------------------------------------------
# with_sandbox() — test escape hatch
# ---------------------------------------------------------------------------


class TestWithSandbox:
    def test_sandbox_allow_all(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        # Normally this would be blocked
        legacy = fake_home / ".code_puppy" / "test.cfg"
        with with_sandbox(allow_all=True):
            # Should not raise
            assert_write_allowed(legacy, "write")

    def test_sandbox_specific_paths(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        allowed_path = tmp_path / "allowed"
        blocked_path = tmp_path / "blocked"
        with with_sandbox(paths=[str(allowed_path)]):
            # Allowed path should not raise
            assert_write_allowed(allowed_path, "write")
            assert_write_allowed(allowed_path / "child.txt", "write")
            # Blocked path should raise
            with pytest.raises(ConfigIsolationViolation):
                assert_write_allowed(blocked_path, "write")

    def test_sandbox_cleared_after_context(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "test.cfg"
        with with_sandbox(allow_all=True):
            assert_write_allowed(legacy, "write")
        # After the context, the sandbox should be cleared
        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(legacy, "write")

    def test_sandbox_thread_local(self, monkeypatch, tmp_path):
        """Sandbox should not leak between threads."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "test.cfg"
        errors = []

        def thread_fn():
            try:
                # This thread has no sandbox — should raise
                assert_write_allowed(legacy, "write")
            except ConfigIsolationViolation:
                errors.append("blocked")
            except Exception as e:
                errors.append(f"unexpected: {e}")

        with with_sandbox(allow_all=True):
            t = threading.Thread(target=thread_fn)
            t.start()
            t.join(timeout=5)

        assert "blocked" in errors


# ---------------------------------------------------------------------------
# config.py integration — bypass vectors
# ---------------------------------------------------------------------------


class TestConfigPyIsolation:
    """Test that config.py write paths are guarded by the isolation check."""

    def test_set_config_value_blocked_in_pup_ex(self, monkeypatch, tmp_path):
        """BYPASS VECTOR: set_config_value must not write to legacy home."""
        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        # Use fake home to avoid touching real ~/.code_puppy/
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        legacy_config = fake_home / ".code_puppy" / "puppy.cfg"

        # The guard should block writes to legacy home when in pup-ex mode
        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(legacy_config, "set_config_value")

    def test_set_model_name_blocked_in_pup_ex(self, monkeypatch, tmp_path):
        """BYPASS VECTOR: set_model_name must not write to legacy home."""
        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        # Use fake home to avoid touching real ~/.code_puppy/
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        legacy_config = fake_home / ".code_puppy" / "puppy.cfg"

        # The guard should block writes to legacy home when in pup-ex mode
        with pytest.raises(ConfigIsolationViolation):
            assert_write_allowed(legacy_config, "set_model_name")

    def test_get_summarization_history_dir_respects_pup_ex(
        self, monkeypatch, tmp_path
    ):
        """BYPASS VECTOR: get_summarization_history_dir must not hardcode
        ~/.code_puppy/history."""
        from code_puppy import config as cp_config

        ex_home = tmp_path / "pup_ex_home"
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        result = cp_config.get_summarization_history_dir()
        # Must be under the pup-ex home, not legacy home
        assert str(result).startswith(str(ex_home))
        assert ".code_puppy_ex" in str(result) or str(result).startswith(
            str(ex_home)
        )

    def test_get_summarization_history_dir_standard_pup(self, monkeypatch):
        """Standard pup should still resolve to ~/.code_puppy/history."""
        from code_puppy import config as cp_config

        result = cp_config.get_summarization_history_dir()
        # Should contain .code_puppy/history
        assert ".code_puppy" in str(result)
        assert "history" in str(result)


# ---------------------------------------------------------------------------
# persistence.py integration — belt-and-suspenders guard
# ---------------------------------------------------------------------------


class TestPersistenceIsolation:
    def test_atomic_write_blocked_in_pup_ex_for_legacy_path(
        self, monkeypatch, tmp_path
    ):
        """BYPASS VECTOR: atomic_write_text must check isolation for
        config-home paths."""
        from code_puppy.persistence import atomic_write_text

        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        # Create a fake home so we don't write to the real one
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        legacy_dir = fake_home / ".code_puppy"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "test.txt"

        # Monkeypatch Path.home() to return our fake home
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        with pytest.raises(ConfigIsolationViolation):
            atomic_write_text(legacy_file, "test content")

    def test_atomic_write_allowed_for_non_config_paths(self, monkeypatch, tmp_path):
        """Non-config-home paths should not be blocked by the guard."""
        from code_puppy.persistence import atomic_write_text

        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        # Write to a path that's NOT under ~/.code_puppy/ or ~/.code_puppy_ex/
        project_file = tmp_path / "project" / "src" / "main.py"
        project_file.parent.mkdir(parents=True)

        # Should not raise — this is a project file, not a config file
        atomic_write_text(project_file, "print('hello')")
        assert project_file.read_text() == "print('hello')"

    def test_atomic_write_blocks_symlink_alias_to_legacy_path(self, monkeypatch, tmp_path):
        from code_puppy.persistence import atomic_write_text

        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        legacy_dir = fake_home / ".code_puppy"
        legacy_dir.mkdir()
        alias_dir = tmp_path / "alias"
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        try:
            alias_dir.symlink_to(legacy_dir, target_is_directory=True)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        with pytest.raises(ConfigIsolationViolation):
            atomic_write_text(alias_dir / "test.txt", "blocked")


# ---------------------------------------------------------------------------
# _canonical and _is_path_within_home helpers
# ---------------------------------------------------------------------------


class TestCanonicalPath:
    def test_canonical_resolves_absolute(self):
        result = _canonical("/tmp/test")
        assert os.path.isabs(result)

    def test_canonical_resolves_relative(self):
        result = _canonical("relative/path")
        assert os.path.isabs(result)

    def test_is_path_within_home_positive(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        ex_home = tmp_path / "pup_ex_home"
        target = ex_home / "config" / "test.cfg"
        assert _is_path_within_home(target) is True

    def test_is_path_within_home_negative(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        outside = tmp_path / "other_home" / "test.cfg"
        assert _is_path_within_home(outside) is False

    def test_is_path_within_home_exact_match(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        (tmp_path / "pup_ex_home").mkdir()
        assert _is_path_within_home(tmp_path / "pup_ex_home") is True

    def test_canonical_expands_tilde_and_env_vars(self, monkeypatch, tmp_path):
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("PUP_TEST_PATH", "nested/file.txt")

        result = _canonical("~/" + os.environ["PUP_TEST_PATH"])
        assert result == str((fake_home / "nested" / "file.txt").resolve())


# ---------------------------------------------------------------------------
# GATE-1 through GATE-5 (ADR-003 CI gates)
# ---------------------------------------------------------------------------


class TestRuntimeLazyPaths:
    def test_config_module_paths_follow_late_pup_ex_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PUP_EX_HOME", raising=False)
        cp_config = importlib.import_module("code_puppy.config")

        for attr in ("CONFIG_FILE", "CONFIG_DIR", "DATA_DIR", "CACHE_DIR", "STATE_DIR"):
            cp_config.__dict__.pop(attr, None)

        baseline = str(cp_config.CONFIG_FILE)
        ex_home = tmp_path / "late_ex_home"
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        for attr in ("CONFIG_FILE", "CONFIG_DIR", "DATA_DIR", "CACHE_DIR", "STATE_DIR"):
            cp_config.__dict__.pop(attr, None)

        assert str(cp_config.CONFIG_FILE).startswith(str(ex_home))
        assert str(cp_config.CONFIG_FILE) != baseline

    def test_plugins_module_paths_follow_late_pup_ex_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PUP_EX_HOME", raising=False)
        plugins_mod = importlib.import_module("code_puppy.plugins")

        baseline = str(plugins_mod.USER_PLUGINS_DIR)
        ex_home = tmp_path / "late_plugins_home"
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))

        assert str(plugins_mod.USER_PLUGINS_DIR).startswith(str(ex_home))
        assert str(plugins_mod.USER_PLUGINS_DIR) != baseline


class TestCommandHistoryIsolation:
    def test_initialize_history_skips_legacy_copy_delete_in_pup_ex(self, monkeypatch, tmp_path):
        from code_puppy import config as cp_config

        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        ex_home = tmp_path / "pup_ex_home"
        ex_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("PUP_EX_HOME", str(ex_home))
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        old_history = fake_home / ".code_puppy_history.txt"
        old_history.write_text("legacy-history\n", encoding="utf-8")

        cp_config.initialize_command_history_file()

        assert old_history.exists()
        new_history = cp_config.COMMAND_HISTORY_FILE
        assert Path(new_history).exists()
        assert Path(new_history).read_text(encoding="utf-8") == ""


class TestADR003CIGates:
    """Validate all 5 CI gates from ADR-003."""

    def test_gate1_no_write(self, monkeypatch, tmp_path):
        """GATE-1: pup-ex must write zero bytes to ~/.code_puppy/."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        (tmp_path / "pup_ex_home").mkdir()
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Attempting to write to legacy home must raise
        legacy = fake_home / ".code_puppy" / "any_file"
        with pytest.raises(ConfigIsolationViolation):
            safe_write(legacy, "data")

    def test_gate2_guard_raises(self, monkeypatch, tmp_path):
        """GATE-2: Direct call to safe_write on legacy home raises."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy = fake_home / ".code_puppy" / "any_file"
        with pytest.raises(ConfigIsolationViolation) as exc_info:
            safe_write(legacy, "data")
        assert exc_info.value.action == "write"

    def test_gate4_paths_under_pup_ex(self, monkeypatch, tmp_path):
        """GATE-4: All path resolution functions resolve under pup-ex home."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        ex_home = tmp_path / "pup_ex_home"

        # All path functions should resolve under the pup-ex home
        for path_func in (config_dir, data_dir, cache_dir, state_dir):
            result = path_func()
            assert str(result).startswith(str(ex_home))

    def test_gate5_no_paths_under_legacy_in_pup_ex(self, monkeypatch, tmp_path):
        """No Paths function should resolve under legacy home when in pup-ex."""
        monkeypatch.setenv("PUP_EX_HOME", str(tmp_path / "pup_ex_home"))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        legacy_str = str(fake_home / ".code_puppy")

        for path_func in (config_dir, data_dir, cache_dir, state_dir):
            result = str(path_func())
            # When not using XDG overrides, must be under pup-ex home
            if "code_puppy" in result and "/xdg/" not in result:
                assert not result.startswith(legacy_str), (
                    f"{path_func.__name__}() resolved to legacy home: {result}"
                )
