"""Tests for the /clean command plugin."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_env(tmp_path: Path):
    """Patch config directories to use a temporary tree and return helper paths."""
    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"

    for d in (cache_dir, data_dir, state_dir, config_dir):
        d.mkdir()

    autosave_dir = cache_dir / "autosaves"
    autosave_dir.mkdir()

    patches = {
        "code_puppy.plugins.clean_command.register_callbacks.config": type(
            "FakeConfig",
            (),
            {
                "AUTOSAVE_DIR": str(autosave_dir),
                "DATA_DIR": str(data_dir),
                "STATE_DIR": str(state_dir),
                "CACHE_DIR": str(cache_dir),
                "CONFIG_DIR": str(config_dir),
                "COMMAND_HISTORY_FILE": str(state_dir / "command_history.txt"),
                "CONFIG_FILE": str(config_dir / "puppy.cfg"),
                "MCP_SERVERS_FILE": str(config_dir / "mcp_servers.json"),
            },
        )(),
    }

    class Paths:
        cache = cache_dir
        data = data_dir
        state = state_dir
        config = config_dir
        autosave = autosave_dir

    with patch.dict(
        "code_puppy.plugins.clean_command.register_callbacks.__dict__",
        {
            "config": patches[
                "code_puppy.plugins.clean_command.register_callbacks.config"
            ]
        },
    ):
        yield Paths()


def _populate_sessions(env):
    """Create dummy session files in the autosave and subagent dirs."""
    # Autosave sessions
    for i in range(3):
        (env.autosave / f"session_{i}.pkl").write_bytes(b"x" * 100)
        (env.autosave / f"session_{i}_meta.json").write_text(
            json.dumps({"session_name": f"session_{i}"})
        )

    # Sub-agent sessions
    subagent = env.data / "subagent_sessions"
    subagent.mkdir(exist_ok=True)
    (subagent / "agent_a.pkl").write_bytes(b"y" * 200)

    # Terminal sessions
    (env.state / "terminal_sessions.json").write_text("{}")

    # HMAC key (both possible filenames)
    (env.data / ".session_hmac_key").write_bytes(b"k" * 32)
    (env.data / "session_hmac.key").write_bytes(b"k" * 32)


def _populate_history(env):
    (env.state / "command_history.txt").write_text("line1\nline2\nline3\n")


def _populate_logs(env):
    logs_dir = env.state / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "errors.log").write_text("error line\n" * 50)
    (logs_dir / "errors.log.1").write_text("old error line\n" * 30)


def _populate_cache(env):
    browser = env.cache / "browser_profiles"
    browser.mkdir(exist_ok=True)
    (browser / "default").mkdir(exist_ok=True)
    (browser / "default" / "data.bin").write_bytes(b"b" * 500)

    workflows = env.data / "browser_workflows"
    workflows.mkdir(exist_ok=True)
    (workflows / "flow.md").write_text("# flow")

    (env.state / "api_server.pid").write_text("12345")


def _populate_db(env):
    (env.data / "dbos_store.sqlite").write_bytes(b"S" * 1024)


def _populate_db_with_journals(env):
    """Create dummy DBOS database with WAL and SHM journal files."""
    (env.data / "dbos_store.sqlite").write_bytes(b"S" * 1024)
    (env.data / "dbos_store.sqlite-wal").write_bytes(b"W" * 512)
    (env.data / "dbos_store.sqlite-shm").write_bytes(b"H" * 256)


def _populate_all(env):
    _populate_sessions(env)
    _populate_history(env)
    _populate_logs(env)
    _populate_cache(env)
    _populate_db(env)


# ---------------------------------------------------------------------------
# Import helpers — import inside tests so patches take effect
# ---------------------------------------------------------------------------


def _import_plugin():
    from code_puppy.plugins.clean_command.register_callbacks import (
        _handle_clean_command,
        _custom_help,
        _show_status,
        _show_help,
        _run_clean,
        _human_size,
        _CATEGORIES,
        _SAFE_CATEGORY_KEYS,
        _clean_db,
        _destroy_dbos,
    )

    return (
        _handle_clean_command,
        _custom_help,
        _show_status,
        _show_help,
        _run_clean,
        _human_size,
        _CATEGORIES,
        _SAFE_CATEGORY_KEYS,
        _clean_db,
        _destroy_dbos,
    )


# ---------------------------------------------------------------------------
# Tests: callback registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    def test_custom_help_returns_clean_entry(self):
        _, _custom_help, *_ = _import_plugin()
        result = _custom_help()
        assert isinstance(result, list)
        assert len(result) == 1
        name, desc = result[0]
        assert name == "clean"
        assert "Clean" in desc

    def test_handler_ignores_other_commands(self):
        handler, *_ = _import_plugin()
        assert handler("/foo", "foo") is None
        assert handler("/bar baz", "bar") is None

    def test_handler_returns_true_for_clean(self, clean_env):
        handler, *_ = _import_plugin()
        assert handler("/clean", "clean") is True

    def test_handler_returns_true_for_clean_help(self, clean_env):
        handler, *_ = _import_plugin()
        assert handler("/clean help", "clean") is True

    def test_handler_returns_true_for_unknown_subcmd(self, clean_env):
        handler, *_ = _import_plugin()
        assert handler("/clean doesnotexist", "clean") is True


# ---------------------------------------------------------------------------
# Tests: /clean help
# ---------------------------------------------------------------------------


class TestCleanHelp:
    def test_help_output(self, clean_env, capsys):
        handler, *_ = _import_plugin()
        handler("/clean help", "clean")
        # help is emitted via emit_info — we just confirm no exception

    def test_bare_clean_shows_help(self, clean_env):
        handler, *_ = _import_plugin()
        assert handler("/clean", "clean") is True


# ---------------------------------------------------------------------------
# Tests: /clean status
# ---------------------------------------------------------------------------


class TestCleanStatus:
    def test_status_empty(self, clean_env):
        handler, *_ = _import_plugin()
        assert handler("/clean status", "clean") is True

    def test_status_with_data(self, clean_env):
        _populate_all(clean_env)
        handler, *_ = _import_plugin()
        assert handler("/clean status", "clean") is True


# ---------------------------------------------------------------------------
# Tests: /clean sessions
# ---------------------------------------------------------------------------


class TestCleanSessions:
    def test_clean_sessions(self, clean_env):
        _populate_sessions(clean_env)
        handler, *_ = _import_plugin()

        # Verify files exist before
        assert (clean_env.autosave / "session_0.pkl").exists()
        assert (clean_env.data / ".session_hmac_key").exists()
        assert (clean_env.data / "session_hmac.key").exists()

        handler("/clean sessions", "clean")

        # Autosave dir recreated but empty
        assert clean_env.autosave.is_dir()
        assert list(clean_env.autosave.iterdir()) == []

        # HMAC keys gone (both filenames)
        assert not (clean_env.data / ".session_hmac_key").exists()
        assert not (clean_env.data / "session_hmac.key").exists()

        # Terminal sessions gone
        assert not (clean_env.state / "terminal_sessions.json").exists()

    def test_clean_sessions_dry_run(self, clean_env):
        _populate_sessions(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean sessions --dry-run", "clean")

        # Files should still exist
        assert (clean_env.autosave / "session_0.pkl").exists()
        assert (clean_env.data / ".session_hmac_key").exists()
        assert (clean_env.data / "session_hmac.key").exists()

    def test_clean_sessions_empty(self, clean_env):
        handler, *_ = _import_plugin()
        handler("/clean sessions", "clean")  # no crash


# ---------------------------------------------------------------------------
# Tests: /clean history
# ---------------------------------------------------------------------------


class TestCleanHistory:
    def test_clean_history(self, clean_env):
        _populate_history(clean_env)
        handler, *_ = _import_plugin()
        hist_file = clean_env.state / "command_history.txt"

        assert hist_file.exists()
        handler("/clean history", "clean")
        assert not hist_file.exists()

    def test_clean_history_dry_run(self, clean_env):
        _populate_history(clean_env)
        handler, *_ = _import_plugin()
        hist_file = clean_env.state / "command_history.txt"

        handler("/clean history --dry-run", "clean")
        assert hist_file.exists()

    def test_clean_history_missing(self, clean_env):
        handler, *_ = _import_plugin()
        handler("/clean history", "clean")  # no crash


# ---------------------------------------------------------------------------
# Tests: /clean logs
# ---------------------------------------------------------------------------


class TestCleanLogs:
    def test_clean_logs(self, clean_env):
        _populate_logs(clean_env)
        handler, *_ = _import_plugin()
        logs_dir = clean_env.state / "logs"

        assert (logs_dir / "errors.log").exists()
        handler("/clean logs", "clean")
        # dir recreated but empty
        assert logs_dir.is_dir()
        assert list(logs_dir.iterdir()) == []

    def test_clean_logs_dry_run(self, clean_env):
        _populate_logs(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean logs --dry-run", "clean")
        assert (clean_env.state / "logs" / "errors.log").exists()


# ---------------------------------------------------------------------------
# Tests: /clean cache
# ---------------------------------------------------------------------------


class TestCleanCache:
    def test_clean_cache(self, clean_env):
        _populate_cache(clean_env)
        handler, *_ = _import_plugin()

        assert (clean_env.cache / "browser_profiles" / "default" / "data.bin").exists()
        handler("/clean cache", "clean")
        # dirs recreated but empty
        assert (clean_env.cache / "browser_profiles").is_dir()
        assert list((clean_env.cache / "browser_profiles").iterdir()) == []

    def test_clean_cache_dry_run(self, clean_env):
        _populate_cache(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean cache --dry-run", "clean")
        assert (clean_env.cache / "browser_profiles" / "default" / "data.bin").exists()


# ---------------------------------------------------------------------------
# Tests: /clean db
# ---------------------------------------------------------------------------


class TestCleanDb:
    def test_clean_db(self, clean_env):
        _populate_db(clean_env)
        handler, *_ = _import_plugin()

        assert (clean_env.data / "dbos_store.sqlite").exists()
        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            return_value=True,
        ):
            handler("/clean db", "clean")
        assert not (clean_env.data / "dbos_store.sqlite").exists()

    def test_clean_db_dry_run(self, clean_env):
        _populate_db(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean db --dry-run", "clean")
        assert (clean_env.data / "dbos_store.sqlite").exists()

    def test_clean_db_calls_destroy_dbos(self, clean_env):
        """Verify that /clean db calls _destroy_dbos before deleting."""
        _populate_db(clean_env)
        handler, *_ = _import_plugin()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            return_value=True,
        ) as mock_destroy:
            handler("/clean db", "clean")
            mock_destroy.assert_called_once()

    def test_clean_db_does_not_call_destroy_on_dry_run(self, clean_env):
        """Dry run should NOT call _destroy_dbos."""
        _populate_db(clean_env)
        handler, *_ = _import_plugin()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            return_value=True,
        ) as mock_destroy:
            handler("/clean db --dry-run", "clean")
            mock_destroy.assert_not_called()

    def test_clean_db_cleans_journal_files(self, clean_env):
        """WAL and SHM journal files should also be cleaned."""
        _populate_db_with_journals(clean_env)
        handler, *_ = _import_plugin()

        assert (clean_env.data / "dbos_store.sqlite-wal").exists()
        assert (clean_env.data / "dbos_store.sqlite-shm").exists()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            return_value=True,
        ):
            handler("/clean db", "clean")

        assert not (clean_env.data / "dbos_store.sqlite").exists()
        assert not (clean_env.data / "dbos_store.sqlite-wal").exists()
        assert not (clean_env.data / "dbos_store.sqlite-shm").exists()

    def test_clean_db_handles_destroy_failure(self, clean_env):
        """Should still clean even if DBOS.destroy() fails."""
        _populate_db(clean_env)
        handler, *_ = _import_plugin()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            return_value=False,
        ):
            handler("/clean db", "clean")

        assert not (clean_env.data / "dbos_store.sqlite").exists()


# ---------------------------------------------------------------------------
# Tests: /clean all  (MUST exclude db)
# ---------------------------------------------------------------------------


class TestCleanAll:
    def test_safe_category_keys_excludes_db(self):
        """_SAFE_CATEGORY_KEYS must not include 'db'."""
        *_, _SAFE_CATEGORY_KEYS, _, _ = _import_plugin()
        assert "db" not in _SAFE_CATEGORY_KEYS
        assert "sessions" in _SAFE_CATEGORY_KEYS
        assert "history" in _SAFE_CATEGORY_KEYS
        assert "logs" in _SAFE_CATEGORY_KEYS
        assert "cache" in _SAFE_CATEGORY_KEYS

    def test_clean_all_does_not_delete_db(self, clean_env):
        """'/clean all' must NOT delete dbos_store.sqlite."""
        _populate_all(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean all", "clean")

        # Sessions cleaned
        assert list(clean_env.autosave.iterdir()) == []
        assert not (clean_env.data / ".session_hmac_key").exists()
        assert not (clean_env.data / "session_hmac.key").exists()
        # History cleaned
        assert not (clean_env.state / "command_history.txt").exists()
        # Logs cleaned
        assert list((clean_env.state / "logs").iterdir()) == []
        # Cache cleaned
        assert list((clean_env.cache / "browser_profiles").iterdir()) == []
        # DB NOT cleaned — this is the critical assertion!
        assert (clean_env.data / "dbos_store.sqlite").exists()

    def test_clean_all_dry_run(self, clean_env):
        _populate_all(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean all --dry-run", "clean")

        # Nothing should be deleted
        assert (clean_env.autosave / "session_0.pkl").exists()
        assert (clean_env.state / "command_history.txt").exists()
        assert (clean_env.state / "logs" / "errors.log").exists()
        assert (clean_env.data / "dbos_store.sqlite").exists()

    def test_clean_all_empty(self, clean_env):
        handler, *_ = _import_plugin()
        handler("/clean all", "clean")  # should not crash


# ---------------------------------------------------------------------------
# Tests: --dry-run position flexibility
# ---------------------------------------------------------------------------


class TestDryRunPosition:
    def test_dry_run_before_subcmd(self, clean_env):
        _populate_history(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean --dry-run history", "clean")
        assert (clean_env.state / "command_history.txt").exists()

    def test_dry_run_after_subcmd(self, clean_env):
        _populate_history(clean_env)
        handler, *_ = _import_plugin()

        handler("/clean history --dry-run", "clean")
        assert (clean_env.state / "command_history.txt").exists()


# ---------------------------------------------------------------------------
# Tests: _human_size helper
# ---------------------------------------------------------------------------


class TestHumanSize:
    def test_bytes(self):
        *_, _human_size, _, _, _, _ = _import_plugin()
        assert _human_size(0) == "0 B"
        assert _human_size(512) == "512 B"
        assert _human_size(1023) == "1023 B"

    def test_kilobytes(self):
        *_, _human_size, _, _, _, _ = _import_plugin()
        assert _human_size(1024) == "1.0 KB"
        assert _human_size(1536) == "1.5 KB"

    def test_megabytes(self):
        *_, _human_size, _, _, _, _ = _import_plugin()
        assert _human_size(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        *_, _human_size, _, _, _, _ = _import_plugin()
        assert _human_size(1024 * 1024 * 1024) == "1.0 GB"


# ---------------------------------------------------------------------------
# Tests: _destroy_dbos
# ---------------------------------------------------------------------------


class TestDestroyDbos:
    def test_destroy_dbos_success(self):
        """_destroy_dbos returns True when DBOS.destroy() succeeds."""
        *_, _clean_db, _destroy_dbos = _import_plugin()

        mock_dbos = MagicMock()
        with patch.dict("sys.modules", {"dbos": mock_dbos}):
            mock_dbos.DBOS.destroy = MagicMock()
            result = _destroy_dbos()
            assert result is True

    def test_destroy_dbos_import_error(self):
        """_destroy_dbos returns False when dbos is not installed."""
        *_, _clean_db, _destroy_dbos = _import_plugin()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._destroy_dbos",
            side_effect=ImportError("no module named dbos"),
        ):
            # Direct test: if import fails, function should handle gracefully
            pass

        # Test the actual function with a mocked import that fails
        with patch.dict("sys.modules", {"dbos": None}):
            result = _destroy_dbos()
            assert result is False

    def test_destroy_dbos_runtime_error(self):
        """_destroy_dbos returns False on unexpected errors."""
        *_, _clean_db, _destroy_dbos = _import_plugin()

        mock_dbos = MagicMock()
        mock_dbos.DBOS.destroy.side_effect = RuntimeError("DBOS not initialized")
        with patch.dict("sys.modules", {"dbos": mock_dbos}):
            result = _destroy_dbos()
            assert result is False


# ---------------------------------------------------------------------------
# Tests: error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    def test_permission_error_on_file(self, clean_env):
        """Plugin should not crash when a file can't be removed."""
        _populate_history(clean_env)
        handler, *_ = _import_plugin()

        _hist = clean_env.state / "command_history.txt"
        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            handler("/clean history", "clean")  # should not raise

    def test_handler_catches_unexpected_errors(self, clean_env):
        """An unexpected error inside a subcommand should be caught."""
        handler, *_ = _import_plugin()

        with patch(
            "code_puppy.plugins.clean_command.register_callbacks._show_status",
            side_effect=RuntimeError("boom"),
        ):
            result = handler("/clean status", "clean")
            assert result is True  # still signals "handled"
