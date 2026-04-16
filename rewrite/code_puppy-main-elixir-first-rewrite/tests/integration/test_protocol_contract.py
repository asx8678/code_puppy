"""Protocol Contract Tests - Verify BRIDGE_PROTOCOL_V1.md compliance.

These tests ensure that the Python bridge implementation exactly matches
the BRIDGE_PROTOCOL_V1.md specification, serving as a contract between
the Python and Elixir implementations.

Contract tests verify:
1. Canonical method names are used (not legacy slash-style or underscore)
2. Message structure matches the spec
3. Framing follows Content-Length protocol
4. No deprecated methods are emitted

See: docs/protocol/BRIDGE_PROTOCOL_V1.md
"""

from __future__ import annotations

import json
import pytest
from typing import Any

# Import from the actual implementation location
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    emit_run_status,
    emit_run_text,
    emit_run_completed,
    emit_run_failed,
    emit_run_tool_result,
    emit_run_prompt,
    emit_run_event,
    emit_bridge_ready,
    emit_bridge_closing,
    frame_message,
    parse_framed_message,
    to_canonical_notification,
    from_wire_params,
    WireMethodError,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
)


class TestProtocolContract:
    """Contract tests ensuring Python bridge matches BRIDGE_PROTOCOL_V1.md."""

    def test_run_status_format(self) -> None:
        """Verify run.status notification has correct structure per spec."""
        msg = emit_run_status(
            run_id="run-123", session_id="sess-456", status="running"
        )

        # Must have jsonrpc field
        assert msg["jsonrpc"] == "2.0", "Must use JSON-RPC 2.0"

        # Must use canonical method name
        assert msg["method"] == "run.status", "Must use dot-style method name"

        # Must have params with required fields
        assert "params" in msg, "Must have params field"
        params = msg["params"]
        assert "run_id" in params, "params must contain run_id"
        assert params["run_id"] == "run-123"
        assert "session_id" in params, "params must contain session_id"
        assert "status" in params, "params must contain status"
        assert "timestamp" in params, "params must contain timestamp"

    def test_run_text_format(self) -> None:
        """Verify run.text notification has correct structure per spec."""
        msg = emit_run_text(
            run_id="run-123",
            session_id="sess-456",
            text="Hello world",
            finished=True,
        )

        assert msg["method"] == "run.text"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert params["text"] == "Hello world"
        assert params["finished"] is True
        assert "timestamp" in params

    def test_run_completed_format(self) -> None:
        """Verify run.completed notification has correct structure per spec."""
        msg = emit_run_completed(
            run_id="run-123",
            session_id="sess-456",
            result={"output": "success"},
        )

        assert msg["method"] == "run.completed"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert params["result"]["output"] == "success"
        assert "timestamp" in params

    def test_run_failed_format(self) -> None:
        """Verify run.failed notification has correct structure per spec."""
        msg = emit_run_failed(
            run_id="run-123",
            session_id="sess-456",
            error_code=-32000,
            error_message="Something went wrong",
            error_details={"traceback": "line 1"},
        )

        assert msg["method"] == "run.failed"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert "error" in params
        assert params["error"]["code"] == -32000
        assert params["error"]["message"] == "Something went wrong"
        assert params["error"]["details"]["traceback"] == "line 1"
        assert "timestamp" in params

    def test_run_tool_result_format(self) -> None:
        """Verify run.tool_result notification has correct structure per spec."""
        msg = emit_run_tool_result(
            run_id="run-123",
            session_id="sess-456",
            tool_call_id="call-789",
            tool_name="file_read",
            result={"content": "test"},
        )

        assert msg["method"] == "run.tool_result"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert params["tool_call_id"] == "call-789"
        assert params["tool_name"] == "file_read"
        assert params["result"]["content"] == "test"
        assert "timestamp" in params

    def test_run_prompt_format(self) -> None:
        """Verify run.prompt notification has correct structure per spec."""
        msg = emit_run_prompt(
            run_id="run-123",
            session_id="sess-456",
            prompt_id="prompt-789",
            question="Continue?",
            options=["yes", "no"],
        )

        assert msg["method"] == "run.prompt"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert params["prompt_id"] == "prompt-789"
        assert params["question"] == "Continue?"
        assert params["options"] == ["yes", "no"]
        assert "timestamp" in params

    def test_run_event_format(self) -> None:
        """Verify run.event notification has correct structure per spec."""
        msg = emit_run_event(
            run_id="run-123",
            session_id="sess-456",
            event_type="custom",
            data={"foo": "bar"},
        )

        assert msg["method"] == "run.event"
        params = msg["params"]
        assert params["run_id"] == "run-123"
        assert params["event_type"] == "custom"
        assert params["data"]["foo"] == "bar"
        assert "timestamp" in params

    def test_bridge_ready_format(self) -> None:
        """Verify bridge.ready notification has correct structure per spec."""
        msg = emit_bridge_ready(
            capabilities=["shell", "agents"],
            version="1.0.0",
        )

        assert msg["method"] == "bridge.ready"
        params = msg["params"]
        assert params["capabilities"] == ["shell", "agents"]
        assert params["version"] == "1.0.0"
        assert "timestamp" in params

    def test_bridge_closing_format(self) -> None:
        """Verify bridge.closing notification has correct structure per spec."""
        msg = emit_bridge_closing(reason="shutdown")

        assert msg["method"] == "bridge.closing"
        params = msg["params"]
        assert params["reason"] == "shutdown"
        assert "timestamp" in params


