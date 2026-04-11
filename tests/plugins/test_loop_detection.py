"""Tests for the Loop Detection Plugin."""

import importlib
import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _get_plugin_module(fresh: bool = False) -> ModuleType:
    """Import the loop detection plugin module with mocked dependencies."""
    module_name = "code_puppy.plugins.loop_detection.register_callbacks"

    if fresh or module_name not in sys.modules:
        # Clear cache to ensure fresh import
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Set up mocks before import
        mock_callbacks = MagicMock()

        # Create a Deny dataclass-like mock with proper attributes
        class MockDeny:
            def __init__(self, reason: str, user_feedback: str | None = None):
                self.reason = reason
                self.user_feedback = user_feedback

        mock_permission = MagicMock()
        mock_permission.Deny = MockDeny
        mock_permission.Deny.side_effect = MockDeny

        mock_config = MagicMock()
        mock_messaging = MagicMock()
        mock_run_context = MagicMock()
        mock_run_context.get_current_run_context = MagicMock(return_value=None)

        sys.modules["code_puppy.callbacks"] = mock_callbacks
        sys.modules["code_puppy.permission_decision"] = mock_permission
        sys.modules["code_puppy.config"] = mock_config
        sys.modules["code_puppy.messaging"] = mock_messaging
        sys.modules["code_puppy.run_context"] = mock_run_context

        mod = importlib.import_module(module_name)
        # Store mocks on module for test access
        mod._mock_callbacks = mock_callbacks
        mod._mock_permission = mock_permission
        mod._mock_config = mock_config
        mod._mock_messaging = mock_messaging
        mod._mock_run_context = mock_run_context
        return mod

    return sys.modules[module_name]


def _clear_config_cache(module):
    """Clear the TTL config cache."""
    module._invalidate_config_cache()


class TestHashToolCalls:
    """Tests for the _hash_tool_calls function."""

    def test_same_args_same_hash(self):
        """Identical tool calls should produce the same hash."""
        module = _get_plugin_module()
        hash1 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py"})
        hash2 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py"})
        assert hash1 == hash2
        assert len(hash1) == 12  # Truncated MD5

    def test_different_args_different_hash(self):
        """Different tool arguments should produce different hashes."""
        module = _get_plugin_module()
        hash1 = module._hash_tool_calls("read_file", {"path": "/tmp/a.py"})
        hash2 = module._hash_tool_calls("read_file", {"path": "/tmp/b.py"})
        assert hash1 != hash2

    def test_different_tools_different_hash(self):
        """Different tool names should produce different hashes."""
        module = _get_plugin_module()
        hash1 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py"})
        hash2 = module._hash_tool_calls("write_file", {"path": "/tmp/test.py"})
        assert hash1 != hash2

    def test_empty_args(self):
        """Empty args should be handled gracefully."""
        module = _get_plugin_module()
        hash_val = module._hash_tool_calls("list_files", {})
        assert isinstance(hash_val, str)
        assert len(hash_val) == 12

    def test_none_args(self):
        """None args should be treated as empty dict."""
        module = _get_plugin_module()
        hash_val = module._hash_tool_calls("list_files", None)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 12

    def test_string_args_parsed_as_json(self):
        """String args that are valid JSON should be parsed."""
        module = _get_plugin_module()
        dict_hash = module._hash_tool_calls("test", {"key": "value"})
        str_hash = module._hash_tool_calls("test", '{"key": "value"}')
        assert dict_hash == str_hash

    def test_read_file_line_bucketing(self):
        """read_file calls should bucket line ranges."""
        module = _get_plugin_module()
        # Same bucket (both within 200-line window)
        hash1 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py", "start_line": 10})
        hash2 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py", "start_line": 50})
        assert hash1 == hash2

    def test_read_file_different_buckets(self):
        """read_file calls in different line buckets should have different hashes."""
        module = _get_plugin_module()
        hash1 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py", "start_line": 10})
        hash2 = module._hash_tool_calls("read_file", {"path": "/tmp/test.py", "start_line": 500})
        assert hash1 != hash2

    def test_write_file_content_matters(self):
        """write_file hashes should include content to avoid false positives."""
        module = _get_plugin_module()
        hash1 = module._hash_tool_calls("write_file", {"path": "/tmp/a.py", "content": "x"})
        hash2 = module._hash_tool_calls("write_file", {"path": "/tmp/a.py", "content": "y"})
        assert hash1 != hash2


