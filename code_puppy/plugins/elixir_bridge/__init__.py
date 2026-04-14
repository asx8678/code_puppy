"""Elixir Bridge Plugin - Bridge mode for Elixir Port communication.

This plugin enables Code Puppy to run as a child process controlled by Elixir
via JSON-RPC over stdio. When CODE_PUPPY_BRIDGE=1 environment variable is set,
the bridge activates and:

1. Emits events to stdout in JSON-RPC format
2. Receives commands from stdin in JSON-RPC format
3. Translates between Python message types and Elixir wire protocol

This prepares Python to be controlled by Elixir for the migration.

Environment:
    CODE_PUPPY_BRIDGE=1    Enable bridge mode
    CODE_PUPPY_BRIDGE_LOG  Optional log file path for debugging

Example Elixir Port usage:
    # Elixir side
    port = Port.open({:spawn, "python -m code_puppy"}, [:binary, :exit_status])
    # Send command
    Port.command(port, ~s({"jsonrpc": "2.0", "id": "1", "method": "invoke_agent", "params": {...}}\\n))
    # Receive event
    receive do
      {^port, {:data, data}} ->
        # data contains JSON-RPC notification
    end

Architecture:
    ┌─────────────┐       stdio (JSON-RPC)       ┌─────────────┐
    │   Elixir    │  ───────────────────────────▶│   Python    │
    │  (Port)     │◀───────────────────────────────│  (Bridge)   │
    └─────────────┘                                  └─────────────┘
                                                          │
                            ┌──────────────────────────────┘
                            ▼
                    ┌─────────────────┐
                    │  Agent Tools    │
                    │  File Ops       │
                    │  Shell Commands │
                    └─────────────────┘

See: docs/architecture/python-singleton-audit.md for migration context.

bd-62: Client mode for calling Elixir control plane from Python
- Added is_connected() to check if Elixir control plane is available
- Added call_method() to send JSON-RPC requests to Elixir
- Used by NativeBackend to route file operations through Elixir
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

# Bridge mode detection - used by register_callbacks to decide whether to activate
BRIDGE_ENABLED = os.environ.get("CODE_PUPPY_BRIDGE", "").strip() == "1"
BRIDGE_LOG_FILE = os.environ.get("CODE_PUPPY_BRIDGE_LOG")

# Client mode: Python calling Elixir control plane
# These are set when Elixir control plane is detected
_elixir_control_plane_url: str | None = None
_pending_responses: dict[str, dict[str, Any]] = {}
_response_lock = threading.Lock()


def is_connected() -> bool:
    """Check if Elixir control plane is connected and available.

    Returns:
        True if Elixir control plane is available for JSON-RPC calls.
    """
    global _elixir_control_plane_url

    # Check environment variable for control plane URL
    if _elixir_control_plane_url is None:
        env_url = os.environ.get("CODE_PUPPY_ELIXIR_URL")
        if env_url:
            _elixir_control_plane_url = env_url

    # For now, connection is established via environment variable
    # Future: Add socket/HTTP discovery mechanism
    return _elixir_control_plane_url is not None


def set_connection_url(url: str | None) -> None:
    """Set the Elixir control plane connection URL.

    Args:
        url: URL for the Elixir control plane (e.g., "http://localhost:4000/rpc"
             or unix socket path), or None to disconnect.
    """
    global _elixir_control_plane_url
    _elixir_control_plane_url = url


def get_connection_url() -> str | None:
    """Get the current Elixir control plane connection URL.

    Returns:
        The connection URL if set, None otherwise.
    """
    return _elixir_control_plane_url


def call_method(method: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    """Call a method on the Elixir control plane via JSON-RPC.

    Sends a JSON-RPC 2.0 request to the Elixir control plane and waits
    for the response. Used by NativeBackend to route file operations.

    Args:
        method: JSON-RPC method name (e.g., "file_list", "file_read")
        params: Method parameters dict
        timeout: Maximum seconds to wait for response

    Returns:
        Response result dict from Elixir

    Raises:
        ConnectionError: If Elixir control plane is not connected
        TimeoutError: If response not received within timeout
        RuntimeError: If the call returns an error response
    """
    global _elixir_control_plane_url, _pending_responses

    if not is_connected():
        raise ConnectionError("Elixir control plane not connected")

    # Generate unique request ID
    request_id = f"req-{uuid.uuid4().hex[:16]}"

    # Build JSON-RPC request
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }

    # Create response slot
    with _response_lock:
        _pending_responses[request_id] = {"ready": False, "result": None, "error": None}

    try:
        # Send the request
        # TODO(code-puppy-elixir-client): Implement actual transport (HTTP, socket, etc.)
        # For now, this is a placeholder that raises NotImplementedError
        # Real implementation will send over socket/HTTP to Elixir
        _send_request_to_elixir(request)

        # Wait for response with timeout
        start_time = time.time()
        while time.time() - start_time < timeout:
            with _response_lock:
                slot = _pending_responses.get(request_id)
                if slot and slot["ready"]:
                    result = slot["result"]
                    error = slot["error"]
                    break
            time.sleep(0.01)  # Short sleep to prevent busy waiting
        else:
            raise TimeoutError(f"Elixir call timed out after {timeout}s")

        # Check for error response
        if error is not None:
            raise RuntimeError(f"Elixir call failed: {error}")

        return result if result is not None else {}

    finally:
        # Clean up response slot
        with _response_lock:
            _pending_responses.pop(request_id, None)


def _send_request_to_elixir(request: dict[str, Any]) -> None:
    """Send a JSON-RPC request to the Elixir control plane.

    TODO(code-puppy-elixir-client): Implement actual transport
    Currently raises NotImplementedError - needs HTTP or socket implementation.

    Args:
        request: JSON-RPC request dict

    Raises:
        NotImplementedError: Transport not yet implemented
    """
    # Placeholder - actual implementation needs:
    # 1. HTTP client to Elixir control plane endpoint
    # 2. Or socket-based communication
    # 3. Or stdio-based if Elixir is child process
    raise NotImplementedError(
        "Elixir control plane client transport not yet implemented. "
        "NativeBackend will fall back to Rust/Python implementations."
    )


def handle_response(response: dict[str, Any]) -> None:
    """Handle a JSON-RPC response from Elixir.

    Called by the transport layer when a response is received from Elixir.

    Args:
        response: JSON-RPC response dict with "id", "result", and/or "error"
    """
    global _pending_responses

    request_id = response.get("id")
    if request_id is None:
        return  # Notification, no response needed

    with _response_lock:
        if request_id in _pending_responses:
            slot = _pending_responses[request_id]
            slot["result"] = response.get("result")
            slot["error"] = response.get("error")
            slot["ready"] = True


__all__ = [
    "BRIDGE_ENABLED",
    "BRIDGE_LOG_FILE",
    # Client mode (Python → Elixir)
    "is_connected",
    "set_connection_url",
    "get_connection_url",
    "call_method",
    "handle_response",
]
