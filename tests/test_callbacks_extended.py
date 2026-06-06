import asyncio
from unittest.mock import patch

import pytest

from code_puppy.callbacks import (
    clear_callbacks,
    count_callbacks,
    get_callbacks,
    on_create_file,
    on_custom_command,
    on_delete_snippet,
    on_edit_file,
    on_load_model_config,
    on_post_tool_call,
    on_pre_tool_call,
    on_replace_in_file,
    on_startup,
    on_stream_event,
    register_callback,
    unregister_callback,
)


class TestCallbacksExtended:
    """Test code_puppy/callbacks.py callback system."""

    def setup_method(self):
        """Clean up callbacks before each test."""
        clear_callbacks()

    def test_register_callback(self):
        """Test callback registration and counting."""

        def test_callback():
            return "test"

        register_callback("startup", test_callback)

        callbacks = get_callbacks("startup")
        assert len(callbacks) == 1
        assert callbacks[0] == test_callback
        assert count_callbacks("startup") == 1
        assert count_callbacks() == 1

    def test_register_multiple_callbacks(self):
        """Test registering multiple callbacks across phases."""

        def callback1():
            return "1"

        def callback2():
            return "2"

        def callback3():
            return "3"

        register_callback("startup", callback1)
        register_callback("startup", callback2)
        register_callback("shutdown", callback3)

        assert count_callbacks("startup") == 2
        assert count_callbacks("shutdown") == 1
        assert count_callbacks() == 3

    @pytest.mark.parametrize(
        "phase,bad_callback,exc,match",
        [
            ("invalid_phase", lambda: "x", ValueError, "Unsupported phase"),
            ("startup", "not_a_function", TypeError, "Callback must be callable"),
        ],
    )
    def test_register_callback_invalid(self, phase, bad_callback, exc, match):
        """Test registering with invalid phase or non-callable raises."""
        with pytest.raises(exc, match=match):
            register_callback(phase, bad_callback)

    def test_unregister_callback(self):
        """Test callback unregistration (and re-unregister returns False)."""

        def test_callback():
            return "test"

        register_callback("startup", test_callback)
        assert count_callbacks("startup") == 1

        assert unregister_callback("startup", test_callback) is True
        assert count_callbacks("startup") == 0
        assert unregister_callback("startup", test_callback) is False

    def test_clear_callbacks_specific_phase(self):
        """Test clearing callbacks for a specific phase only."""

        def callback1():
            return "1"

        def callback2():
            return "2"

        register_callback("startup", callback1)
        register_callback("shutdown", callback2)

        clear_callbacks("startup")

        assert count_callbacks("startup") == 0
        assert count_callbacks("shutdown") == 1

    def test_clear_callbacks_all(self):
        """Test clearing all callbacks."""

        def callback1():
            return "1"

        def callback2():
            return "2"

        register_callback("startup", callback1)
        register_callback("shutdown", callback2)

        clear_callbacks()

        assert count_callbacks() == 0

    @pytest.mark.asyncio
    async def test_execute_callbacks_async(self):
        """Test async callback execution, including multiple in order."""

        def callback1():
            return "result1"

        def callback2():
            return "result2"

        register_callback("startup", callback1)
        register_callback("startup", callback2)

        results = await on_startup()

        assert results == ["result1", "result2"]

    @pytest.mark.parametrize(
        "trigger,phase,args,expected",
        [
            (on_load_model_config, "load_model_config", (), "sync_result"),
            (on_edit_file, "edit_file", ("test.txt", "content"), "edited test.txt"),
            (
                on_create_file,
                "create_file",
                ("new_file.py", "print('hello')"),
                "created new_file.py",
            ),
            (
                on_replace_in_file,
                "replace_in_file",
                ("target.py", [{"old": "a", "new": "b"}]),
                "replaced in target.py",
            ),
            (
                on_delete_snippet,
                "delete_snippet",
                ("target.py", "# remove me"),
                "deleted snippet from target.py",
            ),
            (on_custom_command, "custom_command", ("/test command", "test"), True),
        ],
    )
    def test_sync_trigger_dispatch(self, trigger, phase, args, expected):
        """Test sync triggers dispatch to their phase with correct args/result."""

        def test_callback(*cb_args):
            return expected

        register_callback(phase, test_callback)

        results = trigger(*args)

        assert len(results) == 1
        assert results[0] == expected

    @pytest.mark.parametrize(
        "is_async,phase,trigger",
        [
            (True, "startup", on_startup),
            (False, "load_model_config", on_load_model_config),
        ],
    )
    @pytest.mark.asyncio
    async def test_execute_callbacks_with_exception(self, is_async, phase, trigger):
        """Test errors in callbacks return None and are logged (async + sync)."""

        def failing_callback():
            raise Exception("Test error")

        register_callback(phase, failing_callback)

        with patch("code_puppy.callbacks.logger") as mock_logger:
            results = await trigger() if is_async else trigger()

            assert len(results) == 1
            assert results[0] is None
            mock_logger.error.assert_called_once()

    def test_execute_async_callback_in_sync_context(self):
        """Test async callback executed from sync trigger."""

        async def async_callback():
            await asyncio.sleep(0.001)
            return "async_result"

        register_callback("load_model_config", async_callback)

        results = on_load_model_config()

        assert len(results) == 1
        assert results[0] == "async_result"

    @pytest.mark.asyncio
    async def test_no_callbacks_registered(self):
        """Test behavior when no callbacks are registered."""
        assert await on_startup() == []
        assert on_load_model_config() == []

    def test_get_callbacks_returns_copy(self):
        """Test that get_callbacks returns a copy, not the original list."""

        def test_callback():
            return "test"

        register_callback("startup", test_callback)

        callbacks1 = get_callbacks("startup")
        callbacks2 = get_callbacks("startup")

        def extra_callback():
            return "extra"

        callbacks1.append(extra_callback)

        assert len(callbacks1) == 2
        assert len(callbacks2) == 1
        assert len(get_callbacks("startup")) == 1


