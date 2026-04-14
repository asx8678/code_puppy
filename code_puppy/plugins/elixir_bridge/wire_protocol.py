"""Wire Protocol - Serialization for Elixir communication.

Translates between Python message types and Elixir wire protocol format using
canonical BRIDGE_PROTOCOL_V1 methods.

Canonical Wire Protocol Format (V1):
```json
// Status update
{"jsonrpc":"2.0","method":"run.status","params":{"run_id":"...","status":"running"}}

// Text output
{"jsonrpc":"2.0","method":"run.text","params":{"run_id":"...","text":"..."}}

// Tool result
{"jsonrpc":"2.0","method":"run.tool_result","params":{"run_id":"...","tool_name":"..."}}

// Bridge lifecycle
{"jsonrpc":"2.0","method":"bridge.ready","params":{"version":"1.0.0"}}
```

See: docs/protocol/BRIDGE_PROTOCOL_V1.md for full specification.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


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


def _get_timestamp() -> str:
    """Generate ISO 8601 timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_run_status(
    run_id: str,
    session_id: str | None,
    status: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.status notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        status: Status value (initializing, running, paused, cancelling, completed, failed)
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id

    return {
        "jsonrpc": "2.0",
        "method": "run.status",
        "params": params,
    }


def emit_run_text(
    run_id: str,
    session_id: str | None,
    text: str,
    finished: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.text notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        text: Text content
        finished: Whether this is the final text chunk
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "text": text,
        "finished": finished,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id

    return {
        "jsonrpc": "2.0",
        "method": "run.text",
        "params": params,
    }


def emit_run_tool_result(
    run_id: str,
    session_id: str | None,
    tool_call_id: str,
    tool_name: str,
    result: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.tool_result notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        tool_call_id: Tool call correlation ID
        tool_name: Name of the tool that was executed
        result: Tool execution result dict
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "result": result,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id

    return {
        "jsonrpc": "2.0",
        "method": "run.tool_result",
        "params": params,
    }


def emit_run_completed(
    run_id: str,
    session_id: str | None,
    result: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.completed notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        result: Optional run result data
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id
    if result is not None:
        params["result"] = result

    return {
        "jsonrpc": "2.0",
        "method": "run.completed",
        "params": params,
    }


def emit_run_failed(
    run_id: str,
    session_id: str | None,
    error_code: int,
    error_message: str,
    error_details: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.failed notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        error_code: Error code (see BRIDGE_PROTOCOL_V1.md)
        error_message: Human-readable error message
        error_details: Optional additional error context
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    error: dict[str, Any] = {
        "code": error_code,
        "message": error_message,
    }
    if error_details is not None:
        error["details"] = error_details

    params: dict[str, Any] = {
        "run_id": run_id,
        "error": error,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id

    return {
        "jsonrpc": "2.0",
        "method": "run.failed",
        "params": params,
    }


def emit_run_prompt(
    run_id: str,
    session_id: str | None,
    prompt_id: str,
    question: str,
    options: list[str] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.prompt notification.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        prompt_id: Prompt correlation ID
        question: The prompt question text
        options: Optional list of options for the user to choose from
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "prompt_id": prompt_id,
        "question": question,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id
    if options is not None:
        params["options"] = options

    return {
        "jsonrpc": "2.0",
        "method": "run.prompt",
        "params": params,
    }


def emit_run_event(
    run_id: str,
    session_id: str | None,
    event_type: str,
    data: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit run.event notification (generic events).

    Used for events that don't have a specific canonical method.

    Args:
        run_id: Run identifier
        session_id: Optional session identifier
        event_type: Internal event type identifier
        data: Event-specific data
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    params: dict[str, Any] = {
        "run_id": run_id,
        "event_type": event_type,
        "data": data,
        "timestamp": timestamp or _get_timestamp(),
    }
    if session_id is not None:
        params["session_id"] = session_id

    return {
        "jsonrpc": "2.0",
        "method": "run.event",
        "params": params,
    }


def emit_bridge_ready(
    capabilities: list[str],
    version: str = "1.0.0",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit bridge.ready notification.

    Args:
        capabilities: List of bridge capabilities
        version: Bridge protocol version
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    return {
        "jsonrpc": "2.0",
        "method": "bridge.ready",
        "params": {
            "capabilities": capabilities,
            "version": version,
            "timestamp": timestamp or _get_timestamp(),
        },
    }


def emit_bridge_closing(
    reason: str = "shutdown",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Emit bridge.closing notification.

    Args:
        reason: Reason for bridge closing
        timestamp: Optional timestamp (auto-generated if None)

    Returns:
        JSON-RPC notification dict
    """
    return {
        "jsonrpc": "2.0",
        "method": "bridge.closing",
        "params": {
            "reason": reason,
            "timestamp": timestamp or _get_timestamp(),
        },
    }


def to_canonical_notification(
    event_type: str,
    run_id: str | None,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map internal event type to canonical notification method.

    Translates internal event types to BRIDGE_PROTOCOL_V1 canonical methods:
    - status -> run.status
    - text -> run.text
    - tool_output -> run.tool_result
    - completed -> run.completed
    - failed -> run.failed
    - prompt -> run.prompt
    - other -> run.event

    Args:
        event_type: Internal event type identifier
        run_id: Optional run identifier
        session_id: Optional session identifier
        payload: Event-specific data dict

    Returns:
        JSON-RPC notification dict with canonical method name

    Example:
        >>> notification = to_canonical_notification(
        ...     event_type="tool_output",
        ...     run_id="run-123",
        ...     session_id="sess-456",
        ...     payload={"tool_name": "file_read", "result": {...}}
        ... )
        >>> print(notification["method"])  # "run.tool_result"
    """
    payload = payload or {}

    # Map internal event types to canonical methods
    if event_type == "status":
        return emit_run_status(
            run_id=run_id or "",
            session_id=session_id,
            status=payload.get("status", "unknown"),
        )
    elif event_type == "text":
        return emit_run_text(
            run_id=run_id or "",
            session_id=session_id,
            text=payload.get("text", ""),
            finished=payload.get("finished", False),
        )
    elif event_type == "tool_output":
        return emit_run_tool_result(
            run_id=run_id or "",
            session_id=session_id,
            tool_call_id=payload.get("tool_call_id", ""),
            tool_name=payload.get("tool_name", ""),
            result=payload.get("result", {}),
        )
    elif event_type == "completed":
        return emit_run_completed(
            run_id=run_id or "",
            session_id=session_id,
            result=payload.get("result"),
        )
    elif event_type == "failed":
        return emit_run_failed(
            run_id=run_id or "",
            session_id=session_id,
            error_code=payload.get("error_code", -32000),
            error_message=payload.get("error_message", "Unknown error"),
            error_details=payload.get("error_details"),
        )
    elif event_type == "prompt":
        return emit_run_prompt(
            run_id=run_id or "",
            session_id=session_id,
            prompt_id=payload.get("prompt_id", ""),
            question=payload.get("question", ""),
            options=payload.get("options"),
        )
    else:
        # Generic event for unrecognized types
        return emit_run_event(
            run_id=run_id or "",
            session_id=session_id,
            event_type=event_type,
            data=payload,
        )


def from_wire_params(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize wire protocol params for a method.

    Supports both dot-style (V1) and slash-style (legacy) method names.
    Per BRIDGE_PROTOCOL_V1, dot-style is preferred.

    Args:
        method: Method name being called (e.g., "run.start", "run.cancel")
        params: Raw params from JSON-RPC request

    Returns:
        Validated and normalized params dict

    Raises:
        WireMethodError: If params are invalid
    """
    # Normalize slash-style to dot-style for compatibility
    normalized_method = method.replace("/", ".")

    # V1 canonical methods (dot-style)
    if normalized_method == "run.start":
        if "agent_name" not in params:
            raise WireMethodError("run.start requires 'agent_name' param", INVALID_PARAMS)
        if "prompt" not in params:
            raise WireMethodError("run.start requires 'prompt' param", INVALID_PARAMS)
        return {
            "agent_name": str(params["agent_name"]),
            "prompt": str(params["prompt"]),
            "session_id": params.get("session_id"),
            "run_id": params.get("run_id"),
            "context": params.get("context", {}),
        }

    elif normalized_method == "run.cancel":
        if "run_id" not in params:
            raise WireMethodError("run.cancel requires 'run_id' param", INVALID_PARAMS)
        return {
            "run_id": str(params["run_id"]),
            "reason": params.get("reason", "user_requested"),
        }

    elif normalized_method == "initialize":
        return {
            "capabilities": params.get("capabilities", []),
            "config": params.get("config", {}),
        }

    elif normalized_method == "exit":
        return {
            "reason": params.get("reason", "shutdown"),
            "timeout_ms": int(params.get("timeout_ms", 5000)),
        }

    # Legacy methods (kept for backward compatibility during transition)
    elif normalized_method == "invoke_agent":
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

    elif normalized_method == "run_shell":
        if "command" not in params:
            raise WireMethodError("run_shell requires 'command' param", INVALID_PARAMS)
        return {
            "command": str(params["command"]),
            "cwd": params.get("cwd"),
            "timeout": int(params.get("timeout", 60)),
        }

    elif normalized_method == "file_list":
        if "directory" not in params:
            raise WireMethodError("file_list requires 'directory' param", INVALID_PARAMS)
        return {
            "directory": str(params["directory"]),
            "recursive": bool(params.get("recursive", False)),
        }

    elif normalized_method == "file_read":
        if "path" not in params:
            raise WireMethodError("file_read requires 'path' param", INVALID_PARAMS)
        return {
            "path": str(params["path"]),
            "start_line": params.get("start_line"),
            "num_lines": params.get("num_lines"),
        }

    elif normalized_method == "file_write":
        if "path" not in params:
            raise WireMethodError("file_write requires 'path' param", INVALID_PARAMS)
        if "content" not in params:
            raise WireMethodError("file_write requires 'content' param", INVALID_PARAMS)
        return {
            "path": str(params["path"]),
            "content": str(params["content"]),
        }

    elif normalized_method == "grep_search":
        if "search_string" not in params:
            raise WireMethodError("grep_search requires 'search_string' param", INVALID_PARAMS)
        return {
            "search_string": str(params["search_string"]),
            "directory": str(params.get("directory", ".")),
        }

    elif normalized_method in ("get_status", "ping"):
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


def parse_framed_message(framed: bytes) -> dict[str, Any]:
    """Parse a Content-Length framed message.

    Parses HTTP-style Content-Length framing as per BRIDGE_PROTOCOL_V1.md:
    Content-Length: <byte-length>\\r\\n
    \\r\\n
    <json-body>

    Args:
        framed: Framed message bytes

    Returns:
        Parsed JSON message dict

    Raises:
        WireMethodError: If framing is invalid or JSON is malformed

    Example:
        >>> framed = b'Content-Length: 49\\r\\n\\r\\n{"jsonrpc":"2.0","method":"ping","params":{}}'
        >>> parsed = parse_framed_message(framed)
        >>> print(parsed["method"])
        'ping'
    """
    try:
        # Find the header/body separator
        if b"\r\n\r\n" not in framed:
            raise WireMethodError(
                "Invalid framing: missing header/body separator", PARSE_ERROR
            )

        header_part, body = framed.split(b"\r\n\r\n", 1)

        # Parse Content-Length header
        if not header_part.startswith(b"Content-Length: "):
            raise WireMethodError(
                "Invalid framing: missing Content-Length header", PARSE_ERROR
            )

        try:
            content_length = int(header_part.split(b": ")[1])
        except (IndexError, ValueError) as e:
            raise WireMethodError(
                f"Invalid Content-Length value: {e}", PARSE_ERROR
            ) from e

        # Validate body length
        if len(body) != content_length:
            raise WireMethodError(
                f"Content-Length mismatch: expected {content_length}, got {len(body)}",
                PARSE_ERROR,
            )

        # Parse JSON body
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise WireMethodError(
                f"Invalid JSON in message body: {e}", PARSE_ERROR
            ) from e

    except WireMethodError:
        raise
    except Exception as e:
        raise WireMethodError(
            f"Failed to parse framed message: {e}", PARSE_ERROR
        ) from e


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
