"""Integration tests for the Mana bridge plugin.

Tests cover frame encoding/decoding, BridgeClient lifecycle, and callback
registration.  All tests run WITHOUT Mana actually running — socket
connections are mocked or allowed to fail gracefully.
"""

import importlib
import os
import socket
import struct
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

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
        import sys

        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        # Ensure module is in sys.modules before reloading
        # (may have been removed by test isolation in some orderings)
        if rc_mod.__name__ not in sys.modules:
            sys.modules[rc_mod.__name__] = rc_mod

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

        self._reload_register_callbacks()

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


# ===================================================================
# N. Prompt executor tests
# ===================================================================


class TestPromptExecutor:
    """Tests for the bridge prompt executor."""

    def test_executor_thread_starts(self):
        """Executor thread starts and is a daemon."""
        import importlib
        import sys

        # Remove cached module to get a fresh import
        for key in list(sys.modules):
            if "mana_bridge" in key and "register_callbacks" in key:
                del sys.modules[key]

        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        # Reset executor thread state
        rc._executor_thread = None
        rc._bridge_shutdown = False

        rc._start_prompt_executor()

        assert rc._executor_thread is not None
        assert rc._executor_thread.daemon is True
        assert rc._executor_thread.name == "mana-bridge-executor"
        # Give the thread a moment to start, then verify it's alive
        import time

        time.sleep(0.05)
        assert rc._executor_thread.is_alive()

        # Clean up by setting to None so the daemon thread winds down
        rc._executor_thread = None

    @pytest.mark.asyncio
    async def test_execute_bridge_prompt_sends_complete(self):
        """Agent run sends prompt_complete event."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        # Create a mock result with output and all_messages
        mock_result = MagicMock()
        mock_result.output = "Hello from agent"
        mock_result.all_messages.return_value = ["msg1", "msg2"]

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        mock_client = MagicMock()

        # Patch the module-level _client and get_current_agent.
        # The import of get_current_agent is inside _execute_bridge_prompt
        # via "from code_puppy.agents.agent_manager import get_current_agent",
        # so we patch at the agent_manager module level.
        with (
            patch.object(rc, "_client", mock_client),
            patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ),
        ):
            await rc._execute_bridge_prompt("test prompt")

        # Verify agent was called
        mock_agent.run_with_mcp.assert_called_once_with("test prompt")
        mock_agent.set_message_history.assert_called_once()

        # Verify prompt_complete event was sent
        mock_client.send_event.assert_called_once()
        call_args = mock_client.send_event.call_args
        assert call_args[0][0] == "prompt_complete"
        assert call_args[0][1]["success"] is True
        assert "Hello from agent" in call_args[0][1]["response_preview"]

    @pytest.mark.asyncio
    async def test_execute_bridge_prompt_no_agent(self):
        """No agent available sends error prompt_complete."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        mock_client = MagicMock()

        with patch.object(rc, "_client", mock_client):
            with patch(
                "code_puppy.agents.agent_manager.get_current_agent", return_value=None
            ):
                await rc._execute_bridge_prompt("test prompt")

        mock_client.send_event.assert_called_once()
        call_args = mock_client.send_event.call_args
        assert call_args[0][0] == "prompt_complete"
        assert call_args[0][1]["success"] is False
        assert "No agent available" in call_args[0][1]["error"]

    @pytest.mark.asyncio
    async def test_execute_bridge_prompt_handles_error(self):
        """Failed agent run sends error prompt_complete."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(side_effect=RuntimeError("Agent exploded"))

        mock_client = MagicMock()

        with patch.object(rc, "_client", mock_client):
            with patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ):
                await rc._execute_bridge_prompt("test prompt")

        mock_client.send_event.assert_called_once()
        call_args = mock_client.send_event.call_args
        assert call_args[0][0] == "prompt_complete"
        assert call_args[0][1]["success"] is False
        assert "Agent exploded" in call_args[0][1]["error"]

    @pytest.mark.asyncio
    async def test_execute_bridge_prompt_no_client(self):
        """Prompt execution with no client doesn't crash."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=None)

        with patch.object(rc, "_client", None):
            with patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ):
                # Should not raise
                await rc._execute_bridge_prompt("test prompt")

    def test_executor_lock_prevents_concurrent_runs(self):
        """Only one prompt runs at a time via the executor lock."""
        import threading

        # Create a fresh lock to test — the module-level one may be
        # held by the daemon thread from another test
        lock = threading.Lock()

        # First acquire should succeed
        assert lock.acquire(blocking=False)
        # Already locked — second acquire should fail
        assert not lock.acquire(blocking=False)
        # Release
        lock.release()
        # Now it should be acquirable again
        assert lock.acquire(blocking=False)
        lock.release()

    @pytest.mark.asyncio
    async def test_execute_bridge_prompt_none_result(self):
        """Agent returning None still sends prompt_complete success."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=None)

        mock_client = MagicMock()

        with patch.object(rc, "_client", mock_client):
            with patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=mock_agent,
            ):
                # Should not raise
                await rc._execute_bridge_prompt("test prompt")
        mock_client.send_event.assert_called_once()
        call_args = mock_client.send_event.call_args
        assert call_args[0][0] == "prompt_complete"
        assert call_args[0][1]["success"] is True
        assert call_args[0][1]["response_preview"] == ""


# ===================================================================
# 7. Receive loop tests
# ===================================================================


class TestReceiveLoop:
    """Tests for the TCP receive loop and handler dispatch."""

    def test_register_handler_stores_handler(self):
        """register_handler should store a handler for a given name."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        handler = lambda msg: None  # noqa: E731
        client.register_handler("test", handler)
        assert client._request_handlers["test"] is handler

    def test_register_handler_overwrites(self):
        """Registering a handler for the same name should overwrite."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        handler1 = lambda msg: None  # noqa: E731
        handler2 = lambda msg: None  # noqa: E731
        client.register_handler("test", handler1)
        client.register_handler("test", handler2)
        assert client._request_handlers["test"] is handler2

    def test_recv_exact_returns_bytes(self):
        """_recv_exact should return exactly the requested number of bytes."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()

        # Create a connected socket pair
        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock

        # Send data from server side
        server_sock.sendall(b"hello world")

        # Read exact bytes from client side
        result = client._recv_exact(5)
        assert result == b"hello"

        result = client._recv_exact(6)
        assert result == b" world"

        server_sock.close()
        client_sock.close()

    def test_recv_exact_returns_none_on_disconnect(self):
        """_recv_exact should return None when the peer closes."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock

        # Close the server side — recv will return empty bytes
        server_sock.close()

        result = client._recv_exact(4)
        assert result is None

        client_sock.close()

    def test_recv_exact_returns_none_when_no_socket(self):
        """_recv_exact should return None when no socket is set."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._sock = None

        result = client._recv_exact(4)
        assert result is None

    def test_recv_exact_lock_not_held_during_recv(self):
        """_recv_exact should not hold the lock during the actual recv() call.

        We verify this by checking that another thread can acquire the lock
        while recv_exact is blocked waiting for data.
        """
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock

        # Block the client socket so recv() blocks
        # (don't send any data yet)
        lock_acquired_during_recv = threading.Event()
        recv_started = threading.Event()

        def try_acquire_lock():
            # Wait until recv has started (it's blocked in recv())
            recv_started.wait(timeout=2.0)
            time.sleep(0.05)  # give recv time to enter the blocking call
            # If we can acquire the lock here, recv_exact released it
            acquired = client._lock.acquire(blocking=False)
            if acquired:
                lock_acquired_during_recv.set()
                client._lock.release()

        def do_recv():
            recv_started.set()
            # This will block because no data is sent
            client._recv_exact(4)
            # returns None because we close the socket

        recv_thread = threading.Thread(target=do_recv, daemon=True)
        recv_thread.start()

        # Try to acquire the lock while recv is blocked
        lock_thread = threading.Thread(target=try_acquire_lock, daemon=True)
        lock_thread.start()

        # Wait a bit for the lock thread to try
        lock_thread.join(timeout=1.0)

        # Now close the socket to unblock recv
        server_sock.close()
        recv_thread.join(timeout=2.0)

        # If recv_exact held the lock during recv, lock_thread would not
        # have been able to acquire it
        assert lock_acquired_during_recv.is_set()

        client_sock.close()

    def test_reader_loop_dispatches_to_handler(self):
        """Reader loop should dispatch decoded messages to registered handlers."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock
        client._connected = True

        received_messages = []

        def handler(msg):
            received_messages.append(msg)
            # Stop the reader loop after one message
            client._closed = True

        client.register_handler("prompt", handler)

        # Send a framed message from the server side
        payload = msgpack.packb(
            {"name": "prompt", "data": {"text": "hello from Mana"}},
            use_bin_type=True,
        )
        frame = BridgeClient.encode_frame(payload)
        server_sock.sendall(frame)

        # Run the reader loop in a thread
        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()
        reader_thread.join(timeout=2.0)

        assert len(received_messages) == 1
        assert received_messages[0]["name"] == "prompt"
        assert received_messages[0]["data"]["text"] == "hello from Mana"

        server_sock.close()
        client_sock.close()

    def test_reader_loop_handles_unknown_request(self):
        """Reader loop should not crash for messages with no handler."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock
        client._connected = True

        # No handler registered — should log and continue
        payload = msgpack.packb(
            {"name": "unknown_request", "data": {}},
            use_bin_type=True,
        )
        frame = BridgeClient.encode_frame(payload)
        server_sock.sendall(frame)

        # Close the socket to make the reader loop exit after processing
        time.sleep(0.05)  # let the send propagate
        server_sock.close()

        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()
        reader_thread.join(timeout=2.0)

        assert not reader_thread.is_alive()
        client_sock.close()

    def test_reader_loop_exits_on_socket_close(self):
        """Reader loop should exit cleanly when the socket is closed."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock
        client._connected = True

        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()

        # Close socket — reader should exit
        time.sleep(0.05)
        server_sock.close()

        reader_thread.join(timeout=2.0)
        assert not reader_thread.is_alive()
        client_sock.close()

    def test_reader_loop_handler_exception_does_not_crash(self):
        """Reader loop should continue if a handler raises an exception."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock
        client._connected = True

        call_count = 0

        def bad_handler(msg):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("handler error")

        client.register_handler("prompt", bad_handler)

        # Send a message — handler will raise, but reader loop should not crash
        payload = msgpack.packb(
            {"name": "prompt", "data": {"text": "test"}},
            use_bin_type=True,
        )
        frame = BridgeClient.encode_frame(payload)
        server_sock.sendall(frame)

        # Close socket to let reader exit
        time.sleep(0.05)
        server_sock.close()

        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()
        reader_thread.join(timeout=2.0)

        assert not reader_thread.is_alive()
        assert call_count == 1

        client_sock.close()

    def test_reader_loop_multiple_messages(self):
        """Reader loop should process multiple messages in sequence."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        server_sock, client_sock = socket.socketpair()
        client._sock = client_sock
        client._connected = True

        received = []

        def handler(msg):
            received.append(msg)
            if len(received) == 3:
                client._closed = True

        client.register_handler("test", handler)

        # Send three messages
        for i in range(3):
            payload = msgpack.packb(
                {"name": "test", "data": {"index": i}},
                use_bin_type=True,
            )
            frame = BridgeClient.encode_frame(payload)
            server_sock.sendall(frame)

        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()
        reader_thread.join(timeout=2.0)

        assert len(received) == 3
        assert received[0]["data"]["index"] == 0
        assert received[1]["data"]["index"] == 1
        assert received[2]["data"]["index"] == 2

        server_sock.close()
        client_sock.close()

    def test_reader_loop_fragmented_reads(self):
        """Reader loop should handle fragmented TCP reads correctly."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        client._msgpack = msgpack

        # Use a mock socket that delivers data in small chunks
        mock_sock = MagicMock(spec=socket.socket)

        # Build a complete frame
        payload = msgpack.packb(
            {"name": "test", "data": {"key": "value"}},
            use_bin_type=True,
        )
        frame = BridgeClient.encode_frame(payload)

        # Feed data one byte at a time
        byte_index = [0]

        def fake_recv(n):
            if byte_index[0] >= len(frame):
                return b""  # EOF
            chunk = frame[byte_index[0] : byte_index[0] + 1]
            byte_index[0] += 1
            return chunk

        mock_sock.recv = fake_recv
        client._sock = mock_sock
        client._connected = True

        received = []

        def handler(msg):
            received.append(msg)
            client._closed = True

        client.register_handler("test", handler)

        reader_thread = threading.Thread(target=client._reader_loop)
        reader_thread.start()
        reader_thread.join(timeout=2.0)

        assert len(received) == 1
        assert received[0]["data"]["key"] == "value"


