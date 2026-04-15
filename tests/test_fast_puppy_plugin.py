"""Tests for code_puppy.plugins.fast_puppy.register_callbacks.

Covers the bug fixes:
  - _has_maturin() must check subprocess returncode, not just absence of exception.

bd-91: _try_auto_build() removed - auto-build eliminated, explicit build only.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# We only import the helper functions we need to test.
# Importing the full module is safe — it only registers callbacks at module
# scope and doesn't trigger builds unless startup fires.
from code_puppy.plugins.fast_puppy.register_callbacks import (
    _handle_fast_puppy,
    _on_startup,
)
# bd-91: _has_maturin moved to rust_builder.py
from code_puppy.plugins.fast_puppy.rust_builder import _has_maturin


# ---------------------------------------------------------------------------
# _has_maturin()
# ---------------------------------------------------------------------------


class TestHasMaturin:
    """_has_maturin should return True only when maturin is genuinely available."""

    @patch("code_puppy.plugins.fast_puppy.rust_builder.shutil.which")
    def test_returns_true_when_in_path(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/bin/maturin"
        assert _has_maturin() is True

    @patch(
        "code_puppy.plugins.fast_puppy.rust_builder.shutil.which",
        return_value=None,
    )
    @patch("code_puppy.plugins.fast_puppy.rust_builder.subprocess.run")
    def test_returns_true_on_zero_rc(
        self, mock_run: MagicMock, _mock_which: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert _has_maturin() is True
        # Verify subprocess.run was called with expected args (env is passed)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == [sys.executable, "-m", "maturin", "--version"]
        assert call_args[1].get("capture_output") is True
        assert call_args[1].get("timeout") == 10
        assert "env" in call_args[1]

    @patch(
        "code_puppy.plugins.fast_puppy.rust_builder.shutil.which",
        return_value=None,
    )
    @patch("code_puppy.plugins.fast_puppy.rust_builder.subprocess.run")
    def test_returns_false_on_nonzero_rc(
        self, mock_run: MagicMock, _mock_which: MagicMock
    ) -> None:
        """Bug fix: a completed-but-failing subprocess must *not* be treated as success."""
        mock_run.return_value = MagicMock(returncode=1)
        assert _has_maturin() is False

    @patch(
        "code_puppy.plugins.fast_puppy.rust_builder.shutil.which",
        return_value=None,
    )
    @patch(
        "code_puppy.plugins.fast_puppy.rust_builder.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_returns_false_on_exception(
        self, _mock_run: MagicMock, _mock_which: MagicMock
    ) -> None:
        assert _has_maturin() is False


# bd-91: _try_auto_build() and auto-build functionality removed
# Tests removed as _try_auto_build() was eliminated when auto-build was removed.
# Build functionality now only available via /fast_puppy build command.

# ---------------------------------------------------------------------------
# _handle_fast_puppy()
# ---------------------------------------------------------------------------


class TestHandleFastPuppy:
    """_handle_fast_puppy routes commands correctly."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _handle_fast_puppy("/something_else", "something_else")
        assert result is None

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._find_crate_dir")
    @patch("code_puppy._core_bridge.get_rust_status")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy._core_bridge.RUST_AVAILABLE", True)
    def test_status_shows_diagnostics(
        self,
        mock_emit: MagicMock,
        mock_status: MagicMock,
        mock_find: MagicMock,
        mock_rust: MagicMock,
    ) -> None:
        mock_status.return_value = {"active": True, "installed": True, "enabled": True}
        mock_rust.return_value = True
        mock_find.return_value = Path("/fake/crate")

        result = _handle_fast_puppy("/fast_puppy", "fast_puppy")
        assert result is True
        # Status should emit diagnostic line(s)
        assert mock_emit.call_count >= 1

    @patch("code_puppy.native_backend.NativeBackend.save_preferences")
    @patch("code_puppy.native_backend.NativeBackend.disable_all")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    def test_disable_uses_native_backend(
        self,
        mock_emit: MagicMock,
        mock_disable_all: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """Disable now uses NativeBackend.disable_all() instead of set_rust_enabled."""
        result = _handle_fast_puppy("/fast_puppy disable", "fast_puppy")
        assert result is True
        mock_disable_all.assert_called_once()
        mock_save.assert_called_once()

    @patch("code_puppy.native_backend.NativeBackend.save_preferences")
    @patch("code_puppy.native_backend.NativeBackend.enable_all")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    def test_enable_uses_native_backend(
        self,
        mock_emit: MagicMock,
        mock_enable_all: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """Enable now uses NativeBackend.enable_all() instead of set_rust_enabled."""
        result = _handle_fast_puppy("/fast_puppy enable", "fast_puppy")
        assert result is True
        mock_enable_all.assert_called_once()
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# _on_startup()
# ---------------------------------------------------------------------------


class TestOnStartup:
    """_on_startup detects available backends and respects user preferences."""

    @patch(
        "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends"
    )
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.native_backend.NativeBackend.load_preferences")
    @patch("code_puppy.native_backend.NativeBackend.is_enabled")
    def test_startup_detects_backends_and_emits_info(
        self,
        mock_is_enabled: MagicMock,
        mock_load_prefs: MagicMock,
        mock_emit: MagicMock,
        mock_get_backends: MagicMock,
    ) -> None:
        """Startup now detects backends without auto-building."""
        mock_is_enabled.return_value = True  # Capabilities enabled
        mock_get_backends.return_value = {
            "elixir_available": True,
            "rust_installed": True,
            "python_fallback": True,
        }

        _on_startup()

        mock_load_prefs.assert_called_once()
        mock_get_backends.assert_called_once()
        # Should emit info about native backend status
        mock_emit.assert_called_once()
        # Verify the message mentions Elixir
        call_args = mock_emit.call_args[0][0]
        assert "Elixir" in call_args or "native" in call_args.lower()

    @patch(
        "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends"
    )
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.native_backend.NativeBackend.load_preferences")
    @patch("code_puppy.native_backend.NativeBackend.is_enabled")
    def test_startup_shows_python_fallback_when_no_native_backends(
        self,
        mock_is_enabled: MagicMock,
        mock_load_prefs: MagicMock,
        mock_emit: MagicMock,
        mock_get_backends: MagicMock,
    ) -> None:
        """When no native backends available, shows Python fallback message."""
        mock_is_enabled.return_value = False  # All capabilities disabled
        mock_get_backends.return_value = {
            "elixir_available": False,
            "rust_installed": False,
            "python_fallback": True,
        }

        _on_startup()

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0][0]
        # bd-92: _emit_startup_banner outputs "Python fallback (no native backends)"
        assert "Python fallback" in call_args or "🐕" in call_args
