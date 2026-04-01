"""Tests for the error_logger plugin (code_puppy/plugins/error_logger)."""

import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def log_file(tmp_path):
    """Provide a temporary error log file path and patch error_logging to use it."""
    log_path = str(tmp_path / "errors.log")
    with (
        patch("code_puppy.error_logging.LOGS_DIR", str(tmp_path)),
        patch("code_puppy.error_logging.ERROR_LOG_FILE", log_path),
    ):
        yield log_path


# ---------------------------------------------------------------------------
# _on_agent_exception
# ---------------------------------------------------------------------------


class TestOnAgentException:
    def test_logs_exception_to_file(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_exception,
        )

        exc = ValueError("test error")
        try:
            raise exc
        except ValueError as e:
            _on_agent_exception(e)

        assert os.path.isfile(log_file)
        content = open(log_file).read()
        assert "ValueError" in content
        assert "test error" in content
        assert "agent_exception callback" in content

    def test_includes_args_and_kwargs_in_context(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_exception,
        )

        exc = RuntimeError("boom")
        try:
            raise exc
        except RuntimeError as e:
            _on_agent_exception(e, "extra_arg", agent_name="test-agent")

        content = open(log_file).read()
        assert "extra_arg" in content
        assert "agent_name" in content


# ---------------------------------------------------------------------------
# _on_agent_run_end
# ---------------------------------------------------------------------------


class TestOnAgentRunEnd:
    def test_skips_logging_on_success(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_run_end,
        )

        _on_agent_run_end("agent", "model", success=True, error=None)
        assert not os.path.isfile(log_file)

    def test_skips_logging_when_error_is_none(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_run_end,
        )

        _on_agent_run_end("agent", "model", success=False, error=None)
        assert not os.path.isfile(log_file)

    def test_logs_exception_error(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_run_end,
        )

        exc = TypeError("bad type")
        try:
            raise exc
        except TypeError as e:
            _on_agent_run_end(
                "my-agent", "gpt-4", session_id="sess-1", success=False, error=e
            )

        content = open(log_file).read()
        assert "TypeError" in content
        assert "bad type" in content
        assert "my-agent" in content
        assert "gpt-4" in content
        assert "sess-1" in content

    def test_logs_string_error(self, log_file):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _on_agent_run_end,
        )

        _on_agent_run_end(
            "my-agent", "gpt-4", session_id="sess-2", success=False, error="API timeout"
        )

        content = open(log_file).read()
        assert "API timeout" in content
        assert "my-agent" in content


# ---------------------------------------------------------------------------
# /errors command
# ---------------------------------------------------------------------------


