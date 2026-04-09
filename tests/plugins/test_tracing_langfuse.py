"""Tests for the tracing_langfuse plugin.

Tests cover:
- Graceful degradation when langfuse not installed
- Graceful skip when LANGFUSE keys not set
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
def clear_langfuse_env():
    """Clear LangFuse environment variables."""
    # Store original values
    orig_public_key = os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    orig_secret_key = os.environ.pop("LANGFUSE_SECRET_KEY", None)
    orig_host = os.environ.pop("LANGFUSE_HOST", None)
    orig_project = os.environ.pop("LANGFUSE_PROJECT", None)

    yield

    # Restore original values
    if orig_public_key is not None:
        os.environ["LANGFUSE_PUBLIC_KEY"] = orig_public_key
    if orig_secret_key is not None:
        os.environ["LANGFUSE_SECRET_KEY"] = orig_secret_key
    if orig_host is not None:
        os.environ["LANGFUSE_HOST"] = orig_host
    if orig_project is not None:
        os.environ["LANGFUSE_PROJECT"] = orig_project


@pytest.fixture
def mock_langfuse_client():
    """Create a mock LangFuse client for testing."""
    # Create mock trace object
    mock_trace = MagicMock()
    mock_trace.generation = MagicMock(return_value=MagicMock())
    mock_trace.span = MagicMock(return_value=MagicMock())
    mock_trace.event = MagicMock()
    mock_trace.update = MagicMock()

    # Create mock client
    client = MagicMock()
    client.trace = MagicMock(return_value=mock_trace)
    client.flush = MagicMock()

    return client


def _get_fresh_module_with_mock_client(mock_client=None, env_vars=None):
    """Helper to get a fresh module with injected mock client.

    Args:
        mock_client: Mock client to inject
        env_vars: Dict of env vars to set before import (e.g., {"LANGFUSE_PUBLIC_KEY": "test"})
    """
    # Clear all LangFuse-related env vars first to ensure isolation
    for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
        os.environ.pop(key, None)

    # Set env vars before import if provided
    if env_vars:
        for key, value in env_vars.items():
            if value is not None:
                os.environ[key] = value

    # Remove module and parent package from cache to force reimport
    # Must clear parent packages too since they cache child imports
    modules_to_clear = [
        "code_puppy.plugins.tracing_langfuse.register_callbacks",
        "code_puppy.plugins.tracing_langfuse",
    ]
    for module_name in modules_to_clear:
        if module_name in sys.modules:
            del sys.modules[module_name]

    # Import fresh
    from code_puppy.plugins.tracing_langfuse import register_callbacks as reg_module

    # Reset state and inject mock client
    reg_module._reset_state()
    if mock_client:
        reg_module._set_test_client(mock_client)

    return reg_module


# =============================================================================
# Test: Graceful skip when env var not set
# =============================================================================


class TestEnvVarNotSet:
    """Plugin should be silent and have zero overhead when env vars not set."""

    def test_is_plugin_active_returns_false_without_env(self):
        """_is_plugin_active should return False when no keys."""
        # Clear all env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        # Reimport without keys
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": None,
                "LANGFUSE_SECRET_KEY": None,
            }
        )

        assert reg_module._is_plugin_active() is False

    def test_is_plugin_active_returns_false_with_partial_env(self):
        """_is_plugin_active should return False when only one key is set."""
        # Clear all env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        # Reimport with only public key
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": None,
            }
        )

        assert reg_module._is_plugin_active() is False

        # Reimport with only secret key
        reg_module = _get_fresh_module_with_mock_client(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": None,
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        assert reg_module._is_plugin_active() is False

    def test_callbacks_unchanged_without_env(self):
        """When LangFuse keys are not set, the module should not enable tracing."""
        # Import with no keys (env vars are cleared by helper)
        reg_module = _get_fresh_module_with_mock_client()

        # Verify keys are not set at module level
        assert reg_module.LANGFUSE_PUBLIC_KEY is None
        assert reg_module.LANGFUSE_SECRET_KEY is None

        # Callbacks should exist but not be registered (tested by _is_plugin_active)
        assert not reg_module._is_plugin_active()


# =============================================================================
# Test: Graceful degradation when langfuse not installed
# =============================================================================


class TestLangfuseNotInstalled:
    """Plugin should gracefully handle missing langfuse package."""

    def test_warn_once_fires_when_package_missing(self):
        """When langfuse package is missing, warn_once should hint at installation."""
        # Clear any existing env vars first
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        from code_puppy.async_utils import clear_warn_once_history

        clear_warn_once_history()

        reg_module = _get_fresh_module_with_mock_client(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Reset the warned flag to ensure warning fires
        reg_module._warned_missing = False

        # Clear warn_once history again after module import
        clear_warn_once_history()

        # Capture the actual warning
        warning_messages = []
        original_warn_once = reg_module.warn_once

        def capture_warn_once(key, message, logger=None):
            warning_messages.append((key, message))

        with patch.object(reg_module, 'warn_once', side_effect=capture_warn_once):
            # Try to get client to trigger warning
            client = reg_module._get_langfuse_client()
            assert client is None

        # Verify warning was recorded
        assert len(warning_messages) == 1
        assert warning_messages[0][0] == "langfuse_missing"
        assert "pip install langfuse" in warning_messages[0][1]

    def test_returns_none_when_package_missing(self):
        """_get_langfuse_client should return None when package missing."""
        # Clear any existing env vars first
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        with patch("code_puppy.async_utils.warn_once"):
            client = reg_module._get_langfuse_client()
            assert client is None


# =============================================================================
# Test: Mock client - span creation and nesting
# =============================================================================


class TestWithMockClient:
    """Test span creation and nesting with a mock LangFuse client."""

    def test_agent_run_start_creates_trace(self, mock_langfuse_client):
        """agent_run_start should create a LangFuse trace."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Trigger the callback
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Verify trace was created
        assert mock_langfuse_client.trace.called
        call_kwargs = mock_langfuse_client.trace.call_args[1]
        assert call_kwargs["name"] == "test-agent"
        assert call_kwargs["id"] == "sess-123"
        assert call_kwargs["session_id"] == "sess-123"
        assert call_kwargs["metadata"]["model"] == "gpt-4"

        # Verify generation was created
        mock_trace = mock_langfuse_client.trace.return_value
        assert mock_trace.generation.called

    def test_agent_run_end_updates_trace(self, mock_langfuse_client):
        """agent_run_end should update the LangFuse trace and flush."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
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

        # Verify trace update was called
        mock_trace = mock_langfuse_client.trace.return_value
        assert mock_trace.update.called

        # Verify flush was called
        assert mock_langfuse_client.flush.called

    def test_tool_span_nesting(self, mock_langfuse_client):
        """Tool spans should be nested under agent runs."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Mock run context for correlation
        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "parent-run-123"
        mock_run_ctx.session_id = "sess-123"

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Start agent run
            asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

            # Get the mock trace
            mock_trace = mock_langfuse_client.trace.return_value

            # Tool call start
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

            # Verify span was created on the trace
            assert mock_trace.span.called
            span_call_kwargs = mock_trace.span.call_args[1]
            assert span_call_kwargs["name"] == "list_files"

            # Get the mock span
            mock_span = mock_trace.span.return_value

            # Tool call end
            asyncio.run(
                reg_module._on_post_tool_call(
                    "list_files",
                    {"directory": "/tmp"},
                    ["file1.txt", "file2.txt"],
                    150.0,
                )
            )

            # Verify span end was called
            assert mock_span.end.called

    def test_session_id_correlation(self, mock_langfuse_client):
        """session_id should be used as trace correlation ID."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        session_id = "my-custom-session-456"

        # Start trace with custom session_id
        asyncio.run(reg_module._on_agent_run_start("agent-1", "gpt-4", session_id=session_id))

        # Verify session_id used in trace creation
        call_kwargs = mock_langfuse_client.trace.call_args[1]
        assert call_kwargs["id"] == session_id
        assert call_kwargs["session_id"] == session_id

    def test_error_handling_in_agent_run(self, mock_langfuse_client):
        """Errors in agent runs should be captured in trace."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
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

        # Verify generation was ended with error status
        mock_trace = mock_langfuse_client.trace.return_value
        mock_generation = mock_trace.generation.return_value
        assert mock_generation.end.called
        end_call_kwargs = mock_generation.end.call_args[1]
        assert end_call_kwargs["status"] == "error"

    def test_stream_event_logging(self, mock_langfuse_client):
        """Stream events should be logged to the trace."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Start trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # Get mock trace
        mock_trace = mock_langfuse_client.trace.return_value

        # Send stream event
        event_data = {"type": "token", "delta": "Hello", "content": "Hello world"}
        asyncio.run(reg_module._on_stream_event("token", event_data, agent_session_id="sess-123"))

        # Verify event was called
        assert mock_trace.event.called
        event_call_kwargs = mock_trace.event.call_args[1]
        assert event_call_kwargs["name"] == "stream:token"
        assert "metadata" in event_call_kwargs


# =============================================================================
# Test: Edge cases and error handling
# =============================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_no_active_trace_for_tool_call(self, mock_langfuse_client):
        """Tool calls without active run context should be gracefully skipped."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # No run context - tool call should not fail
        with patch("code_puppy.run_context.get_current_run_context", return_value=None):
            # Should not raise
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

    def test_no_active_trace_for_session(self, mock_langfuse_client):
        """Tool calls with session_id but no active trace should be gracefully skipped."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Run context with session_id but no active trace
        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "run-123"
        mock_run_ctx.session_id = "unknown-session"

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Should not raise even though trace doesn't exist
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

    def test_missing_session_id_handling(self, mock_langfuse_client):
        """Missing session_id should result in generated UUID."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Start without session_id
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id=None))

        # Verify trace was still called with some id
        assert mock_langfuse_client.trace.called
        call_kwargs = mock_langfuse_client.trace.call_args[1]
        # Should have generated a UUID
        assert call_kwargs["id"] is not None
        # Verify it looks like a UUID
        try:
            uuid.UUID(call_kwargs["id"])
        except ValueError:
            pytest.fail("trace id should be a valid UUID")

    def test_cleanup_on_trace_end(self, mock_langfuse_client):
        """Trace context should be cleaned up after agent_run_end."""
        # Clear and set env vars
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
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

    def test_quick_return_without_env(self):
        """Callbacks should return immediately when env vars not set."""
        # Import fresh without env vars (cleared by helper)
        reg_module = _get_fresh_module_with_mock_client()

        # Ensure no keys at module level
        assert reg_module.LANGFUSE_PUBLIC_KEY is None
        assert reg_module.LANGFUSE_SECRET_KEY is None

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
# Test: Client Exception Handling
# =============================================================================


