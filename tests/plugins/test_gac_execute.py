"""Tests for the Git Auto Commit (GAC) execute_commit module.

These tests cover the execute phase of the commit workflow:
- execute_commit() - Run git commit through security boundary

Includes tests for shlex.quote() shell injection prevention.
All tests mock execute_git_command_sync to avoid actual git execution.
"""

import shlex
from unittest.mock import patch

import pytest

from code_puppy.plugins.git_auto_commit.commit_flow import (
    CommitFlowError,
    execute_commit,
)
from code_puppy.plugins.git_auto_commit.context_guard import GACContextError


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_safe_context():
    """Fixture that mocks a safe execution context."""
    with patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.check_gac_context"
    ) as mock:
        mock.return_value = None  # Safe context returns None
        yield mock


@pytest.fixture
def mock_subagent_context():
    """Fixture that mocks an unsafe sub-agent context."""
    with patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.check_gac_context"
    ) as mock:
        mock.side_effect = GACContextError(
            "GAC refused: running in sub-agent context (test-agent, depth=1).",
            reason="sub-agent context",
            agent_name="test-agent",
            depth=1,
        )
        yield mock


# =============================================================================
# Tests for execute_commit()
# =============================================================================


class TestExecuteCommitSafeContext:
    """Test execute_commit() in safe contexts."""

    def test_succeeds_with_valid_message(self, mock_safe_context):
        """Should succeed with valid commit message."""
        commit_output = (
            "[feature/code_puppy-7db.3-architecture-spike abc1234] feat: add new feature\n"
            " 3 files changed, 42 insertions(+)\n"
        )

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": commit_output,
                "error": "",
                "blocked": False,
            }

            result = execute_commit("feat: add new feature")

        assert result["success"] is True
        assert result["commit_hash"] == "abc1234"
        assert "architecture-spike" in result["branch"]

    def test_extracts_commit_hash_correctly(self, mock_safe_context):
        """Should correctly extract commit hash from git output."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1a2b3c4d] commit message\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit("test message")

        assert result["commit_hash"] == "1a2b3c4d"
        assert result["branch"] == "main"

    def test_handles_branch_with_spaces(self, mock_safe_context):
        """Should handle branch names with spaces."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[feature/my branch name abc1234] message\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit("test")

        assert result["commit_hash"] == "abc1234"
        assert result["branch"] == "feature/my branch name"

    def test_handles_detached_head(self, mock_safe_context):
        """Should handle detached HEAD state."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[(HEAD detached at abc1234) def5678] message\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit("test")

        assert result["commit_hash"] == "def5678"

    def test_raises_on_empty_message(self, mock_safe_context):
        """Should raise CommitFlowError on empty message."""
        with pytest.raises(CommitFlowError) as exc_info:
            execute_commit("")

        assert exc_info.value.phase == "execute"
        assert "empty" in str(exc_info.value).lower()

    def test_raises_on_whitespace_only_message(self, mock_safe_context):
        """Should raise CommitFlowError on whitespace-only message."""
        with pytest.raises(CommitFlowError) as exc_info:
            execute_commit("   \n\t  ")

        assert exc_info.value.phase == "execute"

    def test_uses_shlex_quote_for_shell_safety(self, mock_safe_context):
        """Should use shlex.quote() for proper shell escaping."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            # Message with dangerous characters
            dangerous_msg = 'feat: add "quotes" and `backticks` and $variables'
            execute_commit(dangerous_msg)

            # Check the command that was executed
            call_args = mock_exec.call_args
            command = call_args[0][0]

            # Verify shlex.quote was used (message should be properly quoted)
            expected_quoted = shlex.quote(dangerous_msg)
            assert expected_quoted in command
            # The command should be: git commit -m <quoted_message>
            assert command.startswith("git commit -m ")

    def test_handles_double_quotes_in_message(self, mock_safe_context):
        """Should handle double quotes in commit message using shlex.quote."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            msg_with_quotes = 'fix: resolve "unexpected behavior"'
            execute_commit(msg_with_quotes)

            call_args = mock_exec.call_args
            command = call_args[0][0]
            # Verify shlex.quote is used for proper escaping
            expected_quoted = shlex.quote(msg_with_quotes)
            assert expected_quoted in command

    def test_handles_backticks_in_message(self, mock_safe_context):
        """Should handle backticks in commit message using shlex.quote."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            msg_with_backticks = "docs: explain `code` usage"
            execute_commit(msg_with_backticks)

            call_args = mock_exec.call_args
            command = call_args[0][0]
            # Verify shlex.quote is used
            expected_quoted = shlex.quote(msg_with_backticks)
            assert expected_quoted in command

    def test_handles_dollar_signs_in_message(self, mock_safe_context):
        """Should handle dollar signs in commit message using shlex.quote."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            msg_with_dollar = "feat: add $HOME variable support"
            execute_commit(msg_with_dollar)

            call_args = mock_exec.call_args
            command = call_args[0][0]
            # Verify shlex.quote is used
            expected_quoted = shlex.quote(msg_with_dollar)
            assert expected_quoted in command

    def test_handles_command_injection_attempt(self, mock_safe_context):
        """Should safely escape command injection attempts using shlex.quote."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            # Attempt command injection
            injection_msg = 'test"; rm -rf /; "'
            execute_commit(injection_msg)

            call_args = mock_exec.call_args
            command = call_args[0][0]
            # shlex.quote should neutralize the injection attempt
            expected_quoted = shlex.quote(injection_msg)
            assert expected_quoted in command
            # The entire message should be quoted as a single argument
            assert command.startswith("git commit -m ")

    def test_handles_single_quotes_in_message(self, mock_safe_context):
        """Should handle single quotes in commit message using shlex.quote."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            msg_with_quotes = "feat: it's working"
            execute_commit(msg_with_quotes)

            call_args = mock_exec.call_args
            command = call_args[0][0]
            # Verify shlex.quote is used
            expected_quoted = shlex.quote(msg_with_quotes)
            assert expected_quoted in command

    def test_raises_commit_flow_error_when_git_fails(self, mock_safe_context):
        """Should raise CommitFlowError when git commit fails."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": False,
                "output": "",
                "error": "nothing to commit, working tree clean",
                "blocked": False,
            }

            with pytest.raises(CommitFlowError) as exc_info:
                execute_commit("test message")

            assert exc_info.value.phase == "execute"
            assert "nothing to commit" in str(exc_info.value)

    def test_calls_check_gac_context_first(self, mock_safe_context):
        """Should call check_gac_context before any git operations."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] msg\n",
                "error": "",
                "blocked": False,
            }

            execute_commit("test message")

        mock_safe_context.assert_called_once()


class TestExecuteCommitUnsafeContext:
    """Test execute_commit() in unsafe contexts."""

    def test_raises_gac_context_error_in_subagent(self, mock_subagent_context):
        """Should raise GACContextError in sub-agent context."""
        with pytest.raises(GACContextError):
            execute_commit("test message")


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_handles_unicode_in_commit_message(self, mock_safe_context):
        """Should handle unicode characters in commit message."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit("feat: add 日本語 support 🎉")

        assert result["success"] is True

    def test_handles_newlines_in_commit_message(self, mock_safe_context):
        """Should handle newlines in commit message."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            # Multi-line commit message
            result = execute_commit("feat: add feature\n\nDetailed description here")

        assert result["success"] is True

    def test_handles_very_long_commit_message(self, mock_safe_context):
        """Should handle very long commit messages."""
        long_message = "feat: " + "x" * 1000

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] message\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit(long_message)

        assert result["success"] is True

    def test_handles_missing_git_output_fields(self, mock_safe_context):
        """Should handle commit output without expected format."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "Some unexpected output without brackets\n",
                "error": "",
                "blocked": False,
            }

            result = execute_commit("test message")

        # Should succeed but hash/branch might be None
        assert result["success"] is True
        # These might be None if parsing failed
        assert result["commit_hash"] is None or isinstance(result["commit_hash"], str)
        assert result["branch"] is None or isinstance(result["branch"], str)


# =============================================================================
# Main entry point for manual testing
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
