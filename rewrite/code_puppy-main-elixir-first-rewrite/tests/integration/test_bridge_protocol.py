"""
Integration tests for Python↔Elixir bridge protocol V1.

These tests verify that:
1. Wire format matches BRIDGE_PROTOCOL_V1.md specification
2. All canonical event methods are correctly formatted
3. Request/response structures are correct
4. Content-Length framing works correctly
5. Error codes match JSON-RPC 2.0 specification

See: docs/protocol/BRIDGE_PROTOCOL_V1.md
"""

import json
import pytest
from datetime import datetime, timezone

# Import the wire protocol module with V1 canonical methods
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    from_wire_params,
    frame_message,
    JsonRpcError,
    WireMethodError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
    # V1 canonical emitters
    emit_run_status,
    emit_run_text,
    emit_run_tool_result,
    emit_run_completed,
    emit_run_failed,
    emit_run_prompt,
    emit_run_event,
    emit_bridge_ready,
    emit_bridge_closing,
    to_canonical_notification,
)


class TestCanonicalEventFormat:
    """Test that V1 canonical events match the protocol specification."""

    def test_run_status_has_required_fields(self):
        """run.status must have jsonrpc, method, and params with run_id, status, timestamp."""
        notification = emit_run_status(
            run_id="run-123",
            session_id="session-456",
            status="running",
        )

        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "run.status"
        assert "params" in notification
        assert notification["params"]["run_id"] == "run-123"
        assert notification["params"]["session_id"] == "session-456"
        assert notification["params"]["status"] == "running"
        assert "timestamp" in notification["params"]

    def test_run_text_has_required_fields(self):
        """run.text must have run_id, text, finished, timestamp."""
        notification = emit_run_text(
            run_id="run-123",
            session_id="session-456",
            text="Hello world",
            finished=True,
        )

        assert notification["method"] == "run.text"
        assert notification["params"]["text"] == "Hello world"
        assert notification["params"]["finished"] is True
        assert "timestamp" in notification["params"]

    def test_run_tool_result_has_required_fields(self):
        """run.tool_result must have run_id, tool_call_id, tool_name, result."""
        notification = emit_run_tool_result(
            run_id="run-123",
            session_id="session-456",
            tool_call_id="call-789",
            tool_name="file_read",
            result={"content": "test data"},
        )

        assert notification["method"] == "run.tool_result"
        assert notification["params"]["tool_call_id"] == "call-789"
        assert notification["params"]["tool_name"] == "file_read"
        assert notification["params"]["result"]["content"] == "test data"

    def test_run_completed_has_required_fields(self):
        """run.completed must have run_id and timestamp."""
        notification = emit_run_completed(
            run_id="run-123",
            session_id="session-456",
            result={"output": "done"},
        )

        assert notification["method"] == "run.completed"
        assert notification["params"]["run_id"] == "run-123"
        assert notification["params"]["result"]["output"] == "done"
        assert "timestamp" in notification["params"]

    def test_run_failed_has_required_fields(self):
        """run.failed must have run_id and error with code and message."""
        notification = emit_run_failed(
            run_id="run-123",
            session_id="session-456",
            error_code=-32000,
            error_message="Something went wrong",
            error_details={"traceback": "..."},
        )

        assert notification["method"] == "run.failed"
        assert notification["params"]["run_id"] == "run-123"
        assert notification["params"]["error"]["code"] == -32000
        assert notification["params"]["error"]["message"] == "Something went wrong"
        assert notification["params"]["error"]["details"]["traceback"] == "..."

    def test_run_prompt_has_required_fields(self):
        """run.prompt must have run_id, prompt_id, question."""
        notification = emit_run_prompt(
            run_id="run-123",
            session_id="session-456",
            prompt_id="prompt-789",
            question="What file should I analyze?",
            options=["src/", "tests/", "docs/"],
        )

        assert notification["method"] == "run.prompt"
        assert notification["params"]["prompt_id"] == "prompt-789"
        assert notification["params"]["question"] == "What file should I analyze?"
        assert notification["params"]["options"] == ["src/", "tests/", "docs/"]

    def test_run_event_generic(self):
        """run.event is the generic fallback for unknown event types."""
        notification = emit_run_event(
            run_id="run-123",
            session_id="session-456",
            event_type="custom_event",
            data={"foo": "bar"},
        )

        assert notification["method"] == "run.event"
        assert notification["params"]["event_type"] == "custom_event"
        assert notification["params"]["data"]["foo"] == "bar"

    def test_bridge_ready_has_required_fields(self):
        """bridge.ready must have capabilities and version."""
        notification = emit_bridge_ready(
            capabilities=["shell", "file_ops", "agents"],
            version="1.0.0",
        )

        assert notification["method"] == "bridge.ready"
        assert notification["params"]["capabilities"] == ["shell", "file_ops", "agents"]
        assert notification["params"]["version"] == "1.0.0"
        assert "timestamp" in notification["params"]

    def test_bridge_closing_has_required_fields(self):
        """bridge.closing must have reason and timestamp."""
        notification = emit_bridge_closing(reason="shutdown")

        assert notification["method"] == "bridge.closing"
        assert notification["params"]["reason"] == "shutdown"
        assert "timestamp" in notification["params"]

    def test_timestamp_is_iso8601(self):
        """Timestamp must be ISO 8601 format."""
        notification = emit_run_status(
            run_id="run-123",
            session_id="session-456",
            status="running",
        )

        timestamp = notification["params"]["timestamp"]
        # Should parse without error
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert dt is not None
        # Should be UTC
        assert dt.tzinfo is not None

    def test_timestamp_utc(self):
        """Timestamp should be in UTC."""
        import time

        before = time.time()
        notification = emit_run_status(
            run_id="run-123",
            session_id="session-456",
            status="running",
        )
        after = time.time()

        timestamp = notification["params"]["timestamp"]
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Convert to timestamp for comparison (ignoring microsecond differences)
        event_ts = dt.timestamp()
        # Should be within test execution window (with small tolerance)
        assert before - 1 <= event_ts <= after + 1

    def test_optional_session_id_omitted(self):
        """Session ID should be omitted from params when None."""
        notification = emit_run_status(
            run_id="run-123",
            session_id=None,
            status="running",
        )

        assert "session_id" not in notification["params"]


