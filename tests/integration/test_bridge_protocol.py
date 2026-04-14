"""
Integration tests for Python↔Elixir bridge protocol.

These tests verify that:
1. Wire format matches BRIDGE_PROTOCOL.md specification
2. All event types are correctly formatted
3. Request/response structures are correct
4. Content-Length framing works correctly
5. Error codes match JSON-RPC 2.0 specification

See: docs/BRIDGE_PROTOCOL.md
"""

import json
import pytest
from datetime import datetime, timezone

# Import the wire protocol module
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    to_wire_event,
    from_wire_params,
    message_to_wire,
    frame_message,
    JsonRpcError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    WireMethodError,
)
from code_puppy.messaging.messages import BaseMessage, TextMessage, MessageCategory, MessageLevel


class TestWireEventFormat:
    """Test that events match the protocol specification."""

    def test_event_has_required_fields(self):
        """Events must have jsonrpc, method, and params."""
        event = to_wire_event(
            event_type="agent_response",
            run_id="run-123",
            session_id="session-456",
            payload={"text": "Hello", "finished": False},
        )

        parsed = json.loads(event)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "event"
        assert "params" in parsed

    def test_event_params_structure(self):
        """Event params must have event_type, run_id, session_id, timestamp, payload."""
        event = to_wire_event(
            event_type="tool_call",
            run_id="run-123",
            session_id="session-456",
            payload={"tool_name": "read_file", "tool_args": {"path": "test.py"}},
        )

        parsed = json.loads(event)
        params = parsed["params"]

        assert params["event_type"] == "tool_call"
        assert params["run_id"] == "run-123"
        assert params["session_id"] == "session-456"
        assert "timestamp" in params
        assert "payload" in params
        assert params["payload"]["tool_name"] == "read_file"

    def test_timestamp_is_iso8601(self):
        """Timestamp must be ISO 8601 format."""
        event = to_wire_event(
            event_type="run_started",
            run_id="run-123",
            session_id="session-456",
            payload={"agent_name": "code-puppy"},
        )

        parsed = json.loads(event)
        timestamp = parsed["params"]["timestamp"]

        # Should parse without error
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert dt is not None
        # Should be UTC
        assert dt.tzinfo is not None

    def test_timestamp_utc(self):
        """Timestamp should be in UTC."""
        # Use a time window that accounts for microsecond precision differences
        import time
        before = time.time()
        event = to_wire_event(
            event_type="test",
            run_id="run-123",
            session_id="session-456",
            payload={},
        )
        after = time.time()

        parsed = json.loads(event)
        timestamp = parsed["params"]["timestamp"]
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Convert to timestamp for comparison (ignoring microsecond differences)
        event_ts = dt.timestamp()
        # Should be within test execution window (with small tolerance)
        assert before - 1 <= event_ts <= after + 1

    @pytest.mark.parametrize(
        "event_type",
        [
            "bridge_ready",
            "bridge_closing",
            "run_started",
            "agent_response",
            "tool_call",
            "tool_result",
            "status_update",
            "run_completed",
            "run_failed",
        ],
    )
    def test_all_event_types_format_correctly(self, event_type):
        """All documented event types should format without error."""
        event = to_wire_event(
            event_type=event_type,
            run_id="run-123",
            session_id="session-456",
            payload={},
        )

        parsed = json.loads(event)
        assert parsed["params"]["event_type"] == event_type

    def test_event_returns_json_string(self):
        """to_wire_event must return a JSON string, not a dict."""
        event = to_wire_event(
            event_type="test_event",
            run_id="run-123",
            session_id="session-456",
            payload={"key": "value"},
        )

        assert isinstance(event, str)
        # Should be valid JSON
        parsed = json.loads(event)
        assert parsed["params"]["payload"]["key"] == "value"

    def test_empty_payload(self):
        """Events with empty payload should still include payload field."""
        event = to_wire_event(
            event_type="bridge_ready",
            run_id="run-123",
            session_id="session-456",
            payload={},
        )

        parsed = json.loads(event)
        assert parsed["params"]["payload"] == {}

    def test_none_run_id(self):
        """Events with None run_id should still include run_id field."""
        event = to_wire_event(
            event_type="bridge_ready",
            run_id=None,
            session_id="session-456",
            payload={},
        )

        parsed = json.loads(event)
        assert parsed["params"]["run_id"] is None

    def test_none_session_id(self):
        """Events with None session_id should still include session_id field."""
        event = to_wire_event(
            event_type="bridge_ready",
            run_id="run-123",
            session_id=None,
            payload={},
        )

        parsed = json.loads(event)
        assert parsed["params"]["session_id"] is None


