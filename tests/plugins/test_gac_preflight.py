"""Tests for the Git Auto Commit (GAC) preflight_check module.

These tests cover the preflight phase of the commit workflow:
- preflight_check() - Detect staged/unstaged changes

All tests mock execute_git_command_sync to avoid actual git execution.
"""

from unittest.mock import patch

import pytest

from code_puppy.plugins.git_auto_commit.commit_flow import (
    CommitFlowError,
    preflight_check,
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
# Tests for CommitFlowError
# =============================================================================


class TestCommitFlowError:
    """Test CommitFlowError exception class."""

    def test_inherits_from_exception(self):
        """CommitFlowError should inherit from Exception."""
        err = CommitFlowError("test message", phase="test")
        assert isinstance(err, Exception)

    def test_stores_phase_attribute(self):
        """Error should store the phase attribute."""
        err = CommitFlowError("test", phase="preflight")
        assert err.phase == "preflight"

    def test_stores_details_attribute(self):
        """Error should store the details attribute."""
        err = CommitFlowError("test", phase="execute", details="stderr output")
        assert err.details == "stderr output"

    def test_details_can_be_none(self):
        """Details can be None."""
        err = CommitFlowError("test", phase="preview")
        assert err.details is None

    def test_message_formatting(self):
        """Message should be properly formatted."""
        err = CommitFlowError("Failed to commit", phase="execute")
        assert str(err) == "Failed to commit"


# =============================================================================
# Tests for preflight_check()
# =============================================================================


class TestPreflightCheckSafeContext:
    """Test preflight_check() in safe contexts."""

    def test_returns_correct_staged_files(self, mock_safe_context):
        """Should return correct staged files from git status output."""
        git_output = (
            "M  src/file1.py\n"
            "A  src/file2.py\n"
            "D  old_file.py\n"
            " M unstaged.py\n"
            "?? untracked.py\n"
        )

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert result["staged_files"] == ["src/file1.py", "src/file2.py", "old_file.py"]
        assert result["has_staged"] is True

    def test_returns_correct_unstaged_files(self, mock_safe_context):
        """Should return correct unstaged files from git status output."""
        git_output = "M  staged.py\n M unstaged.py\n D deleted.py\n?? untracked.py\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert "unstaged.py" in result["unstaged_files"]
        assert "deleted.py" in result["unstaged_files"]

    def test_returns_correct_untracked_files(self, mock_safe_context):
        """Should return correct untracked files from git status output."""
        git_output = "M  staged.py\n?? untracked.py\n?? new_file.txt\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert "untracked.py" in result["untracked_files"]
        assert "new_file.txt" in result["untracked_files"]

    def test_detects_clean_working_tree(self, mock_safe_context):
        """Should detect clean working tree."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "",
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert result["clean"] is True
        assert result["has_staged"] is False

    def test_detects_dirty_working_tree(self, mock_safe_context):
        """Should detect dirty working tree."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": " M file.py\n",
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert result["clean"] is False

    def test_handles_renamed_files(self, mock_safe_context):
        """Should handle renamed files (R status code)."""
        git_output = "R  old_name.py -> new_name.py\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        # Renamed files should be in staged
        assert any(
            "old_name.py" in f or "new_name.py" in f for f in result["staged_files"]
        )
        assert result["has_staged"] is True

    def test_handles_copied_files(self, mock_safe_context):
        """Should handle copied files (C status code)."""
        git_output = "C  original.py -> copy.py\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert result["has_staged"] is True

    def test_handles_unmerged_files(self, mock_safe_context):
        """Should handle unmerged files (U status code)."""
        git_output = "U  conflict.py\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        assert "conflict.py" in result["staged_files"]
        assert result["has_staged"] is True

    def test_ignores_ignored_files(self, mock_safe_context):
        """Should ignore files marked as ignored (!!)."""
        git_output = "M  staged.py\n!! ignored.pyc\n"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": git_output,
                "error": "",
                "blocked": False,
            }

            result = preflight_check()

        # Ignored files should not appear in any list
        assert "ignored.pyc" not in result["staged_files"]
        assert "ignored.pyc" not in result["unstaged_files"]
        assert "ignored.pyc" not in result["untracked_files"]

    def test_calls_check_gac_context_first(self, mock_safe_context):
        """Should call check_gac_context before any git operations."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "",
                "error": "",
                "blocked": False,
            }

            preflight_check()

        # Verify context was checked
        mock_safe_context.assert_called_once()

    def test_raises_commit_flow_error_when_git_fails(self, mock_safe_context):
        """Should raise CommitFlowError when git command fails."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": False,
                "output": "",
                "error": "fatal: not a git repository",
                "blocked": False,
            }

            with pytest.raises(CommitFlowError) as exc_info:
                preflight_check()

            assert exc_info.value.phase == "preflight"
            assert "not a git repository" in str(exc_info.value)


class TestPreflightCheckUnsafeContext:
    """Test preflight_check() in unsafe contexts."""

    def test_raises_gac_context_error_in_subagent(self, mock_subagent_context):
        """Should raise GACContextError in sub-agent context."""
        with pytest.raises(GACContextError) as exc_info:
            preflight_check()

        assert "sub-agent" in str(exc_info.value).lower()


# =============================================================================
# Main entry point for manual testing
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
