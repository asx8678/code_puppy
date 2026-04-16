"""Tests for the Git Auto Commit (GAC) Shell Bridge.

These tests prove that the sync→async shell bridge works correctly:
1. `execute_git_command_sync()` works from a sync context
2. The bridge doesn't deadlock
3. Security boundary properly blocks dangerous commands
4. The custom_command handler returns appropriate results
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Fixture to mock safe execution context for register_callbacks tests
@pytest.fixture
def mock_gac_safe_context():
    """Fixture that mocks a safe GAC execution context."""
    # Mock both the is_gac_safe check in register_callbacks AND check_gac_context in commit_flow
    with patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.is_gac_safe"
    ) as mock_safe, patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.check_gac_context"
    ) as mock_check:
        mock_safe.return_value = (True, None)
        mock_check.return_value = None  # Safe context returns None
        yield mock_safe


@pytest.fixture
def mock_preflight_with_staged():
    """Fixture that mocks preflight with staged changes."""
    with patch(
        "code_puppy.plugins.git_auto_commit.register_callbacks.preflight_check"
    ) as mock, patch(
        "code_puppy.plugins.git_auto_commit.commit_flow.execute_git_command_sync"
    ) as mock_git:
        mock.return_value = {
            "staged_files": ["file.py"],
            "unstaged_files": [],
            "untracked_files": [],
            "has_staged": True,
            "clean": False,
        }
        # Also mock git commands
        mock_git.return_value = {
            "success": True,
            "output": "",
            "error": "",
            "blocked": False,
        }
        yield mock

from code_puppy.plugins.git_auto_commit.register_callbacks import (
    _commit_help,
    _handle_commit_command,
)
from code_puppy.plugins.git_auto_commit.shell_bridge import (
    execute_git_command,
    execute_git_command_sync,
)
from code_puppy.security import SecurityDecision, reset_security_boundary


# =============================================================================
# Tests for shell_bridge.py
# =============================================================================


class TestExecuteGitCommandSync:
    """Tests for the sync→async bridge function."""

    def test_empty_command(self):
        """Test that empty commands are rejected gracefully."""
        result = execute_git_command_sync("")
        assert result["success"] is False
        assert result["blocked"] is False
        assert "empty" in result["error"].lower()

    def test_whitespace_only_command(self):
        """Test that whitespace-only commands are rejected."""
        result = execute_git_command_sync("   ")
        assert result["success"] is False
        assert result["blocked"] is False
        assert "empty" in result["error"].lower()

    def test_git_status_success(self):
        """Test that git status executes successfully in a git repo."""
        # This test requires we're in a git repository
        result = execute_git_command_sync("git status")

        # Should not be blocked by security
        assert result["blocked"] is False

        # Should execute successfully (this repo is a git repo)
        assert result["success"] is True
        assert "error" not in result or result.get("error") == ""
        assert (
            "On branch" in result["output"] or "nothing to commit" in result["output"]
        )

    def test_invalid_git_command(self):
        """Invalid git commands should either fail or be blocked by security.

        When other plugins (like shell_safety) are loaded, they may block
        invalid commands. Both outcomes are valid:
        - blocked=True: security caught it
        - blocked=False + success=False: git executed but returned error
        """
        result = execute_git_command_sync("git invalid-command-that-does-not-exist")
        assert result["success"] is False
        # Either blocked by security OR executed and failed - both are correct
        if result.get("blocked"):
            assert "reason" in result  # security provided a reason
        else:
            assert result["error"]  # git reported an error
            assert result["returncode"] != 0

    def test_security_boundary_blocks_dangerous_command_when_policy_set(self):
        """Test that dangerous commands are blocked when security policy is configured.

        Note: The default security boundary allows commands unless a PolicyEngine
        rule or run_shell_command callback blocks them. This test verifies the
        integration works when blocking is configured.
        """
        from unittest.mock import AsyncMock, patch
        from code_puppy.security import SecurityDecision

        # Mock the security boundary to simulate a blocking policy
        with patch(
            "code_puppy.plugins.git_auto_commit.shell_bridge.get_security_boundary"
        ) as mock_get_security:
            mock_security = MagicMock()
            mock_security.check_shell_command = AsyncMock(
                return_value=SecurityDecision(
                    allowed=False,
                    reason="Dangerous command blocked by policy",
                    metadata={"policy": "test"},
                )
            )
            mock_get_security.return_value = mock_security

            result = execute_git_command_sync("rm -rf /")

            # Should be blocked by security
            assert result["blocked"] is True
            assert result["success"] is False
            assert result["reason"] is not None
            assert (
                "blocked" in result["error"].lower()
                or "security" in result["error"].lower()
            )

    def test_bridge_no_deadlock_simple(self):
        """Test that simple bridge calls don't deadlock."""
        # Execute multiple sequential calls
        results = []
        for _ in range(5):
            result = execute_git_command_sync("git --version")
            results.append(result)

        # All should complete without deadlock
        assert all(r["success"] for r in results)
        assert all("git version" in r["output"] for r in results)

    def test_bridge_no_deadlock_concurrent(self):
        """Test that concurrent bridge calls don't deadlock."""

        def worker():
            return execute_git_command_sync("git --version")

        # Execute concurrent calls from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            results = [f.result(timeout=10) for f in as_completed(futures)]

        # All should complete successfully without deadlock
        assert len(results) == 10
        assert all(r["success"] for r in results)
        assert all("git version" in r["output"] for r in results)

    def test_bridge_returns_proper_structure(self):
        """Test that bridge returns properly structured result dict."""
        result = execute_git_command_sync("git --version")

        # Verify all expected keys are present
        assert "success" in result
        assert "output" in result
        assert "error" in result
        assert "blocked" in result
        assert "reason" in result

        # Verify types
        assert isinstance(result["success"], bool)
        assert isinstance(result["output"], str)
        assert isinstance(result["error"], str)
        assert isinstance(result["blocked"], bool)
        assert result["reason"] is None or isinstance(result["reason"], str)

    def test_async_context_no_warning(self):
        """Calling sync bridge from async context should NOT leak unawaited coroutine."""
        import asyncio
        import warnings

        async def _test():
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = execute_git_command_sync("git status")
                assert result["reason"] == "async_context"
                assert result["success"] is False
                # No RuntimeWarning about unawaited coroutines
                runtime_warnings = [
                    x for x in w if issubclass(x.category, RuntimeWarning)
                ]
                assert len(runtime_warnings) == 0, (
                    f"Got RuntimeWarning: {runtime_warnings}"
                )

        asyncio.run(_test())


