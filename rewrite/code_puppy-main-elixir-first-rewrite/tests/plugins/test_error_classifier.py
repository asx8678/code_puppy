"""Tests for the Error Classifier plugin.

Covers:
- ExInfo dataclass creation and formatting
- ExceptionRegistry registration and lookup
- MRO-based parent class lookup
- Pattern-based fallback classification
- Built-in exception registrations
- Error severity levels
- Retry recommendations
- Callback execution
- Thread safety
"""

import asyncio
import re
import threading
import time
from unittest.mock import MagicMock

import pytest

from code_puppy.plugins.error_classifier import (
    ErrorSeverity,
    ExInfo,
    ExceptionRegistry,
    register_custom_pattern,
)
from code_puppy.plugins.error_classifier.builtins import register_builtin_exceptions
from code_puppy.plugins.error_classifier.register_callbacks import clear_seen_exceptions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before each test to ensure clean state."""
    ExceptionRegistry.clear()
    clear_seen_exceptions()
    yield
    ExceptionRegistry.clear()
    clear_seen_exceptions()


@pytest.fixture
def registered_builtins():
    """Register built-in exceptions."""
    register_builtin_exceptions()


# ---------------------------------------------------------------------------
# ExInfo Tests
# ---------------------------------------------------------------------------


class TestExInfo:
    """Tests for the ExInfo dataclass."""

    def test_basic_creation(self):
        info = ExInfo(
            name="Test Error",
            retry=True,
            description="A test error for unit testing.",
        )
        assert info.name == "Test Error"
        assert info.retry is True
        assert info.description == "A test error for unit testing."
        assert info.severity == ErrorSeverity.ERROR  # default

    def test_full_creation(self):
        info = ExInfo(
            name="Full Test",
            retry=False,
            description="Complete test.",
            suggestion="Try again later.",
            severity=ErrorSeverity.WARNING,
            retry_after_seconds=30,
        )
        assert info.suggestion == "Try again later."
        assert info.severity == ErrorSeverity.WARNING
        assert info.retry_after_seconds == 30

    def test_format_message_basic(self):
        info = ExInfo(
            name="Test Error",
            retry=False,
            description="Something went wrong.",
        )
        exc = ValueError("test")
        msg = info.format_message(exc)
        assert "[Test Error]" in msg
        assert "Something went wrong." in msg
        assert "retry" not in msg.lower()

    def test_format_message_with_retry(self):
        info = ExInfo(
            name="Transient Error",
            retry=True,
            description="Service temporarily unavailable.",
            suggestion="Wait and retry.",
        )
        exc = ConnectionError("test")
        msg = info.format_message(exc)
        assert "Transient Error" in msg
        assert "Wait and retry." in msg
        assert "🔄" in msg  # retry emoji

    def test_format_message_with_suggestion(self):
        info = ExInfo(
            name="Config Error",
            retry=False,
            description="Invalid configuration.",
            suggestion="Check your config file.",
        )
        exc = ValueError("test")
        msg = info.format_message(exc)
        assert "💡 Suggestion:" in msg
        assert "Check your config file." in msg

    def test_to_dict(self):
        info = ExInfo(
            name="Dict Test",
            retry=True,
            description="Testing serialization.",
            severity=ErrorSeverity.CRITICAL,
            retry_after_seconds=60,
        )
        data = info.to_dict()
        assert data["name"] == "Dict Test"
        assert data["retry"] is True
        assert data["severity"] == "critical"
        assert data["retry_after_seconds"] == 60

    def test_callback_execution(self):
        """Test that callbacks are stored and can be invoked."""
        mock_callback = MagicMock()
        info = ExInfo(
            name="Callback Test",
            retry=False,
            description="Testing callbacks.",
            callback=mock_callback,
        )

        # Simulate callback invocation (as would happen in register_callbacks.py)
        exc = ValueError("test error")
        if info.callback:
            info.callback(exc)

        mock_callback.assert_called_once_with(exc)


# ---------------------------------------------------------------------------
# ExceptionRegistry Tests
# ---------------------------------------------------------------------------


class TestExceptionRegistry:
    """Tests for the ExceptionRegistry class."""

    def test_register_and_lookup(self):
        info = ExInfo(
            name="Custom Error",
            retry=False,
            description="A custom error.",
        )
        ExceptionRegistry.register(ValueError, info)

        found = ExceptionRegistry.get_ex_info(ValueError("test"))
        assert found == info

    def test_lookup_returns_none_for_unknown(self):
        found = ExceptionRegistry.get_ex_info(RuntimeError("unknown"))
        assert found is None

    def test_classify_unknown_returns_false_retry(self):
        should_retry, info = ExceptionRegistry.classify(RuntimeError("unknown"))
        assert should_retry is False
        assert info is None

    def test_classify_known_returns_ex_info(self):
        info = ExInfo(
            name="Known Error",
            retry=True,
            description="A known error.",
        )
        ExceptionRegistry.register(TypeError, info)

        should_retry, found = ExceptionRegistry.classify(TypeError("test"))
        assert should_retry is True
        assert found == info

    def test_mro_lookup_parent_class(self):
        """Test that parent class registrations match child exceptions."""
        info = ExInfo(
            name="OSError",
            retry=False,
            description="OS-level error.",
        )
        ExceptionRegistry.register(OSError, info)

        # FileNotFoundError is a subclass of OSError
        found = ExceptionRegistry.get_ex_info(FileNotFoundError("test"))
        assert found == info

    def test_direct_match_beats_mro(self):
        """Test that direct class registration beats MRO parent."""
        parent_info = ExInfo(name="Parent", retry=False, description="Parent")
        child_info = ExInfo(name="Child", retry=True, description="Child")

        ExceptionRegistry.register(OSError, parent_info)
        ExceptionRegistry.register(FileNotFoundError, child_info)

        # Should get the child registration, not parent
        found = ExceptionRegistry.get_ex_info(FileNotFoundError("test"))
        assert found == child_info

    def test_pattern_registration(self):
        info = ExInfo(
            name="Pattern Match",
            retry=True,
            description="Matched by pattern.",
        )
        ExceptionRegistry.register_pattern(r"rate.?limit", info)

        exc = Exception("Rate limit exceeded")
        found = ExceptionRegistry.get_ex_info(exc)
        assert found == info

    def test_pattern_case_insensitive(self):
        info = ExInfo(
            name="Case Test",
            retry=False,
            description="Case insensitive match.",
        )
        ExceptionRegistry.register_pattern(r"error", info)

        exc = Exception("ERROR occurred")
        found = ExceptionRegistry.get_ex_info(exc)
        assert found == info

    def test_class_lookup_beats_pattern(self):
        """Direct class lookup should be tried before pattern matching."""
        class_info = ExInfo(name="Class", retry=False, description="Class match")
        pattern_info = ExInfo(name="Pattern", retry=True, description="Pattern match")

        ExceptionRegistry.register(ValueError, class_info)
        ExceptionRegistry.register_pattern(r"value", pattern_info)

        # Should get class_info, not pattern_info
        found = ExceptionRegistry.get_ex_info(ValueError("some value"))
        assert found == class_info

    def test_should_retry_method(self):
        info = ExInfo(name="Retryable", retry=True, description="Retry me")
        ExceptionRegistry.register(ValueError, info)

        assert ExceptionRegistry.should_retry(ValueError("test")) is True
        assert ExceptionRegistry.should_retry(RuntimeError("test")) is False

    def test_get_retry_delay(self):
        info = ExInfo(
            name="Delayed",
            retry=True,
            description="Has delay.",
            retry_after_seconds=42,
        )
        ExceptionRegistry.register(ValueError, info)

        assert ExceptionRegistry.get_retry_delay(ValueError("test")) == 42
        assert ExceptionRegistry.get_retry_delay(RuntimeError("test")) == 0

    def test_get_retry_delay_no_delay(self):
        info = ExInfo(name="No Delay", retry=True, description="No delay set")
        ExceptionRegistry.register(ValueError, info)

        assert ExceptionRegistry.get_retry_delay(ValueError("test")) == 0

    def test_clear_registry(self):
        info = ExInfo(name="Test", retry=False, description="Test")
        ExceptionRegistry.register(ValueError, info)
        assert ExceptionRegistry.get_ex_info(ValueError("test")) is not None

        ExceptionRegistry.clear()
        assert ExceptionRegistry.get_ex_info(ValueError("test")) is None

    def test_invalid_regex_pattern(self):
        """Test that invalid regex patterns raise PatternError."""
        with pytest.raises(re.PatternError):
            ExceptionRegistry.register_pattern(
                r"invalid[", ExInfo(name="Invalid", retry=False, description="Test")
            )

    def test_list_registered(self):
        info = ExInfo(name="Test", retry=False, description="Test")
        ExceptionRegistry.register(ValueError, info)
        ExceptionRegistry.register_pattern(r"pattern", info)

        registered = ExceptionRegistry.list_registered()
        assert "ValueError" in registered["classes"]
        assert "pattern" in registered["patterns"]


# ---------------------------------------------------------------------------
# Built-in Exception Tests
# ---------------------------------------------------------------------------


class TestBuiltinExceptions:
    """Tests for built-in exception registrations."""

    def test_connection_error(self, registered_builtins):
        exc = ConnectionError("Network is unreachable")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Connection Failed"
        assert info.retry is True
        assert ExceptionRegistry.should_retry(exc) is True

    def test_timeout_error(self, registered_builtins):
        exc = TimeoutError("Request timed out")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        # In Python 3.10+, asyncio.TimeoutError is the same as TimeoutError
        # so the name could be either depending on registration order
        assert info.name in ("Request Timeout", "Async Request Timeout")
        assert info.retry is True
        assert info.retry_after_seconds == 10

    def test_asyncio_timeout_error(self, registered_builtins):
        """Test that asyncio.TimeoutError is also registered (same as TimeoutError in Py3.10+)."""
        exc = asyncio.TimeoutError("Async operation timed out")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        # In Python 3.10+, these are the same class
        assert info.retry is True
        assert info.retry_after_seconds == 10

    def test_permission_error(self, registered_builtins):
        exc = PermissionError("Access denied")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Permission Denied"
        assert info.retry is False
        assert info.severity == ErrorSeverity.WARNING

    def test_file_not_found_error(self, registered_builtins):
        exc = FileNotFoundError("No such file")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "File Not Found"
        assert info.retry is False

    def test_keyboard_interrupt(self, registered_builtins):
        exc = KeyboardInterrupt()
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Interrupted"
        assert info.retry is False
        assert info.severity == ErrorSeverity.INFO

    def test_rate_limit_pattern(self, registered_builtins):
        exc = Exception("429 Too Many Requests")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Rate Limited"
        assert info.retry is True

    def test_server_error_pattern(self, registered_builtins):
        exc = Exception("500 Internal Server Error")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Server Error"
        assert info.retry is True

    def test_quota_pattern(self, registered_builtins):
        exc = Exception("Quota exceeded - billing issue")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Account Quota"
        assert info.retry is False

    def test_unauthorized_pattern(self, registered_builtins):
        exc = Exception("401 Unauthorized")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Unauthorized"
        assert info.retry is False


# ---------------------------------------------------------------------------
# Thread Safety Tests
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests for concurrent access to the registry."""

    def test_concurrent_registration(self):
        """Test that concurrent registrations don't corrupt the registry."""
        errors_registered = []
        errors_occurred = []

        def register_errors(thread_id: int):
            try:
                for i in range(50):
                    exc_class = type(f"CustomError_{thread_id}_{i}", (Exception,), {})
                    info = ExInfo(
                        name=f"Error_{thread_id}_{i}",
                        retry=i % 2 == 0,
                        description=f"Error from thread {thread_id}, iteration {i}",
                    )
                    ExceptionRegistry.register(exc_class, info)
                    errors_registered.append((thread_id, i))
                time.sleep(0.001)  # Small delay to increase overlap
            except Exception as e:
                errors_occurred.append(e)

        # Start multiple threads
        threads = []
        for i in range(4):
            t = threading.Thread(target=register_errors, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors_occurred) == 0, (
            f"Errors during concurrent registration: {errors_occurred}"
        )

        # Verify all registrations are present
        registered = ExceptionRegistry.list_registered()
        assert len(registered["classes"]) == 200  # 4 threads * 50 errors

    def test_concurrent_lookup_during_registration(self):
        """Test that lookups work correctly during concurrent registrations."""
        # Pre-register some exceptions (store the actual classes)
        registered_classes = []
        for i in range(10):
            exc_class = type(f"LookupTest_{i}", (Exception,), {})
            registered_classes.append(exc_class)
            ExceptionRegistry.register(
                exc_class,
                ExInfo(name=f"Lookup_{i}", retry=False, description=f"Test {i}"),
            )

        lookup_results = []
        lookup_errors = []

        def lookup_loop():
            try:
                for _ in range(100):
                    for exc_class in registered_classes:
                        info = ExceptionRegistry.get_ex_info(exc_class("test"))
                        if info is not None:
                            lookup_results.append(info.name)
            except Exception as e:
                lookup_errors.append(e)

        def register_loop():
            try:
                for i in range(50):
                    exc_class = type(f"ConcurrentReg_{i}", (Exception,), {})
                    ExceptionRegistry.register(
                        exc_class,
                        ExInfo(name=f"Reg_{i}", retry=False, description=f"Reg {i}"),
                    )
                    time.sleep(0.0001)
            except Exception as e:
                lookup_errors.append(e)

        # Start threads
        lookup_thread = threading.Thread(target=lookup_loop)
        register_thread = threading.Thread(target=register_loop)

        lookup_thread.start()
        register_thread.start()

        lookup_thread.join()
        register_thread.join()

        # Verify no errors occurred
        assert len(lookup_errors) == 0, (
            f"Errors during concurrent lookup/registration: {lookup_errors}"
        )

        # Verify lookups found the expected exceptions
        assert len(lookup_results) > 0
        assert all(name.startswith("Lookup_") for name in lookup_results)

    """Tests for the register_custom_pattern helper."""

    def test_register_custom_pattern(self, registered_builtins):
        register_custom_pattern(
            pattern=r"my_custom_error",
            name="Custom Pattern",
            retry=True,
            description="A custom error pattern.",
            suggestion="Fix your custom code.",
        )

        exc = Exception("my_custom_error occurred")
        info = ExceptionRegistry.get_ex_info(exc)
        assert info is not None
        assert info.name == "Custom Pattern"
        assert info.retry is True
        assert info.suggestion == "Fix your custom code."
