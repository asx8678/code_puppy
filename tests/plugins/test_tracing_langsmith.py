"""Tests for the tracing_langsmith plugin.

Tests cover:
- Graceful degradation when langsmith not installed
- Graceful skip when LANGSMITH_API_KEY not set
- Mock client testing for span creation and nesting
- warn_once hint behavior
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def clear_langsmith_env():
    """Clear LANGSMITH environment variables."""
    # Store original values
    orig_api_key = os.environ.pop("LANGSMITH_API_KEY", None)
    orig_project = os.environ.pop("LANGSMITH_PROJECT", None)
    orig_base_url = os.environ.pop("LANGSMITH_BASE_URL", None)

    yield

    # Restore original values
    if orig_api_key is not None:
        os.environ["LANGSMITH_API_KEY"] = orig_api_key
    if orig_project is not None:
        os.environ["LANGSMITH_PROJECT"] = orig_project
    if orig_base_url is not None:
        os.environ["LANGSMITH_BASE_URL"] = orig_base_url


@pytest.fixture
def mock_langsmith_client():
    """Create a mock LangSmith client for testing."""
    client = MagicMock()
    client.create_run = MagicMock()
    client.update_run = MagicMock()
    client.create_feedback = MagicMock()
    return client


def _get_fresh_module_with_mock_client(mock_client=None, env_vars=None):
    """Helper to get a fresh module with injected mock client.
    
    Args:
        mock_client: Mock client to inject
        env_vars: Dict of env vars to set before import (e.g., {"LANGSMITH_API_KEY": "test"})
    """
    # Set env vars before import if provided
    if env_vars:
        for key, value in env_vars.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    # Remove module from cache to force reimport
    module_name = "code_puppy.plugins.tracing_langsmith.register_callbacks"
    if module_name in sys.modules:
        del sys.modules[module_name]

    # Import fresh
    from code_puppy.plugins.tracing_langsmith import register_callbacks as reg_module

    # Reset state and inject mock client
    reg_module._reset_state()
    if mock_client:
        reg_module._set_test_client(mock_client)

    return reg_module


# =============================================================================
# Test: Graceful skip when env var not set
# =============================================================================


class TestEnvVarNotSet:
    """Plugin should be silent and have zero overhead when env var not set."""

    def test_is_plugin_active_returns_false_without_env(self):
        """_is_plugin_active should return False when no API key."""
        # Clear all env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Reimport without API key
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={"LANGSMITH_API_KEY": None}
        )

        assert reg_module._is_plugin_active() is False

    def test_callbacks_unchanged_without_env(self):
        """When LANGSMITH_API_KEY is not set, the module should not enable tracing."""
        # Clear all env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Import with no API key
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={"LANGSMITH_API_KEY": None}
        )

        # Verify API key is not set at module level
        assert reg_module._get_langsmith_api_key() is None

        # Callbacks should exist but not be registered (tested by _is_plugin_active)
        assert not reg_module._is_plugin_active()


# =============================================================================
# Test: Graceful degradation when langsmith not installed
# =============================================================================


class TestLangsmithNotInstalled:
    """Plugin should gracefully handle missing langsmith package."""

    def test_warn_once_fires_when_package_missing(self):
        """When langsmith package is missing, warn_once should hint at installation."""
        # Clear any existing env vars first
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        from code_puppy.async_utils import clear_warn_once_history

        clear_warn_once_history()

        # Patch resolve_variable to simulate missing langsmith package
        with patch("code_puppy.plugins.tracing_langsmith.register_callbacks.resolve_variable") as mock_resolve:
            mock_resolve.side_effect = ImportError("No module named 'langsmith'")
            
            with patch("code_puppy.plugins.tracing_langsmith.register_callbacks.warn_once") as mock_warn_once:
                reg_module = _get_fresh_module_with_mock_client(
                    env_vars={"LANGSMITH_API_KEY": "test-key"}
                )

                # Reset the warned flag to ensure warning fires on first client access
                reg_module._warned_missing = False
                
                # Try to get client to trigger warning
                client = reg_module._get_langsmith_client()
                assert client is None

                # warn_once should have been called with the hint
                mock_warn_once.assert_called_once()
                call_args = mock_warn_once.call_args
                assert call_args[0][0] == "langsmith_missing"  # key
                assert "pip install langsmith" in call_args[0][1]  # message

    def test_returns_none_when_package_missing(self):
        """_get_langsmith_client should return None when package missing."""
        # Clear any existing env vars first
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        with patch("code_puppy.plugins.tracing_langsmith.register_callbacks.warn_once"):
            client = reg_module._get_langsmith_client()
            assert client is None


# =============================================================================
# Test: Mock client - span creation and nesting
# =============================================================================


class TestWithMockClient:
    """Test span creation and nesting with a mock LangSmith client."""

    def test_agent_run_start_creates_trace(self, mock_langsmith_client):
        """agent_run_start should create a LangSmith run."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # Trigger the callback
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Verify create_run was called
        assert mock_langsmith_client.create_run.called
        call_kwargs = mock_langsmith_client.create_run.call_args[1]
        assert call_kwargs["name"] == "test-agent"
        assert call_kwargs["run_type"] == "chain"
        assert call_kwargs["session_id"] == "sess-123"
        assert call_kwargs["inputs"]["model"] == "gpt-4"

    def test_agent_run_end_updates_trace(self, mock_langsmith_client):
        """agent_run_end should update the LangSmith run."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # First start a trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Then end it
        asyncio.run(
            reg_module._on_agent_run_end(
                "test-agent",
                "gpt-4",
                session_id="sess-123",
                success=True,
                response_text="Hello, world!",
            )
        )

        # Verify update_run was called
        assert mock_langsmith_client.update_run.called
        call_kwargs = mock_langsmith_client.update_run.call_args[1]
        assert call_kwargs["outputs"]["success"] is True
        assert "Hello, world!" in call_kwargs["outputs"]["response_preview"]

    def test_tool_span_nesting(self, mock_langsmith_client):
        """Tool spans should be nested under agent runs."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # Mock run context for correlation
        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "parent-run-123"

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Start agent run
            asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

            # Tool call start
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

            # Verify tool run created with parent_run_id
            tool_calls = [
                c
                for c in mock_langsmith_client.create_run.call_args_list
                if c[1].get("run_type") == "tool" or c[1].get("name") == "list_files"
            ]
            assert len(tool_calls) >= 1

            # Tool call end
            asyncio.run(
                reg_module._on_post_tool_call(
                    "list_files",
                    {"directory": "/tmp"},
                    ["file1.txt", "file2.txt"],
                    150.0,
                )
            )

            # Verify update was called for tool
            assert mock_langsmith_client.update_run.called

    def test_session_id_correlation(self, mock_langsmith_client):
        """session_id should be used as trace correlation ID."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        session_id = "my-custom-session-456"

        # Start trace with custom session_id
        asyncio.run(reg_module._on_agent_run_start("agent-1", "gpt-4", session_id=session_id))

        # Verify session_id used in create_run
        call_kwargs = mock_langsmith_client.create_run.call_args[1]
        assert call_kwargs["session_id"] == session_id

    def test_error_handling_in_agent_run(self, mock_langsmith_client):
        """Errors in agent runs should be captured in trace."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # Start and end with error
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        test_error = ValueError("Something went wrong")
        asyncio.run(
            reg_module._on_agent_run_end(
                "test-agent",
                "gpt-4",
                session_id="sess-123",
                success=False,
                error=test_error,
            )
        )

        # Verify error was recorded
        call_kwargs = mock_langsmith_client.update_run.call_args[1]
        assert call_kwargs["outputs"]["success"] is False
        assert "error" in call_kwargs["outputs"]
        assert "Something went wrong" in call_kwargs["error"]

    def test_stream_event_logging(self, mock_langsmith_client):
        """Stream events should be logged to the trace."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # Start trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Send stream event
        event_data = {"type": "token", "delta": "Hello", "content": "Hello world"}
        asyncio.run(reg_module._on_stream_event("token", event_data, agent_session_id="sess-123"))

        # Feedback/event should have been attempted if method exists
        # Just verify no exception was raised


# =============================================================================
# Test: Edge cases and error handling
# =============================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_no_active_trace_for_tool_call(self, mock_langsmith_client):
        """Tool calls without active run context should be gracefully skipped."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # No run context - tool call should not fail
        with patch("code_puppy.run_context.get_current_run_context", return_value=None):
            # Should not raise
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

    def test_missing_session_id_handling(self, mock_langsmith_client):
        """Missing session_id should result in generated UUID."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        # Start without session_id
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id=None))

        # Verify create_run was still called with some session_id
        assert mock_langsmith_client.create_run.called
        call_kwargs = mock_langsmith_client.create_run.call_args[1]
        # Should have generated a UUID
        assert call_kwargs["session_id"] is not None
        # Verify it looks like a UUID
        try:
            uuid.UUID(call_kwargs["session_id"])
        except ValueError:
            pytest.fail("session_id should be a valid UUID")

    def test_cleanup_on_trace_end(self, mock_langsmith_client):
        """Trace context should be cleaned up after agent_run_end."""
        # Clear and set env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )

        session_id = "test-session-789"

        # Start trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id=session_id))

        # Verify trace is active
        assert session_id in reg_module._active_traces

        # End trace
        asyncio.run(reg_module._on_agent_run_end("test-agent", "gpt-4", session_id=session_id, success=True))

        # Verify trace was cleaned up
        assert session_id not in reg_module._active_traces


# =============================================================================
# Test: Zero overhead when disabled
# =============================================================================


class TestZeroOverhead:
    """Verify zero overhead when plugin is disabled."""

    def test_quick_return_without_api_key(self):
        """Callbacks should return immediately when API key not set."""
        # Clear all env vars
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Import fresh without API key
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={"LANGSMITH_API_KEY": None}
        )

        # Ensure no API key at module level
        assert reg_module._get_langsmith_api_key() is None

        # All callbacks should return None quickly (no client init)
        start = time.time()
        result = asyncio.run(reg_module._on_agent_run_start("agent", "model"))
        assert result is None
        assert time.time() - start < 0.01  # Should be nearly instant

        start = time.time()
        result = asyncio.run(reg_module._on_agent_run_end("agent", "model"))
        assert result is None
        assert time.time() - start < 0.01

        start = time.time()
        result = asyncio.run(reg_module._on_pre_tool_call("tool", {}))
        assert result is None
        assert time.time() - start < 0.01

        start = time.time()
        result = asyncio.run(reg_module._on_post_tool_call("tool", {}, None, 100.0))
        assert result is None
        assert time.time() - start < 0.01

        start = time.time()
        result = asyncio.run(reg_module._on_stream_event("event", {}))
        assert result is None
        assert time.time() - start < 0.01


# =============================================================================
# Test: Environment variable handling
# =============================================================================


class TestEnvironmentVariables:
    """Test environment variable configuration."""

    def test_custom_project_name(self, mock_langsmith_client):
        """LANGSMITH_PROJECT should be used as project name."""
        # Clear any existing env vars first
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Set env vars before import
        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_PROJECT": "my-custom-project",
            },
        )

        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Verify project name used
        call_kwargs = mock_langsmith_client.create_run.call_args[1]
        assert call_kwargs["project_name"] == "my-custom-project"

    def test_custom_base_url(self, mock_langsmith_client):
        """LANGSMITH_BASE_URL should be passed to client."""
        # Clear any existing env vars first
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        MockClientClass = MagicMock(return_value=mock_langsmith_client)

        with patch(
            "code_puppy.plugins.tracing_langsmith.register_callbacks.resolve_variable",
            return_value=MockClientClass,
        ):
            # Reimport with custom base URL
            reg_module = _get_fresh_module_with_mock_client(
                env_vars={
                    "LANGSMITH_API_KEY": "test-key",
                    "LANGSMITH_BASE_URL": "https://custom.langsmith.com/api",
                }
            )

            # Force client initialization
            reg_module._get_langsmith_client()

            # Verify client was created with custom URL
            MockClientClass.assert_called_once()
            call_kwargs = MockClientClass.call_args[1]
            assert call_kwargs["api_url"] == "https://custom.langsmith.com/api"

    def test_default_project_name(self, mock_langsmith_client):
        """Default project name should be 'default'."""
        # Clear any existing env vars first
        for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Reimport without setting LANGSMITH_PROJECT
        reg_module = _get_fresh_module_with_mock_client(
            mock_langsmith_client,
            env_vars={"LANGSMITH_API_KEY": "test-key"},  # No LANGSMITH_PROJECT
        )

        # Verify default project
        assert reg_module._get_langsmith_project() == "default"