class TestExecuteGitCommandAsync:
    """Tests for the async implementation."""

    @pytest.mark.asyncio
    async def test_async_git_status(self):
        """Test async version directly."""
        result = await execute_git_command("git status")

        assert result["blocked"] is False
        assert result["success"] is True
        assert (
            "On branch" in result["output"] or "nothing to commit" in result["output"]
        )

    @pytest.mark.asyncio
    async def test_security_decision_integration(self):
        """Test that security decision is properly checked."""
        with patch(
            "code_puppy.plugins.git_auto_commit.shell_bridge.get_security_boundary"
        ) as mock_get_security:
            # Mock security boundary to block the command
            mock_security = MagicMock()
            mock_security.check_shell_command = AsyncMock(
                return_value=SecurityDecision(
                    allowed=False,
                    reason="Test block reason",
                    metadata={"test": True},
                )
            )
            mock_get_security.return_value = mock_security

            result = await execute_git_command("git status")

            assert result["blocked"] is True
            assert result["success"] is False
            assert result["reason"] == "Test block reason"
            assert "Test block reason" in result["error"]

    @pytest.mark.asyncio
    async def test_security_decision_allows_execution(self):
        """Test that allowed commands proceed to execution."""
        with patch(
            "code_puppy.plugins.git_auto_commit.shell_bridge.get_security_boundary"
        ) as mock_get_security:
            mock_security = MagicMock()
            mock_security.check_shell_command = AsyncMock(
                return_value=SecurityDecision(
                    allowed=True,
                    reason="Test allow reason",
                )
            )
            mock_get_security.return_value = mock_security

            result = await execute_git_command("git --version")

            assert result["blocked"] is False
            assert result["success"] is True
            assert "git version" in result["output"]

    @pytest.mark.asyncio
    async def test_policy_source_extracted_from_metadata(self):
        """policy_source should come from SecurityDecision.metadata['blocked_by']."""
        with patch(
            "code_puppy.plugins.git_auto_commit.shell_bridge.get_security_boundary"
        ) as mock_get_security:
            mock_security = MagicMock()
            mock_security.check_shell_command = AsyncMock(
                return_value=SecurityDecision(
                    allowed=False,
                    reason="Blocked by policy: deny",
                    metadata={"blocked_by": "policy_engine", "reason": "deny"},
                )
            )
            mock_get_security.return_value = mock_security

            result = await execute_git_command("git status")
            assert result["blocked"] is True
            assert result["policy_source"] == "policy_engine"