class TestMessageToWire:
    """Test conversion of BaseMessage objects to wire format."""

    def test_message_conversion(self):
        """TextMessage should convert to proper wire format."""
        # Create a simple test message using TextMessage which has proper fields
        msg = TextMessage(
            category=MessageCategory.AGENT,
            level=MessageLevel.INFO,
            text="Hello",
            run_id="run-123",
            session_id="session-456",
        )

        wire = message_to_wire(msg)

        assert wire["jsonrpc"] == "2.0"
        assert wire["method"] == "event"
        assert wire["params"]["event_type"] == "agent"
        assert wire["params"]["run_id"] == "run-123"
        assert wire["params"]["session_id"] == "session-456"
        assert "timestamp" in wire["params"]
        assert "payload" in wire["params"]

    def test_message_payload_excludes_wire_fields(self):
        """Payload should not include wire protocol metadata fields."""
        msg = TextMessage(
            category=MessageCategory.AGENT,
            level=MessageLevel.INFO,
            text="Hello",
            run_id="run-123",
            session_id="session-456",
        )

        wire = message_to_wire(msg)
        payload = wire["params"]["payload"]

        assert "run_id" not in payload
        assert "session_id" not in payload
        assert "timestamp" not in payload
        assert "category" not in payload
        # Text should be in payload
        assert "text" in payload


