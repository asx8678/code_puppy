"""Comprehensive test coverage for terminal_utils.py."""

import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from code_puppy import terminal_utils

# ── reset_windows_terminal_ansi ──


class TestResetWindowsTerminalAnsi:
    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        stdout = MagicMock()
        monkeypatch.setattr(terminal_utils.sys, "stdout", stdout)
        terminal_utils.reset_windows_terminal_ansi()
        stdout.write.assert_not_called()

    def test_writes_reset_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        stdout = MagicMock()
        stderr = MagicMock()
        monkeypatch.setattr(terminal_utils.sys, "stdout", stdout)
        monkeypatch.setattr(terminal_utils.sys, "stderr", stderr)
        terminal_utils.reset_windows_terminal_ansi()
        stdout.write.assert_called_once_with("\x1b[0m")
        stdout.flush.assert_called_once()
        stderr.write.assert_called_once_with("\x1b[0m")
        stderr.flush.assert_called_once()

    def test_exception_silenced(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        stdout = MagicMock()
        stdout.write.side_effect = OSError("broken")
        monkeypatch.setattr(terminal_utils.sys, "stdout", stdout)
        terminal_utils.reset_windows_terminal_ansi()  # should not raise


# ── reset_windows_console_mode ──


class TestResetWindowsConsoleMode:
    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        terminal_utils.reset_windows_console_mode()

    def test_calls_ctypes_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_mode.value = 0
        mock_ctypes.c_ulong.return_value = mock_mode
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        terminal_utils.reset_windows_console_mode()
        # GetStdHandle for both stdout (-11) and stdin (-10)
        assert mock_ctypes.windll.kernel32.GetStdHandle.call_count == 2
        handle_args = [
            c[0][0] for c in mock_ctypes.windll.kernel32.GetStdHandle.call_args_list
        ]
        assert handle_args == [-11, -10]
        # SetConsoleMode for both with the expected ORed flag bits.
        assert mock_ctypes.windll.kernel32.SetConsoleMode.call_count == 2
        set_calls = mock_ctypes.windll.kernel32.SetConsoleMode.call_args_list
        stdout_mode = set_calls[0][0][1]
        assert stdout_mode & 0x0001 and stdout_mode & 0x0002 and stdout_mode & 0x0004
        stdin_mode = set_calls[1][0][1]
        assert stdin_mode & 0x0002 and stdin_mode & 0x0004 and stdin_mode & 0x0001

    def test_exception_silenced(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "ctypes", None)  # force ImportError
        terminal_utils.reset_windows_console_mode()  # should not raise


# ── flush_windows_keyboard_buffer ──


class TestFlushWindowsKeyboardBuffer:
    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        terminal_utils.flush_windows_keyboard_buffer()

    def test_flushes_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_msvcrt = MagicMock()
        mock_msvcrt.kbhit.side_effect = [True, True, False]
        monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)
        terminal_utils.flush_windows_keyboard_buffer()
        assert mock_msvcrt.kbhit.call_count == 3
        assert mock_msvcrt.getch.call_count == 2

    def test_exception_silenced(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "msvcrt", None)
        terminal_utils.flush_windows_keyboard_buffer()


# ── reset_windows_terminal_full ──


class TestResetWindowsTerminalFull:
    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        ansi = MagicMock()
        monkeypatch.setattr(terminal_utils, "reset_windows_terminal_ansi", ansi)
        terminal_utils.reset_windows_terminal_full()
        ansi.assert_not_called()

    def test_calls_all_three_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        ansi = MagicMock()
        console = MagicMock()
        keyboard = MagicMock()
        monkeypatch.setattr(terminal_utils, "reset_windows_terminal_ansi", ansi)
        monkeypatch.setattr(terminal_utils, "reset_windows_console_mode", console)
        monkeypatch.setattr(terminal_utils, "flush_windows_keyboard_buffer", keyboard)
        terminal_utils.reset_windows_terminal_full()
        ansi.assert_called_once()
        console.assert_called_once()
        keyboard.assert_called_once()


# ── reset_unix_terminal ──


