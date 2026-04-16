"""Integration tests for agent lifecycle hooks.

These tests use REAL callback registration and dispatch to catch
signature mismatches and ensure plugins actually receive events.

Unlike unit tests that mock callbacks, these verify the full path:
1. Plugin registers callback with register_callback()
2. Agent calls on_agent_run_start() / on_agent_run_end()
3. Callback receives correct arguments
4. Return values flow back to caller

All I/O in async callbacks is non-blocking per audit rules:
https://github.com/oh-my-pi/ompi/issues/1237
"""

import os
import pytest

from code_puppy.callbacks import (
    register_callback,
    unregister_callback,
    on_agent_run_start,
    on_agent_run_end,
    clear_callbacks,
)
from code_puppy.run_context import RunContext


class TestLifecycleHooksIntegration:
    """Integration tests that verify real callback dispatch."""

    @pytest.fixture(autouse=True)
    def cleanup_callbacks(self):
        """Clear callbacks before and after each test.
        
        Also disables auto-plugin-loading to ensure test isolation.
        """
        # Disable auto-plugin-loading for isolated testing
        old_disable = os.environ.get("PUP_DISABLE_CALLBACK_PLUGIN_LOADING")
        os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = "1"
        
        clear_callbacks("agent_run_start")
        clear_callbacks("agent_run_end")
        yield
        clear_callbacks("agent_run_start")
        clear_callbacks("agent_run_end")
        
        # Restore original value
        if old_disable is None:
            os.environ.pop("PUP_DISABLE_CALLBACK_PLUGIN_LOADING", None)
        else:
            os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = old_disable

    @pytest.mark.asyncio
    async def test_on_agent_run_start_with_tags_and_metadata(self):
        """Verify on_agent_run_start accepts tags and metadata kwargs."""
        received_args = {}

        async def capture_start(agent_name, model_name, session_id):
            received_args["agent_name"] = agent_name
            received_args["model_name"] = model_name
            received_args["session_id"] = session_id
            return {"started": True}

        register_callback("agent_run_start", capture_start)

        # Call with the ACTUAL signature used in base_agent.py
        results, ctx = await on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-session",
            tags=["agent_run"],
            metadata={"agent_version": "1.0.0"},
        )

        # Verify callback received correct args
        assert received_args["agent_name"] == "test-agent"
        assert received_args["model_name"] == "test-model"
        assert received_args["session_id"] == "test-session"

        # Verify returns tuple with results and context
        assert isinstance(results, list)
        assert ctx is not None
        assert ctx.component_name == "test-agent"
        assert ctx.tags == ["agent_run"]
        assert ctx.metadata.get("agent_version") == "1.0.0"

    @pytest.mark.asyncio
    async def test_on_agent_run_end_with_run_context(self):
        """Verify on_agent_run_end accepts run_context kwarg."""
        received_args = {}

        async def capture_end(agent_name, model_name, session_id, success, error, response_text, metadata):
            received_args["success"] = success
            received_args["error"] = error
            received_args["metadata"] = metadata
            return {"ended": True}

        register_callback("agent_run_end", capture_end)

        # First get a context from start
        _, ctx = await on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-session",
        )

        # Call end with the ACTUAL signature used in base_agent.py
        results = await on_agent_run_end(
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-session",
            success=True,
            error=None,
            response_text="Test response",
            metadata={"model": "test-model"},
            run_context=ctx,  # This must be accepted!
        )

        # Verify callback received correct args
        assert received_args["success"] is True
        assert received_args["error"] is None
        assert received_args["metadata"] == {"model": "test-model"}

        # Verify returns list
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_lifecycle_round_trip(self):
        """Test full lifecycle: start -> end with real dispatch."""
        events = []

        async def track_start(agent_name, model_name, session_id):
            events.append(("start", agent_name))

        async def track_end(agent_name, model_name, session_id, success, error, response_text, metadata):
            events.append(("end", agent_name, success))

        register_callback("agent_run_start", track_start)
        register_callback("agent_run_end", track_end)

        # Simulate agent lifecycle
        results, ctx = await on_agent_run_start(
            agent_name="my-agent",
            model_name="claude-3",
            session_id="sess-123",
            tags=["test"],
            metadata={"version": "1.0"},
        )

        # ... agent does work ...

        await on_agent_run_end(
            agent_name="my-agent",
            model_name="claude-3",
            session_id="sess-123",
            success=True,
            error=None,
            response_text="Done!",
            metadata={"tokens": 100},
            run_context=ctx,
        )

        # Verify both hooks fired in order
        assert events == [
            ("start", "my-agent"),
            ("end", "my-agent", True),
        ]

    @pytest.mark.asyncio
    async def test_multiple_callbacks_receive_args(self):
        """Test multiple callbacks all receive correct arguments."""
        callback1_args = {}
        callback2_args = {}

        async def callback1(agent_name, model_name, session_id):
            callback1_args["agent_name"] = agent_name
            callback1_args["model_name"] = model_name

        async def callback2(agent_name, model_name, session_id):
            callback2_args["agent_name"] = agent_name
            callback2_args["model_name"] = model_name

        register_callback("agent_run_start", callback1)
        register_callback("agent_run_start", callback2)

        results, ctx = await on_agent_run_start(
            agent_name="multi-callback-agent",
            model_name="gpt-4",
            session_id="session-456",
        )

        # Both callbacks should have received the same args
        assert callback1_args["agent_name"] == "multi-callback-agent"
        assert callback1_args["model_name"] == "gpt-4"
        assert callback2_args["agent_name"] == "multi-callback-agent"
        assert callback2_args["model_name"] == "gpt-4"

        # Should have 2 results (one from each callback)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_sync_callback_works_alongside_async(self):
        """Test sync callbacks also receive correct args."""
        sync_received = {}

        def sync_callback(agent_name, model_name, session_id):
            sync_received["agent_name"] = agent_name
            sync_received["model_name"] = model_name
            return {"sync": True}

        register_callback("agent_run_start", sync_callback)

        results, ctx = await on_agent_run_start(
            agent_name="sync-test",
            model_name="model-123",
        )

        # Sync callback should have been called
        assert sync_received["agent_name"] == "sync-test"
        assert sync_received["model_name"] == "model-123"
        assert len(results) == 1
        assert results[0] == {"sync": True}

    @pytest.mark.asyncio
    async def test_end_callback_with_error(self):
        """Test on_agent_run_end with error parameter."""
        received_error = None

        async def capture_error(agent_name, model_name, session_id, success, error, response_text, metadata):
            nonlocal received_error
            received_error = error
            return {"captured": True}

        register_callback("agent_run_end", capture_error)

        _, ctx = await on_agent_run_start(
            agent_name="error-test",
            model_name="error-model",
        )

        test_error = ValueError("Something went wrong")

        await on_agent_run_end(
            agent_name="error-test",
            model_name="error-model",
            session_id=None,
            success=False,
            error=test_error,
            response_text=None,
            metadata={"error_code": 500},
            run_context=ctx,
        )

        assert received_error is test_error

    @pytest.mark.asyncio
    async def test_run_context_created_by_start(self):
        """Test that on_agent_run_start creates and returns a RunContext."""
        results, ctx = await on_agent_run_start(
            agent_name="ctx-test",
            model_name="ctx-model",
            session_id="session-abc",
            tags=["tag1", "tag2"],
            metadata={"custom": "data"},
        )

        # Verify context is properly initialized
        assert isinstance(ctx, RunContext)
        assert ctx.component_type == "agent"
        assert ctx.component_name == "ctx-test"
        assert ctx.session_id == "session-abc"
        assert ctx.tags == ["tag1", "tag2"]
        assert ctx.metadata["custom"] == "data"
        assert ctx.metadata["model_name"] == "ctx-model"
        assert ctx.run_id is not None
        assert ctx.parent_run_id is None  # Root context

    @pytest.mark.asyncio
    async def test_return_values_from_callbacks(self):
        """Test that return values from callbacks are collected properly."""
        async def return_1(agent_name, model_name, session_id):
            return {"id": 1}

        async def return_2(agent_name, model_name, session_id):
            return {"id": 2}

        register_callback("agent_run_start", return_1)
        register_callback("agent_run_start", return_2)

        results, ctx = await on_agent_run_start(
            agent_name="return-test",
            model_name="return-model",
        )

        # Results should be a list containing all return values
        assert len(results) == 2
        assert {"id": 1} in results
        assert {"id": 2} in results

    @pytest.mark.asyncio
    async def test_unregister_callback_removes_handler(self):
        """Test that unregister_callback properly removes a callback."""
        calls = []

        async def track(agent_name, model_name, session_id):
            calls.append("tracked")

        register_callback("agent_run_start", track)

        # First call should work
        await on_agent_run_start(agent_name="a", model_name="m")
        assert len(calls) == 1

        # Unregister
        unregistered = unregister_callback("agent_run_start", track)
        assert unregistered is True

        # Second call should not trigger the callback
        await on_agent_run_start(agent_name="a", model_name="m")
        assert len(calls) == 1  # No new call

    @pytest.mark.asyncio
    async def test_end_enriches_run_context(self):
        """Test that on_agent_run_end enriches the run context with results."""
        results, ctx = await on_agent_run_start(
            agent_name="enrich-test",
            model_name="enrich-model",
        )

        await on_agent_run_end(
            agent_name="enrich-test",
            model_name="enrich-model",
            session_id=None,
            success=True,
            error=None,
            response_text="Hello world",
            metadata={"tokens": 50, "custom": "value"},
            run_context=ctx,
        )

        # Context should be enriched with end data
        assert ctx.success is True
        assert ctx.end_time is not None
        assert ctx.metadata["tokens"] == 50
        assert ctx.metadata["custom"] == "value"
        assert ctx.metadata["response_text_length"] == 11  # len("Hello world")
