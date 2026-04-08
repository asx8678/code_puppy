"""
Tests for ManagedMCPServer.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.mcp_.managed_server import (
    ManagedMCPServer,
    ServerConfig,
    _expand_env_vars,
)


@pytest.mark.asyncio
async def test_managed_server_header_env_expansion_mocked():
    """Test that headers with safe env vars are expanded correctly (using mocks).

    Headers are now passed directly to MCPServerStreamableHTTP instead of
    creating a custom http_client. This is a workaround for MCP 1.25.0 bug.

    SECURITY: Only safe environment variables from the whitelist are expanded.
    """

    config_dict = {
        "url": "http://test.com",
        "headers": {
            "Authorization": "Bearer ${USER}",  # USER is a safe env var
            "X-Custom": "FixedValue",
        },
    }

    server_config = ServerConfig(
        id="test-id", name="test-server", type="http", config=config_dict
    )

    mock_http_server = MagicMock()

    with (
        patch.dict(os.environ, {"USER": "testuser"}),
        patch(
            "code_puppy.mcp_.managed_server.MCPServerStreamableHTTP",
            return_value=mock_http_server,
        ) as mock_constructor,
    ):
        ManagedMCPServer(server_config)

        # Verify MCPServerStreamableHTTP was called with expanded headers
        mock_constructor.assert_called_once()
        call_kwargs = mock_constructor.call_args.kwargs

        # Headers should be passed directly and safe env vars expanded
        assert call_kwargs["headers"]["Authorization"] == "Bearer testuser"
        assert call_kwargs["headers"]["X-Custom"] == "FixedValue"
        assert call_kwargs["url"] == "http://test.com"


def test_expand_env_vars_safe_only():
    """Test env var expansion only expands safe/sanctioned variables.

    SECURITY: Only well-known safe environment variables are expanded
    to prevent command injection through malicious environment values.
    """
    # Safe variables that SHOULD be expanded
    safe_env = {
        "HOME": "/home/testuser",
        "USER": "testuser",
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/bash",
    }

    # Unsafe variables that should NOT be expanded
    unsafe_env = {
        "MALICIOUS_VAR": "$(rm -rf /)",
        "API_KEY": "secret123",  # Not in safe list
    }

    with patch.dict(os.environ, {**safe_env, **unsafe_env}):
        # Safe vars - should be expanded
        assert _expand_env_vars("$HOME") == "/home/testuser"
        assert _expand_env_vars("${USER}") == "testuser"
        assert _expand_env_vars("Shell: $SHELL") == "Shell: /bin/bash"

        # Unsafe/unknown vars - should NOT be expanded (prevent injection)
        assert _expand_env_vars("$MALICIOUS_VAR") == "$MALICIOUS_VAR"
        assert _expand_env_vars("$API_KEY") == "$API_KEY"

        # Plain string (no vars)
        assert _expand_env_vars("plain text") == "plain text"


def test_expand_env_vars_dict():
    """Test env var expansion in dicts with safe variables only."""
    with patch.dict(os.environ, {"HOME": "/home/test", "PATH": "/usr/bin"}):
        input_dict = {
            "home_dir": "$HOME",  # Safe - will expand
            "exec_path": "${PATH}",  # Safe - will expand
            "static": "no-change",  # No expansion needed
            "api_key": "$API_KEY",  # Not safe - won't expand
        }
        result = _expand_env_vars(input_dict)
        assert result["home_dir"] == "/home/test"
        assert result["exec_path"] == "/usr/bin"
        assert result["static"] == "no-change"
        assert result["api_key"] == "$API_KEY"  # Not expanded - not in safe list


def test_expand_env_vars_list():
    """Test env var expansion in lists with safe variables only."""
    with patch.dict(os.environ, {"HOME": "/home", "TMP": "/tmp"}):
        input_list = ["$HOME", "static", "${TMP}"]
        result = _expand_env_vars(input_list)
        assert result == ["/home", "static", "/tmp"]


def test_expand_env_vars_nested():
    """Test env var expansion in nested structures with safe variables only."""
    with patch.dict(os.environ, {"HOME": "/home"}):
        input_nested = {
            "paths": {"home": "$HOME"},
            "args": ["--home=$HOME"],
        }
        result = _expand_env_vars(input_nested)
        assert result["paths"]["home"] == "/home"
        assert result["args"] == ["--home=/home"]


def test_expand_env_vars_non_string():
    """Test that non-string values pass through unchanged."""
    assert _expand_env_vars(42) == 42
    assert _expand_env_vars(3.14) == 3.14
    assert _expand_env_vars(True) is True
    assert _expand_env_vars(None) is None