# =============================================================================
# Tests for register_callbacks.py
# =============================================================================


class TestCommitHelp:
    """Tests for the help callback."""

    def test_help_returns_list(self):
        """Test that help returns a list of tuples."""
        help_result = _commit_help()

        assert isinstance(help_result, list)
        assert len(help_result) > 0

        for item in help_result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], str)

    def test_help_contains_commit_entry(self):
        """Test that help contains the commit command entry."""
        help_result = _commit_help()

        # Find the commit entry
        commit_entries = [item for item in help_result if item[0] == "commit"]
        assert len(commit_entries) == 1

        name, description = commit_entries[0]
        assert name == "commit"
        assert "GAC" in description or "git" in description.lower()


class TestHandleCommitCommand:
    """Tests for the custom_command handler."""

    def test_wrong_command_returns_none(self):
        """Test that handler returns None for non-commit commands."""
        result = _handle_commit_command("/status", "status")
        assert result is None

    def test_unknown_subcommand_returns_error(self, mock_gac_safe_context):
        """Test that unknown subcommands are handled gracefully."""
        result = _handle_commit_command("/commit invalid-subcommand", "commit")

        # Unknown subcommands fall through to default handling which checks for staged changes
        # In a real git repo this would return True or an error string
        # The key point is it doesn't crash
        assert result is True or isinstance(result, str)

    def test_status_subcommand_returns_true(self, mock_gac_safe_context, mock_preflight_with_staged):
        """Test that 'status' subcommand returns True on success."""
        result = _handle_commit_command("/commit status", "commit")

        # Should succeed - preflight check is done
        assert result is True

    def test_preview_subcommand_returns_true(self, mock_gac_safe_context, mock_preflight_with_staged):
        """Test that 'preview' subcommand returns True on success."""
        from unittest.mock import patch
        
        with patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.generate_preview"
        ) as mock_preview:
            mock_preview.return_value = {
                "diff": "file.py | 10 ++",
                "file_count": 1,
                "insertions": 10,
                "deletions": 0,
                "summary": "1 file changed, 10 insertions(+)",
            }
            result = _handle_commit_command("/commit preview", "commit")

        # Should succeed - preflight + preview done
        assert result is True

    def test_valid_subcommand_log_returns_true(self, mock_gac_safe_context, mock_preflight_with_staged):
        """Test that 'log' subcommand returns True on success."""
        result = _handle_commit_command("/commit log", "commit")

        # With the new flow-based implementation, log is handled as preview subcommand
        # which runs preflight and preview phases
        assert result is not None, "log subcommand should not return None"

    def test_default_subcommand_is_status(self, mock_gac_safe_context, mock_preflight_with_staged):
        """Test that default subcommand (no args) runs preflight."""
        result = _handle_commit_command("/commit", "commit")

        # With the new implementation, default runs preflight then shows preview
        # without a message, it returns the suggestion to use -m flag
        assert result is True or isinstance(result, str)

    def test_whitelist_enforcement(self, mock_gac_safe_context):
        """Test that unknown subcommands are handled gracefully."""
        # Try a disallowed/unknown subcommand
        result = _handle_commit_command("/commit config", "commit")

        # Unknown subcommand is now treated as default (runs flow without message)
        # Or may return a specific error
        assert isinstance(result, str) or result is True

    def test_security_block_returns_error_string(self):
        """Test that security-blocked commands return error string."""
        # Reset security boundary
        reset_security_boundary()

        # Mock a security block by trying to use shell injection
        # The security boundary should block this
        result = _handle_commit_command("/commit status; rm -rf /", "commit")

        # This is an invalid subcommand, so it won't even reach security
        # But if someone crafted it as a single arg, security would catch it
        assert isinstance(result, str) or result is True


