"""Tests for code_puppy.utils.clipboard."""

import base64
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from code_puppy.utils.clipboard import (
    copy_to_clipboard,
    osc52_copy,
)


class TestOsc52Copy:
    """Tests for the OSC 52 terminal escape clipboard."""

    def test_osc52_escape_format(self, capsys):
        """Verify the exact OSC 52 escape sequence format."""
        osc52_copy("hello")
        captured = capsys.readouterr()
        expected_b64 = base64.b64encode(b"hello").decode("ascii")
        assert captured.out == f"\x1b]52;c;{expected_b64}\x07"

    def test_osc52_unicode(self, capsys):
        """Unicode content is properly base64-encoded."""
        osc52_copy("héllo wörld 🐶")
        captured = capsys.readouterr()
        expected_b64 = base64.b64encode("héllo wörld 🐶".encode("utf-8")).decode("ascii")
        assert captured.out == f"\x1b]52;c;{expected_b64}\x07"

    def test_osc52_empty_string(self, capsys):
        """Empty string produces valid OSC 52 with empty base64."""
        osc52_copy("")
        captured = capsys.readouterr()
        assert captured.out == "\x1b]52;c;\x07"

    def test_osc52_multiline(self, capsys):
        """Multiline content is encoded correctly."""
        osc52_copy("line1\nline2\nline3")
        captured = capsys.readouterr()
        expected_b64 = base64.b64encode(b"line1\nline2\nline3").decode("ascii")
        assert captured.out == f"\x1b]52;c;{expected_b64}\x07"


class TestCopyToClipboard:
    """Tests for the main copy_to_clipboard function."""

    def test_osc52_always_emitted(self, capsys):
        """OSC 52 is always emitted regardless of native clipboard availability."""
        with patch("code_puppy.utils.clipboard._try_native_clipboard", return_value=False):
            copy_to_clipboard("test")
        captured = capsys.readouterr()
        assert "\x1b]52;c;" in captured.out

    def test_osc52_disabled(self, capsys):
        """OSC 52 can be disabled for testing contexts."""
        with patch("code_puppy.utils.clipboard._try_native_clipboard", return_value=False):
            copy_to_clipboard("test", osc52=False)
        captured = capsys.readouterr()
        assert "\x1b]52;c;" not in captured.out

    def test_returns_true_when_native_succeeds(self):
        """Returns True when native clipboard is available."""
        with patch("code_puppy.utils.clipboard._try_native_clipboard", return_value=True):
            with patch("code_puppy.utils.clipboard.osc52_copy"):
                result = copy_to_clipboard("test")
        assert result is True

    def test_returns_false_when_native_fails(self):
        """Returns False when no native clipboard tool is available."""
        with patch("code_puppy.utils.clipboard._try_native_clipboard", return_value=False):
            with patch("code_puppy.utils.clipboard.osc52_copy"):
                result = copy_to_clipboard("test")
        assert result is False

    def test_osc52_error_does_not_crash(self):
        """If OSC 52 fails, native clipboard still attempted."""
        with patch("code_puppy.utils.clipboard.osc52_copy", side_effect=OSError("write failed")):
            with patch("code_puppy.utils.clipboard._try_native_clipboard", return_value=True):
                result = copy_to_clipboard("test")
        assert result is True

    def test_native_error_does_not_crash(self):
        """If native clipboard crashes, function returns False gracefully."""
        with patch("code_puppy.utils.clipboard.osc52_copy"):
            with patch("code_puppy.utils.clipboard._try_native_clipboard", side_effect=RuntimeError("boom")):
                result = copy_to_clipboard("test")
        assert result is False


class TestNativeClipboard:
    """Tests for platform-specific clipboard detection."""

    @patch("sys.platform", "darwin")
    @patch("shutil.which", return_value="/usr/bin/pbcopy")
    @patch("subprocess.run")
    def test_macos_uses_pbcopy(self, mock_run, mock_which):
        from code_puppy.utils.clipboard import _try_native_clipboard
        mock_run.return_value = MagicMock(returncode=0)
        result = _try_native_clipboard("test")
        mock_run.assert_called_once()
        assert "pbcopy" in mock_run.call_args[0][0]
        assert result is True

    @patch("sys.platform", "darwin")
    @patch("shutil.which", return_value=None)
    def test_macos_no_pbcopy(self, mock_which):
        from code_puppy.utils.clipboard import _try_native_clipboard
        result = _try_native_clipboard("test")
        assert result is False

    @patch("sys.platform", "linux")
    @patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False)
    @patch("shutil.which", side_effect=lambda x: "/usr/bin/xclip" if x == "xclip" else None)
    @patch("subprocess.run")
    def test_linux_x11_uses_xclip(self, mock_run, mock_which):
        from code_puppy.utils.clipboard import _try_native_clipboard
        mock_run.return_value = MagicMock(returncode=0)
        # Need to reload to pick up platform change
        result = _try_native_clipboard("test")
        assert result is True