class TestPreToolCallCallback:
    """Test on_pre_tool_call callback hook."""

    def setup_method(self):
        """Clean up callbacks before each test."""
        clear_callbacks()

    @pytest.mark.asyncio
    async def test_pre_tool_call_receives_correct_args(self):
        """Test that pre_tool_call callbacks receive tool_name, tool_args, context."""
        captured_args = []

        async def capture_callback(tool_name, tool_args, context):
            captured_args.append((tool_name, tool_args, context))
            return "captured"

        register_callback("pre_tool_call", capture_callback)

        test_tool_args = {"file_path": "test.py", "content": "hello"}
        test_context = {"session_id": "abc123"}

        results = await on_pre_tool_call("edit_file", test_tool_args, test_context)

        assert len(results) == 1
        assert results[0] == "captured"
        assert captured_args == [("edit_file", test_tool_args, test_context)]

    @pytest.mark.asyncio
    async def test_pre_tool_call_multiple_callbacks(self):
        """Test that multiple pre_tool_call callbacks are all called in order."""
        call_order = []

        async def callback1(tool_name, tool_args, context):
            call_order.append("callback1")
            return 1

        async def callback2(tool_name, tool_args, context):
            call_order.append("callback2")
            return 2

        def callback3_sync(tool_name, tool_args, context):
            call_order.append("callback3")
            return 3

        register_callback("pre_tool_call", callback1)
        register_callback("pre_tool_call", callback2)
        register_callback("pre_tool_call", callback3_sync)

        results = await on_pre_tool_call("list_files", {}, None)

        assert results == [1, 2, 3]
        assert call_order == ["callback1", "callback2", "callback3"]

    @pytest.mark.asyncio
    async def test_pre_tool_call_error_handling(self):
        """Test that callback errors don't crash the system (None context too)."""
        results_collected = []

        async def failing_callback(tool_name, tool_args, context):
            raise RuntimeError("Callback exploded!")

        async def working_callback(tool_name, tool_args, context):
            results_collected.append(context)
            return "success"

        register_callback("pre_tool_call", failing_callback)
        register_callback("pre_tool_call", working_callback)

        with patch("code_puppy.callbacks.logger") as mock_logger:
            results = await on_pre_tool_call("run_shell", {"cmd": "ls"}, None)

            assert len(results) == 2
            assert results[0] is None
            assert results[1] == "success"
            assert results_collected == [None]
            mock_logger.error.assert_called_once()


