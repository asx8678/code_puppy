"""Tests for install_hints module.

Tests platform-aware install hint generation for missing external tools.
"""

import sys
from unittest.mock import patch

from code_puppy.utils.install_hints import (
    install_hint,
    format_missing_tool_message,
    _TOOL_PACKAGES,
    _FALLBACK_URLS,
)


class TestInstallHint:
    """Tests for install_hint function."""

    def test_install_hint_returns_something_reasonable(self):
        """install_hint('ripgrep') returns something on current platform."""
        result = install_hint("ripgrep")
        assert isinstance(result, str)
        assert len(result) > 0
        # Should either be an install command or a fallback URL
        assert "install" in result.lower() or "http" in result

    def test_unknown_tool_returns_manual_message(self):
        """Unknown tool returns manual install message."""
        result = install_hint("unknown_tool_xyz")
        assert "Install unknown_tool_xyz manually" in result

    def test_darwin_with_brew(self):
        """macOS with brew returns brew install command."""
        with patch.object(sys, "platform", "darwin"):
            with patch("shutil.which", lambda x: x == "brew"):
                result = install_hint("ripgrep")
                assert result == "brew install ripgrep"

    def test_darwin_with_port(self):
        """macOS with port (no brew) returns port install command."""

        def mock_which(cmd):
            # Only port is available (brew not found)
            return cmd if cmd == "port" else None

        with patch.object(sys, "platform", "darwin"):
            with patch("shutil.which", mock_which):
                result = install_hint("jq")
                assert result == "port install jq"

    def test_linux_with_apt_get(self):
        """Linux with apt-get returns sudo apt-get install."""
        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", lambda x: x == "apt-get"):
                result = install_hint("ripgrep")
                assert result == "sudo apt-get install ripgrep"

    def test_linux_with_dnf(self):
        """Linux with dnf (no apt-get) returns sudo dnf install."""

        def mock_which(cmd):
            # Only dnf is available (apt-get not found)
            return cmd if cmd == "dnf" else None

        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", mock_which):
                result = install_hint("ripgrep")
                assert result == "sudo dnf install ripgrep"

    def test_win32_with_choco(self):
        """Windows with choco returns choco install."""

        def mock_which(cmd):
            # Only choco is available (winget not found)
            return cmd if cmd == "choco" else None

        with patch.object(sys, "platform", "win32"):
            with patch("shutil.which", mock_which):
                result = install_hint("ripgrep")
                assert result == "choco install ripgrep"

    def test_win32_with_winget(self):
        """Windows with winget (no choco) returns winget install."""
        with patch.object(sys, "platform", "win32"):
            with patch("shutil.which", lambda x: x == "winget"):
                result = install_hint("ripgrep")
                # Winget uses full package name
                assert "winget install" in result
                assert "BurntSushi" in result

    def test_fd_debian_package_name(self):
        """fd uses fd-find on Debian/Ubuntu systems."""
        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", lambda x: x == "apt-get"):
                result = install_hint("fd")
                assert result == "sudo apt-get install fd-find"

    def test_all_package_managers_absent_returns_fallback_url(self):
        """When no package managers found, returns fallback URL."""
        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", return_value=None):
                result = install_hint("ripgrep")
                assert result == _FALLBACK_URLS["ripgrep"]

    def test_empty_string_tool_name(self):
        """Empty string tool name returns manual install."""
        result = install_hint("")
        assert "manually" in result.lower() or "http" in result

    def test_fd_fallback_url(self):
        """fd returns fallback URL when no package manager."""
        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", return_value=None):
                result = install_hint("fd")
                assert result == _FALLBACK_URLS["fd"]

    def test_jq_fallback_url(self):
        """jq returns fallback URL when no package manager."""
        with patch.object(sys, "platform", "linux"):
            with patch("shutil.which", return_value=None):
                result = install_hint("jq")
                assert result == _FALLBACK_URLS["jq"]


class TestFormatMissingToolMessage:
    """Tests for format_missing_tool_message function."""

    def test_basic_message(self):
        """Basic message includes tool name and hint."""
        result = format_missing_tool_message("ripgrep")
        assert "ripgrep" in result
        assert "not installed" in result.lower()
        assert "install" in result.lower()

    def test_message_with_context(self):
        """Message with context includes context string."""
        result = format_missing_tool_message(
            "ripgrep", context="needed for grep searches"
        )
        assert "ripgrep" in result
        assert "needed for grep searches" in result
        assert "install" in result.lower()

    def test_message_contains_install_hint(self):
        """Message contains the install hint result."""
        hint = install_hint("ripgrep")
        result = format_missing_tool_message("ripgrep")
        # The hint should be at the end of the message
        assert hint in result


class TestToolPackages:
    """Tests for _TOOL_PACKAGES registry."""

    def test_ripgrep_has_expected_package_managers(self):
        """ripgrep entry has expected package managers."""
        rg_packages = _TOOL_PACKAGES.get("ripgrep", {})
        expected_managers = ["brew", "apt-get", "choco", "winget", "cargo"]
        for pm in expected_managers:
            assert pm in rg_packages, f"ripgrep should support {pm}"

    def test_fd_has_debian_name_mapping(self):
        """fd entry maps to fd-find for apt-get."""
        fd_packages = _TOOL_PACKAGES.get("fd", {})
        assert fd_packages.get("apt-get") == "fd-find"

    def test_jq_has_common_package_managers(self):
        """jq entry has common package managers."""
        jq_packages = _TOOL_PACKAGES.get("jq", {})
        assert "brew" in jq_packages
        assert "apt-get" in jq_packages


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_end_to_end_flow(self):
        """Full flow from tool detection to formatted message."""
        # Simulate detecting ripgrep is missing
        tool_name = "ripgrep"
        context = "required for searching code"

        # Get the formatted message
        message = format_missing_tool_message(tool_name, context=context)

        # Verify message structure
        assert tool_name in message
        assert context in message
        assert "install" in message.lower()

        # The hint portion should be a valid hint
        hint = install_hint(tool_name)
        assert hint in message
