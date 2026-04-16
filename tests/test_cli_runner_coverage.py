"""Additional coverage tests for cli_runner.py - uncovered branches.

Focuses on: run_prompt_with_attachments, execute_single_prompt, main_entry,
and interactive_mode branches.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunPromptWithAttachments:
    """Test run_prompt_with_attachments function."""

    @pytest.mark.anyio
    async def test_empty_prompt_returns_none(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        # A prompt that becomes empty after attachment parsing
        mock_agent = MagicMock()
        with (
            patch("code_puppy.prompt_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.prompt_runner.get_clipboard_manager") as mock_clip,
        ):
            mock_parse.return_value = MagicMock(
                prompt="",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            clip_mgr.get_pending_count.return_value = 0
            mock_clip.return_value = clip_mgr

            result, task = await run_prompt_with_attachments(mock_agent, "")
            assert result is None
            assert task is None

    @pytest.mark.anyio
    async def test_with_attachments_and_spinner(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        mock_attachment = MagicMock()
        mock_attachment.content = b"image-data"
        mock_link = MagicMock()
        mock_link.url_part = "https://example.com"

        with (
            patch("code_puppy.prompt_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.prompt_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
            patch("code_puppy.messaging.spinner.ConsoleSpinner") as mock_spinner,
        ):
            mock_parse.return_value = MagicMock(
                prompt="do stuff",
                warnings=["warn1"],
                attachments=[mock_attachment],
                link_attachments=[mock_link],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = [b"clip-img"]
            clip_mgr.get_pending_count.return_value = 1
            mock_clip.return_value = clip_mgr

            mock_spinner.return_value.__enter__ = MagicMock()
            mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

            console = MagicMock()
            result, task = await run_prompt_with_attachments(
                mock_agent, "do stuff", spinner_console=console, use_spinner=True
            )
            assert result is mock_result

    @pytest.mark.anyio
    async def test_cancelled_with_spinner(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch("code_puppy.prompt_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.prompt_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
            patch("code_puppy.messaging.spinner.ConsoleSpinner") as mock_spinner,
        ):
            mock_parse.return_value = MagicMock(
                prompt="do stuff",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            clip_mgr.get_pending_count.return_value = 0
            mock_clip.return_value = clip_mgr

            mock_spinner.return_value.__enter__ = MagicMock()
            mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

            console = MagicMock()
            result, task = await run_prompt_with_attachments(
                mock_agent, "do stuff", spinner_console=console, use_spinner=True
            )
            assert result is None

    @pytest.mark.anyio
    async def test_cancelled_without_spinner(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch("code_puppy.prompt_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.prompt_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = MagicMock(
                prompt="do stuff",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = []
            clip_mgr.get_pending_count.return_value = 0
            mock_clip.return_value = clip_mgr

            result, task = await run_prompt_with_attachments(
                mock_agent, "do stuff", use_spinner=False
            )
            assert result is None

    @pytest.mark.anyio
    async def test_clipboard_placeholder_cleaned(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        with (
            patch("code_puppy.prompt_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.prompt_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = MagicMock(
                prompt="[📋 clipboard image 1] describe this",
                warnings=[],
                attachments=[],
                link_attachments=[],
            )
            clip_mgr = MagicMock()
            clip_mgr.get_pending_images.return_value = [b"img"]
            clip_mgr.get_pending_count.return_value = 1
            mock_clip.return_value = clip_mgr

            result, task = await run_prompt_with_attachments(
                mock_agent, "test", use_spinner=False
            )
            # The cleaned prompt should have placeholder removed
            call_args = mock_agent.run_with_mcp.call_args
            assert "clipboard image" not in call_args[0][0]


class TestExecuteSinglePrompt:
    @pytest.mark.anyio
    async def test_success(self):
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        mock_result = MagicMock()
        mock_result.output = "done!"

        with (
            patch("code_puppy.prompt_runner.get_current_agent"),
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments",
                new_callable=AsyncMock,
            ) as mock_run,
            patch("code_puppy.prompt_runner.emit_info"),
        ):
            mock_run.return_value = (mock_result, MagicMock())
            await execute_single_prompt("hello", mock_renderer)

    @pytest.mark.anyio
    async def test_none_response(self):
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        with (
            patch("code_puppy.prompt_runner.get_current_agent"),
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments",
                new_callable=AsyncMock,
            ) as mock_run,
            patch("code_puppy.prompt_runner.emit_info"),
        ):
            mock_run.return_value = None
            await execute_single_prompt("hello", mock_renderer)

    @pytest.mark.anyio
    async def test_cancelled(self):
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        with (
            patch("code_puppy.prompt_runner.get_current_agent"),
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            patch("code_puppy.prompt_runner.emit_info"),
        ):
            await execute_single_prompt("hello", mock_renderer)

    @pytest.mark.anyio
    async def test_exception(self):
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        with (
            patch("code_puppy.prompt_runner.get_current_agent"),
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("code_puppy.prompt_runner.emit_info"),
        ):
            await execute_single_prompt("hello", mock_renderer)


class TestMainEntry:
    @patch("asyncio.run")
    def test_normal_exit(self, mock_run):
        from code_puppy.cli_runner import main_entry

        mock_run.return_value = None
        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            result = main_entry()
        assert result is None

    @patch("asyncio.run", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt(self, mock_run):
        from code_puppy.cli_runner import main_entry

        with (
            patch("code_puppy.cli_runner.reset_unix_terminal"),
            patch("code_puppy.cli_runner.get_use_dbos", return_value=False),
        ):
            result = main_entry()
        assert result == 0

    @patch("asyncio.run", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_with_dbos(self, mock_run):
        from code_puppy.cli_runner import main_entry

        # Mock DBOS using sys.modules approach since imports are deferred
        mock_dbos_module = MagicMock()
        mock_dbos_module.DBOS = MagicMock()
        mock_dbos_module.DBOS.destroy = MagicMock()

        with (
            patch("code_puppy.cli_runner.reset_unix_terminal"),
            patch("code_puppy.config.get_use_dbos", return_value=True),
            patch.dict("sys.modules", {"dbos": mock_dbos_module}),
        ):
            result = main_entry()
        assert result == 0
        mock_dbos_module.DBOS.destroy.assert_called_once()

    @patch("code_puppy.cli_runner._run_full")
    def test_help_fast_path(self, mock_run_full):
        """Test that --help triggers fast path and _run_full is NOT called."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "--help"]):
            result = main_entry()

        # _run_full should NOT be called for --help (fast path)
        mock_run_full.assert_not_called()
        # main_entry returns None after printing help
        assert result is None

    @patch("code_puppy.cli_runner._run_full")
    def test_version_fast_path(self, mock_run_full):
        """Test that --version triggers fast path and _run_full is NOT called."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "--version"]):
            result = main_entry()

        # _run_full should NOT be called for --version (fast path)
        mock_run_full.assert_not_called()
        # main_entry returns None after printing version
        assert result is None

    @patch("code_puppy.cli_runner._run_full")
    def test_help_short_flag_fast_path(self, mock_run_full):
        """Test that -h triggers fast path and _run_full is NOT called."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "-h"]):
            result = main_entry()

        # _run_full should NOT be called for -h (fast path)
        mock_run_full.assert_not_called()
        assert result is None

    @patch("code_puppy.cli_runner._run_full")
    def test_version_short_flag_v_fast_path(self, mock_run_full):
        """Test that -v triggers fast path and _run_full is NOT called."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "-v"]):
            result = main_entry()

        # _run_full should NOT be called for -v (fast path)
        mock_run_full.assert_not_called()
        assert result is None

    @patch("code_puppy.cli_runner._run_full")
    def test_version_short_flag_capital_v_fast_path(self, mock_run_full):
        """Test that -V triggers fast path and _run_full is NOT called."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "-V"]):
            result = main_entry()

        # _run_full should NOT be called for -V (fast path)
        mock_run_full.assert_not_called()
        assert result is None

    @patch("code_puppy.cli_runner._run_full")
    def test_help_not_triggered_as_prompt_value(self, mock_run_full):
        """--help as -p value should NOT trigger fast path (bd-3 regression test)."""
        from code_puppy.cli_runner import main_entry

        # sys.argv = ["code-puppy", "-p", "--help"]
        # Should NOT print help, should try to run the prompt
        with patch("sys.argv", ["code-puppy", "-p", "--help"]):
            main_entry()

        # _run_full SHOULD be called because --help is a prompt value, not a flag
        mock_run_full.assert_called_once()

    @patch("code_puppy.cli_runner._run_full")
    def test_version_not_triggered_as_prompt_value(self, mock_run_full):
        """--version as -p value should NOT trigger fast path (bd-3 regression test)."""
        from code_puppy.cli_runner import main_entry

        # sys.argv = ["code-puppy", "-p", "--version"]
        # Should NOT print version, should try to run the prompt
        with patch("sys.argv", ["code-puppy", "-p", "--version"]):
            main_entry()

        # _run_full SHOULD be called because --version is a prompt value, not a flag
        mock_run_full.assert_called_once()

    @patch("code_puppy.cli_runner._run_full")
    def test_help_not_triggered_as_value_after_other_flags(self, mock_run_full):
        """--help after any flag should NOT trigger fast path."""
        from code_puppy.cli_runner import main_entry

        # Various edge cases where --help appears but not as first arg
        test_cases = [
            ["code-puppy", "-m", "claude-sonnet", "--help"],
            ["code-puppy", "--model", "gpt-4", "--help"],
            ["code-puppy", "some-arg", "--help"],
            ["code-puppy", "-i", "--help"],
        ]

        for argv in test_cases:
            mock_run_full.reset_mock()
            with patch("sys.argv", argv):
                main_entry()
            # Should always call _run_full, NOT trigger fast path
            mock_run_full.assert_called_once()

    @patch("code_puppy.cli_runner._run_full")
    def test_short_help_not_triggered_as_value(self, mock_run_full):
        """-h as a value (e.g., after -p) should NOT trigger fast path."""
        from code_puppy.cli_runner import main_entry

        with patch("sys.argv", ["code-puppy", "-p", "-h"]):
            main_entry()

        # _run_full SHOULD be called because -h is a prompt value, not a flag
        mock_run_full.assert_called_once()

    @patch("code_puppy.cli_runner._run_full")
    def test_short_version_not_triggered_as_value(self, mock_run_full):
        """-v/-V as a value (e.g., after -p) should NOT trigger fast path."""
        from code_puppy.cli_runner import main_entry

        for version_flag in ["-v", "-V"]:
            mock_run_full.reset_mock()
            with patch("sys.argv", ["code-puppy", "-p", version_flag]):
                main_entry()

            # _run_full SHOULD be called because -v/-V is a prompt value, not a flag
            mock_run_full.assert_called_once()