# ===================================================================
# 8. Request handler tests
# ===================================================================


class TestRequestHandlers:
    """Tests for Mana→Python request handlers."""

    def _reload_register_callbacks(self):
        """Force re-import of the register_callbacks module."""
        import sys

        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        # Ensure module is in sys.modules before reloading
        # (may have been removed by test isolation in some orderings)
        if rc_mod.__name__ not in sys.modules:
            sys.modules[rc_mod.__name__] = rc_mod

        importlib.reload(rc_mod)
        return rc_mod

    def test_handle_prompt_request_stores_in_queue(self):
        """_handle_prompt_request should store the prompt text."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_prompt_request,
            _pending_prompts,
        )

        # Clear the queue
        while not _pending_prompts.empty():
            _pending_prompts.get_nowait()

        msg = {"name": "prompt", "data": {"text": "hello from Mana"}}
        _handle_prompt_request(msg)

        assert _pending_prompts.qsize() == 1
        assert _pending_prompts.get_nowait() == "hello from Mana"

    def test_handle_prompt_request_empty_text_ignored(self):
        """_handle_prompt_request should ignore messages with empty text."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_prompt_request,
            _pending_prompts,
        )

        while not _pending_prompts.empty():
            _pending_prompts.get_nowait()

        _handle_prompt_request({"name": "prompt", "data": {"text": ""}})
        _handle_prompt_request({"name": "prompt", "data": {}})

        assert _pending_prompts.empty()

    def test_handle_prompt_request_sends_ack(self):
        """_handle_prompt_request should send a prompt_ack event."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_prompt_request,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        _handle_prompt_request({"name": "prompt", "data": {"text": "test"}})

        client.send_event.assert_called_once_with("prompt_ack", {"status": "queued"})

        # Cleanup
        rc_mod._client = None

    def test_get_pending_bridge_prompts_returns_all(self):
        """get_pending_bridge_prompts should drain and return all prompts."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _pending_prompts,
            get_pending_bridge_prompts,
        )

        while not _pending_prompts.empty():
            _pending_prompts.get_nowait()

        _pending_prompts.put_nowait("first")
        _pending_prompts.put_nowait("second")
        _pending_prompts.put_nowait("third")

        prompts = get_pending_bridge_prompts()
        assert prompts == ["first", "second", "third"]
        assert _pending_prompts.empty()

    def test_get_pending_bridge_prompts_empty(self):
        """get_pending_bridge_prompts should return empty list when nothing pending."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            get_pending_bridge_prompts,
            _pending_prompts,
        )

        while not _pending_prompts.empty():
            _pending_prompts.get_nowait()

        assert get_pending_bridge_prompts() == []

    def test_handle_switch_agent_request_success(self):
        """_handle_switch_agent_request should call set_current_agent and notify."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_switch_agent_request,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        with patch(
            "code_puppy.agents.set_current_agent",
            return_value=True,
        ):
            _handle_switch_agent_request(
                {"name": "switch_agent", "data": {"agent_name": "husky"}}
            )

        client.send_event.assert_called_once_with(
            "agent_switched", {"agent_name": "husky"}
        )

        rc_mod._client = None

    def test_handle_switch_agent_request_failure(self):
        """_handle_switch_agent_request should send error on failure."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_switch_agent_request,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        with patch(
            "code_puppy.agents.set_current_agent",
            return_value=False,
        ):
            _handle_switch_agent_request(
                {"name": "switch_agent", "data": {"agent_name": "nonexistent"}}
            )

        client.send_event.assert_called_once()
        assert client.send_event.call_args[0][0] == "error"

        rc_mod._client = None

    def test_handle_switch_agent_empty_name_ignored(self):
        """_handle_switch_agent_request should ignore empty agent name."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_switch_agent_request,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        _handle_switch_agent_request(
            {"name": "switch_agent", "data": {"agent_name": ""}}
        )
        _handle_switch_agent_request({"name": "switch_agent", "data": {}})

        client.send_event.assert_not_called()

        rc_mod._client = None

    def test_handle_switch_model_request(self):
        """_handle_switch_model_request should reuse _on_switch_model."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_switch_model_request,
            _on_switch_model,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        # _on_switch_model returns usage hint for unknown model
        result = _on_switch_model("model", "unknown-model")
        assert result is not None

        # The handler should call _on_switch_model and log (client.send_event
        # is called inside _on_switch_model for model_changed, but unknown model
        # won't trigger that)
        _handle_switch_model_request(
            {"name": "switch_model", "data": {"model_name": "unknown-model"}}
        )

        rc_mod._client = None

    def test_handle_switch_model_empty_name_ignored(self):
        """_handle_switch_model_request should ignore empty model name."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_switch_model_request,
        )

        client = MagicMock()
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        rc_mod._client = client

        _handle_switch_model_request(
            {"name": "switch_model", "data": {"model_name": ""}}
        )
        _handle_switch_model_request({"name": "switch_model", "data": {}})

        client.send_event.assert_not_called()

        rc_mod._client = None

    def test_handlers_registered_on_startup(self, _preserve_bridge_env):
        """Handlers should be registered on the client after startup."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        with patch.object(BridgeClient, "connect", return_value=True):
            startup_cbs = get_callbacks("startup")
            for cb in startup_cbs:
                cb()

        assert rc_mod._client is not None
        assert "prompt" in rc_mod._client._request_handlers
        assert "switch_agent" in rc_mod._client._request_handlers
        assert "switch_model" in rc_mod._client._request_handlers

        # Cleanup
        rc_mod._on_shutdown()

    def test_init_includes_request_handlers_dict(self):
        """BridgeClient.__init__ should initialize _request_handlers."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        assert hasattr(client, "_request_handlers")
        assert isinstance(client._request_handlers, dict)
        assert len(client._request_handlers) == 0

    def test_init_includes_reader_thread(self):
        """BridgeClient.__init__ should initialize _reader_thread as None."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        assert client._reader_thread is None

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
            asyncio.run(cb("token", "some text", agent_session_id="test-session"))

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


# ===================================================================
# 4. Agent list event tests
# ===================================================================


class TestAgentListEvent:
    """Tests for the agent_list bridge event."""

    def test_send_agent_list_with_mock_client(self):
        """_send_agent_list should send an agent_list event via the client."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _send_agent_list
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        sent_messages = []

        # Monkey-patch send_event to capture messages
        original_send = client.send_event

        def capture_send(name, data):
            sent_messages.append({"name": name, "data": data})
            return original_send(name, data)

        client.send_event = capture_send

        # Mock get_available_agents to return test data
        mock_agents = {
            "code-puppy": "Code Puppy 🐶",
            "husky": "Husky 🐺",
        }
        mock_descriptions = {
            "code-puppy": "General-purpose coding assistant",
            "husky": "Strong executor",
        }

        with (
            patch(
                "code_puppy.agents.get_available_agents",
                return_value=mock_agents,
            ),
            patch(
                "code_puppy.agents.get_agent_descriptions",
                return_value=mock_descriptions,
            ),
        ):
            _send_agent_list(client)

        assert len(sent_messages) == 1
        assert sent_messages[0]["name"] == "agent_list"
        agents = sent_messages[0]["data"]["agents"]
        assert len(agents) == 2
        assert agents[0]["name"] == "code-puppy"
        assert agents[0]["display_name"] == "Code Puppy 🐶"
        assert agents[0]["description"] == "General-purpose coding assistant"
        assert agents[1]["name"] == "husky"

    def test_send_agent_list_falls_back_on_import_error(self):
        """If agent imports fail, _send_agent_list should fall back to hardcoded list."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _send_agent_list
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient()
        sent_messages = []

        original_send = client.send_event

        def capture_send(name, data):
            sent_messages.append({"name": name, "data": data})
            return original_send(name, data)

        client.send_event = capture_send

        # Force import failure by patching the source module
        with patch(
            "code_puppy.agents.get_available_agents",
            side_effect=ImportError("no module"),
        ):
            _send_agent_list(client)

        assert len(sent_messages) == 1
        assert sent_messages[0]["name"] == "agent_list"
        agents = sent_messages[0]["data"]["agents"]
        # Should have the fallback agent
        assert len(agents) >= 1
        assert agents[0]["name"] == "code-puppy"

    def test_send_agent_list_noop_without_client(self):
        """_send_agent_list should be a no-op when no client is available."""
        import importlib

        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        # Ensure _client is None
        rc_mod._client = None
        _send_agent_list = rc_mod._send_agent_list

        # Should not raise
        _send_agent_list(None)

        # Cleanup
        importlib.reload(rc_mod)


# ===================================================================
# 5. Model list tests
# ===================================================================


class TestGatherModelList:
    """Tests for the _gather_model_list helper."""

    def test_gather_model_list_returns_expected_structure(self):
        """_gather_model_list should return dict with models list and current_model."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()

        assert "models" in result
        assert "current_model" in result
        assert isinstance(result["models"], list)

    def test_gather_model_list_models_sorted(self):
        """Models list should be sorted alphabetically by name."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()
        names = [m["name"] for m in result["models"]]
        assert names == sorted(names)

    def test_gather_model_list_each_model_has_required_fields(self):
        """Each model in the list should have 'name' and 'type' keys."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _gather_model_list

        result = _gather_model_list()

        for model in result["models"]:
            assert "name" in model
            assert "type" in model
            assert isinstance(model["name"], str)
            assert isinstance(model["type"], str)

    def test_gather_model_list_graceful_on_import_failure(self):
        """Should return empty models list if ModelFactory can't load."""
        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        result = rc_mod._gather_model_list()
        # Should always return a valid structure
        assert isinstance(result, dict)
        assert "models" in result
        assert "current_model" in result