class TestResetUnixTerminal:
    def test_noop_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        run = MagicMock()
        monkeypatch.setattr(terminal_utils.subprocess, "run", run)
        terminal_utils.reset_unix_terminal()
        run.assert_not_called()

    def test_runs_reset_on_unix(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        run = MagicMock()
        monkeypatch.setattr(terminal_utils.subprocess, "run", run)
        terminal_utils.reset_unix_terminal()
        run.assert_called_once_with(["reset"], check=True, capture_output=True)

    @pytest.mark.parametrize(
        "exc",
        [subprocess.CalledProcessError(1, "reset"), FileNotFoundError()],
    )
    def test_handles_run_errors(self, monkeypatch, exc):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        monkeypatch.setattr(
            terminal_utils.subprocess, "run", MagicMock(side_effect=exc)
        )
        terminal_utils.reset_unix_terminal()  # should not raise


# ── reset_terminal ──


class TestResetTerminal:
    def test_routes_to_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        full = MagicMock()
        monkeypatch.setattr(terminal_utils, "reset_windows_terminal_full", full)
        terminal_utils.reset_terminal()
        full.assert_called_once()

    @pytest.mark.parametrize("system", ["Linux", "Darwin"])
    def test_routes_to_unix(self, monkeypatch, system):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: system)
        unix = MagicMock()
        monkeypatch.setattr(terminal_utils, "reset_unix_terminal", unix)
        terminal_utils.reset_terminal()
        unix.assert_called_once()


# ── disable_windows_ctrl_c ──


class TestDisableWindowsCtrlC:
    def test_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        assert terminal_utils.disable_windows_ctrl_c() is False

    def test_success_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_mode.value = 0x0007
        mock_ctypes.c_ulong.return_value = mock_mode
        mock_ctypes.windll.kernel32.GetConsoleMode.return_value = True
        mock_ctypes.windll.kernel32.SetConsoleMode.return_value = True
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        terminal_utils._original_ctrl_handler = None
        assert terminal_utils.disable_windows_ctrl_c() is True
        assert terminal_utils._original_ctrl_handler == 0x0007
        # ENABLE_PROCESSED_INPUT (0x0001) must be cleared in the new mode.
        new_mode = mock_ctypes.windll.kernel32.SetConsoleMode.call_args[0][1]
        assert not (new_mode & 0x0001)

    @pytest.mark.parametrize("get_ok, set_ok", [(False, True), (True, False)])
    def test_console_mode_call_fails(self, monkeypatch, get_ok, set_ok):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_mode.value = 0x0007
        mock_ctypes.c_ulong.return_value = mock_mode
        mock_ctypes.windll.kernel32.GetConsoleMode.return_value = get_ok
        mock_ctypes.windll.kernel32.SetConsoleMode.return_value = set_ok
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.disable_windows_ctrl_c() is False

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "ctypes", None)
        assert terminal_utils.disable_windows_ctrl_c() is False


# ── enable_windows_ctrl_c ──


