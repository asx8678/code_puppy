"""Tests for the Git Auto Commit (GAC) run_full_flow module.

These tests cover the full commit workflow integration:
- run_full_flow() - Orchestrates preflight → preview → execute

Includes integration tests that verify all phases work together.
All tests mock execute_git_command_sync to avoid actual git execution.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from code_puppy.plugins.git_auto_commit.commit_flow import (
    execute_commit,
    generate_preview,
    preflight_check,
    run_full_flow,
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
# Tests for run_full_flow()
# =============================================================================


class TestRunFullFlow:
    """Test run_full_flow() integration."""

    def test_runs_all_phases_successfully(self, mock_safe_context):
        """Should run all phases successfully."""
        with (
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.preflight_check"
            ) as mock_preflight,
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.generate_preview"
            ) as mock_preview,
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.execute_commit"
            ) as mock_execute,
        ):
            mock_preflight.return_value = {
                "staged_files": ["file.py"],
                "unstaged_files": [],
                "untracked_files": [],
                "has_staged": True,
                "clean": False,
            }
            mock_preview.return_value = {
                "diff": "file.py | 10 ++++",
                "file_count": 1,
                "insertions": 10,
                "deletions": 0,
                "summary": "1 file changed, 10 insertions",
            }
            mock_execute.return_value = {
                "success": True,
                "output": "[main 1234] feat: test\n",
                "commit_hash": "1234",
                "branch": "main",
            }

            result = run_full_flow(message="feat: test")

        assert result["success"] is True
        assert result["phase"] == "execute"
        assert result["preflight"]["has_staged"] is True
        assert result["preview"]["file_count"] == 1
        assert result["commit"]["commit_hash"] == "1234"

    def test_returns_error_when_no_staged_changes(self, mock_safe_context):
        """Should return error when no staged changes exist."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.preflight_check"
        ) as mock_preflight:
            mock_preflight.return_value = {
                "staged_files": [],
                "unstaged_files": ["unstaged.py"],
                "untracked_files": [],
                "has_staged": False,
                "clean": False,
            }

            result = run_full_flow(message="feat: test")

        assert result["success"] is False
        assert result["phase"] == "preflight"
        assert "staged" in result["error"].lower()

    def test_returns_error_when_no_message_and_not_auto_confirm(
        self, mock_safe_context
    ):
        """Should return error when no message provided and not auto-confirm."""
        with (
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.preflight_check"
            ) as mock_preflight,
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.generate_preview"
            ) as mock_preview,
        ):
            mock_preflight.return_value = {
                "staged_files": ["file.py"],
                "has_staged": True,
                "clean": False,
            }
            mock_preview.return_value = {
                "file_count": 1,
                "summary": "1 file changed",
            }

            result = run_full_flow(message=None, auto_confirm=False)

        assert result["success"] is False
        assert result["phase"] == "preview"
        assert "message" in result["error"].lower()

    def test_auto_confirm_generates_message(self, mock_safe_context):
        """run_full_flow with auto_confirm=True and no message generates one."""
        with (
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.preflight_check"
            ) as mock_preflight,
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.generate_preview"
            ) as mock_preview,
            patch(
                "code_puppy.plugins.git_auto_commit.commit_flow.execute_commit"
            ) as mock_execute,
        ):
            # Mock preflight with staged files
            mock_preflight.return_value = {
                "staged_files": ["src/feature.py", "tests/test_feature.py"],
                "unstaged_files": [],
                "untracked_files": [],
                "has_staged": True,
                "clean": False,
            }
            # Mock preview
            mock_preview.return_value = {
                "diff": "src/feature.py | 42 +++",
                "file_count": 2,
                "insertions": 42,
                "deletions": 0,
                "summary": "2 files changed, 42 insertions(+)",
            }
            # Mock execute
            mock_execute.return_value = {
                "success": True,
                "output": "[main abc1234] feat: update 2 files\n",
                "commit_hash": "abc1234",
                "branch": "main",
            }

            # Call run_full_flow with auto_confirm=True but no message
            result = run_full_flow(message=None, auto_confirm=True)

            # Assert execute_commit was called with autogenerated message
            mock_execute.assert_called_once()
            called_message = mock_execute.call_args[0][0]
            assert "feat: update" in called_message
            assert "2 files" in called_message
            assert result["success"] is True
            assert result["phase"] == "execute"

    def test_calls_context_guard_in_preflight(self, mock_safe_context):
        """Should call context guard (via preflight_check)."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.preflight_check"
        ) as mock_preflight:
            mock_preflight.return_value = {
                "staged_files": [],
                "has_staged": False,
                "clean": True,
            }

            run_full_flow(message="test")

        # preflight_check calls check_gac_context
        mock_preflight.assert_called_once()


# =============================================================================
# Integration Tests - Full Flow Sequence
# =============================================================================


class TestFullFlowSequence:
    """Test that the full flow works in sequence."""

    def test_preflight_preview_execute_sequence(self, mock_safe_context):
        """Test that preflight → preview → execute works in sequence."""
        import shlex

        # Simulate real git responses
        git_responses = {
            "git status --porcelain": {
                "success": True,
                "output": "M  src/file.py\n",
                "error": "",
            },
            "git diff --cached --stat": {
                "success": True,
                "output": " src/file.py | 42 +++++\n 1 file changed, 42 insertions(+)\n",
                "error": "",
            },
            f"git commit -m {shlex.quote('feat: add feature')}": {
                "success": True,
                "output": "[main abc1234] feat: add feature\n 1 file changed, 42 insertions(+)\n",
                "error": "",
            },
        }

        def mock_exec(command, cwd=None):
            return git_responses.get(
                command, {"success": False, "error": "unknown command"}
            )

        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync",
            side_effect=mock_exec,
        ):
            # Phase 1: Preflight
            preflight = preflight_check()
            assert preflight["has_staged"] is True

            # Phase 2: Preview
            preview = generate_preview()
            assert preview["file_count"] == 1

            # Phase 3: Execute
            result = execute_commit("feat: add feature")
            assert result["success"] is True
            assert result["commit_hash"] == "abc1234"

    def test_each_phase_calls_check_gac_context(self, mock_safe_context):
        """Verify each phase calls check_gac_context."""
        with patch(
            "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "output": "M  file.py\n",
                "error": "",
            }

            # Reset call count
            mock_safe_context.reset_mock()

            # Phase 1
            preflight_check()
            assert mock_safe_context.call_count == 1

            # Phase 2
            generate_preview()
            assert mock_safe_context.call_count == 2

            # Phase 3
            mock_exec.return_value = {
                "success": True,
                "output": "[main 1234] msg\n",
                "error": "",
            }
            execute_commit("msg")
            assert mock_safe_context.call_count == 3


# =============================================================================
# Main entry point for manual testing
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
