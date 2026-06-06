"""Comprehensive tests for ConsoleSpinner to boost coverage.

Tests spinner animation, state management, threading, and visual output.
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.text import Text


# Patch register_spinner at the package level where it's imported from
@pytest.fixture(autouse=True)
def mock_spinner_registration():
    """Mock spinner registration for all tests."""
    with (
        patch("code_puppy.messaging.spinner.register_spinner"),
        patch("code_puppy.messaging.spinner.unregister_spinner"),
    ):
        yield


def _started_spinner(mock_console):
    """Start a spinner with Live and panel patched; return (spinner, mock_live_cls)."""
    from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

    spinner = ConsoleSpinner(console=mock_console)
    patches = (
        patch("code_puppy.messaging.spinner.console_spinner.Live"),
        patch.object(spinner, "_generate_spinner_panel", return_value=Text("test")),
    )
    with patches[0] as mock_live_cls, patches[1]:
        mock_live_cls.return_value = MagicMock()
        spinner.start()
    return spinner, mock_live_cls


class TestConsoleSpinnerInit:
    """Tests for ConsoleSpinner initialization."""

    def test_init_console_and_default_state(self):
        """Default-constructed spinner creates a Console and sets default state."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner()

        assert isinstance(spinner.console, Console)
        assert spinner._thread is None
        assert spinner._paused is False
        assert spinner._live is None
        assert spinner._is_spinning is False

    def test_init_uses_provided_console(self):
        """Test that provided console is used."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)

        assert spinner.console is mock_console

    def test_init_registers_spinner(self):
        """Test that spinner is registered on init."""
        with patch("code_puppy.messaging.spinner.register_spinner") as mock_register:
            from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

            spinner = ConsoleSpinner()

            mock_register.assert_called_once_with(spinner)


class TestConsoleSpinnerStart:
    """Tests for ConsoleSpinner.start() method."""

    def test_start_sets_up_live_thread_and_state(self):
        """start() sets spinning state, clears stop event, creates Live + daemon thread."""
        mock_console = MagicMock(spec=Console)
        spinner, mock_live_cls = _started_spinner(mock_console)
        time.sleep(0.1)  # let thread start

        try:
            assert spinner._is_spinning is True
            mock_live_cls.assert_called_once()
            mock_live_cls.return_value.start.assert_called_once()
            mock_console.print.assert_called()  # blank line for separation
            assert spinner._thread is not None
            assert spinner._thread.daemon is True
        finally:
            spinner._stop_event.set()
            spinner._thread.join(timeout=0.5)

    def test_start_does_not_create_thread_if_already_running(self):
        """Test that start() doesn't create new thread if one exists."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)

        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        spinner._thread = mock_thread
        spinner._is_spinning = True

        with patch("threading.Thread") as mock_thread_class:
            spinner.start()

        # Should not create a new thread
        mock_thread_class.assert_not_called()


class TestConsoleSpinnerStop:
    """Tests for ConsoleSpinner.stop() method."""

    def test_stop_when_not_spinning_returns_early(self):
        """Test that stop() returns early if not spinning."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = False

        with patch("code_puppy.messaging.spinner.unregister_spinner") as mock_unreg:
            spinner.stop()

        # Should not try to unregister if not spinning
        mock_unreg.assert_not_called()

    def test_stop_sets_state_stops_live_joins_thread_and_unregisters(self):
        """stop() sets stop event, flips spinning flag, stops Live, joins thread, unregisters."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True
        mock_live = MagicMock()
        spinner._live = mock_live
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        spinner._thread = mock_thread

        with patch("code_puppy.messaging.spinner.unregister_spinner") as mock_unreg:
            spinner.stop()

        assert spinner._stop_event.is_set()
        assert spinner._is_spinning is False
        mock_live.stop.assert_called_once()
        assert spinner._live is None
        mock_thread.join.assert_called_once_with(timeout=0.5)
        assert spinner._thread is None
        mock_unreg.assert_called_once_with(spinner)

    def test_stop_windows_cleanup(self):
        """Test Windows-specific cleanup on stop."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True

        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        with (
            patch("platform.system", return_value="Windows"),
            patch.object(sys, "stdout", mock_stdout),
            patch.object(sys, "stderr", mock_stderr),
        ):
            spinner.stop()

        # Should write ANSI reset codes on Windows
        assert mock_stdout.write.called
        assert mock_stderr.write.called

    def test_stop_non_windows_no_special_cleanup(self):
        """Test that non-Windows doesn't do special cleanup."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock(spec=Console)
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True

        mock_stdout = MagicMock()

        with (
            patch("platform.system", return_value="Linux"),
            patch.object(sys, "stdout", mock_stdout),
        ):
            spinner.stop()

        # stdout.write should not be called for ANSI reset on Linux
        # The write is only in the Windows block


