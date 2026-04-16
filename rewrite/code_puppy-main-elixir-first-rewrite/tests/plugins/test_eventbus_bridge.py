"""Tests for MessageBus → EventBus bridge functionality (bd-79).

Tests the bidirectional event routing between Python MessageBus and Elixir EventBus:
1. Wire protocol emit methods for eventbus messages
2. Bridge controller handler for incoming events from Elixir
3. notify_elixir_event for outgoing events to Elixir
4. MessageBus integration with _notify_elixir_if_connected
5. End-to-end dispatch integration

See: docs/adr/ADR-002-python-elixir-event-protocol.md
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from code_puppy.plugins.elixir_bridge.bridge_controller import BridgeController
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    emit_eventbus_broadcast,
    emit_eventbus_subscribe,
    emit_eventbus_unsubscribe,
    WireMethodError,
    INVALID_PARAMS,
)
from code_puppy.plugins.elixir_bridge import notify_elixir_event
from code_puppy.messaging.bus import MessageBus
from code_puppy.messaging.messages import (
    TextMessage,
    ShellOutputMessage,
    MessageLevel,
    MessageCategory,
)


# =============================================================================
# Wire Protocol Tests
# =============================================================================


class TestEmitEventbusBroadcast:
    """Test emit_eventbus_broadcast wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_eventbus_broadcast should return valid JSON-RPC notification."""
        result = emit_eventbus_broadcast(
            topic="session:abc123",
            event_type="agent_run_start",
            payload={"agent_name": "test-agent"},
        )

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "eventbus.broadcast"
        assert "params" in result
        assert result["params"]["topic"] == "session:abc123"
        assert result["params"]["event_type"] == "agent_run_start"
        assert result["params"]["payload"] == {"agent_name": "test-agent"}
        assert "timestamp" in result["params"]

    def test_with_session_topic(self) -> None:
        """emit_eventbus_broadcast should work with session topics."""
        result = emit_eventbus_broadcast(
            topic="session:xyz789",
            event_type="tool_call",
            payload={"tool": "read_file"},
        )

        assert result["params"]["topic"] == "session:xyz789"

    def test_with_run_topic(self) -> None:
        """emit_eventbus_broadcast should work with run topics."""
        result = emit_eventbus_broadcast(
            topic="run:task-123",
            event_type="text_delta",
            payload={"content": "Hello world"},
        )

        assert result["params"]["topic"] == "run:task-123"

    def test_with_global_topic(self) -> None:
        """emit_eventbus_broadcast should work with global topics."""
        result = emit_eventbus_broadcast(
            topic="global:events",
            event_type="system_notification",
            payload={"message": "System update"},
        )

        assert result["params"]["topic"] == "global:events"

    def test_with_various_event_types(self) -> None:
        """emit_eventbus_broadcast should work with different event types."""
        event_types = [
            "agent_run_start",
            "agent_run_end",
            "tool_call",
            "tool_result",
            "text_delta",
            "status_update",
            "error",
            "completed",
        ]

        for event_type in event_types:
            result = emit_eventbus_broadcast(
                topic="session:test",
                event_type=event_type,
                payload={},
            )
            assert result["params"]["event_type"] == event_type

    def test_with_custom_timestamp(self) -> None:
        """emit_eventbus_broadcast should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="test",
            payload={},
            timestamp=custom_ts,
        )

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_eventbus_broadcast should auto-generate timestamp if not provided."""
        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="test",
            payload={},
        )

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        # Should be ISO 8601 format (contains T and ends with Z)
        assert "T" in timestamp
        assert timestamp.endswith("Z")

    def test_preserves_payload_structure(self) -> None:
        """emit_eventbus_broadcast should preserve complex payload structures."""
        complex_payload = {
            "nested": {"deep": {"value": 123}},
            "list": [1, 2, 3],
            "mixed": ["a", 1, {"b": 2}],
            "null": None,
            "bool": True,
        }

        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="complex",
            payload=complex_payload,
        )

        assert result["params"]["payload"] == complex_payload


class TestEmitEventbusSubscribe:
    """Test emit_eventbus_subscribe wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_eventbus_subscribe should return valid JSON-RPC request."""
        result = emit_eventbus_subscribe(topic="session:abc123")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "eventbus.subscribe"
        assert "params" in result
        assert result["params"]["topic"] == "session:abc123"
        assert "timestamp" in result["params"]

    def test_with_session_topic(self) -> None:
        """emit_eventbus_subscribe should work with session topics."""
        result = emit_eventbus_subscribe(topic="session:xyz789")
        assert result["params"]["topic"] == "session:xyz789"

    def test_with_run_topic(self) -> None:
        """emit_eventbus_subscribe should work with run topics."""
        result = emit_eventbus_subscribe(topic="run:task-456")
        assert result["params"]["topic"] == "run:task-456"

    def test_with_global_topic(self) -> None:
        """emit_eventbus_subscribe should work with global topics."""
        result = emit_eventbus_subscribe(topic="global:events")
        assert result["params"]["topic"] == "global:events"

    def test_with_custom_timestamp(self) -> None:
        """emit_eventbus_subscribe should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_eventbus_subscribe(topic="session:test", timestamp=custom_ts)
        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_eventbus_subscribe should auto-generate timestamp if not provided."""
        result = emit_eventbus_subscribe(topic="session:test")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitEventbusUnsubscribe:
    """Test emit_eventbus_unsubscribe wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_eventbus_unsubscribe should return valid JSON-RPC request."""
        result = emit_eventbus_unsubscribe(topic="session:abc123")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "eventbus.unsubscribe"
        assert "params" in result
        assert result["params"]["topic"] == "session:abc123"
        assert "timestamp" in result["params"]

    def test_with_session_topic(self) -> None:
        """emit_eventbus_unsubscribe should work with session topics."""
        result = emit_eventbus_unsubscribe(topic="session:xyz789")
        assert result["params"]["topic"] == "session:xyz789"

    def test_with_run_topic(self) -> None:
        """emit_eventbus_unsubscribe should work with run topics."""
        result = emit_eventbus_unsubscribe(topic="run:task-456")
        assert result["params"]["topic"] == "run:task-456"

    def test_with_global_topic(self) -> None:
        """emit_eventbus_unsubscribe should work with global topics."""
        result = emit_eventbus_unsubscribe(topic="global:events")
        assert result["params"]["topic"] == "global:events"

    def test_with_custom_timestamp(self) -> None:
        """emit_eventbus_unsubscribe should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_eventbus_unsubscribe(topic="session:test", timestamp=custom_ts)
        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_eventbus_unsubscribe should auto-generate timestamp if not provided."""
        result = emit_eventbus_unsubscribe(topic="session:test")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestTopicValidation:
    """Test various topic formats."""

    def test_session_topic_with_uuid(self) -> None:
        """Should handle session topics with UUIDs."""
        topic = "session:550e8400-e29b-41d4-a716-446655440000"
        result = emit_eventbus_broadcast(topic=topic, event_type="test", payload={})
        assert result["params"]["topic"] == topic

    def test_run_topic_with_uuid(self) -> None:
        """Should handle run topics with UUIDs."""
        topic = "run:550e8400-e29b-41d4-a716-446655440000"
        result = emit_eventbus_broadcast(topic=topic, event_type="test", payload={})
        assert result["params"]["topic"] == topic

    def test_topic_with_special_chars(self) -> None:
        """Should handle topics with various valid characters."""
        topics = [
            "session:user_123",
            "run:task-name",
            "session:scope.subscope",
            "global:events.v1",
        ]

        for topic in topics:
            result = emit_eventbus_broadcast(topic=topic, event_type="test", payload={})
            assert result["params"]["topic"] == topic


# =============================================================================
# Bridge Controller Handler Tests
# =============================================================================


@pytest.fixture
def controller() -> BridgeController:
    """Create a fresh bridge controller for each test."""
    return BridgeController()


@pytest.fixture
def mock_message_bus() -> MagicMock:
    """Create a mock MessageBus."""
    bus = MagicMock(spec=MessageBus)
    bus.emit = MagicMock()
    return bus


class TestHandleEventbusEvent:
    """Test _handle_eventbus_event bridge controller method."""

    @pytest.mark.asyncio
    async def test_routes_text_event_to_message_bus(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should route text event from Elixir to MessageBus."""
        params = {
            "topic": "session:abc123",
            "event_type": "text_delta",
            "payload": {"content": "Hello from Elixir"},
            "timestamp": "2024-01-15T10:30:00Z",
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        assert result["topic"] == "session:abc123"
        assert result["event_type"] == "text_delta"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_tool_result_event_to_message_bus(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should route tool_result event from Elixir to MessageBus."""
        params = {
            "topic": "run:task-456",
            "event_type": "tool_result",
            "payload": {
                "tool_name": "read_file",
                "result": {"content": "file contents"},
            },
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_status_event_to_message_bus(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should route status event from Elixir to MessageBus."""
        params = {
            "topic": "session:abc123",
            "event_type": "status_update",
            "payload": {"status": "running", "progress": 50},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_empty_payload(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle events with empty payload."""
        params = {
            "topic": "global:events",
            "event_type": "heartbeat",
            "payload": {},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_missing_payload(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle events without payload field."""
        params = {
            "topic": "session:abc123",
            "event_type": "simple_event",
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_topic_in_message_text(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Message text should include the topic information."""
        params = {
            "topic": "session:abc123",
            "event_type": "test_event",
            "payload": {"data": "value"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            await controller._handle_eventbus_event(params)

        call_args = mock_message_bus.emit.call_args
        message = call_args[0][0]
        assert "session:abc123" in message.text
        assert "test_event" in message.text

    @pytest.mark.asyncio
    async def test_uses_info_level_for_events(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should use INFO level for event messages."""
        params = {
            "topic": "session:abc123",
            "event_type": "any_event",
            "payload": {},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            await controller._handle_eventbus_event(params)

        call_args = mock_message_bus.emit.call_args
        message = call_args[0][0]
        assert message.level == MessageLevel.INFO

    @pytest.mark.asyncio
    async def test_uses_system_category_for_events(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should use SYSTEM category for event messages."""
        params = {
            "topic": "session:abc123",
            "event_type": "test",
            "payload": {},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            await controller._handle_eventbus_event(params)

        call_args = mock_message_bus.emit.call_args
        message = call_args[0][0]
        assert message.category == MessageCategory.SYSTEM

    @pytest.mark.asyncio
    async def test_returns_error_on_exception_without_raising(
        self, controller: BridgeController
    ) -> None:
        """Should return error response but not raise on MessageBus error."""
        params = {
            "topic": "session:abc123",
            "event_type": "test",
            "payload": {},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            side_effect=Exception("MessageBus unavailable"),
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "error"
        assert "MessageBus unavailable" in result["error"]
        assert result["topic"] == "session:abc123"


class TestHandleEventbusEventWithVariousTopics:
    """Test _handle_eventbus_event with different topic types."""

    @pytest.mark.asyncio
    async def test_handles_session_topic(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle session-scoped events."""
        params = {
            "topic": "session:xyz789",
            "event_type": "agent_run_start",
            "payload": {"agent": "test"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        assert "session:xyz789" in mock_message_bus.emit.call_args[0][0].text

    @pytest.mark.asyncio
    async def test_handles_run_topic(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle run-scoped events."""
        params = {
            "topic": "run:task-123",
            "event_type": "completed",
            "payload": {"result": "success"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        assert "run:task-123" in mock_message_bus.emit.call_args[0][0].text

    @pytest.mark.asyncio
    async def test_handles_global_topic(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle global events."""
        params = {
            "topic": "global:events",
            "event_type": "system_notification",
            "payload": {"msg": "Update available"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller._handle_eventbus_event(params)

        assert result["status"] == "ok"
        assert "global:events" in mock_message_bus.emit.call_args[0][0].text


# =============================================================================
# notify_elixir_event Tests
# =============================================================================


class TestNotifyElixirEvent:
    """Test notify_elixir_event function."""

    def test_does_not_raise_on_success(self) -> None:
        """notify_elixir_event should not raise when bridge is connected."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                # Should not raise
                notify_elixir_event(
                    event_type="test_event",
                    payload={"test": "data"},
                    run_id="run-123",
                )

        mock_send.assert_called_once()

    def test_does_not_raise_when_bridge_disconnected(self) -> None:
        """notify_elixir_event should silently return when bridge disconnected."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=False
        ):
            # Should not raise even though disconnected
            notify_elixir_event(
                event_type="test_event",
                payload={"test": "data"},
                session_id="session-123",
            )

    def test_does_not_raise_on_send_exception(self) -> None:
        """notify_elixir_event should silently ignore send errors."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir",
                side_effect=ConnectionError("Send failed"),
            ):
                # Should not raise despite connection error
                notify_elixir_event(
                    event_type="test_event",
                    payload={"test": "data"},
                )

    def test_uses_run_topic_when_run_id_provided(self) -> None:
        """Should use run:<id> topic when run_id is provided."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload={"data": "value"},
                    run_id="run-abc123",
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["topic"] == "run:run-abc123"

    def test_uses_session_topic_when_session_id_provided_no_run_id(self) -> None:
        """Should use session:<id> topic when only session_id is provided."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload={"data": "value"},
                    session_id="session-xyz789",
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["topic"] == "session:session-xyz789"

    def test_uses_global_topic_when_no_ids_provided(self) -> None:
        """Should use global:events topic when no run_id or session_id provided."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload={"data": "value"},
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["topic"] == "global:events"

    def test_run_id_takes_precedence_over_session_id(self) -> None:
        """run_id should take precedence over session_id for topic selection."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload={"data": "value"},
                    run_id="run-123",
                    session_id="session-456",
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["topic"] == "run:run-123"

    def test_adds_session_id_to_payload(self) -> None:
        """Should add session_id to payload if provided."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload={"data": "original"},
                    session_id="session-abc",
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["payload"]["session_id"] == "session-abc"

    def test_preserves_existing_payload_with_session_id(self) -> None:
        """Should preserve existing payload data when adding session_id."""
        original_payload = {"key1": "value1", "key2": "value2"}

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test_event",
                    payload=original_payload.copy(),
                    session_id="session-abc",
                )

        call_args = mock_send.call_args[0][0]
        payload = call_args["params"]["payload"]
        assert payload["key1"] == "value1"
        assert payload["key2"] == "value2"
        assert payload["session_id"] == "session-abc"

    def test_uses_correct_event_type(self) -> None:
        """Should preserve event_type in the message."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="agent_run_start",
                    payload={},
                    run_id="run-123",
                )

        call_args = mock_send.call_args[0][0]
        assert call_args["params"]["event_type"] == "agent_run_start"


class TestNotifyElixirEventAsyncHandling:
    """Test notify_elixir_event async context handling."""

    @pytest.mark.asyncio
    async def test_works_in_async_context(self) -> None:
        """Should work correctly in async context."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test",
                    payload={},
                )

        mock_send.assert_called_once()

    def test_works_in_sync_context(self) -> None:
        """Should work correctly in sync context."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                notify_elixir_event(
                    event_type="test",
                    payload={},
                )

        mock_send.assert_called_once()


# =============================================================================
# MessageBus Integration Tests
# =============================================================================


class TestMessageBusNotifyElixir:
    """Test _notify_elixir_if_connected MessageBus integration."""

    def test_notify_elixir_is_called_on_emit(self) -> None:
        """_notify_elixir_if_connected should be called when emitting messages."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Test message",
            category=MessageCategory.SYSTEM,
        )

        # Patch at class level since instance methods can't be patched directly
        with patch(
            "code_puppy.messaging.bus.MessageBus._notify_elixir_if_connected"
        ) as mock_notify:
            bus.emit(message)

        mock_notify.assert_called_once()

    def test_notify_elixir_is_called_with_correct_message(self) -> None:
        """Should pass the emitted message to _notify_elixir_if_connected."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Specific test content",
            category=MessageCategory.SYSTEM,
        )

        with patch(
            "code_puppy.messaging.bus.MessageBus._notify_elixir_if_connected"
        ) as mock_notify:
            bus.emit(message)

        call_args = mock_notify.call_args[0][0]
        assert call_args.text == "Specific test content"
        assert isinstance(call_args, TextMessage)

    def test_local_delivery_works_when_bridge_fails(self) -> None:
        """Local message delivery should succeed even if bridge notification fails."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Local only",
            category=MessageCategory.SYSTEM,
        )

        # Make bridge notification fail
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected",
            side_effect=Exception("Bridge error"),
        ):
            # Should not raise - local delivery succeeds
            bus.emit(message)

        # Message should be in the buffer
        assert len(list(bus.get_buffered_messages())) == 1

    def test_notify_elixir_does_not_block_emit(self) -> None:
        """MessageBus.emit should not wait for bridge notification."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Non-blocking test",
            category=MessageCategory.SYSTEM,
        )

        # Mock is_connected to be fast but verify emit completes quickly
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=False
        ):
            import time

            start = time.time()
            bus.emit(message)
            elapsed = time.time() - start

        # Should complete quickly
        assert elapsed < 0.1  # emit is fast even with bridge disabled

    def test_notify_elixir_with_text_message(self) -> None:
        """Should extract correct data from TextMessage."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.ERROR,
            text="Error occurred",
            category=MessageCategory.SYSTEM,
        )
        message.session_id = "session-abc"

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["event_type"] == "TextMessage"
        assert call_kwargs["payload"]["text"] == "Error occurred"
        # str(MessageLevel.ERROR) produces "MessageLevel.ERROR"
        assert "error" in call_kwargs["payload"]["level"].lower()
        assert call_kwargs["session_id"] == "session-abc"

    def test_notify_elixir_with_shell_output_message(self) -> None:
        """Should extract correct data from ShellOutputMessage."""
        bus = MessageBus()
        message = ShellOutputMessage(
            command="ls -la",
            stdout="file1.txt file2.txt",
            stderr="",
            exit_code=0,
            duration_seconds=1.5,
        )
        message.session_id = "session-xyz"

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["event_type"] == "ShellOutputMessage"
        # MessageBus extracts: level, category (text is missing from ShellOutputMessage)
        assert "command" not in call_kwargs["payload"]  # Not extracted by MessageBus
        assert call_kwargs["session_id"] == "session-xyz"


class TestMessageBusExtractsPayload:
    """Test MessageBus extracts correct payload from different message types."""

    def test_extracts_level_from_message(self) -> None:
        """Should extract level attribute from message."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.WARNING,
            text="Warning message",
            category=MessageCategory.SYSTEM,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        payload = mock_notify.call_args.kwargs["payload"]
        # str(MessageLevel.WARNING) produces "MessageLevel.WARNING"
        assert "warning" in payload["level"].lower()

    def test_extracts_category_from_message(self) -> None:
        """Should extract category attribute from message."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Agent output",
            category=MessageCategory.AGENT,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        payload = mock_notify.call_args.kwargs["payload"]
        # str(MessageCategory.AGENT) produces "MessageCategory.AGENT"
        assert "agent" in payload["category"].lower()

    def test_handles_message_without_text(self) -> None:
        """Should handle messages that don't have text attribute."""
        bus = MessageBus()
        # Create a minimal mock message
        message = MagicMock()
        message.__class__.__name__ = "MockMessage"
        message.session_id = None
        del message.text  # Ensure no text attribute
        del message.level
        del message.category

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "MockMessage"


class TestMessageBusSilentlyIgnoresErrors:
    """Test that MessageBus ignores bridge errors gracefully."""

    def test_silently_ignores_is_connected_exception(self) -> None:
        """Should ignore exception from is_connected check."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Test",
            category=MessageCategory.SYSTEM,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected",
            side_effect=RuntimeError("Connection check failed"),
        ):
            # Should not raise
            bus._notify_elixir_if_connected(message)

    def test_silently_ignores_notify_exception(self) -> None:
        """Should ignore exception from notify_elixir_event."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Test",
            category=MessageCategory.SYSTEM,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event",
                side_effect=ConnectionError("Notification failed"),
            ):
                # Should not raise
                bus._notify_elixir_if_connected(message)

    def test_silently_ignores_import_error(self) -> None:
        """Should ignore import errors for elixir_bridge module."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Test",
            category=MessageCategory.SYSTEM,
        )

        # Make the import fail
        original_module = None
        import sys

        if "code_puppy.plugins.elixir_bridge" in sys.modules:
            original_module = sys.modules.pop("code_puppy.plugins.elixir_bridge")

        try:
            with patch.dict("sys.modules", {
                "code_puppy.plugins.elixir_bridge": None
            }):
                # ImportError should be caught and ignored
                bus._notify_elixir_if_connected(message)
        finally:
            if original_module:
                sys.modules["code_puppy.plugins.elixir_bridge"] = original_module


# =============================================================================
# End-to-End Dispatch Tests
# =============================================================================


class TestEventbusDispatch:
    """Test that eventbus.event is properly dispatched."""

    @pytest.mark.asyncio
    async def test_dispatch_routes_eventbus_event(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """dispatch should route eventbus.event to _handle_eventbus_event."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eventbus.event",
            "params": {
                "topic": "session:abc123",
                "event_type": "test_event",
                "payload": {"data": "value"},
            },
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        assert result["topic"] == "session:abc123"
        mock_message_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_with_full_event_data(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """dispatch should handle full event data payload."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "eventbus.event",
            "params": {
                "topic": "run:task-789",
                "event_type": "tool_result",
                "payload": {
                    "tool_name": "write_file",
                    "path": "/tmp/test.txt",
                    "success": True,
                },
                "timestamp": "2024-01-15T12:00:00Z",
            },
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        assert result["event_type"] == "tool_result"

    @pytest.mark.asyncio
    async def test_dispatch_event_to_message_bus_format(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """dispatch should format event correctly for MessageBus."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "eventbus.event",
            "params": {
                "topic": "global:events",
                "event_type": "system_status",
                "payload": {"status": "healthy"},
            },
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            await controller.dispatch(request)

        call_args = mock_message_bus.emit.call_args
        message = call_args[0][0]

        # Verify message format
        assert isinstance(message, TextMessage)
        assert message.category == MessageCategory.SYSTEM
        assert message.level == MessageLevel.INFO
        assert "global:events" in message.text
        assert "system_status" in message.text


class TestDispatchErrorHandling:
    """Test dispatch error handling for eventbus.event."""

    @pytest.mark.asyncio
    async def test_dispatch_raises_error_on_missing_topic(
        self, controller: BridgeController
    ) -> None:
        """dispatch should raise WireMethodError when topic is missing."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eventbus.event",
            "params": {
                "event_type": "test",
                "payload": {},
            },
        }

        # wire_protocol validation raises WireMethodError before handler
        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert "topic" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_dispatch_returns_error_on_message_bus_failure(
        self, controller: BridgeController
    ) -> None:
        """dispatch should return error when MessageBus fails."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eventbus.event",
            "params": {
                "topic": "session:test",
                "event_type": "test",
            },
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            side_effect=RuntimeError("MessageBus unavailable"),
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "error"
        assert "MessageBus unavailable" in result["error"]


# =============================================================================
# Fire-and-Forget Behavior Tests
# =============================================================================


class TestFireAndForget:
    """Test fire-and-forget behavior of EventBus bridge."""

    @pytest.mark.asyncio
    async def test_emit_does_not_wait_for_elixir_response(self) -> None:
        """emit should not block waiting for Elixir response."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Test message",
            category=MessageCategory.SYSTEM,
        )

        # Just verify emit completes quickly (no bridge connection)
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=False
        ):
            import time

            start = time.time()
            bus.emit(message)
            elapsed = time.time() - start

        # Should complete quickly without blocking
        assert elapsed < 0.1  # Fast local-only emit

    def test_notify_elixir_event_returns_immediately(self) -> None:
        """notify_elixir_event should return immediately without waiting."""
        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ):
                import time

                start = time.time()
                notify_elixir_event(
                    event_type="test",
                    payload={},
                )
                elapsed = time.time() - start

        # Should complete in microseconds
        assert elapsed < 0.01


# =============================================================================
# Integration with Various Message Types
# =============================================================================


class TestIntegrationWithMessageTypes:
    """Test EventBus bridge with various message types."""

    def test_handles_agent_category_messages(self) -> None:
        """Should correctly process agent category messages."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Agent response",
            category=MessageCategory.AGENT,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        payload = mock_notify.call_args.kwargs["payload"]
        # str(MessageCategory.AGENT) produces "MessageCategory.AGENT"
        assert "agent" in payload["category"].lower()

    def test_handles_tool_output_category_messages(self) -> None:
        """Should correctly process tool output category messages."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Tool output",
            category=MessageCategory.TOOL_OUTPUT,
        )

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                bus._notify_elixir_if_connected(message)

        payload = mock_notify.call_args.kwargs["payload"]
        # str(MessageCategory.TOOL_OUTPUT) produces "MessageCategory.TOOL_OUTPUT"
        assert "tool" in payload["category"].lower()

    def test_handles_different_message_levels(self) -> None:
        """Should correctly process different message levels."""
        bus = MessageBus()

        levels = [
            MessageLevel.DEBUG,
            MessageLevel.INFO,
            MessageLevel.WARNING,
            MessageLevel.ERROR,
            MessageLevel.SUCCESS,
        ]

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge.notify_elixir_event"
            ) as mock_notify:
                for level in levels:
                    message = TextMessage(
                        level=level,
                        text=f"{level.value} message",
                        category=MessageCategory.SYSTEM,
                    )
                    bus._notify_elixir_if_connected(message)

        # Verify each call had correct level (str() of MessageLevel gives the enum name)
        for i, level in enumerate(levels):
            call_payload = mock_notify.call_args_list[i].kwargs["payload"]
            assert level.value in call_payload["level"].lower()


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handles_empty_payload(self) -> None:
        """Should handle events with empty payload."""
        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="empty_test",
            payload={},
        )

        assert result["params"]["payload"] == {}

    def test_handles_none_payload_values(self) -> None:
        """Should handle payload with None values."""
        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="null_test",
            payload={"value": None},
        )

        assert result["params"]["payload"]["value"] is None

    def test_handles_very_long_topic(self) -> None:
        """Should handle topics with very long identifiers."""
        long_id = "x" * 1000
        topic = f"session:{long_id}"

        result = emit_eventbus_broadcast(
            topic=topic,
            event_type="test",
            payload={},
        )

        assert result["params"]["topic"] == topic

    def test_handles_unicode_in_payload(self) -> None:
        """Should handle unicode characters in payload."""
        result = emit_eventbus_broadcast(
            topic="session:test",
            event_type="unicode_test",
            payload={
                "text": "Hello 世界 🌍 مرحبا",
                "emoji": "🚀🐍✨",
            },
        )

        assert result["params"]["payload"]["text"] == "Hello 世界 🌍 مرحبا"
        assert result["params"]["payload"]["emoji"] == "🚀🐍✨"

    @pytest.mark.asyncio
    async def test_handles_rapid_successive_events(
        self, controller: BridgeController, mock_message_bus: MagicMock
    ) -> None:
        """Should handle rapid successive eventbus events."""
        events = [
            {
                "topic": f"session:{i}",
                "event_type": "rapid_event",
                "payload": {"index": i},
            }
            for i in range(100)
        ]

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=mock_message_bus,
        ):
            for event_params in events:
                result = await controller._handle_eventbus_event(event_params)
                assert result["status"] == "ok"

        # Should have emitted 100 messages
        assert mock_message_bus.emit.call_count == 100


# =============================================================================
# Constants and Error Code Tests
# =============================================================================


class TestErrorCodes:
    """Test error code constants."""

    def test_invalid_params_constant(self) -> None:
        """INVALID_PARAMS should have correct JSON-RPC error code."""
        assert INVALID_PARAMS == -32602


# =============================================================================
# Full Flow Integration Tests
# =============================================================================


class TestFullFlow:
    """End-to-end tests for full EventBus bridge flow."""

    @pytest.mark.asyncio
    async def test_full_event_flow_elixir_to_python(
        self, controller: BridgeController
    ) -> None:
        """Test complete flow: Elixir EventBus -> Bridge -> MessageBus."""
        # Simulate an event coming from Elixir
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eventbus.event",
            "params": {
                "topic": "session:abc123",
                "event_type": "agent_response",
                "payload": {
                    "text": "Hello from agent",
                    "metadata": {"model": "gpt-4"},
                },
                "timestamp": "2024-01-15T10:30:00Z",
            },
        }

        bus = MessageBus()

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_message_bus",
            return_value=bus,
        ):
            # Process the event through dispatch
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        # Message should be in the buffer (no renderer active)
        messages = list(bus.get_buffered_messages())
        assert len(messages) == 1
        assert "agent_response" in messages[0].text

    @pytest.mark.asyncio
    async def test_full_event_flow_python_to_elixir(self) -> None:
        """Test complete flow: MessageBus.emit -> notify_elixir_event -> Elixir."""
        bus = MessageBus()
        message = TextMessage(
            level=MessageLevel.INFO,
            text="Hello from Python",
            category=MessageCategory.AGENT,
        )
        message.session_id = "session-xyz789"

        with patch(
            "code_puppy.plugins.elixir_bridge.is_connected", return_value=True
        ):
            with patch(
                "code_puppy.plugins.elixir_bridge._send_request_to_elixir"
            ) as mock_send:
                bus.emit(message)

        # Verify the event was sent to Elixir
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["method"] == "eventbus.broadcast"
        assert call_args["params"]["topic"] == "session:session-xyz789"
        assert call_args["params"]["event_type"] == "TextMessage"

    def test_bidirectional_event_flow(self) -> None:
        """Test that events can flow in both directions."""
        # This test verifies the bridge is bidirectional-capable
        # Python -> Elixir via notify_elixir_event
        # Elixir -> Python via eventbus.event dispatch

        # Verify functions exist and are callable
        assert callable(notify_elixir_event)
        assert callable(emit_eventbus_broadcast)
        assert callable(emit_eventbus_subscribe)
        assert callable(emit_eventbus_unsubscribe)

        # Verify constants
        assert INVALID_PARAMS == -32602
