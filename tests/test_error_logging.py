"""Tests for the error_logging module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from code_puppy.error_logging import (
    format_error_for_display,
    get_log_file_path,
    get_logs_dir,
    log_error,
    log_error_message,
)


class TestErrorLogging:
    """Tests for error logging functionality."""

    def test_get_logs_dir_returns_path(self):
        """Test that get_logs_dir returns a valid path."""
        logs_dir = get_logs_dir()
        assert logs_dir is not None
        assert isinstance(logs_dir, Path)
        assert "logs" in str(logs_dir)

    def test_get_log_file_path_returns_path(self):
        """Test that get_log_file_path returns a valid path."""
        log_path = get_log_file_path()
        assert log_path is not None
        assert isinstance(log_path, Path)
        assert log_path.name == "errors.log"

    def test_ensure_logs_dir_creates_directory(self):
        """Test that _ensure_logs_dir creates the logs directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_logs_dir = os.path.join(tmpdir, "logs")
            with patch("code_puppy.error_logging.LOGS_DIR", test_logs_dir):
                from code_puppy import error_logging

                original_logs_dir = error_logging.LOGS_DIR
                error_logging.LOGS_DIR = test_logs_dir
                try:
                    error_logging._ensure_logs_dir()
                    assert os.path.exists(test_logs_dir)
                    assert os.path.isdir(test_logs_dir)
                finally:
                    error_logging.LOGS_DIR = original_logs_dir

    def test_log_error_writes_to_file(self):
        """Test that log_error writes error details to the log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_logs_dir = os.path.join(tmpdir, "logs")
            test_log_file = os.path.join(test_logs_dir, "errors.log")

            from code_puppy import error_logging

            original_logs_dir = error_logging.LOGS_DIR
            original_log_file = error_logging.ERROR_LOG_FILE
            error_logging.LOGS_DIR = Path(test_logs_dir)
            error_logging.ERROR_LOG_FILE = Path(test_log_file)

            try:
                # Create a test exception
                try:
                    raise ValueError("Test error message")
                except Exception as e:
                    log_error(e, context="Test context")

                # Verify the log file was created and contains expected content
                assert os.path.exists(test_log_file)
                with open(test_log_file, "r") as f:
                    content = f.read()
                    assert "ValueError" in content
                    assert "Test error message" in content
                    assert "Test context" in content
                    assert "Traceback" in content
            finally:
                error_logging.LOGS_DIR = original_logs_dir
                error_logging.ERROR_LOG_FILE = original_log_file

    def test_log_error_without_traceback(self):
        """Test that log_error can skip traceback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_logs_dir = os.path.join(tmpdir, "logs")
            test_log_file = os.path.join(test_logs_dir, "errors.log")

            from code_puppy import error_logging

            original_logs_dir = error_logging.LOGS_DIR
            original_log_file = error_logging.ERROR_LOG_FILE
            error_logging.LOGS_DIR = Path(test_logs_dir)
            error_logging.ERROR_LOG_FILE = Path(test_log_file)

            try:
                try:
                    raise RuntimeError("No traceback test")
                except Exception as e:
                    log_error(e, include_traceback=False)

                with open(test_log_file, "r") as f:
                    content = f.read()
                    assert "RuntimeError" in content
                    assert "No traceback test" in content
                    # Traceback should not be in the content
                    assert "Traceback:" not in content
            finally:
                error_logging.LOGS_DIR = original_logs_dir
                error_logging.ERROR_LOG_FILE = original_log_file

    def test_log_error_message_writes_to_file(self):
        """Test that log_error_message writes a simple message to the log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_logs_dir = os.path.join(tmpdir, "logs")
            test_log_file = os.path.join(test_logs_dir, "errors.log")

            from code_puppy import error_logging

            original_logs_dir = error_logging.LOGS_DIR
            original_log_file = error_logging.ERROR_LOG_FILE
            error_logging.LOGS_DIR = Path(test_logs_dir)
            error_logging.ERROR_LOG_FILE = Path(test_log_file)

            try:
                log_error_message("Simple error message", context="Simple context")

                assert os.path.exists(test_log_file)
                with open(test_log_file, "r") as f:
                    content = f.read()
                    assert "Simple error message" in content
                    assert "Simple context" in content
            finally:
                error_logging.LOGS_DIR = original_logs_dir
                error_logging.ERROR_LOG_FILE = original_log_file

    def test_log_error_handles_write_failure_silently(self):
        """Test that log_error doesn't raise if it can't write."""
        from code_puppy import error_logging

        original_log_file = error_logging.ERROR_LOG_FILE
        # Point to an invalid path that can't be written
        error_logging.ERROR_LOG_FILE = Path(
            "/nonexistent/path/that/cant/exist/errors.log"
        )

        try:
            # This should not raise an exception
            try:
                raise ValueError("Test")
            except Exception as e:
                log_error(e)  # Should silently fail
        finally:
            error_logging.ERROR_LOG_FILE = original_log_file

    def test_log_error_message_handles_write_failure_silently(self):
        """Test that log_error_message doesn't raise if it can't write."""
        from code_puppy import error_logging

        original_log_file = error_logging.ERROR_LOG_FILE
        error_logging.ERROR_LOG_FILE = Path(
            "/nonexistent/path/that/cant/exist/errors.log"
        )

        try:
            # This should not raise an exception
            log_error_message("Test message")  # Should silently fail
        finally:
            error_logging.ERROR_LOG_FILE = original_log_file


class TestFormatErrorForDisplay:
    def test_value_error(self):
        assert format_error_for_display(ValueError("bad input")) == "bad input"

    def test_runtime_error(self):
        assert format_error_for_display(RuntimeError("oops")) == "oops"

    def test_include_type(self):
        result = format_error_for_display(ValueError("x"), include_type=True)
        assert result == "[ValueError] x"

    def test_api_prefix_stripped(self):
        # Simulate an HTTPError whose str() returns "API 500: server error"
        exc = Exception("API 500: server error")
        assert format_error_for_display(exc) == "server error"

    def test_http_prefix_stripped(self):
        exc = Exception("HTTP 404: not found")
        assert format_error_for_display(exc) == "not found"

    def test_fully_qualified_exception_prefix(self):
        exc = Exception("httpx.exceptions.ConnectError: connection refused")
        result = format_error_for_display(exc)
        assert result == "connection refused"

    def test_truncation(self):
        long_msg = "a" * 1000
        exc = ValueError(long_msg)
        result = format_error_for_display(exc, max_length=50)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_whitespace_collapsed(self):
        exc = ValueError("line1\n\n  line2\t\tline3")
        result = format_error_for_display(exc)
        assert result == "line1 line2 line3"

    def test_empty_message_falls_back_to_type_name(self):
        exc = ValueError("")
        result = format_error_for_display(exc)
        assert result == "ValueError"

    def test_unrepresentable_exception(self):
        class Bad(Exception):
            def __str__(self):
                raise RuntimeError("str broken")

        # Should not raise
        result = format_error_for_display(Bad())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_include_type_with_long_message(self):
        exc = ValueError("a" * 200)
        result = format_error_for_display(exc, include_type=True, max_length=50)
        # Type prefix is added AFTER truncation, so total length may exceed max_length slightly
        assert "[ValueError]" in result
        assert "..." in result

    def test_custom_exception(self):
        class MyCustomError(Exception):
            pass

        exc = MyCustomError("details here")
        result = format_error_for_display(exc)
        assert result == "details here"

    def test_nested_prefix_stripping(self):
        # Message with multiple strippable prefixes
        exc = Exception("ValueError: API 500: underlying issue")
        result = format_error_for_display(exc)
        # Both prefixes should be stripped after multiple passes
        assert result == "underlying issue"

    def test_log_error_still_works(self):
        """Regression: adding format_error_for_display shouldn't break log_error."""
        # Just call log_error with a simple exception and ensure it doesn't raise
        try:
            raise ValueError("test for log_error")
        except ValueError as exc:
            log_error(exc, context="regression test")
        # If we got here without raising, test passes
