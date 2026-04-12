"""Regression tests for validate_shell_command and DANGEROUS_PATTERNS.

These tests guard the fix that narrowed DANGEROUS_PATTERNS to only block
process substitution, null bytes, and multiple fd redirections, while allowing:
  - Command substitution with $()
  - Backtick substitution
  - Normal shell operations
  - Single fd redirections (e.g. ``2>&1``)

Note: Multiple fd redirections like ``echo hi 2>&1 3>&1`` are still blocked
by the ``\d*>&\d*\s*\d*>&`` pattern in DANGEROUS_PATTERNS.

See: code_puppy-d6s (watchdog fix for over-broad pattern matching)
"""

import importlib.util
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import command_runner module without pulling in heavy __init__.py deps
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "command_runner_module",
    Path(__file__).parent.parent.parent / "code_puppy" / "tools" / "command_runner.py",
)
assert spec is not None, "Could not locate command_runner.py"
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

validate_shell_command = _mod.validate_shell_command
CommandValidationError = _mod.CommandValidationError
DANGEROUS_PATTERNS = _mod.DANGEROUS_PATTERNS


# ===================================================================
# Allowed: command substitution with $()
# ===================================================================
class TestCommandSubstitutionAllowed:
    """$(...) is a normal shell feature and must NOT be blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(date)",
            "echo $(uname -a)",
            "ls -la $(pwd)",
            "cat $(which python3)",
            "echo today is $(date +%A)",
            # Nested substitution
            "echo $(echo $(date))",
        ],
    )
    def test_dollar_paren_allowed(self, command: str) -> None:
        """Command substitution $(...) must pass validation."""
        result = validate_shell_command(command)
        assert result == command

    def test_dollar_paren_not_in_dangerous_patterns(self) -> None:
        """Verify that no DANGEROUS_PATTERN regex matches plain $(...)."""
        import re

        for raw in DANGEROUS_PATTERNS:
            pat = re.compile(raw)
            assert not pat.search("echo $(date)"), (
                f"DANGEROUS_PATTERN {raw!r} incorrectly matches 'echo $(date)'"
            )


# ===================================================================
# Allowed: backtick substitution
# ===================================================================
class TestBacktickSubstitutionAllowed:
    """Backtick command substitution must NOT be blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo `uname`",
            "echo `date +%s`",
            "ls -la `pwd`",
            "echo `cat /etc/hostname`",
        ],
    )
    def test_backtick_allowed(self, command: str) -> None:
        """Backtick substitution must pass validation."""
        result = validate_shell_command(command)
        assert result == command


# ===================================================================
# Blocked: process substitution <(...)  >(...)
# ===================================================================
class TestProcessSubstitutionBlocked:
    """Process substitution <(...) and >(...) must be blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat <(echo hi)",
            "diff <(sort a.txt) <(sort b.txt)",
            "tee >(gzip > out.gz)",
            "cat  <(  echo hi)",  # whitespace between < and (
        ],
    )
    def test_process_sub_blocked(self, command: str) -> None:
        """Process substitution patterns must raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="dangerous pattern"):
            validate_shell_command(command)


# ===================================================================
# Blocked: null bytes
# ===================================================================
class TestNullBytesBlocked:
    """Null bytes must always be blocked."""

    def test_null_byte_rejected(self) -> None:
        """Commands containing \\x00 must be rejected."""
        with pytest.raises(CommandValidationError):
            validate_shell_command("echo hello\x00world")

    def test_null_byte_at_start(self) -> None:
        with pytest.raises(CommandValidationError):
            validate_shell_command("\x00echo hi")

    def test_null_byte_at_end(self) -> None:
        with pytest.raises(CommandValidationError):
            validate_shell_command("echo hi\x00")


# ===================================================================
# Additional: empty / whitespace / overly-long commands
# ===================================================================
class TestBasicValidation:
    """Cover the other validation branches for completeness."""

    def test_empty_command_rejected(self) -> None:
        with pytest.raises(CommandValidationError, match="empty"):
            validate_shell_command("")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(CommandValidationError, match="empty"):
            validate_shell_command("   \t  ")

    def test_valid_command_passes(self) -> None:
        assert validate_shell_command("echo hello") == "echo hello"

    def test_pipe_allowed(self) -> None:
        """Pipes are normal shell and should not be blocked."""
        assert validate_shell_command("echo hi | grep hi") == "echo hi | grep hi"

    def test_semicolon_allowed(self) -> None:
        """Semicolons are normal shell and should not be blocked."""
        assert validate_shell_command("echo a; echo b") == "echo a; echo b"

    def test_and_allowed(self) -> None:
        assert validate_shell_command("mkdir dir && cd dir") == "mkdir dir && cd dir"


# ===================================================================
# Blocked: multiple fd redirections
# ===================================================================
class TestMultipleFdRedirectionBlocked:
    """Multiple fd redirections (e.g. ``2>&1 3>&1``) must be blocked.

    The pattern ``\d*>&\d*\s*\d*>&`` in DANGEROUS_PATTERNS catches chained
    fd-to-fd redirections, which can be abused to cloak command output.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "echo hi 2>&1 3>&1",
            "some_cmd 1>&2 2>&1",
            "cat file 3>&1 4>&1",
            "echo x 2>&1  3>&1",  # extra whitespace between redirections
        ],
    )
    def test_multiple_fd_redirection_blocked(self, command: str) -> None:
        """Commands with multiple fd redirections must raise CommandValidationError."""
        with pytest.raises(CommandValidationError, match="dangerous pattern"):
            validate_shell_command(command)


# ===================================================================
# Allowed: single fd redirection
# ===================================================================
class TestSingleFdRedirectionAllowed:
    """Single fd redirections (e.g. ``2>&1``) are normal shell and must pass."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo hi 2>&1",
            "some_cmd 1>&2",
            "cat file 2>/dev/null",
            "make 2>&1",
            "python script.py 2>&1",
        ],
    )
    def test_single_fd_redirection_allowed(self, command: str) -> None:
        """Single fd redirection must pass validation."""
        result = validate_shell_command(command)
        assert result == command
