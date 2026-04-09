"""Tests for warn_once helper functionality."""

import logging
import threading
from unittest.mock import MagicMock

import pytest

from code_puppy.async_utils import warn_once, clear_warn_once_history, _warn_once_keys


@pytest.fixture(autouse=True)
def reset_warn_once_state():
    """Reset warn_once state before each test."""
    clear_warn_once_history()
    yield
    clear_warn_once_history()


def test_warn_once_logs_on_first_call():
    """First call with a key should log the message."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    warn_once("test_key", "Test warning message", logger=mock_logger)
    
    mock_logger.warning.assert_called_once_with("Test warning message")


def test_warn_once_suppresses_duplicates():
    """Second call with same key should not log."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    warn_once("duplicate_key", "First message", logger=mock_logger)
    warn_once("duplicate_key", "Second message", logger=mock_logger)
    
    # Should only log once
    assert mock_logger.warning.call_count == 1
    mock_logger.warning.assert_called_once_with("First message")


def test_warn_once_different_keys_log_independently():
    """Different keys should log independently."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    warn_once("key_a", "Message A", logger=mock_logger)
    warn_once("key_b", "Message B", logger=mock_logger)
    warn_once("key_a", "Message A again", logger=mock_logger)  # Should be suppressed
    
    assert mock_logger.warning.call_count == 2
    calls = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert "Message A" in calls
    assert "Message B" in calls
    assert "Message A again" not in calls


def test_warn_once_uses_module_logger_by_default():
    """When no logger provided, uses module-level logger."""
    # Just verify it doesn't crash - we can't easily mock the module logger
    warn_once("default_logger_test", "Test with default logger")
    
    # Key should be tracked
    assert "default_logger_test" in _warn_once_keys


def test_warn_once_thread_safety():
    """Thread-safe under concurrent calls with same key."""
    mock_logger = MagicMock(spec=logging.Logger)
    call_count = threading.Lock()
    logged_count = [0]
    
    def worker():
        warn_once("concurrent_key", "Concurrent message", logger=mock_logger)
        with call_count:
            logged_count[0] = mock_logger.warning.call_count
    
    threads = []
    for _ in range(20):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # Only one call should have logged
    assert mock_logger.warning.call_count == 1


def test_warn_once_thread_safety_different_keys():
    """Thread-safe with many different keys."""
    mock_logger = MagicMock(spec=logging.Logger)
    results = []
    results_lock = threading.Lock()
    
    def worker(key_id: int):
        key = f"thread_key_{key_id}"
        warn_once(key, f"Message {key_id}", logger=mock_logger)
        with results_lock:
            results.append(key_id)
    
    threads = []
    for i in range(50):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # All 50 unique keys should have logged
    assert mock_logger.warning.call_count == 50
    assert len(_warn_once_keys) == 50


def test_clear_warn_once_history_resets_state():
    """clear_warn_once_history() resets all tracking state."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    warn_once("reset_key", "First", logger=mock_logger)
    assert "reset_key" in _warn_once_keys
    
    clear_warn_once_history()
    
    assert "reset_key" not in _warn_once_keys
    
    # Should be able to log again
    warn_once("reset_key", "Second", logger=mock_logger)
    assert mock_logger.warning.call_count == 2


def test_clear_warn_once_history_thread_safe():
    """clear_warn_once_history is thread-safe."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    # Add some keys first
    for i in range(10):
        warn_once(f"clear_test_{i}", f"Message {i}", logger=mock_logger)
    
    def clearer():
        clear_warn_once_history()
    
    def adder(key_id: int):
        warn_once(f"concurrent_add_{key_id}", f"Add {key_id}", logger=mock_logger)
    
    threads = []
    # Mix of clearers and adders
    for i in range(5):
        threads.append(threading.Thread(target=clearer))
        threads.append(threading.Thread(target=adder, args=(i,)))
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Should not crash, state should be consistent
    # (exact count depends on timing, but should be valid)
    assert isinstance(_warn_once_keys, set)


def test_warn_once_empty_key():
    """Empty string key is valid and tracked."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    warn_once("", "Empty key message", logger=mock_logger)
    warn_once("", "Another empty key message", logger=mock_logger)
    
    # Only first should log
    assert mock_logger.warning.call_count == 1
    mock_logger.warning.assert_called_with("Empty key message")


def test_warn_once_special_characters_in_key():
    """Keys with special characters work correctly."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    special_keys = [
        "key/with/slashes",
        "key.with.dots",
        "key:with:colons",
        "key with spaces",
        "unicode_日本語",
        "emoji_🐶",
    ]
    
    for key in special_keys:
        warn_once(key, f"Message for {key}", logger=mock_logger)
    
    assert mock_logger.warning.call_count == 6
    
    # All should be suppressed on second call
    for key in special_keys:
        warn_once(key, f"Second for {key}", logger=mock_logger)
    
    assert mock_logger.warning.call_count == 6


def test_warn_once_long_key():
    """Very long keys work correctly."""
    mock_logger = MagicMock(spec=logging.Logger)
    
    long_key = "a" * 10000
    
    warn_once(long_key, "First long key", logger=mock_logger)
    warn_once(long_key, "Second long key", logger=mock_logger)
    
    assert mock_logger.warning.call_count == 1


def test_warn_once_none_logger_uses_default():
    """Passing None for logger uses module default."""
    # Should not raise
    warn_once("none_logger_test", "Test message", logger=None)
    assert "none_logger_test" in _warn_once_keys


def test_warn_once_integration_with_real_logger(caplog):
    """Integration test with actual logging."""
    with caplog.at_level(logging.WARNING, logger="code_puppy.async_utils"):
        warn_once("integration_key", "Integration test warning")
        warn_once("integration_key", "This should not appear")
    
    assert "Integration test warning" in caplog.text
    assert "This should not appear" not in caplog.text
    assert caplog.text.count("Integration test warning") == 1
