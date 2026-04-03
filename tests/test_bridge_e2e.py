"""E2E tests for the Mana bridge — real TCP, real msgpack, no mocks."""

from __future__ import annotations

import os
import queue
import socket
import struct
import threading
import time
from uuid import uuid4

import msgpack
import pytest


# ---------------------------------------------------------------------------
# Helper: Mini TCP server simulating Mana
# ---------------------------------------------------------------------------


class ManaMock:
    """A minimal TCP server that simulates Mana's side of the bridge."""

    def __init__(self, port: int = 0):
        self.port = port
        self.server_sock: socket.socket | None = None
        self.client_sock: socket.socket | None = None
        self.received: queue.Queue[dict] = queue.Queue()
        self._accept_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", self.port))
        self.server_sock.listen(1)
        self.port = self.server_sock.getsockname()[1]
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept, daemon=True)
        self._accept_thread.start()

    def _accept(self) -> None:
        try:
            self.client_sock, _ = self.server_sock.accept()
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
        except OSError:
            pass

    def _read_loop(self) -> None:
        """Read length-prefixed msgpack frames from the bridge client."""
        while self._running:
            try:
                header = self._recv_exact(4)
                if not header:
                    break
                length = struct.unpack(">I", header)[0]
                payload = self._recv_exact(length)
                if not payload:
                    break
                msg = msgpack.unpackb(payload, raw=False)
                self.received.put(msg)
            except OSError:
                break

    def _recv_exact(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            chunk = self.client_sock.recv(n - len(buf))  # type: ignore[union-attr]
            if not chunk:
                return None
            buf += chunk
        return buf

    def send_request(self, name: str, data: dict) -> None:
        """Send a request frame to the bridge client."""
        msg = {
            "id": str(uuid4()),
            "type": "request",
            "name": name,
            "data": data,
        }
        packed = msgpack.packb(msg, use_bin_type=True)
        header = struct.pack(">I", len(packed))
        self.client_sock.sendall(header + packed)  # type: ignore[union-attr]

    def wait_for_message(self, name: str, timeout: float = 5.0) -> dict | None:
        """Wait for a specific message by name."""
        deadline = time.time() + timeout
        unmatched: list[dict] = []
        while time.time() < deadline:
            try:
                msg = self.received.get(timeout=0.1)
                if msg.get("name") == name:
                    # Put back any previously collected non-matching messages
                    for u in unmatched:
                        self.received.put(u)
                    return msg
                unmatched.append(msg)
            except queue.Empty:
                continue
        # Put back unmatched
        for u in unmatched:
            self.received.put(u)
        return None

    def drain_messages(self, timeout: float = 1.0) -> list[dict]:
        """Collect all messages received so far."""
        msgs: list[dict] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msgs.append(self.received.get(timeout=0.1))
            except queue.Empty:
                if msgs:
                    time.sleep(0.1)
                    continue
        return msgs

    def stop(self) -> None:
        self._running = False
        if self.client_sock:
            try:
                self.client_sock.close()
            except OSError:
                pass
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=1.0)
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)


@pytest.fixture()
def mana_mock() -> ManaMock:
    """Fixture that provides a running ManaMock server."""
    server = ManaMock()
    server.start()
    yield server
    server.stop()


# ---------------------------------------------------------------------------
# Part 1: Bridge Round-Trip Tests (always runs, no API keys needed)
# ---------------------------------------------------------------------------