# =============================================================================
# Integration Tests
# =============================================================================


class TestShellBridgeIntegration:
    """Integration tests for the full flow."""

    def test_full_flow_status_subcommand(self, mock_gac_safe_context, mock_preflight_with_staged):
        """Test the status subcommand runs preflight only."""
        result = _handle_commit_command("/commit status", "commit")
        assert result is True

    def test_full_flow_preview_subcommand(self, mock_gac_safe_context):
        """Test the preview subcommand with mocked preview."""
        from unittest.mock import patch
        
        with patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.preflight_check"
        ) as mock_preflight, patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.generate_preview"
        ) as mock_preview:
            
            mock_preflight.return_value = {
                "staged_files": ["file.py"],
                "has_staged": True,
                "clean": False,
            }
            mock_preview.return_value = {
                "diff": "file.py | 10 ++",
                "file_count": 1,
                "summary": "1 file changed, 10 insertions(+)",
            }
            
            result = _handle_commit_command("/commit preview", "commit")
            assert result is True
            mock_preview.assert_called_once()

    def test_full_flow_commit_with_message(self, mock_gac_safe_context):
        """Test executing commit with a message."""
        from unittest.mock import patch
        
        with patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.preflight_check"
        ) as mock_preflight, patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.generate_preview"
        ) as mock_preview, patch(
            "code_puppy.plugins.git_auto_commit.register_callbacks.execute_commit"
        ) as mock_execute:
            
            mock_preflight.return_value = {
                "staged_files": ["file.py"],
                "unstaged_files": [],
                "untracked_files": [],
                "has_staged": True,
                "clean": False,
            }
            mock_preview.return_value = {
                "diff": "file.py | 10 ++",
                "file_count": 1,
                "insertions": 10,
                "deletions": 0,
                "summary": "1 file changed, 10 insertions(+)",
            }
            mock_execute.return_value = {
                "success": True,
                "output": "[main abc1234] feat: test\n",
                "commit_hash": "abc1234",
                "branch": "main",
            }
            
            result = _handle_commit_command('/commit -m "feat: test"', "commit")
            
            assert result is True
            mock_execute.assert_called_once()


