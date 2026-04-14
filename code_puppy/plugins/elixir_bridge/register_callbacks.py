"""Elixir Bridge Plugin - Registers callbacks for bridge mode operation.

This module registers callbacks when CODE_PUPPY_BRIDGE=1 is set, enabling
Python to be controlled by Elixir via JSON-RPC over stdio.

Callbacks registered:
- startup: Initialize bridge and start stdin reader
- shutdown: Cleanup bridge resources
- stream_event: Emit events to stdout in JSON-RPC format

See __init__.py for architecture overview.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.plugins.elixir_bridge import BRIDGE_ENABLED, BRIDGE_LOG_FILE

# Import the bridge components
from .bridge_controller import BridgeController
from .wire_protocol import to_wire_event

# Module-level logger
logger = logging.getLogger(__name__)

# Module-level state - bridge controller instance
_bridge_controller: BridgeController | None = None

# Protocol configuration - can be set to "newline" for backward compatibility
_BRIDGE_PROTOCOL = os.environ.get("CODE_PUPPY_BRIDGE_PROTOCOL", "content-length")

# Line 600 limit compliance - bridge implementation split into submodules


def _log_bridge(message: str, level: str = "info") -> None:
    """Log bridge activity to file if BRIDGE_LOG_FILE is set."""
    if BRIDGE_LOG_FILE:
        try:
            with open(BRIDGE_LOG_FILE, "a") as f:
                f.write(f"[{level}] {message}\\n")
        except Exception:
            pass  # Best effort logging


def _write_framed_message(msg: dict) -> None:
    """Write a JSON-RPC message with Content-Length framing.
    
    Supports backward compatibility via _BRIDGE_PROTOCOL:
    - "content-length": Uses Content-Length framing (default)
    - "newline": Uses newline-delimited JSON
    """
    global _BRIDGE_PROTOCOL
    try:
        if _BRIDGE_PROTOCOL == "newline":
            # Legacy newline-delimited protocol
            json_line = json.dumps(msg, separators=(",", ":"))
            sys.stdout.write(json_line + "\\n")
            sys.stdout.flush()
        else:
            # Content-Length framing (default, protocol spec)
            body = json.dumps(msg, separators=(",", ":"))
            body_bytes = body.encode("utf-8")
            header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
            sys.stdout.buffer.write(header.encode("utf-8"))
            sys.stdout.buffer.write(body_bytes)
            sys.stdout.buffer.flush()
    except Exception as e:
        _log_bridge(f"Failed to write framed message: {e}", "error")


def _read_framed_message(reader: asyncio.StreamReader) -> dict | None:
    """Read a JSON-RPC message with Content-Length framing from reader.
    
    Supports backward compatibility via _BRIDGE_PROTOCOL:
    - "content-length": Uses Content-Length framing (default)
    - "newline": Uses newline-delimited JSON
    
    Returns None on EOF or parse error.
    """
    global _BRIDGE_PROTOCOL
    try:
        if _BRIDGE_PROTOCOL == "newline":
            # Legacy newline-delimited protocol
            line_bytes = reader.readline()
            if not line_bytes:
                return None  # EOF
            line = line_bytes.decode("utf-8").strip()
            if not line:
                return None  # Empty line
            return json.loads(line)
        else:
            # Content-Length framing (default, protocol spec)
            # Read header line (Content-Length: N\r\n)
            header = b""
            while True:
                byte = reader.read(1)
                if not byte:
                    return None  # EOF
                header += byte
                if header.endswith(b"\r\n"):
                    break
            
            # Parse Content-Length
            header_str = header.decode("utf-8").strip()
            if not header_str.lower().startswith("content-length:"):
                _log_bridge(f"Invalid header: {header_str[:50]}", "error")
                return None
            
            try:
                content_length = int(header_str.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                _log_bridge(f"Failed to parse Content-Length from: {header_str}", "error")
                return None
            
            # Read separator \r\n
            separator = reader.read(2)
            if separator != b"\r\n":
                _log_bridge(f"Invalid separator: {separator!r}", "error")
                return None
            
            # Read exactly content_length bytes
            body_bytes = reader.read(content_length)
            if len(body_bytes) != content_length:
                _log_bridge(f"Incomplete read: got {len(body_bytes)} bytes, expected {content_length}", "error")
                return None
            
            return json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        _log_bridge(f"JSON parse error: {e}", "error")
        return None
    except Exception as e:
        _log_bridge(f"Read error: {e}", "error")
        return None


async def _on_startup() -> None:
    """Initialize the Elixir bridge on startup.
    
    Called when CODE_PUPPY_BRIDGE=1 is set. Sets up:
    1. Bridge controller for command dispatch
    2. Stdin reader for receiving JSON-RPC commands
    3. Event redirection to stdout
    
    Async-safe: Uses non-blocking I/O only (asyncio, not blocking stdin).
    """
    global _bridge_controller
    
    if not BRIDGE_ENABLED:
        return
    
    _log_bridge("Initializing Elixir bridge mode", "info")
    
    try:
        # Create bridge controller - handles command dispatch
        _bridge_controller = BridgeController()
        
        # Emit bridge ready notification
        _emit_bridge_notification("bridge_ready", {
            "version": "1.0.0",
            "pid": os.getpid(),
            "capabilities": ["invoke_agent", "run_shell", "file_ops", "event_stream"]
        })
        
        # Start stdin reader in background task
        # Async-safe: Uses asyncio.StreamReader, not blocking stdlib input()
        asyncio.create_task(_stdin_reader_loop())
        
        _log_bridge("Bridge ready - awaiting commands from stdin", "info")
        
    except Exception as e:
        _log_bridge(f"Bridge initialization failed: {e}", "error")
        logger.error(f"Elixir bridge initialization failed: {e}")
        raise


async def _on_shutdown() -> None:
    """Cleanup bridge resources on shutdown.
    
    Async-safe: Cancels pending tasks, closes resources without blocking.
    """
    global _bridge_controller
    
    if not BRIDGE_ENABLED or _bridge_controller is None:
        return
    
    _log_bridge("Shutting down Elixir bridge", "info")
    
    try:
        # Emit shutdown notification before closing
        _emit_bridge_notification("bridge_closing", {"reason": "shutdown"})
        
        # Cleanup bridge controller
        await _bridge_controller.shutdown()
        _bridge_controller = None
        
        _log_bridge("Bridge shutdown complete", "info")
        
    except Exception as e:
        _log_bridge(f"Bridge shutdown error: {e}", "error")
        logger.error(f"Elixir bridge shutdown error: {e}")


def _on_stream_event(
    event_type: str,
    event_data: dict[str, Any],
    agent_session_id: str | None = None
) -> None:
    """Emit event to stdout in JSON-RPC format.
    
    This callback intercepts all events and forwards them to Elixir
    via stdout in JSON-RPC notification format (no response expected).
    Uses Content-Length framing for Elixir protocol compatibility.
    
    Format: {"jsonrpc": "2.0", "method": "event", "params": {...}}
    
    Args:
        event_type: Type of event (e.g., "tool_call", "agent_response")
        event_data: Event-specific data
        agent_session_id: Optional session identifier
    """
    if not BRIDGE_ENABLED:
        return
    
    try:
        # Convert to wire protocol format
        wire_event = to_wire_event(event_type, event_data, agent_session_id)
        
        # Emit as JSON-RPC notification (no id field)
        notification = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": wire_event
        }
        
        # Write to stdout with Content-Length framing
        # This is the Elixir JSON-RPC protocol specification
        _write_framed_message(notification)
        
        _log_bridge(f"Emitted event: {event_type}", "debug")
        
    except Exception as e:
        _log_bridge(f"Failed to emit event: {e}", "error")
        # Don't raise - event emission should not break agent flow


def _emit_bridge_notification(method: str, params: dict[str, Any]) -> None:
    """Emit a bridge-level notification.
    
    Used for bridge lifecycle events (ready, closing, error).
    Uses Content-Length framing for Elixir protocol compatibility.
    """
    try:
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        _write_framed_message(notification)
    except Exception as e:
        _log_bridge(f"Failed to emit bridge notification: {e}", "error")


async def _stdin_reader_loop() -> None:
    """Read JSON-RPC commands from stdin.
    
    Continuously reads Content-Length framed JSON commands from stdin,
    dispatches them via the bridge controller, and writes responses.
    
    Supports backward compatibility via _BRIDGE_PROTOCOL:
    - "content-length": Uses Content-Length framing (default)
    - "newline": Uses newline-delimited JSON
    
    Async-safe: Uses asyncio.StreamReader for non-blocking I/O.
    See: docs/rules/async-io.md for callback implementation rules.
    """
    global _bridge_controller
    
    if _bridge_controller is None:
        return
    
    _log_bridge("Starting stdin reader loop", "info")
    
    # Get asyncio-compatible stdin reader
    # Async-safe: Uses asyncio.StreamReader, not blocking sys.stdin
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    
    try:
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    except Exception as e:
        _log_bridge(f"Failed to connect stdin pipe: {e}", "error")
        return
    
    while BRIDGE_ENABLED and _bridge_controller is not None:
        try:
            # Read framed message (Content-Length or newline based on protocol)
            request = _read_framed_message(reader)
            
            if request is None:
                # EOF or parse error - reader is exhausted
                _log_bridge("Stdin EOF reached", "info")
                break
            
            _log_bridge(f"Received: {str(request)[:200]}...", "debug")
            
            # Validate basic JSON-RPC structure
            if request.get("jsonrpc") != "2.0":
                _send_jsonrpc_error(
                    request.get("id"), -32600, "Invalid Request: expected jsonrpc 2.0"
                )
                continue
            
            # Dispatch command
            response = await _bridge_controller.dispatch(request)
            
            # Send response if request has an id (not a notification)
            if "id" in request and response is not None:
                _send_jsonrpc_response(request["id"], response)
                
        except asyncio.CancelledError:
            _log_bridge("Stdin reader cancelled", "info")
            break
        except Exception as e:
            _log_bridge(f"Stdin reader error: {e}", "error")
            _send_jsonrpc_error(None, -32603, f"Internal error: {e}")


def _send_jsonrpc_response(request_id: Any, result: Any) -> None:
    """Send a JSON-RPC success response.
    
    Uses Content-Length framing for Elixir protocol compatibility.
    """
    try:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
        _write_framed_message(response)
    except Exception as e:
        _log_bridge(f"Failed to send response: {e}", "error")


def _send_jsonrpc_error(request_id: Any, code: int, message: str, data: Any = None) -> None:
    """Send a JSON-RPC error response.
    
    Uses Content-Length framing for Elixir protocol compatibility.
    """
    try:
        error = {
            "code": code,
            "message": message
        }
        if data is not None:
            error["data"] = data
        
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error
        }
        _write_framed_message(response)
    except Exception as e:
        _log_bridge(f"Failed to send error: {e}", "error")


# =============================================================================
# Callback Registration
# =============================================================================

# Register callbacks only if bridge mode is enabled
if BRIDGE_ENABLED:
    register_callback("startup", _on_startup)
    register_callback("shutdown", _on_shutdown)
    register_callback("stream_event", _on_stream_event)
    
    _log_bridge("Elixir bridge callbacks registered", "info")