class TestCanonicalMethodNames:
    """Verify all canonical method names from BRIDGE_PROTOCOL_V1.md are implemented."""

    def test_all_canonical_notification_methods_exist(self) -> None:
        """Verify all Python→Elixir notification methods from spec exist."""
        # Per BRIDGE_PROTOCOL_V1.md Section 3.2:
        # Python → Elixir Notifications:
        # - run.status, run.event, run.completed, run.failed
        # - run.text, run.tool_result, run.prompt
        # - bridge.ready, bridge.closing

        test_cases = [
            ("run.status", emit_run_status),
            ("run.text", emit_run_text),
            ("run.completed", emit_run_completed),
            ("run.failed", emit_run_failed),
            ("run.tool_result", emit_run_tool_result),
            ("run.prompt", emit_run_prompt),
            ("run.event", emit_run_event),
            ("bridge.ready", emit_bridge_ready),
            ("bridge.closing", emit_bridge_closing),
        ]

        for expected_method, emitter_func in test_cases:
            # Emit a test message and verify the method name
            if expected_method == "run.status":
                msg = emitter_func("run-1", "sess-1", "running")
            elif expected_method == "run.text":
                msg = emitter_func("run-1", "sess-1", "test")
            elif expected_method == "run.completed":
                msg = emitter_func("run-1", "sess-1")
            elif expected_method == "run.failed":
                msg = emitter_func("run-1", "sess-1", -32000, "error")
            elif expected_method == "run.tool_result":
                msg = emitter_func("run-1", "sess-1", "call-1", "tool", {})
            elif expected_method == "run.prompt":
                msg = emitter_func("run-1", "sess-1", "prompt-1", "question?")
            elif expected_method == "run.event":
                msg = emitter_func("run-1", "sess-1", "type", {})
            elif expected_method == "bridge.ready":
                msg = emitter_func(["shell"])
            elif expected_method == "bridge.closing":
                msg = emitter_func()
            else:
                pytest.fail(f"Unknown method: {expected_method}")

            assert msg["method"] == expected_method, (
                f"Method name mismatch for {expected_method}: got {msg['method']}"
            )

    def test_all_canonical_request_methods_supported(self) -> None:
        """Verify all Elixir→Python request methods from spec are handled."""
        # Per BRIDGE_PROTOCOL_V1.md Section 3.1:
        # Elixir → Python Requests:
        # - run.start, run.cancel, initialize, exit
        # - invoke_agent, run_shell, file_list, file_read, file_write
        # - grep_search, get_status, ping

        # These should not raise METHOD_NOT_FOUND
        supported_methods = [
            "run.start",
            "run.cancel",
            "initialize",
            "exit",
            "invoke_agent",
            "run_shell",
            "file_list",
            "file_read",
            "file_write",
            "grep_search",
            "get_status",
            "ping",
        ]

        for method in supported_methods:
            # Should not raise METHOD_NOT_FOUND (may raise INVALID_PARAMS for missing args)
            try:
                # Use minimal valid params for each method
                if method == "run.start":
                    from_wire_params(method, {"agent_name": "test", "prompt": "test"})
                elif method == "run.cancel":
                    from_wire_params(method, {"run_id": "test"})
                elif method == "run_shell":
                    from_wire_params(method, {"command": "ls"})
                elif method == "file_list":
                    from_wire_params(method, {"directory": "."})
                elif method == "file_read":
                    from_wire_params(method, {"path": "test.txt"})
                elif method == "file_write":
                    from_wire_params(method, {"path": "test.txt", "content": "test"})
                elif method == "grep_search":
                    from_wire_params(method, {"search_string": "test"})
                else:
                    # initialize, exit, get_status, ping, invoke_agent - work with empty or minimal
                    try:
                        from_wire_params(method, {})
                    except WireMethodError as e:
                        if e.code == INVALID_PARAMS:
                            # Expected for methods requiring params
                            pass
                        else:
                            raise
            except WireMethodError as e:
                assert e.code != METHOD_NOT_FOUND, (
                    f"Method {method} should be supported but got METHOD_NOT_FOUND"
                )


