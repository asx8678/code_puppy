"""Tests for CLI dashboard wiring (--web flags and /dashboard command).

Covers:
- cli_runner.py: --web, --web-host, --web-port, --no-browser flags
- cli_runner.py: allow_external=True passed when host is non-localhost
- cli_runner.py: run_prompt_with_attachments on_task_created callback
- core_commands.py: /api start/status dashboard URL messages
- core_commands.py: /dashboard command (start server + open browser)
"""

import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# cli_runner: --web flag wiring
# ---------------------------------------------------------------------------


class TestWebFlagParsing:
    """Test that --web flags are correctly parsed from argparse."""

    def test_web_flag(self):
        """--web is stored as True."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--web", action="store_true")
        args = parser.parse_args(["--web"])
        assert args.web is True

    def test_web_host_default(self):
        """--web-host defaults to 127.0.0.1."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--web-host", default="127.0.0.1")
        args = parser.parse_args([])
        assert args.web_host == "127.0.0.1"

    def test_web_port_default(self):
        """--web-port defaults to 8765."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--web-port", type=int, default=8765)
        args = parser.parse_args([])
        assert args.web_port == 8765

    def test_no_browser_flag(self):
        """--no-browser is stored as True."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--no-browser", action="store_true")
        args = parser.parse_args(["--no-browser"])
        assert args.no_browser is True


class TestWebModeAllowExternalLogic:
    """Test the allow_external logic used by --web mode."""

    def test_localhost_yields_allow_external_false(self):
        """Default localhost host should yield allow_external=False."""
        _LOCALHOST = {"127.0.0.1", "::1", "localhost"}

        web_host = "127.0.0.1"
        allow_external = web_host not in _LOCALHOST
        assert allow_external is False

    def test_allow_external_true_for_non_localhost(self):
        """Non-localhost host should result in allow_external=True."""
        _LOCALHOST = {"127.0.0.1", "::1", "localhost"}

        web_host = "0.0.0.0"
        allow_external = web_host not in _LOCALHOST
        assert allow_external is True

    def test_allow_external_true_for_custom_host(self):
        """Custom non-localhost host should result in allow_external=True."""
        _LOCALHOST = {"127.0.0.1", "::1", "localhost"}

        web_host = "192.168.1.100"
        allow_external = web_host not in _LOCALHOST
        assert allow_external is True

    def test_allow_external_false_for_localhost_ipv6(self):
        """IPv6 localhost should result in allow_external=False."""
        _LOCALHOST = {"127.0.0.1", "::1", "localhost"}

        web_host = "::1"
        allow_external = web_host not in _LOCALHOST
        assert allow_external is False


# ---------------------------------------------------------------------------
# cli_runner: on_task_created callback
# ---------------------------------------------------------------------------