class TestEventTypeMapping:
    """Test that internal event types map to canonical methods."""

    @pytest.mark.parametrize(
        ("event_type", "expected_method"),
        [
            ("status", "run.status"),
            ("text", "run.text"),
            ("tool_output", "run.tool_result"),
            ("completed", "run.completed"),
            ("failed", "run.failed"),
            ("prompt", "run.prompt"),
            ("unknown_event", "run.event"),
        ],
    )
    def test_event_type_mapping(self, event_type, expected_method):
        """Internal event types should map to correct canonical methods."""
        notification = to_canonical_notification(
            event_type=event_type,
            run_id="run-123",
            session_id="sess-456",
            payload={"test": "data"},
        )

        assert notification["method"] == expected_method

    def test_status_mapping_extracts_status_field(self):
        """Status event should extract status from payload."""
        notification = to_canonical_notification(
            event_type="status",
            run_id="run-123",
            session_id="sess-456",
            payload={"status": "completed"},
        )

        assert notification["method"] == "run.status"
        assert notification["params"]["status"] == "completed"

    def test_text_mapping_extracts_text_field(self):
        """Text event should extract text from payload."""
        notification = to_canonical_notification(
            event_type="text",
            run_id="run-123",
            session_id="sess-456",
            payload={"text": "Hello", "finished": True},
        )

        assert notification["method"] == "run.text"
        assert notification["params"]["text"] == "Hello"
        assert notification["params"]["finished"] is True

    def test_tool_output_mapping_extracts_tool_fields(self):
        """Tool output event should extract tool fields from payload."""
        notification = to_canonical_notification(
            event_type="tool_output",
            run_id="run-123",
            session_id="sess-456",
            payload={
                "tool_call_id": "call-789",
                "tool_name": "file_read",
                "result": {"content": "test"},
            },
        )

        assert notification["method"] == "run.tool_result"
        assert notification["params"]["tool_call_id"] == "call-789"
        assert notification["params"]["tool_name"] == "file_read"


