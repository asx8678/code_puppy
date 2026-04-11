"""Tests for the Git Auto Commit (GAC) generate_preview module.

These tests cover the preview phase of the commit workflow:
- generate_preview() - Show what would be committed

All tests mock execute_git_command_sync to avoid actual git execution.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from code_puppy.plugins.git_auto_commit.commit_flow import (
    CommitFlowError,
    generate_preview,
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
# Tests for generate_preview()
# =============================================================================


class TestGeneratePreviewSafeContext:
    """Test generate_preview() in safe contexts."""

    def test_returns_correct_diff_stat(self, mock_safe_context):
        """Should parse diff --stat output correctly."""
        diff_output = (
            " src/file1.py      | 10 ++++++\n"  # 6 pluses in "++++++"
            " src/file2.py      |  5 +++++\n"  # 5 pluses in "+++++"
            " src/old_file.py  |  3 ---\n"  # 0 pluses, 3 minuses in "---"
            " 3 files changed, 15 insertions(+), 3 deletions(-)"
        )

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": diff_output,
                "error": "",
                "blocked": False,
            }

            result = generate_preview()

        assert result["file_count"] == 3
        # The implementation counts literal + and - characters per file line
        # Line 1: 6 pluses, Line 2: 5 pluses = 11 total insertions
        assert result["insertions"] == 11  # 6 + 5
        assert result["deletions"] == 3  # 3 minuses in "---"

    def test_handles_empty_staged_changes(self, mock_safe_context):
        """Should handle empty staged changes."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "",
                "error": "",
                "blocked": False,
            }

            result = generate_preview()

        assert result["file_count"] == 0
        assert result["summary"] == "0 file(s) staged for commit"

    def test_extracts_summary_line(self, mock_safe_context):
        """Should extract the summary line from diff output."""
        diff_output = " src/file.py | 42 ++++++++++\n 1 file changed, 42 insertions(+)"

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": diff_output,
                "error": "",
                "blocked": False,
            }

            result = generate_preview()

        assert "1 file changed" in result["summary"]
        assert "42 insertions" in result["summary"]

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

            generate_preview()

        mock_safe_context.assert_called_once()

    def test_raises_commit_flow_error_when_git_fails(self, mock_safe_context):
        """Should raise CommitFlowError when git diff fails."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": False,
                "output": "",
                "error": "fatal: bad revision",
                "blocked": False,
            }

            with pytest.raises(CommitFlowError) as exc_info:
                generate_preview()

            assert exc_info.value.phase == "preview"


class TestGeneratePreviewUnsafeContext:
    """Test generate_preview() in unsafe contexts."""

    def test_raises_gac_context_error_in_subagent(self, mock_subagent_context):
        """Should raise GACContextError in sub-agent context."""
        with pytest.raises(GACContextError):
            generate_preview()


# =============================================================================
# Main entry point for manual testing
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
