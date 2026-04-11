"""Tests for callbacks.py concurrent execution paths.

Covers:
- _trigger_callbacks_sync with sync and async callbacks
- _trigger_callbacks_sync exception handling (callback failure doesn't stop others)
- _trigger_callbacks_sync async callback in running loop (warning path)
- _trigger_callbacks (async) with mixed sync/async callbacks
- _trigger_callbacks exception handling
"""

import asyncio
import os

import pytest

from code_puppy.callbacks import (
    _CALLBACK_FAILED,
    _trigger_callbacks,
    _trigger_callbacks_sync,
    clear_callbacks,
    on_startup,
    on_shutdown,
    register_callback,
)


class TestTriggerCallbacksSync:
    """Tests for _trigger_callbacks_sync (non-async context)."""

    def setup_method(self):
        clear_callbacks()
        # Disable auto-plugin-loading for isolated callback testing
        os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = "1"

    def teardown_method(self):
        """Re-enable plugin loading after each test."""
        os.environ.pop("PUP_DISABLE_CALLBACK_PLUGIN_LOADING", None)

    def test_no_callbacks_returns_empty(self):
        result = _trigger_callbacks_sync("startup")
        assert result == []

    def test_sync_callback_executed(self):
        register_callback("startup", lambda: 42)
        result = _trigger_callbacks_sync("startup")
        assert result == [42]

    def test_multiple_sync_callbacks_executed_in_order(self):
        order = []
        register_callback("startup", lambda: order.append("a"))
        register_callback("startup", lambda: order.append("b"))
        register_callback("startup", lambda: order.append("c"))
        _trigger_callbacks_sync("startup")
        assert order == ["a", "b", "c"]

    def test_sync_callback_exception_doesnt_stop_others(self):
        """A failing callback doesn't prevent subsequent callbacks from running."""
        results = []

        def good1():
            results.append("good1")
            return 1

        def bad():
            raise RuntimeError("boom")

        def good2():
            results.append("good2")
            return 2

        register_callback("startup", good1)
        register_callback("startup", bad)
        register_callback("startup", good2)

        ret = _trigger_callbacks_sync("startup")
        # good1 and good2 ran, bad returned _CALLBACK_FAILED
        assert results == ["good1", "good2"]
        assert ret == [1, _CALLBACK_FAILED, 2]

    def test_async_callback_in_sync_context(self):
        """Async callback is awaited via asyncio.run in sync context."""

        async def async_cb():
            return "async_result"

        register_callback("startup", async_cb)
        result = _trigger_callbacks_sync("startup")
        assert result == ["async_result"]

    def test_async_callback_in_running_loop_schedules_task(self):
        """async callback in running loop is scheduled via asyncio.ensure_future.

        New behavior (after asyncio.gather improvement): instead of returning None
        and logging a warning, _trigger_callbacks_sync schedules the coroutine as a
        Task so it runs later in the event loop. The result is an asyncio.Task, not None.
        """
        import asyncio as _asyncio

        async def async_cb():
            return "should_run_eventually"

        register_callback("startup", async_cb)

        async def run_inside_loop():
            # This calls _trigger_callbacks_sync while an event loop is running
            result = _trigger_callbacks_sync("startup")
            # New behavior: returns a scheduled Task, not None
            assert len(result) == 1
            assert isinstance(result[0], _asyncio.Task), (
                f"Expected asyncio.Task, got {type(result[0])}: {result[0]}"
            )
            # Let the task run to completion
            await _asyncio.sleep(0)

        asyncio.run(run_inside_loop())

    def test_sync_callback_with_args(self):
        captured = {}
        register_callback(
            "agent_exception", lambda exc, **kw: captured.update({"exc": str(exc)})
        )
        _trigger_callbacks_sync("agent_exception", ValueError("test"))
        assert captured == {"exc": "test"}


class TestTriggerCallbacksAsync:
    """Tests for _trigger_callbacks (async context)."""

    def setup_method(self):
        clear_callbacks()
        # Disable auto-plugin-loading for isolated callback testing
        os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = "1"

    def teardown_method(self):
        """Re-enable plugin loading after each test."""
        os.environ.pop("PUP_DISABLE_CALLBACK_PLUGIN_LOADING", None)

    @pytest.mark.asyncio
    async def test_no_callbacks_returns_empty(self):
        result = await _trigger_callbacks("startup")
        assert result == []

    @pytest.mark.asyncio
    async def test_sync_callback_in_async_context(self):
        register_callback("startup", lambda: "sync_in_async")
        result = await _trigger_callbacks("startup")
        assert result == ["sync_in_async"]

    @pytest.mark.asyncio
    async def test_async_callback_in_async_context(self):
        async def async_cb():
            return "async_result"

        register_callback("startup", async_cb)
        result = await _trigger_callbacks("startup")
        assert result == ["async_result"]

    @pytest.mark.asyncio
    async def test_mixed_sync_and_async_callbacks(self):
        async def async_cb():
            return "async"

        register_callback("startup", lambda: "sync")
        register_callback("startup", async_cb)
        register_callback("startup", lambda: "sync2")

        result = await _trigger_callbacks("startup")
        assert result == ["sync", "async", "sync2"]

    @pytest.mark.asyncio
    async def test_async_callback_exception_doesnt_stop_others(self):
        """A failing async callback doesn't prevent subsequent callbacks."""
        results = []

        async def bad():
            raise RuntimeError("async boom")

        register_callback("startup", lambda: results.append("ok"))
        register_callback("startup", bad)
        register_callback("startup", lambda: results.append("ok2"))

        ret = await _trigger_callbacks("startup")
        assert results == ["ok", "ok2"]
        assert ret[0] is None  # first lambda returns None
        assert ret[1] is _CALLBACK_FAILED  # bad callback
        assert ret[2] is None  # second lambda returns None

    @pytest.mark.asyncio
    async def test_callbacks_receive_args_and_kwargs(self):
        captured = {}

        async def capture_cb(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        register_callback("stream_event", capture_cb)
        await _trigger_callbacks("stream_event", "event_type", key="val")
        assert captured["args"] == ("event_type",)
        assert captured["kwargs"] == {"key": "val"}


class TestOnStartupShutdown:
    """Test the public on_startup / on_shutdown helpers."""

    def setup_method(self):
        clear_callbacks()
        # Disable auto-plugin-loading for isolated callback testing
        os.environ["PUP_DISABLE_CALLBACK_PLUGIN_LOADING"] = "1"

    def teardown_method(self):
        """Re-enable plugin loading after each test."""
        os.environ.pop("PUP_DISABLE_CALLBACK_PLUGIN_LOADING", None)

    @pytest.mark.asyncio
    async def test_on_startup_triggers_callbacks(self):
        results = []
        register_callback("startup", lambda: results.append("started"))
        await on_startup()
        assert results == ["started"]

    @pytest.mark.asyncio
    async def test_on_shutdown_triggers_callbacks(self):
        results = []
        register_callback("shutdown", lambda: results.append("stopped"))
        await on_shutdown()
        assert results == ["stopped"]