class TestNoLegacyMethods:
    """Verify deprecated/legacy methods are NOT used per BRIDGE_PROTOCOL_V1.md Section 7."""

    def test_no_slash_style_methods(self) -> None:
        """Legacy slash-style methods (run/start, run/cancel) are deprecated."""
        # Per spec 7.1: run/start -> run.start, run/cancel -> run.cancel
        # from_wire_params should normalize slash to dot, but emitters should use dot

        # Test that normalization works (so we're compatible)
        result = from_wire_params("run/cancel", {"run_id": "test"})
        assert result["run_id"] == "test"

        # But emitters should NEVER produce slash-style methods
        # All our emit functions are tested in TestCanonicalMethodNames

    def test_no_underscore_style_bridge_methods(self) -> None:
        """Legacy underscore bridge methods (bridge_ready, bridge_closing) are deprecated."""
        # Per spec 7.1: bridge_ready -> bridge.ready, bridge_closing -> bridge.closing

        # Verify emitters use dot-style
        ready_msg = emit_bridge_ready([])
        assert ready_msg["method"] == "bridge.ready"
        assert "_" not in ready_msg["method"]

        closing_msg = emit_bridge_closing()
        assert closing_msg["method"] == "bridge.closing"
        assert "_" not in closing_msg["method"]

    def test_no_generic_event_method(self) -> None:
        """Generic 'event' method is replaced by specific methods per spec 7.1."""
        # Per spec 7.1: event -> run.status, run.text, run.tool_result, etc.

        # to_canonical_notification should map internal types to specific methods
        # NOT to generic "event" method

        test_cases = [
            ("status", "run.status"),
            ("text", "run.text"),
            ("tool_output", "run.tool_result"),
            ("completed", "run.completed"),
            ("failed", "run.failed"),
            ("prompt", "run.prompt"),
        ]

        for internal_type, expected_method in test_cases:
            msg = to_canonical_notification(
                event_type=internal_type,
                run_id="run-1",
                session_id="sess-1",
                payload={"status": "test"} if internal_type == "status" else {"text": "test"},
            )
            assert msg["method"] == expected_method, (
                f"Internal type {internal_type} should map to {expected_method}, "
                f"not generic 'event'"
            )

        # Unknown types fall back to run.event (not generic "event")
        unknown_msg = to_canonical_notification(
            event_type="unknown_type",
            run_id="run-1",
            session_id="sess-1",
            payload={},
        )
        assert unknown_msg["method"] == "run.event"
        assert unknown_msg["method"] != "event"


class TestContentLengthFraming:
    """Verify Content-Length framing per BRIDGE_PROTOCOL_V1.md Section 2.1."""

    def test_content_length_framing(self) -> None:
        """Verify framing produces valid Content-Length header."""
        msg = {"jsonrpc": "2.0", "method": "test"}
        framed = frame_message(msg)

        # Must start with Content-Length:
        assert framed.startswith(b"Content-Length: "), "Must have Content-Length header"

        # Must have CRLF CRLF separator
        assert b"\r\n\r\n" in framed, "Must have CRLF CRLF separator"

    def test_content_length_accuracy(self) -> None:
        """Content-Length value must match actual body byte count."""
        msg = {"jsonrpc": "2.0", "method": "test", "params": {"data": "test"}}
        framed = frame_message(msg)

        # Parse the frame
        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])

        # Must match actual body length
        assert content_length == len(body), (
            f"Content-Length {content_length} doesn't match body length {len(body)}"
        )

    def test_round_trip_parsing(self) -> None:
        """Frame and parse should be inverse operations."""
        original = {"jsonrpc": "2.0", "method": "run.event", "params": {"run_id": "test"}}
        framed = frame_message(original)
        parsed = parse_framed_message(framed)

        assert parsed == original, "Round-trip should preserve message exactly"

    def test_parse_invalid_framing(self) -> None:
        """parse_framed_message should reject invalid framing."""
        # Missing separator
        with pytest.raises(WireMethodError) as exc_info:
            parse_framed_message(b"Content-Length: 10")
        assert exc_info.value.code == -32700  # PARSE_ERROR

        # Missing Content-Length header
        with pytest.raises(WireMethodError) as exc_info:
            parse_framed_message(b"X-Header: 10\r\n\r\n{}")
        assert exc_info.value.code == -32700

        # Length mismatch
        with pytest.raises(WireMethodError) as exc_info:
            parse_framed_message(b"Content-Length: 100\r\n\r\n{}")
        assert exc_info.value.code == -32700

    def test_parse_invalid_json(self) -> None:
        """parse_framed_message should reject invalid JSON."""
        bad_json = b'Content-Length: 5\r\n\r\n{ bad'
        with pytest.raises(WireMethodError) as exc_info:
            parse_framed_message(bad_json)
        assert exc_info.value.code == -32700  # PARSE_ERROR


