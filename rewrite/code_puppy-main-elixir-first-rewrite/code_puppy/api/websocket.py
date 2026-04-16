"""WebSocket endpoints for Code Puppy API.

Provides real-time communication channels:
- /ws/events - Server-sent events stream with per-session history replay
- /ws/terminal - Interactive PTY terminal sessions
- /ws/health - Simple health check endpoint

Session History Replay:
    The /ws/events endpoint supports seamless client reconnection via session
    history. Clients can provide a session_id query parameter:
        ws://localhost:8765/ws/events?session_id=abc123

    When a client reconnects with the same session_id, events for that
    session that were recorded via the history buffer are replayed before
    live streaming resumes. The history buffer size is controlled by the
    ws_history_maxlen config setting (default: 200 events per session).

    Isolation: Only events explicitly recorded for a session are replayed.
    There is no cross-session or global replay: a client that supplies no
    session_id receives live events only, and a client that supplies a
    session_id only sees history for that session.
"""

import asyncio
import base64
import logging
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from code_puppy.api.security import is_trusted_origin

logger = logging.getLogger(__name__)


async def _reject_untrusted_origin(websocket: WebSocket) -> bool:
    """Close the connection if the Origin header isn't in the allow-list.

    Returns True when the connection was rejected.
    """
    origin = websocket.headers.get("origin")
    if not is_trusted_origin(origin):
        logger.warning(
            "Rejecting WebSocket from untrusted origin: %r (path=%s)",
            origin,
            websocket.url.path,
        )
        # Close with 1008 (policy violation) before accepting so the peer
        # sees an immediate failure instead of a half-open socket.
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        return True
    return False