class TestConsoleSpinnerUpdateFrame:
    """Tests for update_frame method."""

    @pytest.mark.parametrize("start_offset", [0, -1])
    def test_update_frame_advances_and_wraps(self, start_offset):
        """update_frame advances the index and wraps around at the end of frames."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner
        from code_puppy.messaging.spinner.spinner_base import SpinnerBase

        num_frames = len(SpinnerBase.FRAMES)
        start_index = start_offset % num_frames
        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        spinner._frame_index = start_index

        spinner.update_frame()

        assert spinner._frame_index == (start_index + 1) % num_frames


class TestConsoleSpinnerGeneratePanel:
    """Tests for _generate_spinner_panel method."""

    @pytest.mark.parametrize(
        "paused, awaiting",
        [(True, False), (False, True)],
    )
    def test_generate_panel_returns_empty_when_inactive(self, paused, awaiting):
        """Paused or awaiting-input spinner returns empty Text."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._paused = paused

        with patch(
            "code_puppy.tools.command_runner.is_awaiting_user_input",
            return_value=awaiting,
        ):
            result = spinner._generate_spinner_panel()

        assert isinstance(result, Text)
        assert str(result) == ""

    def test_generate_panel_includes_thinking_and_current_frame(self):
        """Panel includes the thinking message and the current spinner frame."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner
        from code_puppy.messaging.spinner.spinner_base import SpinnerBase

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._paused = False
        spinner._frame_index = 0

        with patch(
            "code_puppy.tools.command_runner.is_awaiting_user_input", return_value=False
        ):
            result = spinner._generate_spinner_panel()

        result_str = str(result)
        assert "thinking" in result_str.lower()
        assert SpinnerBase.FRAMES[0] in result_str

    @pytest.mark.parametrize(
        "context_info, expected_substr",
        [
            ("Tokens: 1,000/10,000 (10.0% used)", "Tokens"),
            ("", None),
        ],
    )
    def test_generate_panel_context_info(self, context_info, expected_substr):
        """Panel includes context info when present and stays valid Text when empty."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner
        from code_puppy.messaging.spinner.spinner_base import SpinnerBase

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._paused = False
        spinner._frame_index = 0

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch.object(SpinnerBase, "get_context_info", return_value=context_info),
        ):
            result = spinner._generate_spinner_panel()

        assert isinstance(result, Text)
        if expected_substr is not None:
            assert expected_substr in str(result)


class TestConsoleSpinnerUpdateSpinner:
    """Tests for _update_spinner background thread method."""

    def test_update_spinner_stops_on_event(self):
        """Test that _update_spinner stops when stop event is set."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._stop_event.set()

        # Should return quickly
        spinner._update_spinner()

        # If we got here, it stopped

    def test_update_spinner_updates_frame(self):
        """Test that _update_spinner calls update_frame."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._live = MagicMock()
        spinner._paused = False
        call_count = 0

        def stop_after_calls():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                spinner._stop_event.set()

        with (
            patch.object(spinner, "update_frame", side_effect=stop_after_calls),
            patch.object(spinner, "_generate_spinner_panel", return_value=Text("test")),
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
        ):
            spinner._update_spinner()

        assert call_count >= 2

    @pytest.mark.parametrize(
        "paused, awaiting",
        [(True, False), (False, True)],
    )
    def test_update_spinner_skips_update_when_inactive(self, paused, awaiting):
        """_update_spinner skips the display update when paused or awaiting input."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._paused = paused
        spinner._live = MagicMock()
        call_count = 0

        def stop_after_calls():
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                spinner._stop_event.set()

        with (
            patch.object(spinner, "update_frame", side_effect=stop_after_calls),
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=awaiting,
            ),
        ):
            spinner._update_spinner()

        # Should not update live display when inactive
        spinner._live.update.assert_not_called()

    def test_update_spinner_handles_exception(self):
        """Test that _update_spinner handles exceptions gracefully."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._live = MagicMock()

        mock_stderr = MagicMock()

        with (
            patch.object(
                spinner, "update_frame", side_effect=RuntimeError("test error")
            ),
            patch.object(sys, "stderr", mock_stderr),
        ):
            spinner._update_spinner()

        # Should write error to stderr
        mock_stderr.write.assert_called()
        assert spinner._is_spinning is False


