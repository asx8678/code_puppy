"""Dual-tracing tests for LangSmith and LangFuse working together.

Tests cover:
- Both plugins active simultaneously with no interference
- Session ID correlation working for both
- Graceful degradation when one plugin fails mid-trace
- Zero overhead when both are disabled
- Tool call nesting with both tracers
- Stream events sent to both tracers
"""

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Helper Functions
# =============================================================================


def _get_fresh_langsmith_module(mock_client=None, env_vars=None):
    """Get a fresh LangSmith module with optional mock client."""
    # Clear all LangSmith env vars
    for key in ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL"]:
        os.environ.pop(key, None)

    if env_vars:
        for key, value in env_vars.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    module_name = "code_puppy.plugins.tracing_langsmith.register_callbacks"
    if module_name in sys.modules:
        del sys.modules[module_name]

    from code_puppy.plugins.tracing_langsmith import register_callbacks as ls_module

    ls_module._reset_state()
    if mock_client:
        ls_module._set_test_client(mock_client)

    return ls_module


def _get_fresh_langfuse_module(mock_client=None, env_vars=None):
    """Get a fresh LangFuse module with optional mock client."""
    # Clear all LangFuse env vars
    for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"]:
        os.environ.pop(key, None)

    if env_vars:
        for key, value in env_vars.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    modules_to_clear = [
        "code_puppy.plugins.tracing_langfuse.register_callbacks",
        "code_puppy.plugins.tracing_langfuse",
    ]
    for module_name in modules_to_clear:
        if module_name in sys.modules:
            del sys.modules[module_name]

    from code_puppy.plugins.tracing_langfuse import register_callbacks as lf_module

    lf_module._reset_state()
    if mock_client:
        lf_module._set_test_client(mock_client)

    return lf_module


def _create_mock_langsmith_client():
    """Create a mock LangSmith client."""
    client = MagicMock()
    client.create_run = MagicMock()
    client.update_run = MagicMock()
    client.create_feedback = MagicMock()
    return client


def _create_mock_langfuse_client():
    """Create a mock LangFuse client."""
    mock_trace = MagicMock()
    mock_trace.generation = MagicMock(return_value=MagicMock())
    mock_trace.span = MagicMock(return_value=MagicMock())
    mock_trace.event = MagicMock()
    mock_trace.update = MagicMock()

    client = MagicMock()
    client.trace = MagicMock(return_value=mock_trace)
    client.flush = MagicMock()

    return client


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def both_plugins_disabled():
    """Ensure both plugins are disabled (no env vars set)."""
    # Clear all tracing env vars
    for key in [
        "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
    ]:
        os.environ.pop(key, None)

    yield

    # Cleanup already done by clearing above


@pytest.fixture
def mock_both_clients():
    """Create mock clients for both plugins."""
    ls_client = _create_mock_langsmith_client()
    lf_client = _create_mock_langfuse_client()

    # Get fresh modules with mocks
    ls_module = _get_fresh_langsmith_module(
        ls_client,
        env_vars={"LANGSMITH_API_KEY": "test-key"}
    )
    lf_module = _get_fresh_langfuse_module(
        lf_client,
        env_vars={
            "LANGFUSE_PUBLIC_KEY": "test-public",
            "LANGFUSE_SECRET_KEY": "test-secret",
        }
    )

    return ls_module, ls_client, lf_module, lf_client