class TestRequestValidation:
    """Test that request parameter validation works correctly for V1 methods."""

    def test_run_start_valid_params(self):
        """run.start requires agent_name and prompt."""
        params = {
            "agent_name": "turbo-executor",
            "prompt": "Analyze code",
            "session_id": "session-123",
            "run_id": "run-456",
            "context": {"key": "value"},
        }

        result = from_wire_params("run.start", params)
        assert result["agent_name"] == "turbo-executor"
        assert result["prompt"] == "Analyze code"
        assert result["session_id"] == "session-123"
        assert result["run_id"] == "run-456"
        assert result["context"] == {"key": "value"}

    def test_run_start_missing_agent_name(self):
        """run.start should reject missing agent_name."""
        params = {"prompt": "Analyze code"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("run.start", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_run_start_missing_prompt(self):
        """run.start should reject missing prompt."""
        params = {"agent_name": "turbo-executor"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("run.start", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_run_cancel_valid_params(self):
        """run.cancel requires run_id."""
        params = {"run_id": "run-123", "reason": "user_requested"}

        result = from_wire_params("run.cancel", params)
        assert result["run_id"] == "run-123"
        assert result["reason"] == "user_requested"

    def test_run_cancel_missing_run_id(self):
        """run.cancel should reject missing run_id."""
        params = {"reason": "timeout"}

        with pytest.raises(WireMethodError) as exc_info:
            from_wire_params("run.cancel", params)
        assert exc_info.value.code == INVALID_PARAMS

    def test_run_cancel_default_reason(self):
        """run.cancel should use default reason."""
        params = {"run_id": "run-123"}

        result = from_wire_params("run.cancel", params)
        assert result["reason"] == "user_requested"

    def test_initialize_valid_params(self):
        """initialize accepts capabilities and config."""
        params = {
            "capabilities": ["shell", "agents"],
            "config": {"timeout": 30},
        }

        result = from_wire_params("initialize", params)
        assert result["capabilities"] == ["shell", "agents"]
        assert result["config"] == {"timeout": 30}

    def test_exit_valid_params(self):
        """exit accepts reason and timeout_ms."""
        params = {"reason": "upgrade", "timeout_ms": 10000}

        result = from_wire_params("exit", params)
        assert result["reason"] == "upgrade"
        assert result["timeout_ms"] == 10000

    def test_exit_default_params(self):
        """exit should use default values."""
        params = {}

        result = from_wire_params("exit", params)
        assert result["reason"] == "shutdown"
        assert result["timeout_ms"] == 5000

    def test_slash_to_dot_normalization(self):
        """Slash-style method names should normalize to dot-style."""
        params = {"run_id": "run-123", "reason": "test"}

        # Use slash-style method name
        result = from_wire_params("run/cancel", params)
        assert result["run_id"] == "run-123"

    # Legacy method tests (kept for backward compatibility during transition)

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
        params = {"prompt": "Hello!"}

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

    def test_run_shell_valid_params(self):
        """run_shell requires command."""
        params = {"command": "ls -la", "cwd": "/tmp", "timeout": 30}

        result = from_wire_params("run_shell", params)
        assert result["command"] == "ls -la"
        assert result["cwd"] == "/tmp"
        assert result["timeout"] == 30

    def test_ping_no_params_required(self):
        """ping should work with empty params."""
        result = from_wire_params("ping", {})
        assert result == {}

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
            "method": "run.text",
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


class TestWireProtocolIntegration:
    """Integration tests for the complete wire protocol flow."""

    def test_notification_round_trip(self):
        """Notifications should serialize and frame correctly."""
        notification = emit_run_text(
            run_id="run-123",
            session_id="session-456",
            text="Hello",
            finished=False,
        )

        # Frame and unframe
        framed = frame_message(notification)
        _, body = framed.split(b"\r\n\r\n", 1)
        parsed = json.loads(body)

        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "run.text"
        assert parsed["params"]["text"] == "Hello"
        assert parsed["params"]["run_id"] == "run-123"

    def test_compact_json_formatting(self):
        """Wire protocol should use compact JSON without whitespace."""
        notification = emit_run_status(
            run_id="run-123",
            session_id="session-456",
            status="running",
        )

        # Frame it
        framed = frame_message(notification)
        _, body = framed.split(b"\r\n\r\n", 1)
        json_str = body.decode("utf-8")

        # Should not contain extra whitespace
        assert "  " not in json_str  # No double spaces
        assert "\n" not in json_str  # No newlines
        assert "\t" not in json_str  # No tabs

    def test_all_v1_methods_have_proper_error_codes(self):
        """All V1 method parameter validation errors should use correct JSON-RPC codes."""
        test_cases = [
            ("run.start", {}, INVALID_PARAMS),
            ("run.start", {"agent_name": "test"}, INVALID_PARAMS),
            ("run.cancel", {}, INVALID_PARAMS),
            ("invoke_agent", {}, INVALID_PARAMS),  # Legacy
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