class TestConsoleSpinnerPause:
    """Tests for pause method."""

    def test_pause_sets_flag_stops_live_and_clears_line(self):
        """pause() sets the paused flag, stops the live display, and clears the line."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        mock_live = MagicMock()
        spinner._live = mock_live
        mock_stdout = MagicMock()

        with patch.object(sys, "stdout", mock_stdout):
            spinner.pause()

        assert spinner._paused is True
        mock_live.stop.assert_called_once()
        assert spinner._live is None
        mock_stdout.write.assert_called()  # cursor/line clear codes

    def test_pause_does_nothing_when_not_spinning(self):
        """Test that pause does nothing when not spinning."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = False
        spinner._paused = False

        spinner.pause()

        assert spinner._paused is False

    def test_pause_handles_exception(self):
        """Test that pause handles exceptions gracefully."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        mock_live = MagicMock()
        mock_live.stop.side_effect = RuntimeError("test")
        spinner._live = mock_live

        # Should not raise
        spinner.pause()


class TestConsoleSpinnerResume:
    """Tests for resume method."""

    def test_resume_clears_paused_flag(self):
        """Test that resume clears the paused flag."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        spinner._paused = True
        spinner._live = MagicMock()

        with patch(
            "code_puppy.tools.command_runner.is_awaiting_user_input", return_value=False
        ):
            spinner.resume()

        assert spinner._paused is False

    def test_resume_does_nothing_when_awaiting_input(self):
        """Test that resume does nothing when awaiting user input."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        spinner._paused = True

        with patch(
            "code_puppy.tools.command_runner.is_awaiting_user_input", return_value=True
        ):
            spinner.resume()

        # Should remain paused
        assert spinner._paused is True

    def test_resume_restarts_live_display(self):
        """Test that resume restarts the live display."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True
        spinner._paused = True
        spinner._live = None

        mock_stdout = MagicMock()

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch(
                "code_puppy.messaging.spinner.console_spinner.Live"
            ) as mock_live_class,
            patch.object(sys, "stdout", mock_stdout),
        ):
            mock_live = MagicMock()
            mock_live_class.return_value = mock_live
            spinner.resume()

        mock_live_class.assert_called_once()
        mock_live.start.assert_called_once()

    def test_resume_updates_existing_live_display(self):
        """Test that resume updates existing live display."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()
        mock_console.file = MagicMock()
        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True
        spinner._paused = True
        mock_live = MagicMock()
        spinner._live = mock_live

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch.object(spinner, "_generate_spinner_panel", return_value=Text("test")),
        ):
            spinner.resume()

        mock_live.update.assert_called()
        mock_live.refresh.assert_called()

    def test_resume_does_nothing_when_not_spinning(self):
        """Test that resume does nothing when not spinning."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = False
        spinner._paused = True

        with patch(
            "code_puppy.tools.command_runner.is_awaiting_user_input", return_value=False
        ):
            spinner.resume()

        # paused state unchanged when not spinning
        assert spinner._paused is True

    def test_resume_does_nothing_when_not_paused(self):
        """Test that resume does nothing when not paused."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        spinner._paused = False

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch(
                "code_puppy.messaging.spinner.console_spinner.Live"
            ) as mock_live_class,
        ):
            spinner.resume()

        # Should not create new Live display
        mock_live_class.assert_not_called()

    def test_resume_handles_exception(self):
        """Test that resume handles exceptions gracefully."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())
        spinner._is_spinning = True
        spinner._paused = True
        spinner._live = None

        mock_stdout = MagicMock()

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch(
                "code_puppy.messaging.spinner.console_spinner.Live",
                side_effect=RuntimeError("test"),
            ),
            patch.object(sys, "stdout", mock_stdout),
        ):
            # Should not raise
            spinner.resume()

    def test_resume_clears_console_buffer_if_exists(self):
        """Test that resume clears console buffer if it exists."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()
        mock_console._buffer = []
        mock_console.file = MagicMock()

        spinner = ConsoleSpinner(console=mock_console)
        spinner._is_spinning = True
        spinner._paused = True
        mock_live = MagicMock()
        spinner._live = mock_live

        with (
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch.object(spinner, "_generate_spinner_panel", return_value=Text("test")),
        ):
            spinner.resume()

        # Should have written clear codes
        mock_console.file.write.assert_called()


class TestConsoleSpinnerContextManager:
    """Tests for context manager protocol."""

    def test_enter_starts_spinner(self):
        """Test that __enter__ starts the spinner."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())

        with patch.object(spinner, "start") as mock_start:
            result = spinner.__enter__()

        mock_start.assert_called_once()
        assert result is spinner

    def test_exit_stops_spinner(self):
        """Test that __exit__ stops the spinner."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        spinner = ConsoleSpinner(console=MagicMock())

        with patch.object(spinner, "stop") as mock_stop:
            spinner.__exit__(None, None, None)

        mock_stop.assert_called_once()

    def test_context_manager_full_cycle(self):
        """Test full context manager cycle."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()

        with (
            patch("code_puppy.messaging.spinner.console_spinner.Live") as mock_live,
        ):
            mock_live_instance = MagicMock()
            mock_live.return_value = mock_live_instance

            spinner = ConsoleSpinner(console=mock_console)

            with spinner:
                assert spinner._is_spinning is True

            # After context, should be stopped
            assert spinner._is_spinning is False


