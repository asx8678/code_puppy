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
        "timestamp": 1713123456789,
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


def to_wire_event(
    event_type: str,
    event_data: dict[str, Any],
    session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Convert an event to Elixir wire protocol format.
    
    Args:
        event_type: Type of event (e.g., "tool_output", "agent_response")
        event_data: Event-specific data dict
        session_id: Optional session identifier
        run_id: Optional run identifier
    
    Returns:
        Wire protocol formatted dict
    
    Example:
        >>> to_wire_event("tool_output", {"command": "ls"}, "session-1")
        {
            "event_type": "tool_output",
            "run_id": None,
            "session_id": "session-1",
            "timestamp": 1713123456789,
            "payload": {"command": "ls"}
        }
    """
    # Generate timestamp
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    return {
        "event_type": event_type,
        "run_id": run_id,
        "session_id": session_id,
        "timestamp": timestamp_ms,
        "payload": event_data,
    }


def message_to_wire(message: BaseMessage) -> dict[str, Any]:
    """Convert a BaseMessage to wire protocol format.
    
    Args:
        message: A Code Puppy message object
    
    Returns:
        Wire protocol formatted dict
    """
    # Get timestamp from message or generate new
    if hasattr(message, "timestamp_unix_ms"):
        timestamp_ms = message.timestamp_unix_ms
    else:
        timestamp_ms = int(message.timestamp.timestamp() * 1000)
    
    # Extract payload (everything except wire protocol fields)
    message_dict = message.model_dump()
    payload = {
        k: v for k, v in message_dict.items()
        if k not in ("run_id", "session_id", "timestamp", "timestamp_unix_ms", "category")
    }
    
    return {
        "event_type": message.category.value,
        "run_id": message.run_id,
        "session_id": message.session_id,
        "timestamp": timestamp_ms,
        "payload": payload,
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
            raise WireMethodError("invoke_agent requires 'agent_name' param", -32602)
        if "prompt" not in params:
            raise WireMethodError("invoke_agent requires 'prompt' param", -32602)
        return {
            "agent_name": str(params["agent_name"]),
            "prompt": str(params["prompt"]),
            "session_id": params.get("session_id"),
        }
    
    elif method == "run_shell":
        if "command" not in params:
            raise WireMethodError("run_shell requires 'command' param", -32602)
        return {
            "command": str(params["command"]),
            "cwd": params.get("cwd"),
            "timeout": int(params.get("timeout", 60)),
        }
    
    elif method == "file_list":
        if "directory" not in params:
            raise WireMethodError("file_list requires 'directory' param", -32602)
        return {
            "directory": str(params["directory"]),
            "recursive": bool(params.get("recursive", False)),
        }
    
    elif method == "file_read":
        if "path" not in params:
            raise WireMethodError("file_read requires 'path' param", -32602)
        return {
            "path": str(params["path"]),
            "start_line": params.get("start_line"),
            "num_lines": params.get("num_lines"),
        }
    
    elif method == "file_write":
        if "path" not in params:
            raise WireMethodError("file_write requires 'path' param", -32602)
        if "content" not in params:
            raise WireMethodError("file_write requires 'content' param", -32602)
        return {
            "path": str(params["path"]),
            "content": str(params["content"]),
        }
    
    elif method == "grep_search":
        if "search_string" not in params:
            raise WireMethodError("grep_search requires 'search_string' param", -32602)
        return {
            "search_string": str(params["search_string"]),
            "directory": str(params.get("directory", ".")),
        }
    
    elif method in ("get_status", "ping"):
        return params
    
    else:
        raise WireMethodError(f"Unknown method: {method}", -32601)


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


# JSON-RPC error codes (per JSON-RPC 2.0 spec)
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_SERVER_ERROR_MIN = -32000
JSONRPC_SERVER_ERROR_MAX = -32099
