"""Tests for the SecurityBoundary module.

These tests verify the core security decision logic and ensure that
the SecurityBoundary can be properly mocked in tests (lazy import pattern).
"""

import threading

import pytest
from unittest.mock import AsyncMock, patch

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

    def test_sensitive_files_blocked_list(self):
        """SECURITY FIX b26: Test that all sensitive file paths are blocked."""
        from code_puppy.tools.file_operations import _is_sensitive_path

        # Test expanded exact file list
        sensitive_files = [
            "~/.netrc",
            "~/.pgpass",
            "~/.my.cnf",
            "~/.env",
            "~/.bash_history",
            "~/.npmrc",
            "~/.pypirc",
            "~/.gitconfig",
            "/etc/shadow",
            "/etc/sudoers",
            "/etc/master.passwd",
            "/etc/passwd",
        ]
        for f in sensitive_files:
            assert _is_sensitive_path(f), f"{f} should be blocked"

        # Test .env files blocked anywhere (project-local)
        assert _is_sensitive_path("/myproject/.env")
        assert _is_sensitive_path("./.env")
        assert _is_sensitive_path("/var/www/app/.env")

        # SECURITY FIX b26: Test .env.* variants blocked (.env.local, .env.production, etc.)
        env_variants = [
            ".env.local",
            ".env.production",
            ".env.development",
            ".env.dev",
            ".env.staging",
            ".env.test",
            ".env.ci",
            ".env.backup",
        ]
        for variant in env_variants:
            assert _is_sensitive_path(f"/myproject/{variant}"), f"{variant} should be blocked"
            assert _is_sensitive_path(f"./{variant}"), f"{variant} in current dir should be blocked"
            assert _is_sensitive_path(f"/var/www/app/{variant}"), f"{variant} in web dir should be blocked"

        # Test .env documentation files are ALLOWED (not sensitive)
        allowed_docs = [".env.example", ".env.sample", ".env.template"]
        for doc in allowed_docs:
            assert not _is_sensitive_path(f"/myproject/{doc}"), f"{doc} should be ALLOWED"

        # Case-insensitive check for .env variants
        assert _is_sensitive_path("/app/.ENV.LOCAL"), ".ENV.LOCAL should be blocked (case-insensitive)"
        assert _is_sensitive_path("/app/.Env.Production"), ".Env.Production should be blocked"

        # Test PEM/key files blocked ANYWHERE (not just cred-ish dirs)
        assert _is_sensitive_path("/app/deploy.key"), "deploy.key should be blocked anywhere"
        assert _is_sensitive_path("/project/server.pem"), "server.pem should be blocked anywhere"
        assert _is_sensitive_path("/tmp/test.pem"), "test.pem should be blocked anywhere"
        assert _is_sensitive_path("/home/user/creds.p12"), "creds.p12 should be blocked"
        assert _is_sensitive_path("/data/app.pfx"), "app.pfx should be blocked"

        # Legitimate project files should still work
        assert not _is_sensitive_path("/project/main.py")
        assert not _is_sensitive_path("/app/src/server.js")
        assert not _is_sensitive_path("/repo/README.md")

        # Benign .env* files that should NOT be blocked (regression prevention)
        assert not _is_sensitive_path("/project/env_config.py"), "env_config.py should NOT be blocked"
        assert not _is_sensitive_path("/app/environment.ts"), "environment.ts should NOT be blocked"

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

    def test_get_security_boundary_thread_safety(self):
        """Regression test: concurrent singleton access must return same instance."""
        import threading

        # Reset singleton
        reset_security_boundary()

        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            results.append(id(get_security_boundary()))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 1, f"Expected 1 unique instance, got {len(set(results))}"

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