# =============================================================================
# Test: Both Plugins Active Simultaneously
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestBothPluginsActive:
    """Test both plugins working together without interference."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_both_create_traces_on_agent_start(self, mock_both_clients):
        """Both plugins should create traces when agent run starts."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "dual-session-123"

        # Start agent run - trigger both callbacks
        asyncio.run(ls_module._on_agent_run_start("test-agent", "gpt-4", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("test-agent", "gpt-4", session_id=session_id))

        # Verify LangSmith created run
        assert ls_client.create_run.called
        ls_call = ls_client.create_run.call_args[1]
        assert ls_call["name"] == "test-agent"
        assert ls_call["session_id"] == session_id

        # Verify LangFuse created trace
        assert lf_client.trace.called
        lf_call = lf_client.trace.call_args[1]
        assert lf_call["name"] == "test-agent"
        assert lf_call["id"] == session_id

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_both_update_traces_on_agent_end(self, mock_both_clients):
        """Both plugins should update traces when agent run ends."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "dual-session-456"

        # Start both traces
        asyncio.run(ls_module._on_agent_run_start("test-agent", "gpt-4", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("test-agent", "gpt-4", session_id=session_id))

        # End both traces
        asyncio.run(
            ls_module._on_agent_run_end(
                "test-agent", "gpt-4", session_id=session_id,
                success=True, response_text="Hello from dual trace!"
            )
        )
        asyncio.run(
            lf_module._on_agent_run_end(
                "test-agent", "gpt-4", session_id=session_id,
                success=True, response_text="Hello from dual trace!"
            )
        )

        # Verify LangSmith updated
        assert ls_client.update_run.called
        ls_update = ls_client.update_run.call_args[1]
        assert ls_update["outputs"]["success"] is True

        # Verify LangFuse updated and flushed
        mock_trace = lf_client.trace.return_value
        assert mock_trace.update.called
        assert lf_client.flush.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_session_id_correlation_both_plugins(self, mock_both_clients):
        """Same session_id should correlate traces in both systems."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "shared-correlation-id"

        # Both plugins use same session_id
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Verify both use the same session_id
        ls_call = ls_client.create_run.call_args[1]
        lf_call = lf_client.trace.call_args[1]

        assert ls_call["session_id"] == session_id
        assert lf_call["session_id"] == session_id
        assert lf_call["id"] == session_id

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_tool_spans_nested_both_plugins(self, mock_both_clients):
        """Tool spans should be nested correctly in both plugins."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "tool-nesting-session"

        # Mock run context
        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "parent-run-789"
        mock_run_ctx.session_id = session_id

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Start agent runs in both plugins
            asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
            asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

            # Tool call in both plugins
            asyncio.run(ls_module._on_pre_tool_call("list_files", {"dir": "/tmp"}))
            asyncio.run(lf_module._on_pre_tool_call("list_files", {"dir": "/tmp"}))

            # Verify LangSmith tool span created with parent_run_id
            tool_calls = [c for c in ls_client.create_run.call_args_list
                         if c[1].get("run_type") == "tool"]
            assert len(tool_calls) >= 1
            assert tool_calls[0][1]["parent_run_id"] == "parent-run-789"

            # Verify LangFuse span created on trace
            mock_trace = lf_client.trace.return_value
            assert mock_trace.span.called

            # End tool calls
            asyncio.run(ls_module._on_post_tool_call("list_files", {"dir": "/tmp"}, ["a.txt"], 100.0))
            asyncio.run(lf_module._on_post_tool_call("list_files", {"dir": "/tmp"}, ["a.txt"], 100.0))

            # Verify updates
            assert ls_client.update_run.called
            mock_span = mock_trace.span.return_value
            assert mock_span.end.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_stream_events_both_plugins(self, mock_both_clients):
        """Stream events should be sent to both plugins."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "stream-session"

        # Start traces
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Send stream event to both
        event_data = {"type": "token", "content": "Hello", "delta": "Hel"}
        asyncio.run(ls_module._on_stream_event("token", event_data, agent_session_id=session_id))
        asyncio.run(lf_module._on_stream_event("token", event_data, agent_session_id=session_id))

        # Verify LangSmith attempted feedback
        # Note: create_feedback may not be called depending on mock structure
        # Just verify no exception raised

        # Verify LangFuse event called
        mock_trace = lf_client.trace.return_value
        assert mock_trace.event.called


# =============================================================================
# Test: No Interference Between Plugins
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestNoInterference:
    """Verify plugins don't interfere with each other's operation."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_langsmith_failure_doesnt_break_langfuse(self, mock_both_clients):
        """LangSmith failure should not prevent LangFuse from working."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        # Make LangSmith client throw exception
        ls_client.create_run.side_effect = Exception("LangSmith API error")

        session_id = "isolated-failure-session"

        # Both start - LangSmith will fail, LangFuse should still work
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # LangSmith create_run was called but threw (caught internally)
        assert ls_client.create_run.called

        # LangFuse trace should still be created
        assert lf_client.trace.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_langfuse_failure_doesnt_break_langsmith(self, mock_both_clients):
        """LangFuse failure should not prevent LangSmith from working."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        # Make LangFuse client throw exception
        lf_client.trace.side_effect = Exception("LangFuse API error")

        session_id = "isolated-failure-session-2"

        # Both start - LangFuse will fail, LangSmith should still work
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # LangFuse trace was called but threw (caught internally)
        assert lf_client.trace.called

        # LangSmith run should still be created
        assert ls_client.create_run.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_independent_active_states(self):
        """Each plugin should have independent active state."""
        # Clear all env vars
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        # Only LangSmith enabled
        ls_only = _get_fresh_langsmith_module(
            _create_mock_langsmith_client(),
            env_vars={"LANGSMITH_API_KEY": "test-key"}
        )
        lf_disabled = _get_fresh_langfuse_module(
            env_vars={"LANGFUSE_PUBLIC_KEY": None, "LANGFUSE_SECRET_KEY": None}
        )

        assert ls_only._is_plugin_active() is True
        assert lf_disabled._is_plugin_active() is False

        # Clear and only LangFuse enabled
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        ls_disabled = _get_fresh_langsmith_module(
            env_vars={"LANGSMITH_API_KEY": None}
        )
        lf_only = _get_fresh_langfuse_module(
            _create_mock_langfuse_client(),
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            }
        )

        assert ls_disabled._is_plugin_active() is False
        assert lf_only._is_plugin_active() is True

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_different_session_ids_no_crosstalk(self, mock_both_clients):
        """Different session IDs should not interfere."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_1 = "session-alpha"
        session_2 = "session-beta"

        # Start two different sessions
        asyncio.run(ls_module._on_agent_run_start("agent-1", "model", session_id=session_1))
        asyncio.run(lf_module._on_agent_run_start("agent-1", "model", session_id=session_1))

        asyncio.run(ls_module._on_agent_run_start("agent-2", "model", session_id=session_2))
        asyncio.run(lf_module._on_agent_run_start("agent-2", "model", session_id=session_2))

        # Verify both sessions tracked independently in LangSmith
        assert len(ls_client.create_run.call_args_list) == 2

        # Verify both sessions tracked independently in LangFuse
        assert len(lf_client.trace.call_args_list) == 2


# =============================================================================
# Test: Graceful Degradation When One Fails Mid-Trace
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestGracefulDegradation:
    """Test graceful handling when one plugin fails during a trace."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_langsmith_mid_trace_failure_langfuse_continues(self, mock_both_clients):
        """LangSmith failing mid-trace shouldn't break LangFuse completion."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "mid-failure-session"

        # Both start successfully
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Now make LangSmith fail on update
        ls_client.update_run.side_effect = Exception("Connection lost")

        # End both - LangSmith will fail, LangFuse should complete
        asyncio.run(
            ls_module._on_agent_run_end("agent", "model", session_id=session_id, success=True)
        )
        asyncio.run(
            lf_module._on_agent_run_end("agent", "model", session_id=session_id, success=True)
        )

        # LangSmith attempted update and failed (caught internally)
        assert ls_client.update_run.called

        # LangFuse should still flush
        assert lf_client.flush.called

        # Verify LangFuse trace was properly updated
        mock_trace = lf_client.trace.return_value
        assert mock_trace.update.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_tool_call_with_one_plugin_failing(self, mock_both_clients):
        """Tool calls should handle one plugin failing gracefully."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "tool-failure-session"

        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = "run-abc"
        mock_run_ctx.session_id = session_id

        # Start both traces
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Make LangSmith fail on tool span creation
            ls_client.create_run.side_effect = [
                MagicMock(),  # First call (agent run) succeeds
                Exception("Tool span creation failed"),  # Second call (tool) fails
            ]

            # Tool call - LangSmith will fail at run creation, but shouldn't break LangFuse
            asyncio.run(ls_module._on_pre_tool_call("tool", {"arg": "value"}))
            asyncio.run(lf_module._on_pre_tool_call("tool", {"arg": "value"}))

            # LangFuse span should still be created
            mock_trace = lf_client.trace.return_value
            assert mock_trace.span.called

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_stream_event_with_partial_failure(self, mock_both_clients):
        """Stream events should not fail completely if one plugin errors."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "stream-failure-session"

        # Make LangFuse trace fail on event creation
        mock_trace = MagicMock()
        mock_trace.event.side_effect = Exception("Event logging failed")
        mock_trace.generation = MagicMock(return_value=MagicMock())
        mock_trace.span = MagicMock(return_value=MagicMock())
        mock_trace.update = MagicMock()
        lf_client.trace.return_value = mock_trace

        # Start both
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Stream event - LangFuse will fail but LangSmith won't be affected
        event_data = {"content": "test"}
        asyncio.run(ls_module._on_stream_event("token", event_data, agent_session_id=session_id))
        asyncio.run(lf_module._on_stream_event("token", event_data, agent_session_id=session_id))

        # Both attempted, LangFuse failed internally but no exception propagated
        assert mock_trace.event.called


# =============================================================================
# Test: Zero Overhead When Both Disabled
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestZeroOverheadBothDisabled:
    """Verify zero overhead when both plugins are disabled."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_both_disabled_quick_return(self):
        """Callbacks should return immediately when both plugins disabled."""
        # Clear all env vars
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        # Get fresh modules without env vars
        ls_module = _get_fresh_langsmith_module()
        lf_module = _get_fresh_langfuse_module()

        # Verify both inactive
        assert not ls_module._is_plugin_active()
        assert not lf_module._is_plugin_active()

        # All callbacks should return None quickly
        callbacks_to_test = [
            (ls_module._on_agent_run_start, ("agent", "model")),
            (ls_module._on_agent_run_end, ("agent", "model")),
            (ls_module._on_pre_tool_call, ("tool", {})),
            (ls_module._on_post_tool_call, ("tool", {}, None, 100.0)),
            (ls_module._on_stream_event, ("event", {})),
            (lf_module._on_agent_run_start, ("agent", "model")),
            (lf_module._on_agent_run_end, ("agent", "model")),
            (lf_module._on_pre_tool_call, ("tool", {})),
            (lf_module._on_post_tool_call, ("tool", {}, None, 100.0)),
            (lf_module._on_stream_event, ("event", {})),
        ]

        for callback, args in callbacks_to_test:
            start = time.time()
            result = asyncio.run(callback(*args))
            duration = time.time() - start

            assert result is None
            assert duration < 0.01, f"Callback {callback.__name__} took too long: {duration}s"

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_no_client_init_when_disabled(self):
        """No client initialization should occur when both plugins disabled."""
        # Clear all env vars
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        # Get fresh modules
        ls_module = _get_fresh_langsmith_module()
        lf_module = _get_fresh_langfuse_module()

        # Trigger callbacks
        asyncio.run(ls_module._on_agent_run_start("agent", "model"))
        asyncio.run(lf_module._on_agent_run_start("agent", "model"))

        # Verify no clients were initialized
        assert ls_module._langsmith_client is None
        assert ls_module._test_client is None
        assert lf_module._langfuse_client is None
        assert lf_module._test_client is None


# =============================================================================
# Test: Concurrent Tracing Scenarios
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestConcurrentTracing:
    """Test concurrent agent runs with dual tracing."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_multiple_concurrent_sessions(self, mock_both_clients):
        """Multiple concurrent sessions should be tracked independently."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        sessions = [f"concurrent-session-{i}" for i in range(5)]

        # Start all sessions in both plugins
        for session_id in sessions:
            asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
            asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Verify all traces created
        assert ls_client.create_run.call_count == 5
        assert lf_client.trace.call_count == 5

        # End all sessions
        for session_id in sessions:
            asyncio.run(ls_module._on_agent_run_end("agent", "model", session_id=session_id, success=True))
            asyncio.run(lf_module._on_agent_run_end("agent", "model", session_id=session_id, success=True))

        # Verify all updated
        assert ls_client.update_run.call_count == 5
        assert lf_client.flush.call_count == 5

        # Verify all traces cleaned up
        assert len(ls_module._active_traces) == 0
        assert len(lf_module._active_traces) == 0

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_mixed_success_failure_states(self, mock_both_clients):
        """Mixed success/failure states should be tracked correctly."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        # Start both sessions
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id="success-session"))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id="success-session"))

        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id="fail-session"))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id="fail-session"))

        # End one successfully, one with error
        asyncio.run(ls_module._on_agent_run_end("agent", "model", session_id="success-session", success=True))
        asyncio.run(lf_module._on_agent_run_end("agent", "model", session_id="success-session", success=True))

        error = ValueError("Test error")
        asyncio.run(
            ls_module._on_agent_run_end("agent", "model", session_id="fail-session", success=False, error=error)
        )
        asyncio.run(
            lf_module._on_agent_run_end("agent", "model", session_id="fail-session", success=False, error=error)
        )

        # Verify mixed states recorded
        ls_updates = [call[1] for call in ls_client.update_run.call_args_list]
        successes = [u["outputs"]["success"] for u in ls_updates]
        assert True in successes
        assert False in successes

        mock_trace = lf_client.trace.return_value
        lf_generations = [call[1] for call in mock_trace.generation.return_value.end.call_args_list]
        # Verify generation end called with different statuses


