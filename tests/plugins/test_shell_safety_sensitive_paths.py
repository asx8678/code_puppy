"""Regression tests for shell safety sensitive path bypass (bd-60).

These tests verify that commands targeting sensitive paths are NOT auto-allowed
by the regex classifier, ensuring the security gap stays closed.

See bd-59 for the original fix that created shared sensitive path definitions.
See bd-60 for the regression test requirement.
"""

import pytest
from code_puppy.plugins.shell_safety.regex_classifier import classify_command


class TestSensitivePathRegression:
    """Regression tests for shell safety sensitive path bypass (bd-60).
    
    Verifies that commands targeting sensitive paths (macOS /private/etc,
    device files, root user home, other user SSH keys) are classified as
    ambiguous or higher (not risk='none'), ensuring they get LLM review
    instead of being auto-allowed.
    """

    # =========================================================================
    # macOS /private/etc paths (system credential files)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat /private/etc/passwd",
        "head /private/etc/master.passwd",
        "grep root /private/etc/shadow",
        "cat '/private/etc/passwd'",
        'cat "/private/etc/passwd"',
        "less /private/etc/sudoers",
        "tail -f /private/etc/passwd",
        "cat < /private/etc/passwd",
    ])
    def test_macos_private_etc_not_auto_allowed(self, command: str) -> None:
        """macOS /private/etc paths must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # Device file paths (disk access)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat /dev/sda",
        "grep foo /dev/sda",
        "dd if=/dev/sda of=/tmp/disk.img",
        "head /dev/sda1",
        "strings /dev/nvme0n1",
        "cat '/dev/sda'",
        'cat "/dev/sda"',
        "xxd /dev/sdb",
    ])
    def test_device_files_not_auto_allowed(self, command: str) -> None:
        """Direct device file access must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # Root user tilde expansion (~root)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat ~root/.ssh/id_rsa",
        "grep foo ~root/.ssh/config",
        "less ~root/.bashrc",
        "cat ~root/.ssh/authorized_keys",
        "head ~root/.ssh/id_rsa.pub",
        "grep -r secret ~root/.ssh/",
    ])
    def test_root_tilde_expansion_not_auto_allowed(self, command: str) -> None:
        """Root user home directory access via tilde must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # Other user SSH keys (~other/.ssh)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat ~admin/.ssh/id_rsa",
        "grep foo ~nobody/.ssh/authorized_keys",
        "cat ~www-data/.ssh/config",
        "head ~ubuntu/.ssh/id_ed25519",
        "less ~postgres/.ssh/known_hosts",
        "cat '~admin/.ssh/id_rsa'",
        'cat "~admin/.ssh/id_rsa"',
        "grep -i private ~deploy/.ssh/id_rsa",
        "cat ~user/.ssh/id_dsa",
    ])
    def test_other_user_ssh_not_auto_allowed(self, command: str) -> None:
        """Other users' SSH keys via tilde expansion must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # Regular /etc paths (system credential files)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat /etc/shadow",
        "cat /etc/passwd",
        "cat /etc/sudoers",
        "head /etc/master.passwd",
    ])
    def test_etc_sensitive_files_not_auto_allowed(self, command: str) -> None:
        """Standard /etc credential files must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # User home SSH paths (own SSH)
    # =========================================================================

    @pytest.mark.parametrize("command", [
        "cat ~/.ssh/id_rsa",
        "grep foo ~/.ssh/config",
        "cat ~/.ssh/id_ed25519",
    ])
    def test_user_ssh_keys_not_auto_allowed(self, command: str) -> None:
        """User's own SSH keys must not be auto-allowed."""
        result = classify_command(command)
        assert result.risk != "none", (
            f"Command should not be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )

    # =========================================================================
    # Positive tests - legitimate commands that SHOULD be allowed
    # =========================================================================

    @pytest.mark.parametrize("command", [
        # Project-relative paths
        "cat ./src/main.py",
        "grep foo ./src/main.py",
        "head ./README.md",
        "less ./docs/guide.md",
        "cat src/main.py",
        "grep function src/utils.py",
        # Temporary/build paths
        "cat /tmp/build/output.txt",
        "grep error /tmp/logs/app.log",
        "head /tmp/test_results.xml",
        # Home directory non-sensitive files
        "cat ~/documents/notes.txt",
        "grep todo ~/notes.md",
        # Current directory traversal
        "cat ../sibling/file.txt",
        "grep pattern ../../parent/file.py",
        # Valid grep in project files
        "grep -r TODO .",
        "grep foo *.py",
    ])
    def test_legitimate_commands_allowed(self, command: str) -> None:
        """Legitimate project-local commands should be auto-allowed (risk='none')."""
        result = classify_command(command)
        assert result.risk == "none", (
            f"Command should be auto-allowed: {command}\n"
            f"Got risk='{result.risk}', reasoning='{result.reasoning}'"
        )


class TestSensitivePathSpecificScenarios:
    """Specific bypass scenarios that were tested during bd-60 development."""

    def test_quoted_macos_private_etc_blocked(self) -> None:
        """Quoted /private/etc paths must still be blocked."""
        # Single quotes
        result = classify_command("cat '/private/etc/passwd'")
        assert result.risk != "none"
        # Double quotes
        result = classify_command('cat "/private/etc/passwd"')
        assert result.risk != "none"

    def test_quoted_device_files_blocked(self) -> None:
        """Quoted device file paths must still be blocked."""
        result = classify_command("cat '/dev/sda'")
        assert result.risk != "none"
        result = classify_command('cat "/dev/sda"')
        assert result.risk != "none"

    def test_grep_with_device_file_blocked(self) -> None:
        """grep with device files must not be auto-allowed."""
        result = classify_command("grep foo /dev/sda")
        assert result.risk != "none"

    def test_dd_with_device_file_blocked(self) -> None:
        """dd with device input file must be blocked (high/critical risk)."""
        result = classify_command("dd if=/dev/sda of=/tmp/disk.img")
        # dd with device files should be critical due to disk read pattern
        assert result.risk in ["critical", "high", "ambiguous"], (
            f"dd with device file should be blocked, got: {result.risk}"
        )

    def test_other_user_variations_blocked(self) -> None:
        """Various other user tilde patterns must be blocked."""
        users = ["admin", "nobody", "www-data", "ubuntu", "postgres", "deploy", "user"]
        for user in users:
            cmd = f"cat ~{user}/.ssh/id_rsa"
            result = classify_command(cmd)
            assert result.risk != "none", (
                f"~{user} SSH access should be blocked: {cmd}"
            )


class TestRiskLevels:
    """Verify specific risk levels for different sensitive path types."""

    def test_device_dd_is_blocked_or_ambiguous(self) -> None:
        """dd from device files should be at least ambiguous (not auto-allowed)."""
        result = classify_command("dd if=/dev/sda of=/tmp/disk.img")
        # The command should NOT be auto-allowed (not risk='none')
        # It can be critical, high, or ambiguous - all are acceptable
        assert result.risk in ["critical", "high", "ambiguous"], (
            f"dd from device should not be auto-allowed, got: {result.risk}"
        )

    def test_sensitive_grep_is_ambiguous(self) -> None:
        """grep on sensitive paths should be ambiguous (needs LLM review)."""
        result = classify_command("grep root /etc/passwd")
        assert result.risk in ["ambiguous", "medium", "high"], (
            f"grep on /etc/passwd should not be auto-allowed, got: {result.risk}"
        )

    def test_sensitive_cat_is_blocked_or_ambiguous(self) -> None:
        """cat on sensitive paths should be blocked or ambiguous."""
        result = classify_command("cat /etc/shadow")
        # Should be at least ambiguous, possibly blocked
        assert result.risk in ["critical", "high", "ambiguous"], (
            f"cat /etc/shadow should not be auto-allowed, got: {result.risk}"
        )
