"""Tests for code_puppy.plugins.fast_puppy.register_callbacks.

Covers the bug fixes:
  - _has_maturin() must check subprocess returncode, not just absence of exception.
  - _try_auto_build() must bail out when pip-installing maturin fails.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# We only import the two helper functions we need to test.
# Importing the full module is safe — it only registers callbacks at module
# scope and doesn't trigger builds unless startup fires.
from code_puppy.plugins.fast_puppy.register_callbacks import (
    _handle_fast_puppy,
    _has_maturin,
    _on_startup,
    _try_auto_build,
)


# ---------------------------------------------------------------------------
# _has_maturin()
# ---------------------------------------------------------------------------

class TestHasMaturin:
    """_has_maturin should return True only when maturin is genuinely available."""

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.shutil.which")
    def test_returns_true_when_in_path(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/bin/maturin"
        assert _has_maturin() is True

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.shutil.which", return_value=None)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.subprocess.run")
    def test_returns_true_on_zero_rc(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert _has_maturin() is True
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "maturin", "--version"],
            capture_output=True,
            timeout=10,
        )

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.shutil.which", return_value=None)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.subprocess.run")
    def test_returns_false_on_nonzero_rc(self, mock_run: MagicMock, _mock_which: MagicMock) -> None:
        """Bug fix: a completed-but-failing subprocess must *not* be treated as success."""
        mock_run.return_value = MagicMock(returncode=1)
        assert _has_maturin() is False

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.shutil.which", return_value=None)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_false_on_exception(self, _mock_run: MagicMock, _mock_which: MagicMock) -> None:
        assert _has_maturin() is False


# ---------------------------------------------------------------------------
# _try_auto_build()
# ---------------------------------------------------------------------------

class TestTryAutoBuild:
    """_try_auto_build must not proceed to build when maturin install fails."""

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._build_rust_module")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain", return_value=True)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._find_crate_dir")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._has_maturin", return_value=False)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.subprocess.run")
    def test_bails_on_failed_pip_install(
        self,
        mock_run: MagicMock,
        mock_has_maturin: MagicMock,
        mock_find_crate: MagicMock,
        mock_rust: MagicMock,
        mock_build: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """When pip install maturin fails, _try_auto_build returns False and
        never calls _build_rust_module."""
        with patch("code_puppy._core_bridge.RUST_AVAILABLE", False):
            # Simulate pip install failure
            mock_run.return_value = MagicMock(
                returncode=1, stderr="ERROR: Could not install maturin", stdout=""
            )
            mock_find_crate.return_value = Path("/fake/code_puppy_core")

            result = _try_auto_build()

            assert result is False
            mock_build.assert_not_called()

    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._build_rust_module", return_value=True)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain", return_value=True)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._find_crate_dir")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._has_maturin", return_value=False)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.subprocess.run")
    def test_proceeds_on_successful_pip_install(
        self,
        mock_run: MagicMock,
        mock_has_maturin: MagicMock,
        mock_find_crate: MagicMock,
        mock_rust: MagicMock,
        mock_build: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """When pip install succeeds, _build_rust_module should be called."""
        with patch("code_puppy._core_bridge.RUST_AVAILABLE", False):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            mock_find_crate.return_value = Path("/fake/code_puppy_core")

            _try_auto_build()

            mock_build.assert_called_once_with(Path("/fake/code_puppy_core"))


# ---------------------------------------------------------------------------
# _handle_fast_puppy()
# ---------------------------------------------------------------------------

class TestHandleFastPuppy:
    """_handle_fast_puppy routes commands correctly."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _handle_fast_puppy("/something_else", "something_else")
        assert result is None

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference")
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
        mock_pref: MagicMock,
    ) -> None:
        mock_status.return_value = {"active": True, "installed": True, "enabled": True}
        mock_rust.return_value = True
        mock_find.return_value = Path("/fake/crate")
        mock_pref.return_value = True

        result = _handle_fast_puppy("/fast_puppy", "fast_puppy")
        assert result is True
        # Status should emit multiple diagnostic lines
        assert mock_emit.call_count >= 2

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference")
    @patch("code_puppy._core_bridge.set_rust_enabled")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy._core_bridge.RUST_AVAILABLE", True)
    def test_disable_persists_false(
        self,
        mock_emit: MagicMock,
        mock_set_rust: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        result = _handle_fast_puppy("/fast_puppy disable", "fast_puppy")
        assert result is True
        mock_set_rust.assert_called_once_with(False)
        mock_write.assert_called_once_with(False)

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference")
    @patch("code_puppy._core_bridge.set_rust_enabled")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy._core_bridge.RUST_AVAILABLE", True)
    def test_enable_when_rust_available(
        self,
        mock_emit: MagicMock,
        mock_set_rust: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        result = _handle_fast_puppy("/fast_puppy enable", "fast_puppy")
        assert result is True
        mock_set_rust.assert_called_once_with(True)
        mock_write.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# _on_startup()
# ---------------------------------------------------------------------------

class TestOnStartup:
    """_on_startup applies persisted preferences and optionally auto-builds."""

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build")
    @patch("code_puppy._core_bridge.set_rust_enabled")
    @patch("code_puppy._core_bridge.is_rust_enabled", return_value=False)
    @patch("code_puppy._core_bridge.RUST_AVAILABLE", False)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference", return_value=False)
    def test_skips_auto_build_when_disabled(
        self,
        mock_pref: MagicMock,
        mock_emit: MagicMock,
        mock_is_enabled: MagicMock,
        mock_set_rust: MagicMock,
        mock_auto_build: MagicMock,
    ) -> None:
        """When persisted preference is False, _try_auto_build should NOT be called."""
        _on_startup()
        mock_auto_build.assert_not_called()

    @patch("code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build")
    @patch("code_puppy._core_bridge.set_rust_enabled")
    @patch("code_puppy._core_bridge.is_rust_enabled", return_value=True)
    @patch("code_puppy._core_bridge.RUST_AVAILABLE", True)
    @patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info")
    @patch("code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference", return_value=True)
    def test_applies_persisted_preference(
        self,
        mock_pref: MagicMock,
        mock_emit: MagicMock,
        mock_is_enabled: MagicMock,
        mock_set_rust: MagicMock,
        mock_auto_build: MagicMock,
    ) -> None:
        """When preference is True, set_rust_enabled(True) is called."""
        _on_startup()
        mock_set_rust.assert_called_once_with(True)