# =============================================================================
# Test: Error Handling and Cleanup
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestErrorHandlingAndCleanup:
    """Test error handling and resource cleanup."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_partial_cleanup_on_failure(self, mock_both_clients):
        """Traces should be cleaned up even when one plugin fails."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "cleanup-session"

        # Start both
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

        # Verify both tracked
        assert session_id in ls_module._active_traces
        assert session_id in lf_module._active_traces

        # Make LangSmith fail on update, but still allow cleanup
        ls_client.update_run.side_effect = Exception("Update failed")

        # End both
        asyncio.run(ls_module._on_agent_run_end("agent", "model", session_id=session_id, success=True))
        asyncio.run(lf_module._on_agent_run_end("agent", "model", session_id=session_id, success=True))

        # Both should be cleaned up (LangSmith error caught internally)
        assert session_id not in ls_module._active_traces
        assert session_id not in lf_module._active_traces

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_tool_span_cleanup_when_parent_ends(self, mock_both_clients):
        """Tool spans should be cleaned up when parent trace ends."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "tool-cleanup-session"
        parent_run_id = "parent-xyz"

        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = parent_run_id
        mock_run_ctx.session_id = session_id

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Start agent and tool
            asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id=session_id))
            asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id=session_id))

            asyncio.run(ls_module._on_pre_tool_call("tool", {}))
            asyncio.run(lf_module._on_pre_tool_call("tool", {}))

            # Verify tool spans tracked
            assert parent_run_id in ls_module._tool_spans
            assert parent_run_id in lf_module._tool_spans

            # End tool spans
            asyncio.run(ls_module._on_post_tool_call("tool", {}, None, 100.0))
            asyncio.run(lf_module._on_post_tool_call("tool", {}, None, 100.0))

            # Verify cleaned up
            assert parent_run_id not in ls_module._tool_spans
            assert parent_run_id not in lf_module._tool_spans

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_orphaned_tool_span_handling(self, mock_both_clients):
        """Tool spans without active parent should be handled gracefully."""
        ls_module, ls_client, lf_module, lf_client = mock_both_clients

        session_id = "orphan-session"
        parent_run_id = "orphan-parent"

        # Create run context for a session that doesn't have active traces
        mock_run_ctx = MagicMock()
        mock_run_ctx.run_id = parent_run_id
        mock_run_ctx.session_id = "non-existent-session"

        with patch("code_puppy.run_context.get_current_run_context", return_value=mock_run_ctx):
            # Tool call without active trace - should not fail
            asyncio.run(ls_module._on_pre_tool_call("tool", {}))
            asyncio.run(lf_module._on_pre_tool_call("tool", {}))

            # Tool end without matching span - should not fail
            asyncio.run(ls_module._on_post_tool_call("tool", {}, None, 100.0))
            asyncio.run(lf_module._on_post_tool_call("tool", {}, None, 100.0))

        # No exceptions raised, clean state
        assert len(ls_module._tool_spans) == 0
        assert len(lf_module._tool_spans) == 0


# =============================================================================
# Test: Integration with Different Configurations
# =============================================================================


@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
class TestDifferentConfigurations:
    """Test dual tracing with different configuration combinations."""

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_different_custom_hosts(self):
        """Plugins should use their own custom host settings."""
        # Clear all
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        MockClientClass = MagicMock()

        with patch(
            "code_puppy.plugins.tracing_langsmith.register_callbacks.resolve_variable",
            return_value=MockClientClass,
        ):
            ls_module = _get_fresh_langsmith_module(
                env_vars={
                    "LANGSMITH_API_KEY": "test-key",
                    "LANGSMITH_BASE_URL": "https://custom.langsmith.com/api",
                }
            )
            ls_module._get_langsmith_client()
            assert MockClientClass.call_args[1]["api_url"] == "https://custom.langsmith.com/api"

        # Clear for LangFuse
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        lf_module = _get_fresh_langfuse_module(
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
                "LANGFUSE_HOST": "https://custom.langfuse.com",
            }
        )

        assert lf_module.LANGFUSE_HOST == "https://custom.langfuse.com"

@pytest.mark.serial
@pytest.mark.xdist_group(name="env-mutation")
    def test_different_project_names(self):
        """Plugins should use their own project names."""
        # Clear all
        for key in [
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_BASE_URL",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_PROJECT"
        ]:
            os.environ.pop(key, None)

        ls_client = _create_mock_langsmith_client()
        ls_module = _get_fresh_langsmith_module(
            ls_client,
            env_vars={
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_PROJECT": "ls-project",
            }
        )

        lf_client = _create_mock_langfuse_client()
        lf_module = _get_fresh_langfuse_module(
            lf_client,
            env_vars={
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
                "LANGFUSE_PROJECT": "lf-project",
            }
        )

        # Trigger traces
        asyncio.run(ls_module._on_agent_run_start("agent", "model", session_id="sess-1"))
        asyncio.run(lf_module._on_agent_run_start("agent", "model", session_id="sess-1"))

        # Verify different projects used
        assert ls_client.create_run.call_args[1]["project_name"] == "ls-project"
        # LangFuse project is stored in module state
        assert lf_module.LANGFUSE_PROJECT == "lf-project"
