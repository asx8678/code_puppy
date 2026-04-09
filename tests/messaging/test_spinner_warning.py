"""Tests for long_spinner_with_warning flashing behavior."""

import asyncio
from unittest.mock import patch

import pytest

from code_puppy.messaging import spinner as spinner_mod


@pytest.mark.asyncio
async def test_long_spinner_starts_with_message():
    """Initial call should start the spinner with the main message."""
    with patch.object(spinner_mod, "_start_spinner_impl") as mock_start:
        await spinner_mod.long_spinner_with_warning(
            "Working...",
            "Taking longer than expected",
            initial_delay_s=10.0,
            warning_duration_s=10.0,
        )
        # Immediate call with main message
        assert mock_start.called
        assert mock_start.call_args_list[0].args[0] == "Working..."
        # Cleanup: cancel the flasher task
        spinner_mod.stop_long_spinner_with_warning()


@pytest.mark.asyncio
async def test_warning_appears_after_delay():
    """After initial_delay_s, the spinner text switches to the warning."""
    calls = []

    def capture(msg):
        calls.append(msg)

    with patch.object(spinner_mod, "_start_spinner_impl", side_effect=capture):
        await spinner_mod.long_spinner_with_warning(
            "Working...",
            "Slow!",
            initial_delay_s=0.1,
            warning_duration_s=0.1,
        )
        # Wait enough time for: initial -> delay -> warning -> delay -> back to main
        await asyncio.sleep(0.25)
        spinner_mod.stop_long_spinner_with_warning()

    assert "Working..." in calls
    assert "Slow!" in calls
    # Should have started with main, then gone to warning, then back
    assert calls[0] == "Working..."
    assert "Slow!" in calls[1:]


@pytest.mark.asyncio
async def test_cancellation_stops_flasher():
    """Calling stop_long_spinner_with_warning should prevent further flashes."""
    calls = []

    def capture(msg):
        calls.append(msg)

    with patch.object(spinner_mod, "_start_spinner_impl", side_effect=capture):
        await spinner_mod.long_spinner_with_warning(
            "A",
            "B",
            initial_delay_s=0.05,
            warning_duration_s=0.05,
        )
        await asyncio.sleep(0.02)  # before first flash
        spinner_mod.stop_long_spinner_with_warning()
        calls_count_at_cancel = len(calls)
        await asyncio.sleep(0.2)  # wait past what would have been a flash

    # No additional flashes should have happened after cancellation
    assert len(calls) == calls_count_at_cancel


@pytest.mark.asyncio
async def test_new_call_supersedes_old():
    """A second call to long_spinner_with_warning should cancel the first flasher."""
    with patch.object(spinner_mod, "_start_spinner_impl"):
        await spinner_mod.long_spinner_with_warning(
            "First",
            "FirstWarn",
            initial_delay_s=10.0,
            warning_duration_s=10.0,
        )
        task1 = spinner_mod._current_warning_task
        await spinner_mod.long_spinner_with_warning(
            "Second",
            "SecondWarn",
            initial_delay_s=10.0,
            warning_duration_s=10.0,
        )
        # The first task should be cancelled
        await asyncio.sleep(0.01)
        assert task1.cancelled() or task1.done()
        spinner_mod.stop_long_spinner_with_warning()