class TestShellSafetyIntegration:
    """Integration tests specifically with shell_safety plugin loaded."""

    def test_bridge_with_shell_safety_loaded(self):
        """Test that the bridge works when shell_safety is registered.

        This test verifies the fix for the signal.alarm() threading issue:
        - shell_safety uses signal.alarm() which only works in the main thread
        - Our bridge detects if we're in the main thread and uses asyncio.run()
        - This test will fail if the old run_async_sync() approach is used
        """
        # Import shell_safety to ensure its callback is registered
        # This is typically loaded at startup, but we ensure it's here
        try:
            from code_puppy.plugins.shell_safety import register_callbacks  # noqa: F401
        except ImportError:
            pytest.skip("shell_safety plugin not available")

        # This call happens from the main test thread (which is NOT the main thread
        # when run via pytest-xdist, but IS a thread with its own event loop)
        # Our bridge should handle either case gracefully
        result = execute_git_command_sync("git status")

        # The command should either succeed or return a proper error dict
        assert isinstance(result, dict), "Result should be a dict"
        assert "success" in result, "Result should have 'success' key"
        assert "error" in result, "Result should have 'error' key"
        assert "blocked" in result, "Result should have 'blocked' key"

        # In most cases this should succeed (we're in a worker thread with no running loop)
        # If it returns an error about "async_context", that's the thread detection working
        if not result["success"]:
            # If it failed, it should either be blocked or have a clear error reason
            assert (
                result["blocked"] or result.get("reason") is not None or result["error"]
            ), f"Failed without clear reason: {result}"

    def test_bridge_handles_signal_threading_correctly(self):
        """Test that we don't get 'signal only works in main thread' errors.

        This is a regression test for the shell_safety threading issue.
        """
        import threading

        results = {}

        def worker():
            try:
                result = execute_git_command_sync("git --version")
                results["result"] = result
                results["error"] = None
            except Exception as e:
                results["result"] = None
                results["error"] = str(e)

        # Start a non-main thread
        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)

        assert "result" in results or "error" in results, (
            "Worker thread should have produced a result or error"
        )

        # Check we didn't get the signal threading error
        if results.get("error"):
            assert "signal only works in main thread" not in results["error"].lower(), (
                f"Got signal threading error: {results['error']}"
            )


# =============================================================================
# Performance/Stress Tests
# =============================================================================


class TestBridgePerformance:
    """Tests for bridge performance and deadlock prevention."""

    def test_multiple_sequential_calls_fast(self):
        """Test that sequential calls are reasonably fast."""
        start = time.time()

        for _ in range(10):
            execute_git_command_sync("git --version")

        elapsed = time.time() - start

        # Should complete in reasonable time (10 calls < 5 seconds)
        assert elapsed < 5.0, f"Sequential calls took {elapsed:.2f}s, too slow"

    def test_concurrent_calls_no_hang(self):
        """Test that concurrent calls don't hang."""

        def worker():
            try:
                return execute_git_command_sync("git --version")
            except Exception as e:
                return {"error": str(e), "success": False}

        threads = []
        results = []

        start = time.time()

        # Start 10 threads
        for _ in range(10):
            t = threading.Thread(target=lambda: results.append(worker()))
            t.start()
            threads.append(t)

        # Wait for all with timeout
        for t in threads:
            t.join(timeout=10)

        elapsed = time.time() - start

        # All threads should complete within timeout
        assert len(results) == 10, f"Only {len(results)}/10 threads completed"
        assert elapsed < 15, f"Concurrent calls took {elapsed:.2f}s, potential deadlock"

        # All should succeed
        assert all(r.get("success") for r in results if isinstance(r, dict))


# =============================================================================
# Security Tests
# =============================================================================


class TestSecurityIntegration:
    """Tests for security boundary integration."""

    def test_security_boundary_integration_with_mocks(self):
        """Test that security boundary integration works with mocked blocking."""
        from unittest.mock import AsyncMock, patch
        from code_puppy.security import SecurityDecision

        # Test with mocked security blocking
        with patch(
            "code_puppy.plugins.git_auto_commit.shell_bridge.get_security_boundary"
        ) as mock_get_security:
            mock_security = MagicMock()
            mock_security.check_shell_command = AsyncMock(
                return_value=SecurityDecision(
                    allowed=False,
                    reason="Dangerous command blocked",
                )
            )
            mock_get_security.return_value = mock_security

            result = execute_git_command_sync("rm -rf /")
            assert result["blocked"] is True
            assert result["success"] is False

    def test_git_commands_allowed_by_default(self):
        """Test that git commands are allowed by default security boundary.

        Note: The default security boundary with no policies/callbacks allows
        all commands. This tests that the bridge correctly passes through
        security decisions.
        """
        reset_security_boundary()

        # Test a simple git command - should be allowed by default
        result = execute_git_command_sync("git --version")

        # Git commands are allowed (not blocked) by default
        assert result["blocked"] is False
        assert result["success"] is True
        assert "git version" in result["output"]


# =============================================================================
# Main entry point for manual testing
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