class TestErrorsCommand:
    def test_returns_none_for_other_commands(self):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        result = _handle_errors_command("/help", "help")
        assert result is None

    @patch("code_puppy.plugins.error_logger.register_callbacks.get_log_file_path")
    def test_path_shows_log_path(self, mock_path, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        log_path = str(tmp_path / "errors.log")
        mock_path.return_value = log_path

        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_errors_command("/errors", "errors")

        assert result is True
        calls = [str(c) for c in mock_emit.call_args_list]
        assert any(log_path in c for c in calls)

    @patch("code_puppy.plugins.error_logger.register_callbacks.get_log_file_path")
    def test_path_shows_file_size(self, mock_path, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        log_path = tmp_path / "errors.log"
        log_path.write_text("x" * 2048)
        mock_path.return_value = str(log_path)

        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_errors_command("/errors path", "errors")

        assert result is True
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "KB" in calls

    @patch("code_puppy.plugins.error_logger.register_callbacks.get_log_file_path")
    def test_path_no_file_yet(self, mock_path, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        mock_path.return_value = str(tmp_path / "nonexistent.log")

        with patch("code_puppy.messaging.emit_success") as mock_emit:
            result = _handle_errors_command("/errors", "errors")

        assert result is True
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "clean slate" in calls

    def test_tail_no_entries(self):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        with (
            patch(
                "code_puppy.plugins.error_logger.register_callbacks._read_last_entries",
                return_value=[],
            ),
            patch("code_puppy.messaging.emit_success") as mock_emit,
        ):
            result = _handle_errors_command("/errors tail", "errors")

        assert result is True
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "good puppy" in calls

    def test_tail_with_entries(self):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        entries = ["Error entry 1", "Error entry 2"]
        with (
            patch(
                "code_puppy.plugins.error_logger.register_callbacks._read_last_entries",
                return_value=entries,
            ) as mock_read,
            patch("code_puppy.messaging.emit_info"),
            patch("code_puppy.messaging.emit_warning") as mock_warn,
        ):
            result = _handle_errors_command("/errors tail 2", "errors")

        assert result is True
        mock_read.assert_called_once_with(2)
        assert mock_warn.call_count == 2

    def test_tail_invalid_n_defaults_to_5(self):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        with (
            patch(
                "code_puppy.plugins.error_logger.register_callbacks._read_last_entries",
                return_value=[],
            ) as mock_read,
            patch("code_puppy.messaging.emit_success"),
        ):
            _handle_errors_command("/errors tail abc", "errors")

        mock_read.assert_called_once_with(5)

    @patch("code_puppy.plugins.error_logger.register_callbacks.get_log_file_path")
    def test_clear_truncates_file(self, mock_path, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        log_path = tmp_path / "errors.log"
        log_path.write_text("lots of errors here")
        mock_path.return_value = str(log_path)

        with patch("code_puppy.messaging.emit_success") as mock_emit:
            result = _handle_errors_command("/errors clear", "errors")

        assert result is True
        assert log_path.read_text() == ""
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "cleared" in calls

    @patch("code_puppy.plugins.error_logger.register_callbacks.get_log_file_path")
    def test_clear_no_file(self, mock_path, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        mock_path.return_value = str(tmp_path / "nonexistent.log")

        with patch("code_puppy.messaging.emit_success") as mock_emit:
            result = _handle_errors_command("/errors clear", "errors")

        assert result is True
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "No error log to clear" in calls

    def test_unknown_subcommand_shows_usage(self):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _handle_errors_command,
        )

        with patch("code_puppy.messaging.emit_info") as mock_emit:
            result = _handle_errors_command("/errors foobar", "errors")

        assert result is True
        calls = " ".join(str(c) for c in mock_emit.call_args_list)
        assert "Usage" in calls


# ---------------------------------------------------------------------------
# _read_last_entries
# ---------------------------------------------------------------------------


class TestReadLastEntries:
    def test_no_file(self, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _read_last_entries,
        )

        with patch(
            "code_puppy.plugins.error_logger.register_callbacks.get_log_file_path",
            return_value=str(tmp_path / "nonexistent.log"),
        ):
            assert _read_last_entries() == []

    def test_reads_entries(self, tmp_path):
        from code_puppy.plugins.error_logger.register_callbacks import (
            _SEPARATOR,
            _read_last_entries,
        )

        log_path = tmp_path / "errors.log"
        # Write 3 entries in the format error_logging.py uses
        entries_text = ""
        for i in range(3):
            entries_text += f"\n{_SEPARATOR}\nEntry {i}\n{_SEPARATOR}\n"
        log_path.write_text(entries_text)

        with patch(
            "code_puppy.plugins.error_logger.register_callbacks.get_log_file_path",
            return_value=str(log_path),
        ):
            result = _read_last_entries(2)

        assert len(result) == 2
        assert "Entry 1" in result[0]
        assert "Entry 2" in result[1]


# ---------------------------------------------------------------------------
# _errors_help
# ---------------------------------------------------------------------------


class TestErrorsHelp:
    def test_returns_help_tuple(self):
        from code_puppy.plugins.error_logger.register_callbacks import _errors_help

        result = _errors_help()
        assert isinstance(result, list)
        assert len(result) == 1
        name, desc = result[0]
        assert name == "errors"
        assert "error log" in desc.lower()