class TestPostToolCallCallback:
    """Test on_post_tool_call callback hook."""

    def setup_method(self):
        """Clean up callbacks before each test."""
        clear_callbacks()

    @pytest.mark.asyncio
    async def test_post_tool_call_receives_all_args(self):
        """Test callbacks receive tool_name, tool_args, result, duration_ms, context."""
        captured_args = []

        async def capture_callback(tool_name, tool_args, result, duration_ms, context):
            captured_args.append(
                {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": result,
                    "duration_ms": duration_ms,
                    "context": context,
                }
            )
            return "logged"

        register_callback("post_tool_call", capture_callback)

        test_args = {"file_path": "/tmp/test.txt"}
        test_result = {"success": True, "content": "file content"}
        test_context = {"agent": "code_puppy"}

        results = await on_post_tool_call(
            "read_file", test_args, test_result, 42.5, test_context
        )

        assert len(results) == 1
        assert results[0] == "logged"
        assert captured_args == [
            {
                "tool_name": "read_file",
                "tool_args": test_args,
                "result": test_result,
                "duration_ms": 42.5,
                "context": test_context,
            }
        ]

    @pytest.mark.asyncio
    async def test_post_tool_call_duration_and_error_result(self):
        """Test duration_ms is passed through as float and error results forwarded."""
        captured = []

        async def capture(tool_name, tool_args, result, duration_ms, context):
            captured.append((duration_ms, result))

        register_callback("post_tool_call", capture)

        error_result = {"error": "File not found", "success": False}
        await on_post_tool_call("tool1", {}, {}, 0.001, None)
        await on_post_tool_call("tool2", {}, {}, 9999.99, None)
        await on_post_tool_call("read_file", {}, error_result, 5.0, None)

        durations = [d for d, _ in captured]
        assert all(isinstance(d, float) and d > 0 for d in durations)
        assert captured[-1][1] == error_result

    @pytest.mark.asyncio
    async def test_post_tool_call_multiple_callbacks(self):
        """Test that multiple post_tool_call callbacks are all called."""
        call_order = []

        async def logger_callback(tool_name, tool_args, result, duration_ms, context):
            call_order.append(f"logged:{tool_name}")

        async def metrics_callback(tool_name, tool_args, result, duration_ms, context):
            call_order.append(f"metrics:{duration_ms}ms")

        register_callback("post_tool_call", logger_callback)
        register_callback("post_tool_call", metrics_callback)

        await on_post_tool_call(
            "delete_file", {"path": "x.txt"}, {"deleted": True}, 15.3, None
        )

        assert call_order == ["logged:delete_file", "metrics:15.3ms"]

    @pytest.mark.asyncio
    async def test_post_tool_call_error_handling(self):
        """Test that errors in callbacks don't crash the system."""
        successful_calls = []

        async def bad_callback(tool_name, tool_args, result, duration_ms, context):
            raise ValueError("Analytics service unavailable")

        async def good_callback(tool_name, tool_args, result, duration_ms, context):
            successful_calls.append(tool_name)
            return "OK"

        register_callback("post_tool_call", bad_callback)
        register_callback("post_tool_call", good_callback)

        with patch("code_puppy.callbacks.logger") as mock_logger:
            results = await on_post_tool_call(
                "edit_file", {}, {"edited": True}, 200.0, None
            )

            assert len(results) == 2
            assert results[0] is None
            assert results[1] == "OK"
            assert successful_calls == ["edit_file"]
            mock_logger.error.assert_called_once()


class TestStreamEventCallback:
    """Test on_stream_event callback hook."""

    def setup_method(self):
        """Clean up callbacks before each test."""
        clear_callbacks()

    @pytest.mark.asyncio
    async def test_stream_event_receives_correct_args(self):
        """Test callbacks receive event_type, event_data, agent_session_id (None ok)."""
        captured_events = []

        async def capture_event(event_type, event_data, agent_session_id):
            captured_events.append((event_type, event_data, agent_session_id))

        register_callback("stream_event", capture_event)

        await on_stream_event("token", {"content": "Hello"}, "session-123")
        await on_stream_event("token", {"text": "hi"}, None)

        assert captured_events == [
            ("token", {"content": "Hello"}, "session-123"),
            ("token", {"text": "hi"}, None),
        ]

    @pytest.mark.asyncio
    async def test_stream_event_different_event_types(self):
        """Test different event types are handled correctly."""
        events_by_type = {}

        async def categorize_event(event_type, event_data, agent_session_id):
            events_by_type.setdefault(event_type, []).append(event_data)

        register_callback("stream_event", categorize_event)

        await on_stream_event("token", {"content": "foo"}, "sess-1")
        await on_stream_event("tool_call_start", {"tool": "edit_file"}, "sess-1")
        await on_stream_event(
            "tool_call_end", {"tool": "edit_file", "success": True}, "sess-1"
        )
        await on_stream_event("token", {"content": "bar"}, "sess-1")
        await on_stream_event("stream_end", {"reason": "complete"}, "sess-1")

        assert len(events_by_type["token"]) == 2
        assert len(events_by_type["tool_call_start"]) == 1
        assert len(events_by_type["tool_call_end"]) == 1
        assert len(events_by_type["stream_end"]) == 1

    @pytest.mark.asyncio
    async def test_stream_event_multiple_callbacks(self):
        """Test that multiple stream_event callbacks are all called."""
        call_count = {"logger": 0, "metrics": 0, "ui": 0}

        async def logger_cb(event_type, event_data, agent_session_id):
            call_count["logger"] += 1

        async def metrics_cb(event_type, event_data, agent_session_id):
            call_count["metrics"] += 1

        def ui_cb_sync(event_type, event_data, agent_session_id):
            call_count["ui"] += 1

        register_callback("stream_event", logger_cb)
        register_callback("stream_event", metrics_cb)
        register_callback("stream_event", ui_cb_sync)

        await on_stream_event("token", {}, "s1")

        assert call_count == {"logger": 1, "metrics": 1, "ui": 1}

    @pytest.mark.asyncio
    async def test_stream_event_error_handling(self):
        """Test that errors in stream callbacks don't crash the system."""
        successful_events = []

        async def crashing_callback(event_type, event_data, agent_session_id):
            raise ConnectionError("WebSocket disconnected")

        async def resilient_callback(event_type, event_data, agent_session_id):
            successful_events.append(event_type)
            return "OK"

        register_callback("stream_event", crashing_callback)
        register_callback("stream_event", resilient_callback)

        with patch("code_puppy.callbacks.logger") as mock_logger:
            results = await on_stream_event("token", {"content": "x"}, "sess")

            assert len(results) == 2
            assert results[0] is None
            assert results[1] == "OK"
            assert successful_events == ["token"]
            mock_logger.error.assert_called_once()
