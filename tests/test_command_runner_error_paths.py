"""Regression tests for command_runner error path fixes.

These tests guard against regression of two cascading bugs:
1. Invalid `newline=""` kwarg in subprocess.Popen (caused TypeError on Python 3.14)
2. Missing default values for optional fields in ShellCommandOutput pydantic model

The fixes ensure error-path ShellCommandOutput constructions don't raise ValidationError
and that Popen no longer uses the invalid newline parameter.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.tools.command_runner import ShellCommandOutput, _run_command_inner


class TestShellCommandOutputModel:
    """Tests for ShellCommandOutput pydantic model field defaults."""

    def test_shell_command_output_accepts_minimal_kwargs(self):
        """ShellCommandOutput with only success=False must not raise ValidationError.

        Regression guard: Previously, fields like command, stdout, stderr,
        exit_code, execution_time had no defaults and would cause ValidationError
        when constructing error-path results without all fields.
        """
        result = ShellCommandOutput(success=False)

        assert result.success is False
        assert result.command is None
        assert result.stdout is None
        assert result.stderr is None
        assert result.exit_code is None
        assert result.execution_time is None
        assert result.timeout is False
        assert result.error == ""

    def test_shell_command_output_accepts_full_kwargs(self):
        """ShellCommandOutput round-trips correctly with all fields populated."""
        result = ShellCommandOutput(
            success=True,
            command="echo hello",
            stdout="hello\n",
            stderr="",
            exit_code=0,
            execution_time=0.5,
            timeout=False,
            error="",
            user_interrupted=False,
            background=False,
        )

        dumped = result.model_dump()
        assert dumped["success"] is True
        assert dumped["command"] == "echo hello"
        assert dumped["stdout"] == "hello\n"
        assert dumped["stderr"] == ""
        assert dumped["exit_code"] == 0
        assert dumped["execution_time"] == 0.5
        assert dumped["timeout"] is False

    def test_shell_command_output_empty_command_field_shape(self):
        """ShellCommandOutput handles empty string command field gracefully."""
        result = ShellCommandOutput(
            success=False,
            command="",
            error="Command cannot be empty"
        )

        assert result.success is False
        assert result.command == ""
        assert result.error == "Command cannot be empty"
        assert result.stdout is None
        assert result.stderr is None


class TestPopenNewlineRegression:
    """Guard tests for subprocess.Popen newline= kwarg removal."""

    def test_popen_no_longer_uses_newline_kwarg(self):
        """Ensure newline= parameter is not used in any Popen calls.

        Context: Python 3.14 removed support for the `newline` parameter in
        subprocess.Popen, which previously caused TypeError. We fixed this by
        removing all newline= kwargs and using text=True with encoding instead.

        This test reads the source as text to verify no regression.
        """
        source_path = Path(__file__).parent.parent / "code_puppy" / "tools" / "command_runner.py"
        source_text = source_path.read_text()

        # Assert newline= does not appear anywhere (including variations)
        assert "newline=" not in source_text, (
            "newline= kwarg found in command_runner.py - "
            "this causes TypeError on Python 3.14"
        )


class TestRunCommandInnerErrorHandling:
    """Tests for _run_command_inner exception handling paths."""

    async def test_run_command_inner_handles_popen_typeerror(self):
        """_run_command_inner must return ShellCommandOutput on Popen TypeError.

        Regression guard: When subprocess.Popen raises TypeError (e.g., due to
        invalid newline= kwarg), the error path must construct a valid
        ShellCommandOutput without raising another exception.
        """
        with patch("code_puppy.tools.command_runner.subprocess.Popen") as mock_popen:
            with patch("code_puppy.tools.command_runner.get_message_bus") as mock_get_bus:
                # Setup mocks
                mock_popen.side_effect = TypeError("simulated popen failure")
                mock_bus = MagicMock()
                mock_get_bus.return_value = mock_bus

                # Call the function under test
                result = await _run_command_inner(
                    command="echo hi",
                    cwd=None,
                    timeout=5,
                    group_id="test-group",
                    silent=True
                )

        # Assert result is a valid ShellCommandOutput (not an exception)
        assert isinstance(result, ShellCommandOutput)
        assert result.success is False
        assert result.exit_code == -1
        assert result.execution_time is None
        assert "simulated" in (result.error or "").lower()