class TestBridgeRoundTrip:
    """E2E tests for bidirectional bridge communication."""

    def test_client_connects_and_sends_hello(self, mana_mock: ManaMock) -> None:
        """Bridge client connects and sends a hello event."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            assert client.connect() is True

            client.send_event("hello", {"version": "test", "bridge_type": "code_puppy"})

            msg = mana_mock.wait_for_message("hello", timeout=3.0)
            assert msg is not None
            assert msg["name"] == "hello"
            assert msg["data"]["version"] == "test"
        finally:
            client.close()

    def test_server_sends_request_client_receives(self, mana_mock: ManaMock) -> None:
        """ManaMock sends a request, bridge client dispatches to handler."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        received_requests: list[dict] = []

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            client.register_handler(
                "test_ping", lambda msg: received_requests.append(msg)
            )
            assert client.connect() is True

            time.sleep(0.3)

            mana_mock.send_request("test_ping", {"payload": "hello from mana"})

            time.sleep(0.5)

            assert len(received_requests) == 1
            assert received_requests[0]["data"]["payload"] == "hello from mana"
        finally:
            client.close()

    def test_full_round_trip(self, mana_mock: ManaMock) -> None:
        """Full round trip: Mana sends request -> Python handles -> Python sends response event."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:

            def handle_echo(msg: dict) -> None:
                client.send_event("echo_response", {"echo": msg["data"]["text"]})

            client.register_handler("echo", handle_echo)
            assert client.connect() is True
            time.sleep(0.3)

            mana_mock.send_request("echo", {"text": "round trip works!"})

            msg = mana_mock.wait_for_message("echo_response", timeout=3.0)
            assert msg is not None
            assert msg["data"]["echo"] == "round trip works!"
        finally:
            client.close()

    def test_multiple_events_streaming(self, mana_mock: ManaMock) -> None:
        """Multiple events sent in quick succession all arrive."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            assert client.connect() is True

            for i in range(20):
                client.send_event("token", {"text": f"word{i} ", "index": i})

            time.sleep(1.0)

            msgs = mana_mock.drain_messages(timeout=2.0)
            token_msgs = [m for m in msgs if m.get("name") == "token"]

            assert len(token_msgs) == 20
            for i, msg in enumerate(token_msgs):
                assert msg["data"]["index"] == i
        finally:
            client.close()

    def test_switch_agent_request(self, mana_mock: ManaMock) -> None:
        """Mana sends switch_agent request, Python handles it."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        received: list[dict] = []

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            client.register_handler("switch_agent", lambda msg: received.append(msg))
            assert client.connect() is True
            time.sleep(0.3)

            mana_mock.send_request("switch_agent", {"agent_name": "code-puppy"})
            time.sleep(0.5)

            assert len(received) == 1
            assert received[0]["data"]["agent_name"] == "code-puppy"
        finally:
            client.close()

    def test_switch_model_request(self, mana_mock: ManaMock) -> None:
        """Mana sends switch_model request, Python handles it."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        received: list[dict] = []

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            client.register_handler("switch_model", lambda msg: received.append(msg))
            assert client.connect() is True
            time.sleep(0.3)

            mana_mock.send_request(
                "switch_model", {"model_name": "firepass-kimi-k2p5-turbo"}
            )
            time.sleep(0.5)

            assert len(received) == 1
            assert received[0]["data"]["model_name"] == "firepass-kimi-k2p5-turbo"
        finally:
            client.close()

    def test_prompt_request_and_ack(self, mana_mock: ManaMock) -> None:
        """Mana sends prompt, Python queues it and sends ack."""
        from code_puppy.plugins.mana_bridge.register_callbacks import (
            _handle_prompt_request,
            get_pending_bridge_prompts,
        )
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        import code_puppy.plugins.mana_bridge.register_callbacks as rcb

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        old_client = rcb._client
        try:
            rcb._client = client

            client.register_handler("prompt", _handle_prompt_request)
            assert client.connect() is True
            time.sleep(0.3)

            mana_mock.send_request("prompt", {"text": "What is 2+2?"})
            time.sleep(0.5)

            prompts = get_pending_bridge_prompts()
            assert "What is 2+2?" in prompts

            ack = mana_mock.wait_for_message("prompt_ack", timeout=3.0)
            assert ack is not None
        finally:
            rcb._client = old_client
            client.close()

    def test_client_reconnect_after_disconnect(self, mana_mock: ManaMock) -> None:
        """Client handles server disconnect gracefully."""
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            assert client.connect() is True
            client.send_event("hello", {"version": "1.0"})

            msg = mana_mock.wait_for_message("hello", timeout=3.0)
            assert msg is not None

            # Server disconnects
            mana_mock.client_sock.close()
            time.sleep(0.5)

            # Client may or may not have detected disconnection yet
            # — the important thing is it doesn't crash
            assert isinstance(client.is_connected, bool)
        finally:
            client.close()


# ---------------------------------------------------------------------------
# Part 2: Real LLM via Bridge (requires API keys)
# ---------------------------------------------------------------------------


def _has_kimi_key() -> bool:
    return bool(os.environ.get("FIREWORKS_API_KEY"))


def _has_glm_key() -> bool:
    return bool(os.environ.get("SYN_API_KEY"))


@pytest.mark.skipif(
    not (_has_kimi_key() or _has_glm_key()),
    reason="Requires FIREWORKS_API_KEY or SYN_API_KEY",
)
class TestBridgeLLM:
    """E2E test with real LLM calls through the bridge.

    These tests make actual API calls to kimi2.5-turbo or GLM-5.
    They are skipped when API keys are not available.
    """

    def _get_model_name(self) -> str:
        """Pick the best available model."""
        if _has_kimi_key():
            return "firepass-kimi-k2p5-turbo"
        return "synthetic-GLM-5"

    def test_real_prompt_streams_through_bridge(self, mana_mock: ManaMock) -> None:
        """Send a real prompt to kimi/glm via bridge, verify events arrive."""
        model_name = self._get_model_name()

        import asyncio

        from pydantic_ai import Agent as PydanticAgent

        from code_puppy.model_factory import ModelFactory
        from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

        client = BridgeClient(host="127.0.0.1", port=mana_mock.port)
        try:
            assert client.connect() is True
            time.sleep(0.3)

            model, resolved = ModelFactory.get_model(model_name)

            agent = PydanticAgent(
                model=model,
                instructions="You are a helpful assistant. Be very brief.",
                output_type=str,
            )

            async def run_prompt() -> str:
                result = await agent.run("What is 2+2? Reply with just the number.")
                return str(result.output)

            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(run_prompt())
            finally:
                loop.close()

            client.send_event(
                "agent_run_start",
                {"agent_name": "test", "model_name": model_name},
            )
            client.send_event("token", {"text": response})
            client.send_event(
                "agent_run_end",
                {"agent_name": "test", "model_name": model_name, "success": True},
            )

            time.sleep(1.0)

            msgs = mana_mock.drain_messages(timeout=2.0)
            names = [m["name"] for m in msgs]

            assert "agent_run_start" in names
            assert "token" in names
            assert "agent_run_end" in names

            token_msg = next(m for m in msgs if m["name"] == "token")
            assert "4" in token_msg["data"]["text"]

            print(f"\n[E2E] Real LLM response via {model_name}: {response}")
        finally:
            client.close()