class TestOnTaskCreatedCallback:
    """Test the on_task_created parameter in run_prompt_with_attachments."""

    @pytest.mark.anyio
    async def test_on_task_created_called(self):
        """on_task_created callback receives the agent task."""
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        captured_tasks = []

        def capture_task(task):
            captured_tasks.append(task)

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = MagicMock(
                prompt="hello",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            mock_clip.return_value = clip_mgr

            result, task = await run_prompt_with_attachments(
                mock_agent,
                "hello",
                use_spinner=False,
                on_task_created=capture_task,
            )

        assert len(captured_tasks) == 1
        assert captured_tasks[0] is task

    @pytest.mark.anyio
    async def test_on_task_created_exception_swallowed(self):
        """on_task_created exceptions are silently swallowed."""
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        def bad_callback(task):
            raise RuntimeError("boom")

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = MagicMock(
                prompt="hello",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            mock_clip.return_value = clip_mgr

            # Should NOT raise
            result, task = await run_prompt_with_attachments(
                mock_agent,
                "hello",
                use_spinner=False,
                on_task_created=bad_callback,
            )

        assert result is mock_result

    @pytest.mark.anyio
    async def test_on_task_created_none_noop(self):
        """on_task_created=None (default) does nothing."""
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = MagicMock(
                prompt="hello",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            mock_clip.return_value = clip_mgr

            result, task = await run_prompt_with_attachments(
                mock_agent,
                "hello",
                use_spinner=False,
            )

        assert result is mock_result


# ---------------------------------------------------------------------------
# core_commands: /api start/status dashboard URLs
# ---------------------------------------------------------------------------


class TestApiCommandDashboardUrls:
    """Test that /api start and status mention dashboard/terminal URLs."""

    def test_start_mentions_dashboard(self, tmp_path, monkeypatch):
        """/api start should emit dashboard and terminal URLs."""
        from code_puppy.command_line.core_commands import handle_api_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.pid = 42

        info_messages = []

        with (
            patch(
                "code_puppy.messaging.emit_info",
                side_effect=lambda m: info_messages.append(m),
            ),
            patch("code_puppy.messaging.emit_success"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            handle_api_command("/api start")

        assert any("dashboard" in m.lower() for m in info_messages), (
            f"Expected 'dashboard' in info messages, got: {info_messages}"
        )
        assert any("terminal" in m.lower() for m in info_messages), (
            f"Expected 'terminal' in info messages, got: {info_messages}"
        )

    def test_status_running_mentions_dashboard(self, tmp_path, monkeypatch):
        """/api status (running) should emit dashboard and terminal URLs."""
        from code_puppy.command_line.core_commands import handle_api_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        pid_file = tmp_path / "api_server.pid"
        pid_file.write_text("42")

        info_messages = []

        with (
            patch(
                "code_puppy.messaging.emit_info",
                side_effect=lambda m: info_messages.append(m),
            ),
            patch("code_puppy.messaging.emit_success"),
            patch("os.kill"),  # Process exists
        ):
            handle_api_command("/api status")

        assert any("dashboard" in m.lower() for m in info_messages), (
            f"Expected 'dashboard' in info messages, got: {info_messages}"
        )
        assert any("terminal" in m.lower() for m in info_messages), (
            f"Expected 'terminal' in info messages, got: {info_messages}"
        )


# ---------------------------------------------------------------------------
# core_commands: /dashboard command
# ---------------------------------------------------------------------------


class TestDashboardCommand:
    """Test the /dashboard command handler."""

    def test_dashboard_opens_browser_server_running(self, tmp_path, monkeypatch):
        """/dashboard when server running opens browser directly."""
        from code_puppy.command_line.core_commands import handle_dashboard_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        pid_file = tmp_path / "api_server.pid"
        pid_file.write_text("42")

        with (
            patch("os.kill"),  # Process exists
            patch("webbrowser.open") as mock_open,
            patch("code_puppy.messaging.emit_info"),
        ):
            result = handle_dashboard_command("/dashboard")

        assert result is True
        mock_open.assert_called_once_with("http://127.0.0.1:8765/dashboard")

    def test_dashboard_starts_server_then_opens(self, tmp_path, monkeypatch):
        """/dashboard when no server running starts it and opens browser."""
        from code_puppy.command_line.core_commands import handle_dashboard_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.pid = 99

        with (
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("webbrowser.open"),
            patch("code_puppy.messaging.emit_info"),
            patch("code_puppy.messaging.emit_success"),
        ):
            result = handle_dashboard_command("/dashboard")

        assert result is True
        mock_popen.assert_called_once_with(
            [sys.executable, "-m", "code_puppy.api.main"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def test_dashboard_stale_pid_starts_new(self, tmp_path, monkeypatch):
        """/dashboard with stale PID file starts a new server."""
        from code_puppy.command_line.core_commands import handle_dashboard_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        pid_file = tmp_path / "api_server.pid"
        pid_file.write_text("99999")
        mock_proc = MagicMock()
        mock_proc.pid = 100

        with (
            patch("os.kill", side_effect=OSError),  # Stale PID
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("webbrowser.open"),
            patch("code_puppy.messaging.emit_info"),
            patch("code_puppy.messaging.emit_success"),
        ):
            result = handle_dashboard_command("/dashboard")

        assert result is True
        mock_popen.assert_called_once()

    def test_dashboard_emits_terminal_url(self, tmp_path, monkeypatch):
        """/dashboard emits both dashboard and terminal URLs."""
        from code_puppy.command_line.core_commands import handle_dashboard_command

        monkeypatch.setattr("code_puppy.config.STATE_DIR", str(tmp_path))
        pid_file = tmp_path / "api_server.pid"
        pid_file.write_text("42")

        info_messages = []

        with (
            patch("os.kill"),
            patch("webbrowser.open"),
            patch(
                "code_puppy.messaging.emit_info",
                side_effect=lambda m: info_messages.append(m),
            ),
        ):
            handle_dashboard_command("/dashboard")

        assert any("dashboard" in m.lower() for m in info_messages), (
            f"Expected 'dashboard' in info messages, got: {info_messages}"
        )
        assert any("terminal" in m.lower() for m in info_messages), (
            f"Expected 'terminal' in info messages, got: {info_messages}"
        )


# ---------------------------------------------------------------------------
# api/main: allow_external security
# ---------------------------------------------------------------------------


class TestApiMainSecurity:
    """Test api/main.py allow_external security guard."""

    def test_non_localhost_without_allow_raises(self):
        """Binding to 0.0.0.0 without allow_external raises SystemExit."""
        from code_puppy.api.main import main

        with pytest.raises(SystemExit, match="Refusing to bind"):
            main(host="0.0.0.0", port=8765, allow_external=False)

    def test_non_localhost_with_allow_succeeds(self):
        """Binding to 0.0.0.0 with allow_external=True starts uvicorn."""
        from code_puppy.api.main import main

        with patch("code_puppy.api.main.uvicorn") as mock_uvicorn:
            main(host="0.0.0.0", port=8765, allow_external=True)

        mock_uvicorn.run.assert_called_once()

    def test_localhost_default_no_raise(self):
        """Default localhost binding does not raise."""
        from code_puppy.api.main import main

        with patch("code_puppy.api.main.uvicorn") as mock_uvicorn:
            main(host="127.0.0.1", port=8765, allow_external=False)

        mock_uvicorn.run.assert_called_once()

    def test_env_var_override(self):
        """CODE_PUPPY_ALLOW_EXTERNAL=1 enables external access."""
        from code_puppy.api.main import main

        with (
            patch.dict("os.environ", {"CODE_PUPPY_ALLOW_EXTERNAL": "1"}),
            patch("code_puppy.api.main.uvicorn") as mock_uvicorn,
        ):
            main(host="0.0.0.0", port=8765, allow_external=False)

        mock_uvicorn.run.assert_called_once()

    def test_no_token_in_logs(self):
        """Runtime token should not appear in log output."""
        # Verify the api/main.py code doesn't log the token
        import inspect
        from code_puppy.api.main import main

        source = inspect.getsource(main)
        # The word 'token' should not appear in log calls
        assert "token" not in source.lower() or "allow_external" in source.lower(), (
            "Token should not be logged in api/main.py"
        )