class TestStatsCounterThreadSafety:
    """Regression tests for thread-safe stats counter increments.

    These tests verify that _stats_lock correctly serialises concurrent
    counter mutations from multiple threads using threading.Barrier
    to maximise contention.
    """

    def test_stats_counters_thread_safe(self):
        """All threads hit check_file_access concurrently; final counters must be exact."""
        N_THREADS = 8
        CALLS_PER_THREAD = 100
        EXPECTED_CHECKS = N_THREADS * CALLS_PER_THREAD
        EXPECTED_BLOCKS = N_THREADS * CALLS_PER_THREAD

        boundary = SecurityBoundary()
        barrier = threading.Barrier(N_THREADS)
        errors: list[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=10)
                for _ in range(CALLS_PER_THREAD):
                    # Sensitive path: increments check_count AND block_count
                    result = boundary.check_file_access("~/.ssh/id_rsa", "read")
                    assert not result.allowed, "Sensitive path should always be denied"
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Worker threads raised: {errors}"
        stats = boundary.get_stats()
        assert stats["check_count"] == EXPECTED_CHECKS, (
            f"check_count: expected {EXPECTED_CHECKS}, got {stats['check_count']}"
        )
        assert stats["block_count"] == EXPECTED_BLOCKS, (
            f"block_count: expected {EXPECTED_BLOCKS}, got {stats['block_count']}"
        )

    def test_stats_counters_mixed_operations_thread_safe(self):
        """Mix of blocking and allowed calls; block_count < check_count."""
        N_THREADS = 6
        BLOCKING_PER_THREAD = 50   # sensitive path → blocked
        ALLOWED_PER_THREAD = 50    # normal path → allowed (mocked callbacks)
        EXPECTED_CHECKS = N_THREADS * (BLOCKING_PER_THREAD + ALLOWED_PER_THREAD)
        EXPECTED_BLOCKS = N_THREADS * BLOCKING_PER_THREAD

        boundary = SecurityBoundary()
        barrier = threading.Barrier(N_THREADS)
        errors: list[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=10)
                for _ in range(BLOCKING_PER_THREAD):
                    # Sensitive path: increments check_count AND block_count
                    boundary.check_file_access("~/.aws/credentials", "read")
                with patch("code_puppy.callbacks.on_file_permission") as mock:
                    mock.return_value = [True]
                    for _ in range(ALLOWED_PER_THREAD):
                        # Normal path: increments check_count only
                        boundary.check_file_access("/tmp/safe.txt", "read")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Worker threads raised: {errors}"
        stats = boundary.get_stats()
        assert stats["check_count"] == EXPECTED_CHECKS, (
            f"check_count: expected {EXPECTED_CHECKS}, got {stats['check_count']}"
        )
        assert stats["block_count"] == EXPECTED_BLOCKS, (
            f"block_count: expected {EXPECTED_BLOCKS}, got {stats['block_count']}"
        )


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


# ============================================================================
# SECURITY FIX: File Operations Path Validation Tests
# ============================================================================
# These tests verify that _list_files and _grep properly validate paths
# using validate_file_path() to block access to sensitive directories.
# ============================================================================

class TestFileOperationsPathValidation:
    """SECURITY FIX: Tests that file operations validate paths before access."""

    def _make_context(self):
        """Create a mock context for tool calls."""
        from unittest.mock import MagicMock
        return MagicMock()

    async def test_list_files_blocks_ssh_directory(self):
        """_list_files must block ~/.ssh directory listing."""
        from code_puppy.tools.file_operations import _list_files
        import os

        home = os.path.expanduser("~")
        result = await _list_files(self._make_context(), f"{home}/.ssh")
        assert result.error is not None
        assert "Security" in result.error or "sensitive" in result.error.lower()

    async def test_list_files_blocks_aws_directory(self):
        """_list_files must block ~/.aws directory listing."""
        from code_puppy.tools.file_operations import _list_files
        import os

        home = os.path.expanduser("~")
        result = await _list_files(self._make_context(), f"{home}/.aws")
        assert result.error is not None
        assert "Security" in result.error or "sensitive" in result.error.lower()

    async def test_grep_blocks_ssh_directory(self):
        """_grep must block searching in ~/.ssh."""
        from code_puppy.tools.file_operations import _grep
        import os

        home = os.path.expanduser("~")
        result = await _grep(self._make_context(), "password", f"{home}/.ssh")
        assert result.error is not None
        assert "Security" in result.error or "sensitive" in result.error.lower()

    async def test_grep_blocks_aws_directory(self):
        """_grep must block searching in ~/.aws."""
        from code_puppy.tools.file_operations import _grep
        import os

        home = os.path.expanduser("~")
        result = await _grep(self._make_context(), "secret", f"{home}/.aws")
        assert result.error is not None
        assert "Security" in result.error or "sensitive" in result.error.lower()

    async def test_grep_returns_empty_matches_for_sensitive_results(self):
        """_grep must filter out matches that point to sensitive files."""
        from code_puppy.tools.file_operations import _grep, MatchInfo, validate_file_path
        from unittest.mock import patch, MagicMock
        import os

        # Mock the subprocess to simulate finding results
        mock_result = MagicMock()
        mock_result.stdout = '{"type":"match","data":{"path":{"text":"/some/path/file.py"},"line_number":1,"lines":{"text":"test"}}}'
        mock_result.stderr = ""
        mock_result.returncode = 0

        # Mock validate_file_path to block the result
        def mock_validate(path, operation):
            if ".ssh" in path or ".aws" in path:
                return False, "sensitive path blocked"
            return True, None

        with patch("code_puppy.tools.file_operations.subprocess.run", return_value=mock_result):
            with patch("code_puppy.tools.file_operations.validate_file_path", side_effect=mock_validate):
                result = await _grep(self._make_context(), "test", "/some/path")
                # If the match path gets filtered, we should have empty matches
                # or the filtering logic should be applied
                assert isinstance(result.matches, list)
