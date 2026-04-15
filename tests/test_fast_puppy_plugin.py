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
    _on_startup,
)
from code_puppy.plugins.fast_puppy.builder import (
    _has_maturin,
    _try_auto_build,
)


# ---------------------------------------------------------------------------
# _has_maturin()
# ---------------------------------------------------------------------------


class TestHasMaturin:
    """_has_maturin should return True only when maturin is genuinely available."""

    @patch("code_puppy.plugins.fast_puppy.builder.shutil.which")
    def test_returns_true_when_in_path(self, mock_which: MagicMock) -> None:
        mock_which.return_value = "/usr/bin/maturin"
        assert _has_maturin() is True

    @patch(
        "code_puppy.plugins.fast_puppy.builder.shutil.which",
        return_value=None,
    )
    @patch("code_puppy.plugins.fast_puppy.builder.subprocess.run")
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
        "code_puppy.plugins.fast_puppy.builder.shutil.which",
        return_value=None,
    )
    @patch("code_puppy.plugins.fast_puppy.builder.subprocess.run")
    def test_returns_false_on_nonzero_rc(
        self, mock_run: MagicMock, _mock_which: MagicMock
    ) -> None:
        """Bug fix: a completed-but-failing subprocess must *not* be treated as success."""
        mock_run.return_value = MagicMock(returncode=1)
        assert _has_maturin() is False

    @patch(
        "code_puppy.plugins.fast_puppy.builder.shutil.which",
        return_value=None,
    )
    @patch(
        "code_puppy.plugins.fast_puppy.builder.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_returns_false_on_exception(
        self, _mock_run: MagicMock, _mock_which: MagicMock
    ) -> None:
        assert _has_maturin() is False


# ---------------------------------------------------------------------------
# _try_auto_build()
# ---------------------------------------------------------------------------


class TestTryAutoBuild:
    """_try_auto_build must not proceed to build when maturin install fails."""

    @patch("code_puppy.plugins.fast_puppy.builder.emit_info")
    @patch("code_puppy.plugins.fast_puppy.builder._build_crate")
    @patch(
        "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain",
        return_value=True,
    )
    @patch("code_puppy.plugins.fast_puppy.builder._find_crate_dir")
    @patch(
        "code_puppy.plugins.fast_puppy.builder._has_maturin",
        return_value=False,
    )
    @patch("code_puppy.plugins.fast_puppy.builder.subprocess.run")
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
        never calls _build_crate."""
        with patch("code_puppy._core_bridge.RUST_AVAILABLE", False):
            # Simulate pip install failure
            mock_run.return_value = MagicMock(
                returncode=1, stderr="ERROR: Could not install maturin", stdout=""
            )
            mock_find_crate.return_value = Path("/fake/code_puppy_core")

            result = _try_auto_build()

            assert result is False
            mock_build.assert_not_called()

    @patch("code_puppy.plugins.fast_puppy.builder.emit_info")
    @patch(
        "code_puppy.plugins.fast_puppy.builder._build_crate",
        return_value=(True, ""),
    )
    @patch(
        "code_puppy.plugins.fast_puppy.builder._is_crate_fresh",
        return_value=False,
    )
    @patch(
        "code_puppy.plugins.fast_puppy.builder._is_crate_installed",
        return_value=False,
    )
    @patch(
        "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain",
        return_value=True,
    )
    @patch("code_puppy.plugins.fast_puppy.builder._find_crate_dir")
    @patch("code_puppy.plugins.fast_puppy.builder._find_repo_root")
    @patch(
        "code_puppy.plugins.fast_puppy.builder._has_maturin",
        return_value=False,
    )
    @patch(
        "code_puppy.plugins.fast_puppy.builder._check_disable_autobuild",
        return_value=False,
    )
    @patch("code_puppy.plugins.fast_puppy.builder.subprocess.run")
    def test_proceeds_on_successful_pip_install(
        self,
        mock_run: MagicMock,
        mock_check_disable: MagicMock,
        mock_has_maturin: MagicMock,
        mock_repo_root: MagicMock,
        mock_find_crate: MagicMock,
        mock_rust: MagicMock,
        mock_installed: MagicMock,
        mock_fresh: MagicMock,
        mock_build: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """When pip install succeeds, _build_crate should be called for code_puppy_core."""
        with patch("code_puppy._core_bridge.RUST_AVAILABLE", False):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            # All crate dirs return the same path in this mock setup
            mock_find_crate.return_value = Path("/fake/code_puppy_core")
            mock_repo_root.return_value = Path("/fake/repo")

            _try_auto_build()

            # Legacy _try_auto_build calls _try_auto_build_all which builds all crates
            # Check that code_puppy_core was among the calls
            mock_build.assert_any_call(Path("/fake/code_puppy_core"), "code_puppy_core")


# ---------------------------------------------------------------------------
# _handle_fast_puppy()
# ---------------------------------------------------------------------------


class TestHandleFastPuppy:
    """_handle_fast_puppy routes commands correctly."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _handle_fast_puppy("/something_else", "something_else")
        assert result is None

    @patch(
        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference"
    )
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
    def test_startup_shows_disabled_when_all_capabilities_off(
        self,
        mock_is_enabled: MagicMock,
        mock_load_prefs: MagicMock,
        mock_emit: MagicMock,
        mock_get_backends: MagicMock,
    ) -> None:
        """When all capabilities disabled, shows disabled message."""
        mock_is_enabled.return_value = False  # All capabilities disabled
        mock_get_backends.return_value = {
            "elixir_available": False,
            "rust_installed": False,
            "python_fallback": True,
        }

        _on_startup()

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0][0]
        assert "disabled" in call_args.lower() or "💤" in call_args