class TestClientExceptionHandling:
    """Test handling when LangFuse client throws exceptions."""

    def test_exception_during_trace_start(self, mock_langfuse_client):
        """Exception during trace start should be caught gracefully."""
        # Make trace throw exception
        mock_langfuse_client.trace.side_effect = Exception("API unavailable")

        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Should not raise exception
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # trace was called but exception was caught
        assert mock_langfuse_client.trace.called

    def test_exception_during_trace_end(self, mock_langfuse_client):
        """Exception during trace end should be caught gracefully."""
        mock_trace = MagicMock()
        mock_trace.generation = MagicMock(return_value=MagicMock())
        mock_trace.span = MagicMock(return_value=MagicMock())
        mock_trace.event = MagicMock()
        # Make update throw
        mock_trace.update.side_effect = Exception("Connection timeout")

        mock_langfuse_client.trace.return_value = mock_trace

        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Start trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # End trace - should not raise even though update fails
        asyncio.run(reg_module._on_agent_run_end("test-agent", "gpt-4", session_id="sess-123", success=True))

        # update was called but exception was caught
        assert mock_trace.update.called

    def test_exception_during_tool_span(self, mock_langfuse_client):
        """Exception during tool span creation should be caught."""
        mock_trace = MagicMock()
        mock_trace.generation = MagicMock(return_value=MagicMock())
        # Make span throw
        mock_trace.span.side_effect = Exception("Span creation failed")
        mock_trace.event = MagicMock()
        mock_trace.update = MagicMock()

        mock_langfuse_client.trace.return_value = mock_trace

        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "parent-run-123"
        mock_run_ctx.session_id = "sess-123"

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Start agent run
            asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

            # Tool call - should not raise
            asyncio.run(reg_module._on_pre_tool_call("list_files", {"directory": "/tmp"}))

    def test_exception_during_flush(self, mock_langfuse_client):
        """Exception during flush should be caught gracefully."""
        mock_langfuse_client.flush.side_effect = Exception("Flush failed")

        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # Start trace
        asyncio.run(reg_module._on_agent_run_start("test-agent", "gpt-4", session_id="sess-123"))

        # End trace - should not raise even though flush fails
        asyncio.run(reg_module._on_agent_run_end("test-agent", "gpt-4", session_id="sess-123", success=True))

        # flush was called but exception was caught
        assert mock_langfuse_client.flush.called


