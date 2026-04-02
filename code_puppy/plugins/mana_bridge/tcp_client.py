"""TCP client for the Mana bridge.

Manages a persistent TCP connection to Mana LiveView on localhost:9847,
sending msgpack-framed event messages.  Includes reconnect logic with
exponential backoff and a background sender thread for non-blocking writes.
"""

from __future__ import annotations

import logging
import os
import queue
import socket
import struct
import threading
import time
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_BRIDGE_HOST = os.environ.get("CODE_PUPPY_BRIDGE_HOST", "127.0.0.1")
_BRIDGE_PORT = int(os.environ.get("CODE_PUPPY_BRIDGE_PORT", "9847"))
_DEFAULT_TIMEOUT = 5.0  # seconds for socket connect/send

# Reconnect backoff constants
_INITIAL_BACKOFF = 0.5
_MAX_BACKOFF = 30.0
_BACKOFF_MULTIPLIER = 2.0

# Sentinel to signal the sender thread to exit
_SENTINEL = object()


class BridgeClient:
    """Thread-safe TCP client that sends msgpack-framed events to Mana.

    Usage::

        client = BridgeClient()
        client.connect()
        client.send_event("hello", {"version": "1.0"})
        ...
        client.close()
    """

    def __init__(
        self,
        host: str = _BRIDGE_HOST,
        port: int = _BRIDGE_PORT,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._send_queue: queue.Queue[Any] = queue.Queue(maxsize=10_000)
        self._sender_thread: threading.Thread | None = None
        self._connected = False
        self._closed = False
        self._backoff = _INITIAL_BACKOFF

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Open a TCP connection to Mana and start the sender thread.

        Returns True if the connection was established, False otherwise.
        Logs a warning on failure but never raises.
        """
        try:
            import msgpack
        except ImportError:
            logger.warning(
                "msgpack is not installed — Mana bridge disabled. "
                "Install with: pip install msgpack"
            )
            return False

        self._msgpack = msgpack  # stash for use in sender thread

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._timeout)
            sock.connect((self._host, self._port))
            sock.settimeout(None)  # switch to blocking for sends

            with self._lock:
                self._sock = sock
                self._connected = True
                self._backoff = _INITIAL_BACKOFF

            # Start background sender thread
            self._sender_thread = threading.Thread(
                target=self._sender_loop,
                name="mana-bridge-sender",
                daemon=True,
            )
            self._sender_thread.start()

            logger.info("Mana bridge connected to %s:%s", self._host, self._port)
            return True

        except OSError as exc:
            self._connected = False
            logger.warning(
                "Mana bridge failed to connect to %s:%s — %s. "
                "Bridge events will be dropped until reconnection.",
                self._host,
                self._port,
                exc,
            )
            return False

    def close(self) -> None:
        """Gracefully close the connection and stop the sender thread."""
        with self._lock:
            self._closed = True
            self._connected = False
            sock = self._sock
            self._sock = None

        # Signal the sender thread to exit
        try:
            self._send_queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass

        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        if self._sender_thread and self._sender_thread.is_alive():
            self._sender_thread.join(timeout=3.0)

        logger.info("Mana bridge closed")

    @property
    def is_connected(self) -> bool:
        """Return whether the socket is currently connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_event(self, name: str, data: Any = None) -> None:
        """Enqueue an event message for transmission to Mana.

        This method is non-blocking.  If the internal queue is full the
        message is silently dropped.

        Args:
            name: Event name (e.g. "token", "tool_call_start").
            data: Arbitrary msgpack-serializable payload.
        """
        if self._closed:
            return

        msg: dict[str, Any] = {
            "id": str(uuid4()),
            "type": "event",
            "name": name,
            "data": data,
        }
        try:
            self._send_queue.put_nowait(msg)
        except queue.Full:
            logger.debug("Mana bridge send queue full — dropping '%s'", name)

    # ------------------------------------------------------------------
    # Internal sender loop
    # ------------------------------------------------------------------

    def _sender_loop(self) -> None:
        """Background thread that drains the send queue and writes frames."""
        while True:
            item = self._send_queue.get()

            if item is _SENTINEL:
                break

            if not self._connected:
                # Try reconnecting before discarding the message
                self._try_reconnect()
                if not self._connected:
                    self._send_queue.task_done()
                    continue

            if self._send_frame(item) is False:
                # Send failed — mark disconnected
                with self._lock:
                    self._connected = False

            self._send_queue.task_done()

    def _send_frame(self, payload: dict[str, Any]) -> bool:
        """Encode *payload* as a msgpack frame and write it to the socket.

        Returns True on success, False on failure.
        """
        with self._lock:
            sock = self._sock
        if sock is None:
            return False

        try:
            packed = self._msgpack.packb(payload, use_bin_type=True)
            header = struct.pack(">I", len(packed))
            sock.sendall(header + packed)
            return True
        except (OSError, struct.error) as exc:
            logger.debug("Mana bridge send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    def _try_reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        if self._closed:
            return

        backoff = self._backoff
        logger.debug(
            "Mana bridge reconnecting in %.1fs …",
            backoff,
        )
        time.sleep(min(backoff, _MAX_BACKOFF))

        # Increase backoff for next attempt
        with self._lock:
            self._backoff = min(self._backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF)

        if self.connect():
            # Reset backoff on successful reconnect
            with self._lock:
                self._backoff = _INITIAL_BACKOFF

    # ------------------------------------------------------------------
    # Static helpers (exposed for tests)
    # ------------------------------------------------------------------

    @staticmethod
    def encode_frame(payload: bytes) -> bytes:
        """Encode *payload* with a 4-byte big-endian length header."""
        return struct.pack(">I", len(payload)) + payload

    @staticmethod
    def decode_frame_header(data: bytes) -> int:
        """Decode the 4-byte big-endian length header.

        Raises ``struct.error`` if *data* is shorter than 4 bytes.
        """
        return struct.unpack(">I", data[:4])[0]