class TestNormalizeToolArgs:
    """Tests for the _normalize_tool_args function."""

    def test_dict_returned_as_is(self):
        """Dict args should be returned unchanged."""
        module = _get_plugin_module()
        args = {"key": "value", "num": 123}
        result = module._normalize_tool_args(args)
        assert result == args

    def test_none_returns_empty_dict(self):
        """None should return empty dict."""
        module = _get_plugin_module()
        result = module._normalize_tool_args(None)
        assert result == {}

    def test_valid_json_string_parsed(self):
        """Valid JSON string should be parsed to dict."""
        module = _get_plugin_module()
        result = module._normalize_tool_args('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json_string_returns_raw(self):
        """Invalid JSON string should be wrapped in _raw key."""
        module = _get_plugin_module()
        result = module._normalize_tool_args("not json")
        assert result == {"_raw": "not json"}

    def test_non_dict_json_array(self):
        """JSON array should be wrapped in _parsed key."""
        module = _get_plugin_module()
        result = module._normalize_tool_args('[1, 2, 3]')
        assert result == {"_parsed": [1, 2, 3]}

    def test_other_types_wrapped(self):
        """Non-dict, non-string types should be wrapped."""
        module = _get_plugin_module()
        result = module._normalize_tool_args(42)
        assert result == {"_value": 42}


class TestStableToolKey:
    """Tests for the _stable_tool_key function."""

    def test_read_file_key_includes_path(self):
        """read_file key should include the path."""
        module = _get_plugin_module()
        key = module._stable_tool_key("read_file", {"path": "/tmp/test.py"})
        assert "/tmp/test.py" in key

    def test_read_file_key_buckets_lines(self):
        """read_file key should bucket line numbers."""
        module = _get_plugin_module()
        key = module._stable_tool_key("read_file", {"path": "/tmp/test.py", "start_line": 50})
        assert "0" in key  # 50 is in bucket 0 (0-199)

    def test_read_file_with_num_lines(self):
        """read_file key should handle num_lines parameter."""
        module = _get_plugin_module()
        key = module._stable_tool_key(
            "read_file", {"path": "/tmp/test.py", "start_line": 100, "num_lines": 300}
        )
        assert "0-1" in key or "100" in key  # Should show bucketing

    def test_write_file_includes_content(self):
        """write_file key should include content."""
        module = _get_plugin_module()
        key1 = module._stable_tool_key("write_file", {"path": "/tmp/a.py", "content": "x"})
        key2 = module._stable_tool_key("write_file", {"path": "/tmp/a.py", "content": "y"})
        assert key1 != key2

    def test_grep_includes_pattern(self):
        """grep-like tools should use pattern in key."""
        module = _get_plugin_module()
        key1 = module._stable_tool_key("grep", {"path": "/tmp", "pattern": "foo"})
        key2 = module._stable_tool_key("grep", {"path": "/tmp", "pattern": "bar"})
        assert key1 != key2
        assert "foo" in key1 or "bar" in key2 or json.loads(key1) != json.loads(key2)


class TestGetSessionId:
    """Tests for the _get_session_id function."""

    def test_from_context_dict(self):
        """Should extract session_id from context dict."""
        module = _get_plugin_module()
        result = module._get_session_id({"agent_session_id": "session-123"})
        assert result == "session-123"

    def test_from_run_context(self):
        """Should fall back to run_context if no session in context."""
        module = _get_plugin_module()

        mock_ctx = MagicMock()
        mock_ctx.session_id = "run-session-456"

        with patch.object(
            module, "get_current_run_context", return_value=mock_ctx, create=True
        ):
            # Patch the import in the module
            with patch.dict(
                sys.modules, {"code_puppy.run_context": MagicMock(get_current_run_context=lambda: mock_ctx)}
            ):
                # Need to re-import with new mocks
                mod = _get_plugin_module()
                result = mod._get_session_id({})
                assert result == "run-session-456"

    def test_default_when_no_context(self):
        """Should return 'default' when no context available."""
        module = _get_plugin_module(fresh=True)
        # Mock get_current_run_context to return None
        module._mock_run_context.get_current_run_context.return_value = None

        result = module._get_session_id(None)
        assert result == "default"


class TestConfigReading:
    """Tests for configuration reading functions."""

    def test_get_exempt_tools_default(self):
        """Should return default exempt tools when config not set."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = None

        result = module._get_exempt_tools()
        assert "wait" in result
        assert "sleep" in result

    def test_get_exempt_tools_from_config(self):
        """Should parse comma-separated tools from config."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = "wait, sleep, my_tool"

        result = module._get_exempt_tools()
        assert "wait" in result
        assert "sleep" in result
        assert "my_tool" in result

    def test_get_warn_threshold_default(self):
        """Should return default warn threshold when config not set."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = None

        result = module._get_warn_threshold()
        assert result == 3  # Default value

    def test_get_warn_threshold_from_config(self):
        """Should parse warn threshold from config."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = "5"

        result = module._get_warn_threshold()
        assert result == 5

    def test_get_hard_threshold_default(self):
        """Should return default hard threshold when config not set."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = None

        result = module._get_hard_threshold()
        assert result == 5  # Default value

    def test_get_hard_threshold_from_config(self):
        """Should parse hard threshold from config."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = "10"

        result = module._get_hard_threshold()
        assert result == 10

    def test_invalid_threshold_returns_default(self):
        """Should return default on invalid threshold value."""
        module = _get_plugin_module(fresh=True)
        _clear_config_cache(module)
        module._mock_config.get_value.return_value = "not_a_number"

        result = module._get_warn_threshold()
        assert result == 3  # Default


class TestIsToolExempt:
    """Tests for the _is_tool_exempt function."""

    def test_exempt_tool(self):
        """Should return True for exempt tools."""
        module = _get_plugin_module()

        with patch.object(module, "_get_exempt_tools", return_value=frozenset({"wait", "sleep"})):
            assert module._is_tool_exempt("wait") is True
            assert module._is_tool_exempt("sleep") is True

    def test_non_exempt_tool(self):
        """Should return False for non-exempt tools."""
        module = _get_plugin_module()

        with patch.object(module, "_get_exempt_tools", return_value=frozenset({"wait", "sleep"})):
            assert module._is_tool_exempt("read_file") is False
            assert module._is_tool_exempt("write_file") is False


class TestOnPreToolCall:
    """Tests for the _on_pre_tool_call callback."""

    @pytest.mark.asyncio
    async def test_exempt_tool_not_blocked(self):
        """Exempt tools should never be blocked."""
        module = _get_plugin_module(fresh=True)

        with patch.object(module, "_is_tool_exempt", return_value=True):
            result = await module._on_pre_tool_call("wait", {"seconds": 5}, None)
            assert result is None

    @pytest.mark.asyncio
    async def test_empty_args_not_tracked(self):
        """Tools with empty args should not be tracked."""
        module = _get_plugin_module(fresh=True)

        with patch.object(module, "_is_tool_exempt", return_value=False):
            result = await module._on_pre_tool_call("list_files", {}, None)
            assert result is None

    @pytest.mark.asyncio
    async def test_below_threshold_not_blocked(self):
        """Tools below hard threshold should not be blocked."""
        module = _get_plugin_module(fresh=True)

        with (
            patch.object(module, "_is_tool_exempt", return_value=False),
            patch.object(module, "_get_hard_threshold", return_value=5),
            patch.object(module, "_get_session_id", return_value="test-session"),
        ):
            # First call
            result = await module._on_pre_tool_call("read_file", {"path": "/tmp/test.py"}, None)
            assert result is None

    @pytest.mark.asyncio
    async def test_at_hard_threshold_blocked(self):
        """Tools at hard threshold should be blocked with Deny."""
        module = _get_plugin_module(fresh=True)

        # Pre-populate history with 4 identical calls
        with module._lock:
            for _ in range(4):
                module._session_history["threshold-test"].append(
                    module._hash_tool_calls("read_file", {"path": "/tmp/test.py"})
                )

        with (
            patch.object(module, "_is_tool_exempt", return_value=False),
            patch.object(module, "_get_hard_threshold", return_value=5),
            patch.object(module, "_get_session_id", return_value="threshold-test"),
        ):
            # 5th call should be blocked
            result = await module._on_pre_tool_call("read_file", {"path": "/tmp/test.py"}, None)

            # Check that it's a Deny - the mock_permission.Deny should be returned
            # The result should have 'reason' and optionally 'user_feedback'
            assert result is not None
            assert hasattr(result, "reason")
            assert "loop" in result.reason.lower() or "Loop" in result.reason

        # Clean up
        module.reset_loop_detection("threshold-test")


class TestOnPostToolCall:
    """Tests for the _on_post_tool_call callback."""

    @pytest.mark.asyncio
    async def test_exempt_tool_no_warning(self):
        """Exempt tools should not trigger warnings."""
        module = _get_plugin_module(fresh=True)
        mock_messaging = module._mock_messaging

        with patch.object(module, "_is_tool_exempt", return_value=True):
            await module._on_post_tool_call("wait", {"seconds": 1}, None, 100, None)
            mock_messaging.emit_warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_warn_at_threshold(self):
        """Warning should be emitted at warn threshold."""
        module = _get_plugin_module(fresh=True)
        mock_messaging = module._mock_messaging

        session_id = "warn-test"
        tool_args = {"path": "/tmp/test.py"}
        call_hash = module._hash_tool_calls("read_file", tool_args)

        # Pre-populate history with 3 identical calls (at warn threshold)
        with module._lock:
            for _ in range(3):
                module._session_history[session_id].append(call_hash)

        with (
            patch.object(module, "_is_tool_exempt", return_value=False),
            patch.object(module, "_get_warn_threshold", return_value=3),
            patch.object(module, "_get_session_id", return_value=session_id),
        ):
            # Post-call should trigger warning when count >= threshold
            await module._on_post_tool_call("read_file", tool_args, "result", 100, None)

            # Should have emitted a warning
            mock_messaging.emit_warning.assert_called_once()
            call_args = mock_messaging.emit_warning.call_args[0][0]
            assert "LOOP WARNING" in call_args or "loop" in call_args.lower()

        # Clean up
        module.reset_loop_detection(session_id)

    @pytest.mark.asyncio
    async def test_warn_only_once_per_hash(self):
        """Warning should only be emitted once per unique hash."""
        module = _get_plugin_module(fresh=True)
        mock_messaging = module._mock_messaging

        session_id = "once-test"
        tool_args = {"path": "/tmp/test.py"}
        call_hash = module._hash_tool_calls("read_file", tool_args)

        # Pre-populate history and warned set
        with module._lock:
            for _ in range(5):
                module._session_history[session_id].append(call_hash)
            module._session_warned[session_id].add(call_hash)

        with (
            patch.object(module, "_is_tool_exempt", return_value=False),
            patch.object(module, "_get_warn_threshold", return_value=3),
            patch.object(module, "_get_session_id", return_value=session_id),
        ):
            # Should not emit since already warned
            await module._on_post_tool_call("read_file", tool_args, "result", 100, None)

            mock_messaging.emit_warning.assert_not_called()

        # Clean up
        module.reset_loop_detection(session_id)


class TestResetLoopDetection:
    """Tests for the reset_loop_detection function."""

    def test_reset_specific_session(self):
        """Should clear state for a specific session."""
        module = _get_plugin_module()

        # Add some state
        with module._lock:
            module._session_history["session-1"].append("hash1")
            module._session_warned["session-1"].add("hash1")
            module._session_history["session-2"].append("hash2")

        module.reset_loop_detection("session-1")

        with module._lock:
            assert "session-1" not in module._session_history
            assert "session-1" not in module._session_warned
            assert "session-2" in module._session_history

        # Clean up
        module.reset_loop_detection("session-2")

    def test_reset_all_sessions(self):
        """Should clear all state when no session specified."""
        module = _get_plugin_module()

        # Add some state
        with module._lock:
            module._session_history["session-1"].append("hash1")
            module._session_history["session-2"].append("hash2")

        module.reset_loop_detection()

        with module._lock:
            assert len(module._session_history) == 0
            assert len(module._session_warned) == 0


class TestGetLoopStats:
    """Tests for the get_loop_stats function."""

    def test_stats_for_specific_session(self):
        """Should return stats for a specific session."""
        module = _get_plugin_module()

        # Add some state
        with module._lock:
            module._session_history["stats-test"].append("hash1")
            module._session_history["stats-test"].append("hash2")
            module._session_history["stats-test"].append("hash1")  # Duplicate

        stats = module.get_loop_stats("stats-test")

        assert stats["session_id"] == "stats-test"
        assert stats["history_size"] == 3
        assert stats["unique_hashes"] == 2

        # Clean up
        module.reset_loop_detection("stats-test")

    def test_stats_for_all_sessions(self):
        """Should return aggregate stats when no session specified."""
        module = _get_plugin_module(fresh=True)

        # Clear any existing state first
        with module._lock:
            module._session_history.clear()
            module._session_warned.clear()

        # Add state for multiple sessions
        with module._lock:
            module._session_history["session-a"].append("hash1")
            module._session_history["session-b"].append("hash2")

        stats = module.get_loop_stats()

        assert stats["total_sessions"] == 2
        assert stats["total_history_entries"] == 2

        # Clean up
        module.reset_loop_detection()


class TestHistoryEviction:
    """Tests for history deque maxlen behavior."""

    def test_history_respects_maxlen(self):
        """History should not exceed maxlen (50)."""
        module = _get_plugin_module()
        session_id = "maxlen-test"

        # Add more than 50 entries
        with module._lock:
            for i in range(60):
                module._session_history[session_id].append(f"hash-{i}")

        with module._lock:
            history = module._session_history[session_id]
            assert len(history) <= 50
            # Oldest entries should have been evicted
            assert "hash-0" not in list(history)
            # Newest entries should be present
            assert "hash-59" in list(history)

        # Clean up
        module.reset_loop_detection(session_id)


class TestThreadSafety:
    """Tests for thread safety of the loop detection state."""

    def test_lock_exists(self):
        """Module should have a lock for thread safety."""
        module = _get_plugin_module()
        assert hasattr(module, "_lock")

    def test_concurrent_access_does_not_crash(self):
        """Concurrent access should not crash."""
        import threading
        import time

        module = _get_plugin_module()
        session_id = "concurrent-test"
        errors = []

        def add_entries():
            try:
                for i in range(20):
                    with module._lock:
                        module._session_history[session_id].append(f"hash-{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=add_entries) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent access errors: {errors}"

        # Clean up
        module.reset_loop_detection(session_id)
