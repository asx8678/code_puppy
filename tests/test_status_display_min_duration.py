"""Tests for StatusDisplay spinner min-display-time behavior."""
import time
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.status_display import StatusDisplay


def _make_display() -> StatusDisplay:
    console = MagicMock()
    return StatusDisplay(console)


def test_min_duration_constants_defined():
    assert StatusDisplay.MIN_DURATION_WITH_MSG_S == pytest.approx(0.70)
    assert StatusDisplay.MIN_DURATION_WITHOUT_MSG_S == pytest.approx(0.35)


def test_stop_sleeps_when_fast_with_message():
    """If elapsed < 700ms and there's a loading message, stop should sleep the residual."""
    display = _make_display()
    display.is_active = True
    display.start_time = time.time() - 0.1  # 100ms ago
    # loading_messages is populated by default, so has_message should be True

    with patch("code_puppy.status_display.time.sleep") as mock_sleep:
        # Mock out the Live object to avoid real Rich interaction
        display.live = MagicMock()
        display.task = None
        display.stop()

    # Should have slept approximately 600ms (700 - 100)
    assert mock_sleep.called
    slept_for = mock_sleep.call_args[0][0]
    assert 0.55 < slept_for < 0.65, f"Expected ~600ms sleep, got {slept_for:.3f}s"


def test_stop_does_not_sleep_when_slow():
    """If elapsed > 700ms, no sleep should happen."""
    display = _make_display()
    display.is_active = True
    display.start_time = time.time() - 2.0  # 2 seconds ago

    with patch("code_puppy.status_display.time.sleep") as mock_sleep:
        display.live = MagicMock()
        display.task = None
        display.stop()

    # Either not called, or called with 0/negative
    if mock_sleep.called:
        slept_for = mock_sleep.call_args[0][0]
        assert slept_for <= 0


def test_stop_handles_none_start_time():
    """Defensive: if start_time is None, stop should not crash."""
    display = _make_display()
    display.start_time = None
    display.live = MagicMock()
    display.task = None
    # Should not raise
    display.stop()


def test_stop_sleeps_without_message():
    """If elapsed < 350ms and there's no loading message, stop should sleep the residual."""
    display = _make_display()
    display.is_active = True
    display.loading_messages = []  # No messages
    display.start_time = time.time() - 0.1  # 100ms ago

    with patch("code_puppy.status_display.time.sleep") as mock_sleep:
        display.live = MagicMock()
        display.task = None
        display.stop()

    # Should have slept approximately 250ms (350 - 100)
    assert mock_sleep.called
    slept_for = mock_sleep.call_args[0][0]
    assert 0.20 < slept_for < 0.30, f"Expected ~250ms sleep, got {slept_for:.3f}s"


def test_stop_uses_with_message_duration_when_has_messages():
    """Verify the 700ms path is taken when loading_messages is populated."""
    display = _make_display()
    display.is_active = True
    display.loading_messages = ["Some message"]  # Has message
    display.start_time = time.time() - 0.5  # 500ms ago

    with patch("code_puppy.status_display.time.sleep") as mock_sleep:
        display.live = MagicMock()
        display.task = None
        display.stop()

    # Should sleep ~200ms (700 - 500), not 0 (would be 350 - 500 = negative)
    assert mock_sleep.called
    slept_for = mock_sleep.call_args[0][0]
    # Should be around 200ms (700 - 500), definitely not 0
    assert 0.15 < slept_for < 0.25, f"Expected ~200ms sleep, got {slept_for:.3f}s"
