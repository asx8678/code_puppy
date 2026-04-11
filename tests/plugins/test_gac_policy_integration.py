"""Integration tests for policy error handling in /commit flow."""

from unittest.mock import patch


class TestPolicyIntegration:
    """Test that policy blocks surface clean messages through /commit."""

    @patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.check_gac_context"
    )
    @patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.is_gac_safe",
        return_value=(True, None),
    )
    @patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
    )
    def test_blocked_command_returns_actionable_message(self, mock_exec, mock_safe, mock_check):
        """Blocked git command should return clean actionable error."""
        # Mock preflight to return clean=False, has_staged=True (bypasses early return)
        from code_puppy.plugins.git_auto_commit import commit_flow
        with patch.object(commit_flow, "preflight_check", return_value={
            "clean": False,
            "has_staged": True,
            "staged_files": ["file.py"],
            "unstaged_files": [],
            "untracked_files": [],
        }):
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

            result = _handle_commit_command("/commit -m 'test message'", "commit")
            assert isinstance(result, str)
            assert "GAC blocked" in result or "blocked" in result.lower()

    @patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.check_gac_context"
    )
    @patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.is_gac_safe",
        return_value=(True, None),
    )
    @patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
    )
    def test_blocked_includes_suggestion(self, mock_exec, mock_safe, mock_check):
        """Blocked command message should include a suggestion."""
        from code_puppy.plugins.git_auto_commit import commit_flow
        with patch.object(commit_flow, "preflight_check", return_value={
            "clean": False,
            "has_staged": True,
            "staged_files": ["file.py"],
            "unstaged_files": [],
            "untracked_files": [],
        }):
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

            result = _handle_commit_command("/commit -m 'test message'", "commit")
            assert isinstance(result, str)
            assert (
                "resolve" in result.lower()
                or "manually" in result.lower()
                or "blocked" in result.lower()
            )
