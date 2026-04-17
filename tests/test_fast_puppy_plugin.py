"""Tests for code_puppy.plugins.fast_puppy.register_callbacks.

Covers the bug fixes:
  - _has_maturin() must check subprocess returncode, not just absence of exception.

bd-91: _try_auto_build() removed - auto-build eliminated, explicit build only.
"""

import sys
from unittest.mock import MagicMock, patch

# We only import the helper functions we need to test.
# Importing the full module is safe — it only registers callbacks at module
# scope and doesn't trigger builds unless startup fires.
from code_puppy.plugins.fast_puppy.register_callbacks import _on_custom_command
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
# _on_custom_command()
# ---------------------------------------------------------------------------


class TestOnCustomCommand:
    """_on_custom_command routes /fast_puppy commands correctly."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _on_custom_command("/something_else", "something_else")
        assert result is None

    def test_returns_status_for_fast_puppy_command(self) -> None:
        result = _on_custom_command("/fast_puppy", "fast_puppy")
        assert result is not None
        assert "Fast Puppy Status:" in result
        assert "Native acceleration layer removed" in result

    # bd-86: Tests removed - _core_bridge and native_backend modules deleted.
    # These tests depended on deleted modules. Fast puppy plugin simplified.


# bd-86: TestOnStartup class removed - native_backend module deleted.
# Tests depended on deleted NativeBackend class. _on_startup() simplified.
