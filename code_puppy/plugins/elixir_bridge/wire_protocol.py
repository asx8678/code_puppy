"""Wire Protocol - Serialization for Elixir communication.

Translates between Python message types and Elixir wire protocol format.

Elixir Wire Protocol Format:
```json
{
    "jsonrpc": "2.0",
    "method": "event",
    "params": {
        "event_type": "tool_output",
        "run_id": "run-abc123",
        "session_id": "session-xyz789",
        "timestamp": "2026-04-14T12:00:00Z",
        "payload": {...}
    }
}
```

See: docs/architecture/python-singleton-audit.md for migration context.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from code_puppy.messaging.messages import BaseMessage


class WireMethodError(Exception):
    """Error in wire protocol method dispatch."""

    def __init__(self, message: str, code: int = -32600):
        self.code = code
        super().__init__(message)


# Backwards compatibility alias for tests
JsonRpcError = WireMethodError

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR_MIN = -32000
SERVER_ERROR_MAX = -32099

# Legacy constant names (for backwards compatibility)
JSONRPC_PARSE_ERROR = PARSE_ERROR
JSONRPC_INVALID_REQUEST = INVALID_REQUEST
JSONRPC_METHOD_NOT_FOUND = METHOD_NOT_FOUND
JSONRPC_INVALID_PARAMS = INVALID_PARAMS
JSONRPC_INTERNAL_ERROR = INTERNAL_ERROR
JSONRPC_SERVER_ERROR_MIN = SERVER_ERROR_MIN
JSONRPC_SERVER_ERROR_MAX = SERVER_ERROR_MAX


def to_wire_event(
    event_type: str,
    run_id: str | None = None,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Convert an event to Elixir wire protocol format.

    Creates a JSON-RPC 2.0 notification message with the event wrapped in params.

    Args:
        event_type: Type of event (e.g., "tool_output", "agent_response")
        run_id: Optional run identifier
        session_id: Optional session identifier
        payload: Event-specific data dict

    Returns:
        JSON-RPC formatted string ready for wire transmission

    Example:
        >>> event = to_wire_event(
        ...     event_type="tool_output",
        ...     run_id="run-123",
        ...     session_id="session-1",
        ...     payload={"command": "ls"}
        ... )
        >>> print(event)
        {"jsonrpc":"2.0","method":"event","params":{"event_type":"tool_output",...}}
    """
    # Generate ISO 8601 timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    event_data = {
        "event_type": event_type,
        "run_id": run_id,
        "session_id": session_id,
        "timestamp": timestamp,
        "payload": payload or {},
    }

    # Wrap in JSON-RPC 2.0 notification format
    message = {
        "jsonrpc": "2.0",
        "method": "event",
        "params": event_data,
    }

    return json.dumps(message, separators=(",", ":"))


def message_to_wire(message: BaseMessage) -> dict[str, Any]:
    """Convert a BaseMessage to wire protocol format.

    Args:
        message: A Code Puppy message object

    Returns:
        Wire protocol formatted dict
    """
    # Get timestamp as ISO 8601 string
    if hasattr(message, "timestamp"):
        timestamp = message.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Extract payload (everything except wire protocol fields)
    message_dict = message.model_dump()
    payload = {
        k: v
        for k, v in message_dict.items()
        if k not in ("run_id", "session_id", "timestamp", "timestamp_unix_ms", "category")
    }

    # Build params structure
    params = {
        "event_type": message.category.value,
        "run_id": message.run_id,
        "session_id": message.session_id,
        "timestamp": timestamp,
        "payload": payload,
    }

    # Return full JSON-RPC notification
    return {
        "jsonrpc": "2.0",
        "method": "event",
        "params": params,
    }


def from_wire_params(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize wire protocol params for a method.

    Args:
        method: Method name being called
        params: Raw params from JSON-RPC request

    Returns:
        Validated and normalized params dict

    Raises:
        WireMethodError: If params are invalid
    """
    # Method-specific validation
    if method == "invoke_agent":
        if "agent_name" not in params:
            raise WireMethodError("invoke_agent requires 'agent_name' param", INVALID_PARAMS)
        if "prompt" not in params:
            raise WireMethodError("invoke_agent requires 'prompt' param", INVALID_PARAMS)
        return {
            "agent_name": str(params["agent_name"]),
            "prompt": str(params["prompt"]),
            "session_id": params.get("session_id"),
            "run_id": params.get("run_id"),
        }

    elif method == "run_shell":
        if "command" not in params:
            raise WireMethodError("run_shell requires 'command' param", INVALID_PARAMS)
        return {
            "command": str(params["command"]),
            "cwd": params.get("cwd"),
            "timeout": int(params.get("timeout", 60)),
        }

    elif method == "file_list":
        if "directory" not in params:
            raise WireMethodError("file_list requires 'directory' param", INVALID_PARAMS)
        return {
            "directory": str(params["directory"]),
            "recursive": bool(params.get("recursive", False)),
        }

    elif method == "file_read":
        if "path" not in params:
            raise WireMethodError("file_read requires 'path' param", INVALID_PARAMS)
        return {
            "path": str(params["path"]),
            "start_line": params.get("start_line"),
            "num_lines": params.get("num_lines"),
        }

    elif method == "file_write":
        if "path" not in params:
            raise WireMethodError("file_write requires 'path' param", INVALID_PARAMS)
        if "content" not in params:
            raise WireMethodError("file_write requires 'content' param", INVALID_PARAMS)
        return {
            "path": str(params["path"]),
            "content": str(params["content"]),
        }

    elif method == "grep_search":
        if "search_string" not in params:
            raise WireMethodError("grep_search requires 'search_string' param", INVALID_PARAMS)
        return {
            "search_string": str(params["search_string"]),
            "directory": str(params.get("directory", ".")),
        }

    elif method in ("get_status", "ping"):
        return params

    else:
        raise WireMethodError(f"Unknown method: {method}", METHOD_NOT_FOUND)


def frame_message(message: dict[str, Any]) -> bytes:
    """Frame a message with Content-Length header for wire transmission.

    Uses HTTP-style Content-Length framing as per BRIDGE_PROTOCOL.md:
    Content-Length: <byte-length>\\r\\n
    \\r\\n
    <json-body>

    Args:
        message: Message dict to frame

    Returns:
        Framed message as bytes ready for stdio

    Example:
        >>> message = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        >>> framed = frame_message(message)
        >>> print(framed)
        b'Content-Length: 49\\r\\n\\r\\n{"jsonrpc":"2.0","method":"ping","params":{}}'
    """
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    return header + body


def serialize_for_wire(data: Any) -> str:
    """Serialize data to JSON string for wire protocol.

    Uses compact formatting (no whitespace) for efficiency.

    Args:
        data: Data to serialize

    Returns:
        JSON string
    """
    return json.dumps(data, separators=(",", ":"), default=_json_default)


def _json_default(obj: Any) -> Any:
    """JSON serializer for special types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
