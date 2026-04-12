"""Tests for fast_puppy Rust extension edge cases.

This module tests edge cases in the fast_puppy plugin:
1. Empty results dict handling - _on_startup() shouldn't claim all active when empty
2. _install_maturin() fallback logic - uv first, then pip fallback
3. Partial success messaging - correct active/total counts when some crates available
"""

from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.fast_puppy.builder import (
    _install_maturin,
    CRATES,
)
from code_puppy.plugins.fast_puppy.register_callbacks import _on_startup


class TestFastPuppyStartup:
    """Tests for fast_puppy startup behavior."""

    def test_empty_results_no_false_positive(self):
        """Empty results dict should not claim all accelerators active."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={},  # Empty results
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=None,  # First run
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should NOT claim all accelerators are active
        assert "All Rust accelerators active" not in all_output
        # Should NOT show "3/0" or other nonsensical counts
        assert "/0" not in all_output
        # Should indicate pure Python mode or no accelerators
        assert (
            "Pure Python" in all_output
            or "0/3" in all_output
            or "install" in all_output.lower()
            or "🐕" in all_output
        )

    def test_partial_results_correct_count(self):
        """Partial success should show correct active/total counts."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={
                    "code_puppy_core": True,
                    "turbo_ops": False,
                    "turbo_parse": False,
                },
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=True,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should show correct count (1/3)
        assert "1/3" in all_output
        # Should NOT claim all are active
        assert "All Rust accelerators active" not in all_output
        # Should mention the missing crates
        assert "turbo_ops" in all_output or "turbo_parse" in all_output

    def test_two_of_three_active_message(self):
        """When 2 of 3 crates are active, show correct message."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={
                    "code_puppy_core": True,
                    "turbo_ops": True,
                    "turbo_parse": False,
                },
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=True,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should show 2/3 count
        assert "2/3" in all_output
        # Should mention only missing crate
        assert "turbo_parse" in all_output
        # Should NOT claim all are active
        assert "All Rust accelerators active" not in all_output

    def test_all_three_active_shows_success_message(self):
        """When all 3 crates are active, show success message."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={
                    "code_puppy_core": True,
                    "turbo_ops": True,
                    "turbo_parse": True,
                },
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=True,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should show all active message
        assert "All Rust accelerators active" in all_output
        # Should show rocket emoji
        assert "🚀" in all_output


