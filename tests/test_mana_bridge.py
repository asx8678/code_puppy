"""Integration tests for the Mana bridge plugin.

Tests cover frame encoding/decoding, BridgeClient lifecycle, and callback
registration.  All tests run WITHOUT Mana actually running — socket
connections are mocked or allowed to fail gracefully.
"""

from __future__ import annotations

import importlib
import os
import queue
import struct
from unittest.mock import MagicMock, patch

import msgpack
import pytest

from code_puppy.callbacks import clear_callbacks, count_callbacks, get_callbacks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_callbacks():
    """Reset callback registry between tests to avoid cross-test pollution."""
    clear_callbacks()
    yield
    clear_callbacks()


@pytest.fixture()
def _preserve_bridge_env():
    """Save and restore CODE_PUPPY_BRIDGE env var around a test."""
    old_val = os.environ.get("CODE_PUPPY_BRIDGE")
    yield
    if old_val is None:
        os.environ.pop("CODE_PUPPY_BRIDGE", None)
    else:
        os.environ["CODE_PUPPY_BRIDGE"] = old_val


# ===================================================================
# 1. Frame encoding / decoding tests
# ===================================================================


class TestFrameEncoding:
    """Tests for BridgeClient.encode_frame and decode_frame_header."""

    def test_encode_frame_produces_length_prefixed_msgpack(self):
        """Encoded frame should start with a 4-byte big-endian length header."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        payload = msgpack.packb({"hello": "world"}, use_bin_type=True)
        frame = BridgeClient.encode_frame(payload)

        # First 4 bytes are the length header
        header = frame[:4]
        length = struct.unpack(">I", header)[0]

        assert length == len(payload)
        # Remaining bytes should be the original payload
        assert frame[4:] == payload

    def test_decode_frame_header_extracts_length(self):
        """decode_frame_header should return the correct length from 4 bytes."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        # Encode a known-length payload
        payload = b"test payload data"
        frame = BridgeClient.encode_frame(payload)
        header_bytes = frame[:4]

        length = BridgeClient.decode_frame_header(header_bytes)
        assert length == len(payload)

    def test_decode_frame_header_with_empty_payload(self):
        """decode_frame_header should return 0 for an empty payload."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        payload = b""
        frame = BridgeClient.encode_frame(payload)
        length = BridgeClient.decode_frame_header(frame[:4])
        assert length == 0

    def test_decode_frame_header_raises_on_short_data(self):
        """decode_frame_header should raise struct.error for < 4 bytes."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        with pytest.raises(struct.error):
            BridgeClient.decode_frame_header(b"\x00\x01")

    def test_encode_decode_roundtrip(self):
        """Encode a message, decode the header, verify length matches payload."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        original = {"type": "event", "name": "token", "data": "hello"}
        payload = msgpack.packb(original, use_bin_type=True)
        frame = BridgeClient.encode_frame(payload)

        # Decode the header
        decoded_length = BridgeClient.decode_frame_header(frame[:4])
        assert decoded_length == len(payload)

        # Verify the payload portion is valid msgpack that round-trips
        decoded_msg = msgpack.unpackb(frame[4:], raw=False)
        assert decoded_msg == original

    def test_encode_frame_with_all_message_types(self):
        """Test encoding various event message types."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        messages = [
            {"type": "event", "name": "hello", "data": {"version": "1.0"}},
            {"type": "event", "name": "token", "data": "some text"},
            {"type": "event", "name": "tool_call_start", "data": {"tool": "read_file"}},
            {"type": "event", "name": "tool_call_end", "data": {"duration_ms": 42.5}},
            {"type": "event", "name": "agent_run_start", "data": {"agent": "husky"}},
            {"type": "event", "name": "agent_run_end", "data": {"success": True}},
            {"type": "event", "name": "goodbye", "data": {"reason": "shutdown"}},
        ]

        for msg in messages:
            payload = msgpack.packb(msg, use_bin_type=True)
            frame = BridgeClient.encode_frame(payload)

            # Verify header
            length = BridgeClient.decode_frame_header(frame[:4])
            assert length == len(payload), f"Length mismatch for {msg['name']}"

            # Verify payload round-trips
            decoded = msgpack.unpackb(frame[4:], raw=False)
            assert decoded == msg, f"Round-trip failed for {msg['name']}"

    def test_encode_frame_large_payload(self):
        """Frame encoding should work for large payloads."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        large_data = {"text": "x" * 100_000}
        payload = msgpack.packb(large_data, use_bin_type=True)
        frame = BridgeClient.encode_frame(payload)

        length = BridgeClient.decode_frame_header(frame[:4])
        assert length == len(payload)
        assert len(frame) == 4 + len(payload)


# ===================================================================
# 2. BridgeClient unit tests (no actual socket)
# ===================================================================


class TestBridgeClient:
    """Unit tests for BridgeClient with mocked sockets."""

    def test_bridge_client_init(self):
        """Client initializes with correct defaults (host, port, not connected)."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        assert client._host == "127.0.0.1"
        assert client._port == 9847
        assert client._timeout == 5.0
        assert not client.is_connected
        assert client._sock is None
        assert client._closed is False
        # Queue should be empty
        assert client._send_queue.empty()

    def test_bridge_client_init_custom_params(self):
        """Client accepts custom host, port, and timeout."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="192.168.1.1", port=9999, timeout=10.0)
        assert client._host == "192.168.1.1"
        assert client._port == 9999
        assert client._timeout == 10.0

    def test_bridge_client_connect_failure_graceful(self):
        """Connecting to a non-existent server should return False, not crash."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        # Use a port that nothing is listening on
        client = BridgeClient(port=1)  # port 1 is reserved/unlikely to be open
        result = client.connect()
        assert result is False
        assert not client.is_connected

    def test_bridge_client_send_event_builds_correct_schema(self):
        """send_event should enqueue a message with id, type, name, and data keys."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client.send_event("token", {"text": "hello"})

        # Message should be in the queue
        assert not client._send_queue.empty()
        msg = client._send_queue.get_nowait()

        assert "id" in msg
        assert len(msg["id"]) == 36  # UUID format: 8-4-4-4-12
        assert msg["type"] == "event"
        assert msg["name"] == "token"
        assert msg["data"] == {"text": "hello"}

    def test_bridge_client_send_event_generates_unique_ids(self):
        """Each send_event call should produce a unique message ID."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client.send_event("token", "first")
        client.send_event("token", "second")

        msg1 = client._send_queue.get_nowait()
        msg2 = client._send_queue.get_nowait()

        assert msg1["id"] != msg2["id"]

    def test_bridge_client_queue_drops_when_full(self):
        """When queue is full (10000), messages are dropped without error."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()

        # Fill the queue to maxsize (10000)
        maxsize = client._send_queue.maxsize
        for i in range(maxsize):
            client.send_event("token", f"msg-{i}")

        assert client._send_queue.full()

        # This should NOT raise — message is silently dropped
        client.send_event("token", "overflow-msg")

        # Queue should still be at maxsize
        assert client._send_queue.qsize() == maxsize

    def test_bridge_client_send_event_after_close(self):
        """send_event should be a no-op after close()."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client.close()
        client.send_event("token", "should be ignored")
        # close() puts a sentinel on the queue, but no user messages
        # Queue should have at most 1 item (the sentinel)
        assert client._send_queue.qsize() <= 1

    def test_bridge_client_close_without_connect(self):
        """close() should be safe to call even if connect() was never called."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        # Should not raise
        client.close()
        assert not client.is_connected

    def test_bridge_client_close_is_idempotent(self):
        """Calling close() multiple times should not crash."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client.close()
        client.close()
        client.close()
        assert not client.is_connected


