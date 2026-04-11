"""Integration tests for policy error handling in /commit flow."""

from unittest.mock import patch


class TestPolicyIntegration:
    """Test that policy blocks surface clean messages through /commit."""

    @patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.execute_git_command_sync"
    )
    def test_blocked_command_returns_actionable_message(self, mock_exec):
        """Blocked git command should return clean actionable error."""
        mock_exec.return_value = {
            "success": False,
            "output": "",
            "error": "Security blocked: Policy denied",
            "blocked": True,
            "reason": "Policy denied: git commit not in allowlist",
            "policy_source": "policy_engine",
        }
        from code_puppy.plugins.git_auto_commit.register_callbacks import (
            _handle_commit_command,
        )

        result = _handle_commit_command("/commit status", "commit")
        assert isinstance(result, str)
        assert "GAC blocked" in result
        assert "policy" in result.lower() or "denied" in result.lower()

    @patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.execute_git_command_sync"
    )
    def test_blocked_includes_suggestion(self, mock_exec):
        """Blocked command message should include a suggestion."""
        mock_exec.return_value = {
            "success": False,
            "blocked": True,
            "reason": "git push is not allowed",
            "output": "",
            "error": "blocked",
        }
        from code_puppy.plugins.git_auto_commit.register_callbacks import (
            _handle_commit_command,
        )

        result = _handle_commit_command("/commit status", "commit")
        assert isinstance(result, str)
        assert (
            "resolve" in result.lower()
            or "manually" in result.lower()
            or "policy" in result.lower()
        )