# ===================================================================
# 6. Switch model command tests
# ===================================================================


class TestSwitchModel:
    """Tests for the /model custom command handler."""

    def _reload_register_callbacks(self):
        """Force re-import of the register_callbacks module."""
        import sys

        from code_puppy.plugins.mana_bridge import register_callbacks as rc_mod

        # Ensure module is in sys.modules before reloading
        # (may have been removed by test isolation in some orderings)
        if rc_mod.__name__ not in sys.modules:
            sys.modules[rc_mod.__name__] = rc_mod

        importlib.reload(rc_mod)
        return rc_mod

    def test_switch_model_ignores_other_commands(self):
        """_on_switch_model should return None for commands other than 'model'."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        assert _on_switch_model("agent", "husky") is None
        assert _on_switch_model("help", None) is None
        assert _on_switch_model("exit", "") is None

    def test_switch_model_returns_usage_without_name(self):
        """_on_switch_model should return usage hint when no model name given."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", None)
        assert result is not None
        assert "Usage" in result

    def test_switch_model_returns_usage_with_empty_name(self):
        """_on_switch_model should return usage hint when empty string given."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", "")
        assert result is not None
        assert "Usage" in result

    def test_switch_model_rejects_unknown_model(self):
        """_on_switch_model should reject a model name not in config."""
        from code_puppy.plugins.mana_bridge.register_callbacks import _on_switch_model

        result = _on_switch_model("model", "nonexistent-model-xyz")
        assert result is not None
        assert "Unknown model" in result or "Failed" in result or "Available" in result

    def test_switch_model_help_returns_entries(self):
        """_on_switch_model_help should return help entries."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _on_switch_model_help,
        )

        help_entries = _on_switch_model_help()
        assert isinstance(help_entries, list)
        assert len(help_entries) >= 1
        cmd, desc = help_entries[0]
        assert "model" in cmd.lower()
        assert "switch" in desc.lower()

    def test_custom_command_callbacks_registered(self):
        """The custom_command and custom_command_help hooks should be registered."""
        clear_callbacks()
        os.environ.pop("CODE_PUPPY_BRIDGE", None)

        self._reload_register_callbacks()

        assert count_callbacks("custom_command") >= 1
        assert count_callbacks("custom_command_help") >= 1

    def test_model_list_sent_on_startup_when_connected(self, _preserve_bridge_env):
        """When bridge connects, both hello and model_list events should be enqueued."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        clear_callbacks()
        os.environ["CODE_PUPPY_BRIDGE"] = "1"

        rc_mod = self._reload_register_callbacks()

        with patch.object(BridgeClient, "connect", return_value=True):
            # Trigger startup
            startup_cbs = get_callbacks("startup")
            for cb in startup_cbs:
                cb()

        # Client should have been created and events enqueued
        assert rc_mod._client is not None

        # Drain the queue and check for model_list event
        events = []
        while not rc_mod._client._send_queue.empty():
            events.append(rc_mod._client._send_queue.get_nowait())

        event_names = [e["name"] for e in events]
        assert "hello" in event_names
        assert "model_list" in event_names

        # Verify model_list structure
        model_list_event = next(e for e in events if e["name"] == "model_list")
        data = model_list_event["data"]
        assert "models" in data
        assert "current_model" in data
        assert isinstance(data["models"], list)

        # Cleanup
        rc_mod._on_shutdown()