class TestMaturinInstall:
    """Tests for maturin installation logic."""

    def test_tries_uv_first(self):
        """Should try uv pip install before falling back to pip."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv is available
                mock_which.return_value = "/usr/bin/uv"
                # uv install succeeds
                mock_run.return_value = MagicMock(returncode=0)

                result = _install_maturin()

        assert result is True
        # Should have called subprocess.run exactly once (uv path)
        mock_run.assert_called_once()
        # Verify it was the uv pip install command
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "uv"
        assert "pip" in call_args
        assert "install" in call_args
        assert "maturin" in call_args

    def test_fallback_to_pip_when_uv_fails(self):
        """Should fall back to pip when uv fails."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv is available
                mock_which.return_value = "/usr/bin/uv"
                # First call (uv) fails, need to simulate two calls
                mock_run.side_effect = [
                    MagicMock(returncode=1),  # uv fails
                    MagicMock(returncode=0),  # pip succeeds
                ]

                with patch("sys.executable", "/usr/bin/python"):
                    result = _install_maturin()

        assert result is True
        # Should have called subprocess.run twice (uv + pip)
        assert mock_run.call_count == 2
        # First call should be uv
        first_call = mock_run.call_args_list[0][0][0]
        assert first_call[0] == "uv"
        # Second call should be pip
        second_call = mock_run.call_args_list[1][0][0]
        assert second_call[0] == "/usr/bin/python"
        assert "-m" in second_call
        assert "pip" in second_call

    def test_fallback_to_pip_when_uv_missing(self):
        """Should use pip when uv is not available."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv is NOT available, but we need both calls for _has_maturin check
                # First call checks for maturin (None), second checks for uv (None)
                mock_which.side_effect = [None, None]
                # pip install succeeds
                mock_run.return_value = MagicMock(returncode=0)

                with patch("sys.executable", "/usr/bin/python"):
                    result = _install_maturin()

        assert result is True
        # Should only have called subprocess.run once (pip path only)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/python"
        assert "-m" in call_args
        assert "pip" in call_args

    def test_returns_false_when_both_fail(self):
        """Should return False when both uv and pip fail."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv is available but both install methods fail
                mock_which.return_value = "/usr/bin/uv"
                mock_run.side_effect = [
                    MagicMock(returncode=1),  # uv fails
                    MagicMock(returncode=1),  # pip fails
                ]

                with patch("sys.executable", "/usr/bin/python"):
                    result = _install_maturin()

        assert result is False

    def test_handles_uv_exception(self):
        """Should handle exceptions from uv and fall back to pip."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv is available
                mock_which.return_value = "/usr/bin/uv"
                # First call raises exception, second succeeds
                mock_run.side_effect = [
                    Exception("uv not working"),  # uv throws exception
                    MagicMock(returncode=0),  # pip succeeds
                ]

                with patch("sys.executable", "/usr/bin/python"):
                    result = _install_maturin()

        assert result is True
        # Should have called subprocess.run twice
        assert mock_run.call_count == 2

    def test_handles_pip_exception(self):
        """Should handle exceptions from pip and return False."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # uv not available
                mock_which.side_effect = [None, None]
                # pip raises exception
                mock_run.side_effect = Exception("pip not working")

                with patch("sys.executable", "/usr/bin/python"):
                    result = _install_maturin()

        assert result is False


class TestMaturinInstallTimeout:
    """Tests for maturin installation timeout handling."""

    def test_uv_respects_timeout(self):
        """Should pass 120s timeout to uv command."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                mock_which.return_value = "/usr/bin/uv"
                mock_run.return_value = MagicMock(returncode=0)

                _install_maturin()

        # Check timeout parameter was passed
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("timeout") == 120

    def test_pip_respects_timeout(self):
        """Should pass 120s timeout to pip command."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                mock_which.side_effect = [None, None]
                mock_run.return_value = MagicMock(returncode=0)

                with patch("sys.executable", "/usr/bin/python"):
                    _install_maturin()

        # Check timeout parameter was passed
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("timeout") == 120


class TestStartupEdgeCases:
    """Additional edge cases for startup behavior."""

    def test_single_crate_result_shows_correct_message(self):
        """When only 1 crate in results (edge case), show correct count."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={
                    "code_puppy_core": True,
                    # Note: only 1 crate in results (unexpected but handle gracefully)
                },
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=True,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should show 1/1 count for the results we have
        assert "1/1" in all_output
        # Should NOT claim all accelerators (since we expect 3)
        assert "All Rust accelerators active" not in all_output

    def test_all_false_results_shows_pure_python(self):
        """When all results are False, show pure Python message."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                return_value={
                    "code_puppy_core": False,
                    "turbo_ops": False,
                    "turbo_parse": False,
                },
            ):
                with patch("code_puppy._core_bridge.set_rust_enabled"):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=True,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                        ):
                            _on_startup()

        all_output = " ".join(emit_calls)
        # Should indicate pure Python mode
        assert (
            "Pure Python" in all_output
            or "0/3" in all_output
            or "missing" in all_output.lower()
        )
        # Should NOT claim all are active
        assert "All Rust accelerators active" not in all_output

    def test_startup_handles_exception_gracefully(self):
        """When startup throws exception, emit fallback message."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.emit_info",
            side_effect=mock_emit,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                side_effect=Exception("Unexpected error"),
            ):
                _on_startup()

        all_output = " ".join(emit_calls)
        # Should show fallback message about startup hiccup
        assert "hiccup" in all_output.lower() or "startup error" in all_output.lower()
