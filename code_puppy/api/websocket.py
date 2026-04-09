"""WebSocket endpoints for Code Puppy API.

Provides real-time communication channels:
- /ws/events - Server-sent events stream with per-session history replay
- /ws/terminal - Interactive PTY terminal sessions
- /ws/health - Simple health check endpoint

Session History Replay:
    The /ws/events endpoint supports seamless client reconnection via session
    history. Clients can provide a session_id query parameter:
        ws://localhost:8765/ws/events?session_id=abc123

    When a client reconnects with the same session_id, all events that were
    emitted while disconnected are replayed before live streaming resumes.
    The history buffer size is controlled by the ws_history_maxlen config
    setting (default: 200 events per session).

    Graceful degradation: If no session_id is provided, history replay is
    skipped and the client receives only live events.
"""

import asyncio
import base64
import logging
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


def setup_websocket(app: FastAPI) -> None:
    """Setup WebSocket endpoints for the application."""

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        """Stream real-time events to connected clients with history replay.

        Supports session-based history replay for seamless reconnection.
        Provide session_id as query param: /ws/events?session_id=abc123
        """
        await websocket.accept()

        # Extract session_id from query params for history replay
        session_id = websocket.query_params.get("session_id")
        logger.info(f"Events WebSocket client connected (session_id={session_id})")

        from code_puppy.messaging.history_buffer import get_history_buffer
        from code_puppy.plugins.frontend_emitter.emitter import (
            get_recent_events,
            record_event,
            subscribe,
            unsubscribe,
        )

        event_queue = subscribe()
        history_buffer = get_history_buffer()

        try:
            # Step 1: Replay session-specific history (if session_id provided)
            if session_id:
                session_history = history_buffer.get_history(session_id)
                for event in session_history:
                    await websocket.send_json(event)
                logger.debug(
                    f"Replayed {len(session_history)} events for session {session_id}"
                )

            # Step 2: Replay global recent events (legacy behavior for backward compat)
            recent_events = get_recent_events()
            for event in recent_events:
                await websocket.send_json(event)

            # Step 3: Live streaming with optional session recording
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=30.0)

                    # Record to session history if session_id provided
                    if session_id:
                        record_event(session_id, event)

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
            # reconnection scenarios. Consider adding TTL cleanup later.

    @app.websocket("/ws/terminal")
    async def websocket_terminal(websocket: WebSocket) -> None:
        """Interactive terminal WebSocket endpoint."""
        await websocket.accept()
        logger.info("Terminal WebSocket client connected")

        from code_puppy.api.pty_manager import get_pty_manager

        manager = get_pty_manager()
        session_id = str(uuid.uuid4())[:8]
        session = None

        # Get the current event loop for thread-safe scheduling
        loop = asyncio.get_running_loop()

        # Queue to receive PTY output in a thread-safe way
        output_queue: asyncio.Queue[bytes] = asyncio.Queue()

        # Output callback - called from thread pool, puts data in queue
        def on_output(data: bytes) -> None:
            try:
                loop.call_soon_threadsafe(output_queue.put_nowait, data)
            except Exception as e:
                logger.error(f"on_output error: {e}")

        async def output_sender() -> None:
            """Coroutine that sends queued output to WebSocket."""
            try:
                while True:
                    data = await output_queue.get()
                    await websocket.send_json(
                        {
                            "type": "output",
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"output_sender error: {e}")

        sender_task = None

        try:
            # Create PTY session
            session = await manager.create_session(
                session_id=session_id, on_output=on_output
            )

            # Send session info
            await websocket.send_json({"type": "session", "id": session_id})

            # Start output sender task
            sender_task = asyncio.create_task(output_sender())

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
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"echo: {data}")
        except WebSocketDisconnect:
            pass