# ===================================================================
# 3. Callback registration tests
# ===================================================================


class TestCallbackRegistration:
    """Tests for mana_bridge callback registration behavior."""

    def _reload_register_callbacks(self):
        """Force re-import of the register_callbacks module."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        importlib.reload(rc_mod)
        return rc_mod

    def test_callbacks_registered_on_import(self):
        """Importing the module should register mana bridge callbacks."""
        clear_callbacks()
        # Ensure bridge env is not set so startup doesn't try to connect
        os.environ.pop("CODE_PUPPY_BRIDGE", None)

        self._reload_register_callbacks()

        # The module registers these hooks unconditionally
        expected_hooks = [
            "startup",
            "shutdown",
            "stream_event",
            "agent_run_start",
            "agent_run_end",
            "pre_tool_call",
            "post_tool_call",
        ]
        for hook in expected_hooks:
            cbs = get_callbacks(hook)
            # At least one callback should be registered for each hook
            assert len(cbs) >= 1, f"Expected callback for '{hook}' but got {len(cbs)}"

    def test_callbacks_registered_when_bridge_enabled(self, _preserve_bridge_env):
        """With CODE_PUPPY_BRIDGE=1, callbacks are registered and startup connects."""
        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        self._reload_register_callbacks()

        # Callbacks should be registered
        assert count_callbacks("startup") >= 1
        assert count_callbacks("shutdown") >= 1
        assert count_callbacks("stream_event") >= 1

    def test_startup_callback_connects_when_enabled(self, _preserve_bridge_env):
        """The startup callback should attempt to connect when bridge is enabled."""
        import asyncio

        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        # Trigger the startup callback
        # Since no Mana server is running, connect will return False
        # but the callback should not crash
        startup_cbs = get_callbacks("startup")
        for cb in startup_cbs:
            # The callback is _on_startup from register_callbacks (sync)
            if asyncio.iscoroutinefunction(cb):
                asyncio.run(cb())
            else:
                cb()

    def test_callbacks_not_registered_when_bridge_disabled(self, _preserve_bridge_env):
        """Without CODE_PUPPY_BRIDGE, _on_startup is still registered but is a no-op.

        Note: The current implementation always registers callbacks on import.
        The env var only controls whether _on_startup() actually connects.
        This test verifies that the startup callback doesn't create a client
        when the bridge is disabled.
        """
        clear_callbacks()
        os.environ.pop("CODE_PUPPY_BRIDGE", None)

        rc_mod = self._reload_register_callbacks()

        # Callbacks are still registered (module always registers)
        assert count_callbacks("startup") >= 1

        # But invoking _on_startup should NOT create a client
        # since _is_enabled() returns False
        startup_cbs = get_callbacks("startup")
        for cb in startup_cbs:
            cb()

        # The _client singleton should remain None
        assert rc_mod._client is None

    def test_graceful_fallback_when_mana_not_running(self, _preserve_bridge_env):
        """Bridge enables but Mana not running → warning logged, no crash."""
        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        # Trigger startup — no Mana server is actually listening.
        # This should NOT raise — the bridge handles connection failure gracefully.
        startup_cbs = get_callbacks("startup")
        for cb in startup_cbs:
            cb()

        # The client should exist (was created) but not be connected
        assert rc_mod._client is not None
        assert not rc_mod._client.is_connected

        # Cleanup
        rc_mod._on_shutdown()

    def test_stream_event_callback_does_not_crash_without_client(self):
        """Stream event callback should be a no-op when no client exists."""
        import asyncio

        clear_callbacks()
        os.environ.pop("CODE_PUPPY_BRIDGE", None)

        rc_mod = self._reload_register_callbacks()

        # _client should be None since bridge is disabled
        assert rc_mod._client is None

        # Trigger a stream event — should not crash.
        # The callback is async, so use asyncio.run() to invoke it.
        stream_cbs = get_callbacks("stream_event")
        for cb in stream_cbs:
            asyncio.run(
                cb("token", "some text", agent_session_id="test-session")
            )

    def test_shutdown_callback_cleans_up_client(self, _preserve_bridge_env):
        """Shutdown callback should close and null out the client."""
        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        # Trigger startup (will fail to connect, but creates client)
        startup_cbs = get_callbacks("startup")
        for cb in startup_cbs:
            cb()

        # Client should exist even though not connected
        assert rc_mod._client is not None

        # Trigger shutdown
        shutdown_cbs = get_callbacks("shutdown")
        for cb in shutdown_cbs:
            cb()

        # Client should be cleaned up
        assert rc_mod._client is None

    def test_sanitize_args_trims_long_strings(self):
        """_sanitize_args should trim strings longer than 500 chars."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _sanitize_args

        args = {
            "short": "hello",
            "long": "x" * 1000,
            "number": 42,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"a": 1},
        }

        result = _sanitize_args(args)

        assert result["short"] == "hello"
        assert len(result["long"]) == 500  # trimmed to 500 (497 + "...")
        assert result["long"].endswith("...")
        assert result["number"] == 42
        assert result["bool"] is True
        assert result["none"] is None
        assert result["list"] == "<list[3]>"
        assert result["dict"] == "<dict[1]>"

    def test_sanitize_args_with_non_dict_input(self):
        """_sanitize_args should return empty dict for non-dict input."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _sanitize_args

        assert _sanitize_args("not a dict") == {}
        assert _sanitize_args(None) == {}
        assert _sanitize_args(42) == {}

    def test_is_successful_heuristic(self):
        """_is_successful should correctly classify result types."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _is_successful

        assert _is_successful(None) is True
        assert _is_successful({"status": "ok"}) is True
        assert _is_successful({"error": "something failed"}) is False
        assert _is_successful({"success": False}) is False
        assert _is_successful(True) is True
        assert _is_successful(False) is False
        assert _is_successful("any string") is True

    def test_summarize_result_various_types(self):
        """_summarize_result should produce readable one-line summaries."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _summarize_result

        assert _summarize_result(None) == "<no result>"
        assert _summarize_result("short") == "short"
        assert _summarize_result("x" * 300).endswith("...")
        assert _summarize_result({"error": "boom"}) == "Error: boom"
        assert _summarize_result({"message": "hi"}) == "hi"
        assert _summarize_result({"a": 1, "b": 2}) == "<dict with 2 keys>"
        assert _summarize_result([1, 2, 3]) == "<list[3]>"
        assert _summarize_result(42) == "42"