class TestJsonRpc20Compliance:
    """Verify JSON-RPC 2.0 compliance per BRIDGE_PROTOCOL_V1.md Section 2.2."""

    def test_all_messages_have_jsonrpc_field(self) -> None:
        """All messages must have jsonrpc: "2.0" field."""
        emitters = [
            emit_run_status("run-1", "sess-1", "running"),
            emit_run_text("run-1", "sess-1", "text"),
            emit_run_completed("run-1", "sess-1"),
            emit_run_failed("run-1", "sess-1", -32000, "error"),
            emit_run_tool_result("run-1", "sess-1", "call-1", "tool", {}),
            emit_run_prompt("run-1", "sess-1", "p-1", "q?"),
            emit_run_event("run-1", "sess-1", "type", {}),
            emit_bridge_ready(["shell"]),
            emit_bridge_closing(),
        ]

        for msg in emitters:
            assert "jsonrpc" in msg, f"Message missing jsonrpc field: {msg}"
            assert msg["jsonrpc"] == "2.0", f"jsonrpc must be '2.0': {msg}"

    def test_notifications_have_no_id(self) -> None:
        """Notifications (Python→Elixir) must NOT have id field per JSON-RPC 2.0."""
        # Per spec 2.2.3: Notifications have no `id` field
        msg = emit_run_status("run-1", "sess-1", "running")
        assert "id" not in msg, f"Notification should not have id: {msg}"

    def test_compact_json_encoding(self) -> None:
        """Wire protocol must use compact JSON without whitespace."""
        msg = {"jsonrpc": "2.0", "method": "test", "params": {"key": "value"}}
        framed = frame_message(msg)
        _, body = framed.split(b"\r\n\r\n", 1)
        json_str = body.decode("utf-8")

        # No extra whitespace
        assert "  " not in json_str, "No double spaces allowed"
        assert "\n" not in json_str, "No newlines allowed"
        assert "\t" not in json_str, "No tabs allowed"
        assert ": " not in json_str, "No space after colon allowed"


class TestTimestampFormat:
    """Verify ISO 8601 timestamp format per BRIDGE_PROTOCOL_V1.md."""

    def test_timestamp_is_iso8601_utc(self) -> None:
        """Timestamps must be ISO 8601 format in UTC."""
        from datetime import datetime

        msg = emit_run_status("run-1", "sess-1", "running")
        timestamp = msg["params"]["timestamp"]

        # Must be parseable as ISO 8601
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert dt.tzinfo is not None, "Timestamp must have timezone"


class TestErrorCodes:
    """Verify JSON-RPC 2.0 error codes per BRIDGE_PROTOCOL_V1.md Section 5."""

    def test_standard_error_codes(self) -> None:
        """Standard JSON-RPC 2.0 error codes must match spec."""
        from code_puppy.plugins.elixir_bridge.wire_protocol import (
            PARSE_ERROR,
            INVALID_REQUEST,
            METHOD_NOT_FOUND,
            INVALID_PARAMS,
            INTERNAL_ERROR,
        )

        # Per spec Section 5
        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602
        assert INTERNAL_ERROR == -32603


class TestEventTypeMappingCompliance:
    """Verify to_canonical_notification maps per BRIDGE_PROTOCOL_V1.md Section 8.1."""

    @pytest.mark.parametrize(
        ("internal_type", "canonical_method", "required_payload"),
        [
            ("status", "run.status", {"status": "running"}),
            ("text", "run.text", {"text": "hello"}),
            ("tool_output", "run.tool_result", {"tool_call_id": "c1", "tool_name": "t1", "result": {}}),
            ("completed", "run.completed", {}),
            ("failed", "run.failed", {"error_code": -32000, "error_message": "err"}),
            ("prompt", "run.prompt", {"prompt_id": "p1", "question": "q?"}),
        ],
    )
    def test_event_type_mapping(
        self,
        internal_type: str,
        canonical_method: str,
        required_payload: dict[str, Any],
    ) -> None:
        """Verify each internal event type maps to correct canonical method."""
        msg = to_canonical_notification(
            event_type=internal_type,
            run_id="run-123",
            session_id="sess-456",
            payload=required_payload,
        )

        assert msg["method"] == canonical_method, (
            f"Internal type '{internal_type}' must map to '{canonical_method}'"
        )
        assert msg["params"]["run_id"] == "run-123"
        assert msg["params"]["session_id"] == "sess-456"
        assert "timestamp" in msg["params"]