# =============================================================================
# Test: Concurrent Session Handling
# =============================================================================


class TestConcurrentSessions:
    """Test handling of multiple concurrent sessions."""

    def test_multiple_concurrent_sessions(self, mock_langfuse_client):
        """Multiple concurrent sessions should be tracked independently."""
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        sessions = [f"concurrent-session-{i}" for i in range(5)]

        # Start all sessions
        for session_id in sessions:
            asyncio.run(reg_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Verify all tracked
        assert len(reg_module._active_traces) == 5

        # End all sessions
        for session_id in sessions:
            asyncio.run(reg_module._on_agent_run_end("agent", "model", session_id=session_id, success=True))

        # Verify all cleaned up
        assert len(reg_module._active_traces) == 0

    def test_same_session_id_reuse(self, mock_langfuse_client):
        """Reusing same session_id should replace previous trace."""
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
            os.environ.pop(key, None)

        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        session_id = "reused-session"

        # Start first trace
        asyncio.run(reg_module._on_agent_run_start("agent-1", "model", session_id=session_id))

        # Verify trace is tracked
        assert session_id in reg_module._active_traces
        assert reg_module._active_traces[session_id]["agent_name"] == "agent-1"

        # Start second trace with same session_id - should replace
        asyncio.run(reg_module._on_agent_run_start("agent-2", "model", session_id=session_id))

        # New trace should replace old one
        assert len(reg_module._active_traces) == 1
        assert reg_module._active_traces[session_id]["agent_name"] == "agent-2"

        # Verify trace was called twice (once for each agent start)
        assert mock_langfuse_client.trace.call_count == 2


# =============================================================================
# Test: Environment variable handling
# =============================================================================


class TestEnvironmentVariables:
    """Test environment variable configuration."""

    def test_custom_host(self, mock_langfuse_client):
        """LANGFUSE_HOST should be used as host."""
        # Reimport with custom host - verify host is set at module level
        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
                "LANGFUSE_HOST": "https://custom.langfuse.com",
            }
        )

        # Verify custom host is set at module level
        assert reg_module.LANGFUSE_HOST == "https://custom.langfuse.com"

        # Verify client can be initialized
        client = reg_module._get_langfuse_client()
        assert client is mock_langfuse_client

    def test_default_host(self, mock_langfuse_client):
        """Default host should be https://cloud.langfuse.com."""
        # Reimport without setting LANGFUSE_HOST (cleared by helper)
        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            },
        )

        # Verify default host
        assert reg_module.LANGFUSE_HOST == "https://cloud.langfuse.com"

    def test_custom_project_name_in_metadata(self, mock_langfuse_client):
        """LANGFUSE_PROJECT should be included in trace metadata if set."""
        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
                "LANGFUSE_PROJECT": "my-custom-project",
            },
        )

        # Verify project is tracked at module level
        assert reg_module.LANGFUSE_PROJECT == "my-custom-project"


# =============================================================================
# Test: Dual tracing with LangSmith
# =============================================================================


class TestDualTracing:
    """Test that LangFuse can run simultaneously with LangSmith."""

    def test_dual_tracing_independent(self, mock_langfuse_client):
        """Both plugins should be able to be active independently."""
        # Clear all env vars including LangSmith ones
        for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
                    "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
            os.environ.pop(key, None)

        # Only set LangFuse keys with mock client
        reg_module = _get_fresh_module_with_mock_client(
            mock_langfuse_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        # LangFuse should be active (with mock client)
        assert reg_module._is_plugin_active() is True

        # Verify both keys are set
        assert reg_module.LANGFUSE_PUBLIC_KEY == "test-public"
        assert reg_module.LANGFUSE_SECRET_KEY == "test-secret"