class TestEnableWindowsCtrlC:
    def test_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        assert terminal_utils.enable_windows_ctrl_c() is False

    def test_returns_true_if_nothing_to_restore(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        terminal_utils._original_ctrl_handler = None
        assert terminal_utils.enable_windows_ctrl_c() is True

    def test_restores_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        terminal_utils._original_ctrl_handler = 0x0007
        mock_ctypes = MagicMock()
        stdin_handle = MagicMock()
        mock_ctypes.windll.kernel32.GetStdHandle.return_value = stdin_handle
        mock_ctypes.windll.kernel32.SetConsoleMode.return_value = True
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.enable_windows_ctrl_c() is True
        assert terminal_utils._original_ctrl_handler is None
        # Restores the exact saved mode.
        mock_ctypes.windll.kernel32.SetConsoleMode.assert_called_once_with(
            stdin_handle, 0x0007
        )

    def test_set_console_mode_fails(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        terminal_utils._original_ctrl_handler = 0x0007
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.SetConsoleMode.return_value = False
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.enable_windows_ctrl_c() is False

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        terminal_utils._original_ctrl_handler = 0x0007
        monkeypatch.setitem(sys.modules, "ctypes", None)
        assert terminal_utils.enable_windows_ctrl_c() is False


# ── set_keep_ctrl_c_disabled / ensure_ctrl_c_disabled ──


class TestKeepCtrlCDisabled:
    @pytest.mark.parametrize("value", [True, False])
    def test_set_keep_ctrl_c_disabled(self, value):
        terminal_utils.set_keep_ctrl_c_disabled(value)
        assert terminal_utils._keep_ctrl_c_disabled is value


class TestEnsureCtrlCDisabled:
    def test_returns_true_when_not_keeping(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", False)
        assert terminal_utils.ensure_ctrl_c_disabled() is True

    def test_returns_true_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", True)
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        assert terminal_utils.ensure_ctrl_c_disabled() is True

    def test_already_disabled(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", True)
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_mode.value = 0x0000  # ENABLE_PROCESSED_INPUT not set
        mock_ctypes.c_ulong.return_value = mock_mode
        mock_ctypes.windll.kernel32.GetConsoleMode.return_value = True
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.ensure_ctrl_c_disabled() is True
        mock_ctypes.windll.kernel32.SetConsoleMode.assert_not_called()

    def test_disables_when_enabled(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", True)
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_mode.value = 0x0001  # ENABLE_PROCESSED_INPUT is set
        mock_ctypes.c_ulong.return_value = mock_mode
        mock_ctypes.windll.kernel32.GetConsoleMode.return_value = True
        mock_ctypes.windll.kernel32.SetConsoleMode.return_value = True
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.ensure_ctrl_c_disabled() is True
        # ENABLE_PROCESSED_INPUT (0x0001) cleared in new mode.
        new_mode = mock_ctypes.windll.kernel32.SetConsoleMode.call_args[0][1]
        assert not (new_mode & 0x0001)

    def test_get_console_mode_fails(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", True)
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_mode = MagicMock()
        mock_ctypes.c_ulong.return_value = mock_mode
        mock_ctypes.windll.kernel32.GetConsoleMode.return_value = False
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        assert terminal_utils.ensure_ctrl_c_disabled() is False

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "_keep_ctrl_c_disabled", True)
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "ctypes", None)
        assert terminal_utils.ensure_ctrl_c_disabled() is False


# ── detect_truecolor_support ──


class TestDetectTruecolorSupport:
    # Env vars that, on their own, signal truecolor support. Each case sets a
    # clean environment with only the given var(s).
    @pytest.mark.parametrize(
        "env",
        [
            {"COLORTERM": "truecolor"},
            {"COLORTERM": "24bit"},
            {"COLORTERM": "TRUECOLOR"},  # case-insensitive
            {"COLORTERM": "TrueColor"},
            {"TERM": "xterm-direct"},
            {"TERM": "xterm-truecolor"},
            {"TERM": "iterm2"},
            {"TERM": "vte-256color"},
            {"TERM": "xterm-direct-256color"},  # substring match
            {"ITERM_SESSION_ID": "abc"},
            {"KITTY_WINDOW_ID": "1"},
            {"ALACRITTY_SOCKET": "/tmp/sock"},
            {"WT_SESSION": "abc"},
        ],
    )
    def test_env_signals_truecolor(self, monkeypatch, env):
        for var in (
            "COLORTERM",
            "TERM",
            "ITERM_SESSION_ID",
            "KITTY_WINDOW_ID",
            "ALACRITTY_SOCKET",
            "WT_SESSION",
        ):
            monkeypatch.delenv(var, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert terminal_utils.detect_truecolor_support() is True

    @pytest.mark.parametrize(
        "color_system, expected",
        [("truecolor", True), ("256", False), ("standard", False)],
    )
    def test_rich_fallback(self, monkeypatch, color_system, expected):
        for var in (
            "COLORTERM",
            "TERM",
            "ITERM_SESSION_ID",
            "KITTY_WINDOW_ID",
            "ALACRITTY_SOCKET",
            "WT_SESSION",
        ):
            monkeypatch.delenv(var, raising=False)
        import rich.console

        mock_console_cls = MagicMock()
        mock_console_cls.return_value.color_system = color_system
        monkeypatch.setattr(rich.console, "Console", mock_console_cls)
        assert terminal_utils.detect_truecolor_support() is expected

    def test_rich_import_error(self, monkeypatch):
        for var in (
            "COLORTERM",
            "TERM",
            "ITERM_SESSION_ID",
            "KITTY_WINDOW_ID",
            "ALACRITTY_SOCKET",
            "WT_SESSION",
        ):
            monkeypatch.delenv(var, raising=False)
        import rich.console

        monkeypatch.setattr(
            rich.console, "Console", MagicMock(side_effect=Exception("fail"))
        )
        assert terminal_utils.detect_truecolor_support() is False


# ── print_truecolor_warning ──


class TestPrintTruecolorWarning:
    def test_no_warning_when_truecolor_supported(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "detect_truecolor_support", lambda: True)
        mock_console = MagicMock()
        terminal_utils.print_truecolor_warning(console=mock_console)
        mock_console.print.assert_not_called()

    def test_rich_console_warning(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "detect_truecolor_support", lambda: False)
        mock_console = MagicMock()
        mock_console.color_system = "256"
        terminal_utils.print_truecolor_warning(console=mock_console)
        assert mock_console.print.call_count > 10

    def test_creates_console_when_none(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "detect_truecolor_support", lambda: False)
        mock_console = MagicMock()
        mock_console.color_system = "standard"
        import rich.console

        monkeypatch.setattr(rich.console, "Console", lambda: mock_console)
        terminal_utils.print_truecolor_warning(console=None)
        assert mock_console.print.call_count > 10

    def test_fallback_to_plain_print(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "detect_truecolor_support", lambda: False)
        # Make the import of rich.console.Console raise ImportError
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "rich.console":
                raise ImportError("no rich")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        printed = []
        monkeypatch.setattr(builtins, "print", lambda *a, **kw: printed.append(a))
        terminal_utils.print_truecolor_warning(console=None)
        assert len(printed) > 5
        all_text = " ".join(str(p) for p in printed).lower()
        assert "warning" in all_text and "truecolor" in all_text

    def test_console_color_system_none(self, monkeypatch):
        monkeypatch.setattr(terminal_utils, "detect_truecolor_support", lambda: False)
        mock_console = MagicMock()
        mock_console.color_system = None
        terminal_utils.print_truecolor_warning(console=mock_console)
        # Should use "unknown" for color_system
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("unknown" in c for c in calls)


# ── install_windows_ctrl_c_swallower ──


class TestInstallWindowsCtrlCSwallower:
    def teardown_method(self):
        # Always blow away the pinned ref between tests so we don't leak
        # state into other test classes.
        terminal_utils._ctrl_c_swallower_ref = None

    def test_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        assert terminal_utils.install_windows_ctrl_c_swallower() is False
        assert terminal_utils._ctrl_c_swallower_ref is None

    def test_installs_on_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        # WINFUNCTYPE returns a class; calling it with a Python fn returns
        # the callable handler object. Make that round-trip work.
        mock_handler_factory = MagicMock(side_effect=lambda fn: ("HANDLER", fn))
        mock_ctypes.WINFUNCTYPE.return_value = mock_handler_factory
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.return_value = 1
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        # ctypes.wintypes is a submodule — stub it too.
        monkeypatch.setitem(sys.modules, "ctypes.wintypes", MagicMock())

        terminal_utils._ctrl_c_swallower_ref = None
        assert terminal_utils.install_windows_ctrl_c_swallower() is True
        # Handler was pinned so the GC doesn't eat it.
        assert terminal_utils._ctrl_c_swallower_ref is not None
        # SetConsoleCtrlHandler(handler, True) was called.
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.assert_called_once()
        args, _ = mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.call_args
        assert args[1] is True

    def test_swallower_returns_true_for_ctrl_c_and_break(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        captured = {}

        def _factory(fn):
            captured["fn"] = fn
            return ("HANDLER", fn)

        mock_ctypes = MagicMock()
        mock_ctypes.WINFUNCTYPE.return_value = _factory
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.return_value = 1
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        monkeypatch.setitem(sys.modules, "ctypes.wintypes", MagicMock())

        terminal_utils._ctrl_c_swallower_ref = None
        terminal_utils.install_windows_ctrl_c_swallower()

        # CTRL_C_EVENT (0) and CTRL_BREAK_EVENT (1) -> swallow (True)
        assert captured["fn"](0) is True
        assert captured["fn"](1) is True
        # CTRL_CLOSE_EVENT (2) etc -> let default handler run (False)
        assert captured["fn"](2) is False
        assert captured["fn"](5) is False

    def test_idempotent(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        terminal_utils._ctrl_c_swallower_ref = ("already", "installed")
        assert terminal_utils.install_windows_ctrl_c_swallower() is True
        # Should not call into ctypes a second time.
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.assert_not_called()

    def test_set_console_ctrl_handler_fails(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_ctypes.WINFUNCTYPE.return_value = lambda fn: ("H", fn)
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.return_value = 0
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        monkeypatch.setitem(sys.modules, "ctypes.wintypes", MagicMock())

        terminal_utils._ctrl_c_swallower_ref = None
        assert terminal_utils.install_windows_ctrl_c_swallower() is False
        assert terminal_utils._ctrl_c_swallower_ref is None

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        # Force the ctypes import to detonate.
        monkeypatch.setitem(sys.modules, "ctypes", None)
        terminal_utils._ctrl_c_swallower_ref = None
        assert terminal_utils.install_windows_ctrl_c_swallower() is False


# ── uninstall_windows_ctrl_c_swallower ──


class TestUninstallWindowsCtrlCSwallower:
    def teardown_method(self):
        terminal_utils._ctrl_c_swallower_ref = None

    def test_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Linux")
        assert terminal_utils.uninstall_windows_ctrl_c_swallower() is False

    def test_returns_true_when_nothing_installed(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        terminal_utils._ctrl_c_swallower_ref = None
        assert terminal_utils.uninstall_windows_ctrl_c_swallower() is True

    def test_uninstalls_and_clears_ref(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.return_value = 1
        monkeypatch.setitem(sys.modules, "ctypes", mock_ctypes)
        terminal_utils._ctrl_c_swallower_ref = "PINNED_HANDLER"

        assert terminal_utils.uninstall_windows_ctrl_c_swallower() is True
        assert terminal_utils._ctrl_c_swallower_ref is None
        # SetConsoleCtrlHandler called with (handler, False) to remove
        args, _ = mock_ctypes.windll.kernel32.SetConsoleCtrlHandler.call_args
        assert args[1] is False

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr(terminal_utils.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "ctypes", None)
        terminal_utils._ctrl_c_swallower_ref = "PINNED"
        assert terminal_utils.uninstall_windows_ctrl_c_swallower() is False