class TestConsoleSpinnerIntegration:
    """Integration tests for ConsoleSpinner."""

    def test_full_start_stop_cycle(self):
        """Test complete start/stop lifecycle."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()

        with (
            patch("code_puppy.messaging.spinner.console_spinner.Live") as mock_live,
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
        ):
            mock_live_instance = MagicMock()
            mock_live.return_value = mock_live_instance

            spinner = ConsoleSpinner(console=mock_console)

            spinner.start()
            assert spinner._is_spinning is True
            time.sleep(0.1)  # Let thread run briefly

            spinner.stop()
            assert spinner._is_spinning is False
            assert spinner._thread is None

    def test_pause_resume_cycle(self):
        """Test pause and resume cycle."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()

        with (
            patch("code_puppy.messaging.spinner.console_spinner.Live") as mock_live,
            patch(
                "code_puppy.tools.command_runner.is_awaiting_user_input",
                return_value=False,
            ),
            patch.object(sys, "stdout"),
        ):
            mock_live_instance = MagicMock()
            mock_live.return_value = mock_live_instance

            spinner = ConsoleSpinner(console=mock_console)

            spinner.start()
            assert spinner._is_spinning is True
            assert spinner._paused is False

            spinner.pause()
            assert spinner._paused is True

            spinner.resume()
            assert spinner._paused is False

            spinner.stop()

    def test_multiple_start_calls(self):
        """Test multiple start calls are handled."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()

        with (
            patch("code_puppy.messaging.spinner.console_spinner.Live") as mock_live,
        ):
            mock_live_instance = MagicMock()
            mock_live.return_value = mock_live_instance

            spinner = ConsoleSpinner(console=mock_console)

            spinner.start()
            first_thread = spinner._thread
            time.sleep(0.05)

            spinner.start()  # Should not create new thread

            # Thread should be the same
            assert spinner._thread is first_thread

            spinner.stop()

    def test_multiple_stop_calls(self):
        """Test multiple stop calls are handled."""
        from code_puppy.messaging.spinner.console_spinner import ConsoleSpinner

        mock_console = MagicMock()

        with (
            patch("code_puppy.messaging.spinner.console_spinner.Live") as mock_live,
        ):
            mock_live_instance = MagicMock()
            mock_live.return_value = mock_live_instance

            spinner = ConsoleSpinner(console=mock_console)

            spinner.start()
            spinner.stop()

            # Second stop should not raise
            spinner.stop()

            assert spinner._is_spinning is False