def setup_websocket(app: FastAPI) -> None:
    """Setup WebSocket endpoints for the application."""

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        """Stream real-time events to connected clients with history replay.

        Supports session-based history replay for seamless reconnection.
        Provide session_id as query param: /ws/events?session_id=abc123
        """
        if await _reject_untrusted_origin(websocket):
            return

        await websocket.accept()

        # Extract session_id from query params for history replay
        session_id = websocket.query_params.get("session_id")
        logger.info(f"Events WebSocket client connected (session_id={session_id})")

        from code_puppy.messaging.history_buffer import get_history_buffer
        from code_puppy.plugins.frontend_emitter.emitter import (
            subscribe,
            unsubscribe,
        )

        # Subscribe with session_id filtering - only receive events for this session
        event_queue = subscribe(session_id=session_id)
        history_buffer = get_history_buffer()

        try:
            # Replay session-specific history (if session_id provided).
            #
            # SECURITY: We deliberately do NOT replay a global "recent events"
            # buffer here. Previously this endpoint unconditionally replayed
            # every event that had been emitted across all sessions, which
            # leaked prompt previews and session metadata to any new client.
            # History is now strictly per-session.
            if session_id:
                session_history = history_buffer.get_history(session_id)
                for event in session_history:
                    await websocket.send_json(event)
                logger.debug(
                    f"Replayed {len(session_history)} events for session {session_id}"
                )

            # Live streaming. Recording of events into the per-session
            # history buffer is the responsibility of emit_event's producer
            # side, not this WebSocket handler: allowing any connected
            # client to write into an arbitrary session_id's buffer was
            # another cross-session leak vector.
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        break
        except WebSocketDisconnect:
            logger.info(
                f"Events WebSocket client disconnected (session_id={session_id})"
            )
        except Exception as e:
            logger.error(f"Events WebSocket error (session_id={session_id}): {e}")
        finally:
            unsubscribe(event_queue)
            # Note: We don't clear session history here - it's needed for
            # reconnection scenarios. TTL cleanup handles abandoned sessions.

    async def _queue_output_with_backpressure(
        output_queue: asyncio.Queue,
        data: bytes,
        timeout: float = 1.0,
    ) -> bool:
        """Queue output with backpressure - returns False if queue is full."""
        try:
            await asyncio.wait_for(output_queue.put(data), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"PTY output queue full (size={output_queue.qsize()}), "
                f"dropping {len(data)} bytes"
            )
            return False

    @app.websocket("/ws/terminal")
    async def websocket_terminal(websocket: WebSocket) -> None:
        """Interactive terminal WebSocket endpoint with binary frame support."""
        if await _reject_untrusted_origin(websocket):
            return

        await websocket.accept()
        logger.info("Terminal WebSocket client connected")

        from code_puppy.api.pty_manager import get_pty_manager

        manager = get_pty_manager()
        session_id = str(uuid.uuid4())[:8]
        session = None

        # Get the current event loop for thread-safe scheduling
        loop = asyncio.get_running_loop()

        # Check for binary mode support via query param
        use_binary = websocket.query_params.get("binary", "true").lower() == "true"
        if use_binary:
            logger.debug("Terminal WebSocket using binary frame mode")
        else:
            logger.debug("Terminal WebSocket using legacy JSON/base64 mode")

        # Queue to receive PTY output with larger capacity (was 1000, now 5000)
        # Increased to accommodate coalescing delays
        output_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=5000)

        # Create output callback with proper backpressure handling
        def create_output_callback(
            output_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
        ):
            """Create a callback that safely queues output from the PTY thread."""

            def on_output(data: bytes):
                try:
                    # Use run_coroutine_threadsafe for proper async handling from sync context
                    future = asyncio.run_coroutine_threadsafe(
                        _queue_output_with_backpressure(output_queue, data),
                        loop,
                    )
                    # Don't block waiting for result - fire and forget with logging
                    future.add_done_callback(
                        lambda f: f.exception()
                        and logger.warning(f"Queue error: {f.exception()}")
                    )
                except RuntimeError:
                    # Loop closed - session is shutting down, ignore
                    pass
                except Exception as e:
                    logger.debug(f"Output callback error: {e}")

            return on_output

        async def output_sender_binary() -> None:
            """Send PTY output to WebSocket client using binary frames with coalescing."""
            try:
                while True:
                    # Get first chunk
                    first = await output_queue.get()

                    # Coalesce small chunks within a short window (reduces frame count)
                    batch = bytearray(first)
                    coalesce_deadline = (
                        asyncio.get_event_loop().time() + 0.005
                    )  # 5ms window

                    # Keep coalescing until we hit size limit or deadline
                    while len(batch) < 65536:  # Max 64KB per frame
                        try:
                            remaining = coalesce_deadline - asyncio.get_event_loop().time()
                            if remaining <= 0:
                                break
                            more = await asyncio.wait_for(
                                output_queue.get(),
                                timeout=remaining,
                            )
                            batch.extend(more)
                        except asyncio.TimeoutError:
                            break

                    # Send as binary frame (no base64 encoding overhead)
                    await websocket.send_bytes(bytes(batch))
            except WebSocketDisconnect:
                logger.debug("Output sender: client disconnected")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Binary output sender error: {e}")

        async def output_sender_json() -> None:
            """Send PTY output to WebSocket client using legacy JSON/base64 encoding."""
            try:
                while True:
                    # Get first chunk
                    first = await output_queue.get()

                    # Simple batching for JSON mode (smaller coalescing window)
                    batch = bytearray(first)
                    deadline = asyncio.get_event_loop().time() + 0.002  # 2ms window

                    while len(batch) < 32768:  # Smaller limit for JSON mode
                        try:
                            remaining = deadline - asyncio.get_event_loop().time()
                            if remaining <= 0:
                                break
                            more = await asyncio.wait_for(
                                output_queue.get(),
                                timeout=remaining,
                            )
                            batch.extend(more)
                        except asyncio.TimeoutError:
                            break

                    # Send as JSON with base64 encoding (33% overhead vs binary)
                    await websocket.send_json(
                        {
                            "type": "output",
                            "data": base64.b64encode(bytes(batch)).decode("ascii"),
                        }
                    )
            except WebSocketDisconnect:
                logger.debug("Output sender: client disconnected")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"JSON output sender error: {e}")

        sender_task = None

        try:
            # Create output callback
            on_output = create_output_callback(output_queue, loop)

            # Create PTY session
            session = await manager.create_session(
                session_id=session_id, on_output=on_output
            )

            # Send session info. Key names must match the browser template
            # in code_puppy/api/templates/terminal.html which listens for
            # {"type": "session_started", "session_id": "..."}.
            await websocket.send_json(
                {"type": "session_started", "session_id": session_id}
            )

            # Start appropriate output sender based on negotiated mode
            if use_binary:
                sender_task = asyncio.create_task(output_sender_binary())
            else:
                sender_task = asyncio.create_task(output_sender_json())

            # Handle incoming messages
            while True:
                try:
                    msg = await websocket.receive_json()

                    if msg.get("type") == "input":
                        data = msg.get("data", "")
                        if isinstance(data, str):
                            data = data.encode("utf-8")
                        await manager.write(session_id, data)
                    elif msg.get("type") == "resize":
                        cols = msg.get("cols", 80)
                        rows = msg.get("rows", 24)
                        await manager.resize(session_id, cols, rows)
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Terminal WebSocket error: {e}")
                    break
        except Exception as e:
            logger.error(f"Terminal session error: {e}")
        finally:
            if sender_task:
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass
            if session:
                await manager.close_session(session_id)
            logger.info("Terminal WebSocket disconnected")

    @app.websocket("/ws/health")
    async def websocket_health(websocket: WebSocket) -> None:
        """Simple WebSocket health check - echoes messages back."""
        if await _reject_untrusted_origin(websocket):
            return

        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"echo: {data}")
        except WebSocketDisconnect:
            pass