class TestRequestValidation:
    """Test that request parameter validation works correctly."""

    def test_invoke_agent_valid_params(self):
        """invoke_agent requires agent_name and prompt."""
        params = {
            "agent_name": "code-puppy",
            "prompt": "Hello!",
            "session_id": "session-123",
            "run_id": "run-456",
        }

        result = from_wire_params("invoke_agent", params)
        assert result["agent_name"] == "code-puppy"
        assert result["prompt"] == "Hello!"
        assert result["session_id"] == "session-123"
        assert result["run_id"] == "run-456"

    def test_invoke_agent_missing_agent_name(self):
        """invoke_agent should reject missing agent_name."""
        params = {"prompt": "Hello!"}  # missing agent_name

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("invoke_agent", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_invoke_agent_missing_prompt(self):
        """invoke_agent should reject missing prompt."""
        params = {"agent_name": "code-puppy"}  # missing prompt

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("invoke_agent", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_file_read_valid_params(self):
        """file_read requires path."""
        params = {"path": "/test/file.py", "start_line": 1, "num_lines": 50}

        result = from_wire_params("file_read", params)
        assert result["path"] == "/test/file.py"
        assert result["start_line"] == 1
        assert result["num_lines"] == 50

    def test_file_read_missing_path(self):
        """file_read should reject missing path."""
        params = {"start_line": 1}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("file_read", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_run_shell_valid_params(self):
        """run_shell requires command."""
        params = {"command": "ls -la", "cwd": "/tmp", "timeout": 30}

        result = from_wire_params("run_shell", params)
        assert result["command"] == "ls -la"
        assert result["cwd"] == "/tmp"
        assert result["timeout"] == 30

    def test_run_shell_missing_command(self):
        """run_shell should reject missing command."""
        params = {"cwd": "/tmp"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("run_shell", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_run_shell_default_timeout(self):
        """run_shell should use default timeout of 60."""
        params = {"command": "ls"}

        result = from_wire_params("run_shell", params)
        assert result["timeout"] == 60

    def test_ping_no_params_required(self):
        """ping should work with empty params."""
        result = from_wire_params("ping", {})
        assert result == {}

    def test_get_status_no_params_required(self):
        """get_status should work with empty params."""
        result = from_wire_params("get_status", {})
        assert result == {}

    def test_file_list_valid_params(self):
        """file_list requires directory."""
        params = {"directory": "/test", "recursive": True}

        result = from_wire_params("file_list", params)
        assert result["directory"] == "/test"
        assert result["recursive"] is True

    def test_file_list_missing_directory(self):
        """file_list should reject missing directory."""
        params = {"recursive": True}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("file_list", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_file_list_default_recursive(self):
        """file_list should default recursive to False."""
        params = {"directory": "/test"}

        result = from_wire_params("file_list", params)
        assert result["recursive"] is False

    def test_file_write_valid_params(self):
        """file_write requires path and content."""
        params = {"path": "/test/file.py", "content": "print('hello')"}

        result = from_wire_params("file_write", params)
        assert result["path"] == "/test/file.py"
        assert result["content"] == "print('hello')"

    def test_file_write_missing_path(self):
        """file_write should reject missing path."""
        params = {"content": "print('hello')"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("file_write", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_file_write_missing_content(self):
        """file_write should reject missing content."""
        params = {"path": "/test/file.py"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("file_write", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_grep_search_valid_params(self):
        """grep_search requires search_string."""
        params = {"search_string": "def test", "directory": "/test"}

        result = from_wire_params("grep_search", params)
        assert result["search_string"] == "def test"
        assert result["directory"] == "/test"

    def test_grep_search_missing_search_string(self):
        """grep_search should reject missing search_string."""
        params = {"directory": "/test"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("grep_search", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_grep_search_default_directory(self):
        """grep_search should default directory to current directory."""
        params = {"search_string": "def test"}

        result = from_wire_params("grep_search", params)
        assert result["directory"] == "."

    def test_unknown_method(self):
        """Unknown methods should raise method not found error."""
        params = {}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("unknown_method", params)
        assert exc_info.value.code == METHOD_NOT_FOUND


class TestJsonRpcErrorCodes:
    """Test that error codes match JSON-RPC 2.0 spec."""

    def test_parse_error_code(self):
        """Parse error should be -32700."""
        assert PARSE_ERROR == -32700

    def test_invalid_request_code(self):
        """Invalid request should be -32600."""
        assert INVALID_REQUEST == -32600

    def test_method_not_found_code(self):
        """Method not found should be -32601."""
        assert METHOD_NOT_FOUND == -32601

    def test_invalid_params_code(self):
        """Invalid params should be -32602."""
        assert INVALID_PARAMS == -32602

    def test_internal_error_code(self):
        """Internal error should be -32603."""
        assert INTERNAL_ERROR == -32603


class TestJsonRpcErrorClass:
    """Test that JsonRpcError class works correctly."""

    def test_error_has_code(self):
        """JsonRpcError should have a code attribute."""
        err = JsonRpcError("test message", INVALID_PARAMS)
        assert err.code == INVALID_PARAMS
        assert str(err) == "test message"

    def test_error_default_code(self):
        """JsonRpcError should have default code -32600."""
        err = JsonRpcError("test message")
        assert err.code == INVALID_REQUEST  # -32600


class TestContentLengthFraming:
    """Test Content-Length framing format."""

    def test_frame_format(self):
        """Frames should use Content-Length: N\\r\\n\\r\\n<body> format."""
        message = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        framed = frame_message(message)

        # Should start with Content-Length header
        assert framed.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in framed

    def test_frame_length_accuracy(self):
        """Content-Length should match actual body length."""
        message = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        framed = frame_message(message)

        # Parse it back
        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        assert len(body) == content_length

    def test_frame_body_is_valid_json(self):
        """Frame body should be valid JSON."""
        message = {"jsonrpc": "2.0", "method": "ping", "params": {}}
        framed = frame_message(message)

        _, body = framed.split(b"\r\n\r\n", 1)
        parsed = json.loads(body)
        assert parsed["method"] == "ping"

    def test_frame_handles_unicode(self):
        """Frames should handle unicode content correctly."""
        message = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {"text": "Hello 世界 🌍"},
        }
        framed = frame_message(message)

        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])

        # Length should account for UTF-8 encoding
        assert len(body) == content_length

        # Should parse correctly
        parsed = json.loads(body)
        assert parsed["params"]["text"] == "Hello 世界 🌍"

    def test_frame_empty_message(self):
        """Frames should handle empty messages."""
        message: dict = {}
        framed = frame_message(message)

        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        assert len(body) == content_length
        assert body == b"{}"

    def test_frame_complex_message(self):
        """Frames should handle complex nested messages."""
        message = {
            "jsonrpc": "2.0",
            "method": "invoke_agent",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Test",
                "options": {"stream": True, "max_tokens": 1000},
            },
        }
        framed = frame_message(message)

        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        assert len(body) == content_length

        parsed = json.loads(body)
        assert parsed["method"] == "invoke_agent"
        assert parsed["params"]["options"]["stream"] is True


class TestWireProtocolIntegration:
    """Integration tests for the complete wire protocol flow."""

    def test_event_round_trip(self):
        """Events should serialize and deserialize correctly."""
        original = {
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "event_type": "agent_response",
                "run_id": "run-123",
                "session_id": "session-456",
                "timestamp": "2026-04-14T12:00:00Z",
                "payload": {"text": "Hello", "finished": False},
            },
        }

        # Frame and unframe
        framed = frame_message(original)
        _, body = framed.split(b"\r\n\r\n", 1)
        parsed = json.loads(body)

        assert parsed["jsonrpc"] == original["jsonrpc"]
        assert parsed["method"] == original["method"]
        assert parsed["params"]["event_type"] == "agent_response"
        assert parsed["params"]["payload"]["text"] == "Hello"

    def test_compact_json_formatting(self):
        """Wire protocol should use compact JSON without whitespace."""
        event = to_wire_event(
            event_type="test",
            run_id="run-123",
            session_id="session-456",
            payload={"key": "value"},
        )

        # Should not contain extra whitespace
        assert "  " not in event  # No double spaces
        assert "\n" not in event  # No newlines
        assert "\t" not in event  # No tabs

    def test_all_methods_have_proper_error_codes(self):
        """All parameter validation errors should use correct JSON-RPC codes."""
        test_cases = [
            ("invoke_agent", {}, INVALID_PARAMS),
            ("invoke_agent", {"agent_name": "test"}, INVALID_PARAMS),
            ("run_shell", {}, INVALID_PARAMS),
            ("file_list", {}, INVALID_PARAMS),
            ("file_read", {}, INVALID_PARAMS),
            ("file_write", {}, INVALID_PARAMS),
            ("file_write", {"path": "/test"}, INVALID_PARAMS),
            ("grep_search", {}, INVALID_PARAMS),
            ("nonexistent", {}, METHOD_NOT_FOUND),
        ]

        for method, params, expected_code in test_cases:
            with pytest.raises(WireMethodError) as exc_info:
                from_wire_params(method, params)
            assert exc_info.value.code == expected_code, (
                f"Method {method} should return code {expected_code}"
            )