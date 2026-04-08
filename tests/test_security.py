"""Tests for the SecurityBoundary module.

These tests verify the core security decision logic and ensure that
the SecurityBoundary can be properly mocked in tests (lazy import pattern).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from code_puppy.security import (
    SecurityDecision,
    SecurityBoundary,
    get_security_boundary,
    set_security_boundary,
    reset_security_boundary,
)


@pytest.fixture(autouse=True)
def reset_boundary_fixture():
    """Reset the security boundary singleton before each test."""
    reset_security_boundary()
    yield
    reset_security_boundary()


class TestSecurityDecision:
    """Tests for the SecurityDecision dataclass."""

    def test_bool_returns_allowed_field_true(self):
        """Test that __bool__ returns the allowed field when True."""
        decision = SecurityDecision(allowed=True, reason="Allowed")
        assert bool(decision) is True
        assert decision.allowed is True
        assert decision.reason == "Allowed"

    def test_bool_returns_allowed_field_false(self):
        """Test that __bool__ returns the allowed field when False."""
        decision = SecurityDecision(allowed=False, reason="Denied")
        assert bool(decision) is False
        assert decision.allowed is False
        assert decision.reason == "Denied"

    def test_bool_with_default_reason(self):
        """Test SecurityDecision with default None reason."""
        decision = SecurityDecision(allowed=True)
        assert bool(decision) is True
        assert decision.reason is None
        assert decision.metadata == {}


class TestSecurityBoundaryShellCommand:
    """Tests for check_shell_command method."""

    async def test_empty_command_denied(self):
        """Test that empty command returns denied decision."""
        boundary = SecurityBoundary()
        result = await boundary.check_shell_command("")
        assert result.allowed is False
        assert "empty" in result.reason.lower()

    async def test_whitespace_only_command_denied(self):
        """Test that whitespace-only command returns denied."""
        boundary = SecurityBoundary()
        result = await boundary.check_shell_command("   \t\n  ")
        assert result.allowed is False
        assert "empty" in result.reason.lower()

    async def test_command_allowed_with_mocked_callbacks(self):
        """Test that command is allowed when callbacks return no blocks."""
        boundary = SecurityBoundary()

        # Patch the callbacks at the module level (lazy import makes this possible)
        with patch("code_puppy.callbacks.on_run_shell_command", new_callable=AsyncMock) as mock:
            mock.return_value = []  # No callbacks blocked

            result = await boundary.check_shell_command("ls -la")

        assert result.allowed is True
        assert "passed all security checks" in result.reason.lower()
        mock.assert_awaited_once()

    async def test_command_blocked_by_plugin(self):
        """Test that command is blocked when a plugin returns blocked=True."""
        boundary = SecurityBoundary()

        with patch("code_puppy.callbacks.on_run_shell_command", new_callable=AsyncMock) as mock:
            mock.return_value = [{"blocked": True, "reasoning": "Dangerous command detected"}]

            result = await boundary.check_shell_command("rm -rf /")

        assert result.allowed is False
        assert "dangerous" in result.reason.lower()
        mock.assert_awaited_once()


class TestSecurityBoundaryFileAccess:
    """Tests for check_file_access method."""

    def test_empty_path_denied(self):
        """Test that empty path returns denied decision."""
        boundary = SecurityBoundary()
        result = boundary.check_file_access("", "read")
        assert result.allowed is False
        assert "empty" in result.reason.lower()

    def test_sensitive_ssh_key_path_denied(self):
        """Test that access to SSH keys is denied."""
        boundary = SecurityBoundary()
        result = boundary.check_file_access("~/.ssh/id_rsa", "read")
        assert result.allowed is False
        assert "sensitive" in result.reason.lower()

    def test_sensitive_aws_credentials_denied(self):
        """Test that access to AWS credentials is denied."""
        boundary = SecurityBoundary()
        result = boundary.check_file_access("~/.aws/credentials", "read")
        assert result.allowed is False
        assert "sensitive" in result.reason.lower()

    def test_sensitive_pem_file_in_secrets_dir_denied(self):
        """Test that .pem files in secrets directories are denied."""
        boundary = SecurityBoundary()
        result = boundary.check_file_access("/app/secrets/cert.pem", "read")
        assert result.allowed is False
        assert "sensitive" in result.reason.lower()

    def test_file_access_allowed_with_mocked_callbacks(self):
        """Test that file access is allowed when callbacks permit it."""
        boundary = SecurityBoundary()

        with patch("code_puppy.callbacks.on_file_permission") as mock:
            mock.return_value = [True]  # Callbacks allowed

            result = boundary.check_file_access("/tmp/test.txt", "read")

        assert result.allowed is True
        mock.assert_called_once()

    def test_file_access_denied_by_plugin(self):
        """Test that file access is denied when a plugin returns False."""
        boundary = SecurityBoundary()

        with patch("code_puppy.callbacks.on_file_permission") as mock:
            mock.return_value = [False]  # Callback denied

            result = boundary.check_file_access("/tmp/test.txt", "write")

        assert result.allowed is False
        assert "denied by security plugin" in result.reason.lower()
        mock.assert_called_once()


class TestSecurityBoundaryStats:
    """Tests for stats and reset methods."""

    async def test_get_stats_initially_zero(self):
        """Test that stats are initially zero."""
        boundary = SecurityBoundary()
        stats = boundary.get_stats()
        assert stats["check_count"] == 0
        assert stats["block_count"] == 0

    async def test_get_stats_tracks_checks(self):
        """Test that stats track security checks."""
        boundary = SecurityBoundary()

        # Check sensitive path (should be denied via sensitive path check)
        boundary.check_file_access("~/.ssh/id_rsa", "read")
        stats = boundary.get_stats()
        assert stats["check_count"] == 1
        assert stats["block_count"] == 1

        # Check another sensitive path (AWS credentials)
        boundary.check_file_access("~/.aws/credentials", "read")
        stats = boundary.get_stats()
        assert stats["check_count"] == 2
        assert stats["block_count"] == 2

    def test_reset_stats_clears_counts(self):
        """Test that reset_stats clears the counters."""
        boundary = SecurityBoundary()

        # Perform some checks
        boundary.check_file_access("~/.ssh/id_rsa", "read")
        assert boundary.get_stats()["check_count"] == 1

        # Reset and verify
        boundary.reset_stats()
        stats = boundary.get_stats()
        assert stats["check_count"] == 0
        assert stats["block_count"] == 0


class TestSecurityBoundarySingleton:
    """Tests for the singleton behavior of SecurityBoundary."""

    def test_get_security_boundary_returns_same_instance(self):
        """Test that get_security_boundary returns the same singleton instance."""
        boundary1 = get_security_boundary()
        boundary2 = get_security_boundary()
        assert boundary1 is boundary2

    def test_get_security_boundary_creates_new_after_reset(self):
        """Test that a new instance is created after reset."""
        boundary1 = get_security_boundary()
        reset_security_boundary()
        boundary2 = get_security_boundary()
        assert boundary1 is not boundary2

    def test_set_security_boundary_sets_custom_instance(self):
        """Test that set_security_boundary sets a custom instance."""
        custom_boundary = SecurityBoundary()
        set_security_boundary(custom_boundary)
        retrieved = get_security_boundary()
        assert retrieved is custom_boundary

    def test_reset_security_boundary_creates_fresh_instance(self):
        """Test that reset creates a fresh instance."""
        # Get initial instance
        initial = get_security_boundary()
        initial._check_count = 42  # Modify state

        # Reset and get new instance
        reset_security_boundary()
        fresh = get_security_boundary()

        # Should be different instance with clean state
        assert fresh is not initial
        assert fresh._check_count == 0


class TestLazyImportPatchability:
    """Tests that verify the lazy import pattern enables proper mocking."""

    async def test_shell_command_callbacks_can_be_mocked(self):
        """Verify that on_run_shell_command can be mocked at call time."""
        # This test would fail if imports were at module level
        # because the mock wouldn't affect the already-imported reference
        with patch("code_puppy.callbacks.on_run_shell_command", new_callable=AsyncMock) as mock:
            mock.return_value = [{"blocked": True, "reasoning": "Mocked"}]

            boundary = SecurityBoundary()
            result = await boundary.check_shell_command("echo hello")

            # If lazy import works, the mock was called
            mock.assert_awaited_once()
            assert result.allowed is False
            assert result.reason == "Mocked"

    def test_file_permission_callbacks_can_be_mocked(self):
        """Verify that on_file_permission can be mocked at call time."""
        with patch("code_puppy.callbacks.on_file_permission") as mock:
            mock.return_value = [False]

            boundary = SecurityBoundary()
            result = boundary.check_file_access("/tmp/test.txt", "write")

            # If lazy import works, the mock was called
            mock.assert_called_once()
            assert result.allowed is False
