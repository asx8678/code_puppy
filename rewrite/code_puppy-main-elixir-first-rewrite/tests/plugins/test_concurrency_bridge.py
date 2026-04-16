"""Tests for concurrency bridge functionality (bd-77).

Tests the bridge-aware concurrency limits that coordinate between Python and Elixir:
1. Wire protocol emit methods for concurrency messages
2. Bridge controller handlers for concurrency operations
3. Fallback behavior when bridge is unavailable

See: docs/adr/ADR-002-python-elixir-event-protocol.md
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from code_puppy.plugins.elixir_bridge.bridge_controller import BridgeController
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    emit_concurrency_acquire,
    emit_concurrency_release,
    emit_concurrency_status,
    WireMethodError,
    INVALID_PARAMS,
)


# =============================================================================
# Wire Protocol Tests
# =============================================================================


class TestEmitConcurrencyAcquire:
    """Test emit_concurrency_acquire wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_concurrency_acquire should return valid JSON-RPC request."""
        result = emit_concurrency_acquire("file_ops")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "concurrency.acquire"
        assert "params" in result
        assert result["params"]["type"] == "file_ops"
        assert "timestamp" in result["params"]

    def test_with_different_limiter_types(self) -> None:
        """emit_concurrency_acquire should work with all limiter types."""
        types = ["file_ops", "api_calls", "tool_calls"]

        for limiter_type in types:
            result = emit_concurrency_acquire(limiter_type)
            assert result["params"]["type"] == limiter_type

    def test_with_timeout_parameter(self) -> None:
        """emit_concurrency_acquire should include timeout when provided."""
        result = emit_concurrency_acquire("file_ops", timeout=5.0)

        assert "timeout" in result["params"]
        assert result["params"]["timeout"] == 5.0

    def test_without_timeout_parameter(self) -> None:
        """emit_concurrency_acquire should not include timeout if None."""
        result = emit_concurrency_acquire("file_ops", timeout=None)

        assert "timeout" not in result["params"]

    def test_with_custom_timestamp(self) -> None:
        """emit_concurrency_acquire should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_concurrency_acquire("file_ops", timestamp=custom_ts)

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_concurrency_acquire should auto-generate timestamp if not provided."""
        result = emit_concurrency_acquire("file_ops")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        # Should be ISO 8601 format (contains T and Z)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitConcurrencyRelease:
    """Test emit_concurrency_release wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_concurrency_release should return valid JSON-RPC notification."""
        result = emit_concurrency_release("api_calls")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "concurrency.release"
        assert "params" in result
        assert result["params"]["type"] == "api_calls"
        assert "timestamp" in result["params"]

    def test_with_different_limiter_types(self) -> None:
        """emit_concurrency_release should work with all limiter types."""
        types = ["file_ops", "api_calls", "tool_calls"]

        for limiter_type in types:
            result = emit_concurrency_release(limiter_type)
            assert result["params"]["type"] == limiter_type

    def test_with_custom_timestamp(self) -> None:
        """emit_concurrency_release should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_concurrency_release("tool_calls", timestamp=custom_ts)

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_concurrency_release should auto-generate timestamp if not provided."""
        result = emit_concurrency_release("file_ops")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitConcurrencyStatus:
    """Test emit_concurrency_status wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_concurrency_status should return valid JSON-RPC request."""
        result = emit_concurrency_status()

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "concurrency.status"
        assert "params" in result
        assert "timestamp" in result["params"]

    def test_with_custom_timestamp(self) -> None:
        """emit_concurrency_status should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_concurrency_status(timestamp=custom_ts)

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_concurrency_status should auto-generate timestamp if not provided."""
        result = emit_concurrency_status()

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


# =============================================================================
# Bridge Controller Handler Tests
# =============================================================================


@pytest.fixture
def controller() -> BridgeController:
    """Create a fresh bridge controller for each test."""
    return BridgeController()


class TestHandleConcurrencyAcquire:
    """Test _handle_concurrency_acquire bridge controller method."""

    @pytest.mark.asyncio
    async def test_acquire_file_ops_slot(self, controller: BridgeController) -> None:
        """Should acquire file_ops slot successfully."""
        params = {"type": "file_ops"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
            new_callable=AsyncMock,
        ) as mock_acquire:
            result = await controller._handle_concurrency_acquire(params)

        mock_acquire.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "file_ops"

    @pytest.mark.asyncio
    async def test_acquire_api_calls_slot(self, controller: BridgeController) -> None:
        """Should acquire api_calls slot successfully."""
        params = {"type": "api_calls"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_api_call_slot",
            new_callable=AsyncMock,
        ) as mock_acquire:
            result = await controller._handle_concurrency_acquire(params)

        mock_acquire.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "api_calls"

    @pytest.mark.asyncio
    async def test_acquire_tool_calls_slot(self, controller: BridgeController) -> None:
        """Should acquire tool_calls slot successfully."""
        params = {"type": "tool_calls"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_tool_call_slot",
            new_callable=AsyncMock,
        ) as mock_acquire:
            result = await controller._handle_concurrency_acquire(params)

        mock_acquire.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "tool_calls"

    @pytest.mark.asyncio
    async def test_default_to_file_ops(self, controller: BridgeController) -> None:
        """Should default to file_ops when type not specified."""
        params = {}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
            new_callable=AsyncMock,
        ) as mock_acquire:
            result = await controller._handle_concurrency_acquire(params)

        mock_acquire.assert_called_once()
        assert result["type"] == "file_ops"

    @pytest.mark.asyncio
    async def test_rejects_unknown_limiter_type(
        self, controller: BridgeController
    ) -> None:
        """Should raise error for unknown limiter type."""
        params = {"type": "unknown_type"}

        with pytest.raises(WireMethodError) as exc_info:
            await controller._handle_concurrency_acquire(params)

        assert exc_info.value.code == INVALID_PARAMS
        assert "unknown_type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_preserves_timeout_param(self, controller: BridgeController) -> None:
        """Should accept timeout parameter (for future use)."""
        params = {"type": "file_ops", "timeout": 10.0}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
            new_callable=AsyncMock,
        ):
            result = await controller._handle_concurrency_acquire(params)

        assert result["status"] == "ok"


class TestHandleConcurrencyRelease:
    """Test _handle_concurrency_release bridge controller method."""

    @pytest.mark.asyncio
    async def test_release_file_ops_slot(self, controller: BridgeController) -> None:
        """Should release file_ops slot successfully."""
        params = {"type": "file_ops"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_file_ops_slot"
        ) as mock_release:
            result = await controller._handle_concurrency_release(params)

        mock_release.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "file_ops"

    @pytest.mark.asyncio
    async def test_release_api_calls_slot(self, controller: BridgeController) -> None:
        """Should release api_calls slot successfully."""
        params = {"type": "api_calls"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_api_call_slot"
        ) as mock_release:
            result = await controller._handle_concurrency_release(params)

        mock_release.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "api_calls"

    @pytest.mark.asyncio
    async def test_release_tool_calls_slot(self, controller: BridgeController) -> None:
        """Should release tool_calls slot successfully."""
        params = {"type": "tool_calls"}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_tool_call_slot"
        ) as mock_release:
            result = await controller._handle_concurrency_release(params)

        mock_release.assert_called_once()
        assert result["status"] == "ok"
        assert result["type"] == "tool_calls"

    @pytest.mark.asyncio
    async def test_default_to_file_ops(self, controller: BridgeController) -> None:
        """Should default to file_ops when type not specified."""
        params = {}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_file_ops_slot"
        ) as mock_release:
            result = await controller._handle_concurrency_release(params)

        mock_release.assert_called_once()
        assert result["type"] == "file_ops"

    @pytest.mark.asyncio
    async def test_rejects_unknown_limiter_type(
        self, controller: BridgeController
    ) -> None:
        """Should raise error for unknown limiter type."""
        params = {"type": "invalid_type"}

        with pytest.raises(WireMethodError) as exc_info:
            await controller._handle_concurrency_release(params)

        assert exc_info.value.code == INVALID_PARAMS
        assert "invalid_type" in str(exc_info.value)


class TestHandleConcurrencyStatus:
    """Test _handle_concurrency_status bridge controller method."""

    @pytest.mark.asyncio
    async def test_returns_concurrency_status(
        self, controller: BridgeController
    ) -> None:
        """Should return current concurrency status."""
        mock_status = {
            "file_ops_limit": 4,
            "file_ops_available": 3,
            "api_calls_limit": 2,
            "api_calls_available": 1,
            "tool_calls_limit": 8,
            "tool_calls_available": 6,
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_concurrency_status",
            return_value=mock_status,
        ):
            result = await controller._handle_concurrency_status({})

        assert result["status"] == "ok"
        assert result["concurrency"] == mock_status

    @pytest.mark.asyncio
    async def test_status_contains_all_semaphores(
        self, controller: BridgeController
    ) -> None:
        """Should include all semaphore types in status."""
        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_concurrency_status"
        ) as mock_get_status:
            mock_get_status.return_value = {
                "file_ops_limit": 4,
                "file_ops_available": 2,
                "api_calls_limit": 2,
                "api_calls_available": 1,
                "tool_calls_limit": 8,
                "tool_calls_available": 4,
            }

            result = await controller._handle_concurrency_status({})
            status = result["concurrency"]

            assert "file_ops_limit" in status
            assert "file_ops_available" in status
            assert "api_calls_limit" in status
            assert "api_calls_available" in status
            assert "tool_calls_limit" in status
            assert "tool_calls_available" in status


# =============================================================================
# Dispatch Integration Tests
# =============================================================================


class TestConcurrencyDispatch:
    """Test that concurrency methods are properly dispatched."""

    @pytest.mark.asyncio
    async def test_dispatch_concurrency_acquire(
        self, controller: BridgeController
    ) -> None:
        """dispatch should route concurrency.acquire to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "concurrency.acquire",
            "params": {"type": "file_ops"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
            new_callable=AsyncMock,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_dispatch_concurrency_release(
        self, controller: BridgeController
    ) -> None:
        """dispatch should route concurrency.release to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "concurrency.release",
            "params": {"type": "api_calls"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_api_call_slot"
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_dispatch_concurrency_status(
        self, controller: BridgeController
    ) -> None:
        """dispatch should route concurrency.status to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "concurrency.status",
            "params": {},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_concurrency_status",
            return_value={"file_ops_available": 4},
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        assert "concurrency" in result


# =============================================================================
# Fallback Behavior Tests
# =============================================================================


class TestFallbackBehavior:
    """Test fallback to local semaphore when bridge is unavailable."""

    @pytest.mark.asyncio
    async def test_acquire_uses_local_when_not_connected(self) -> None:
        """When is_connected() returns False, acquire should use local semaphore."""
        from code_puppy.concurrency_limits import acquire_file_ops_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=False):
            with patch(
                "code_puppy.concurrency_limits._get_file_ops_semaphore"
            ) as mock_get_sem:
                mock_sem = AsyncMock()
                mock_sem.acquire = AsyncMock()
                mock_get_sem.return_value = mock_sem

                await acquire_file_ops_slot()

        # Should use local semaphore (Elixir bridge not called)
        mock_get_sem.assert_called_once()
        mock_sem.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_uses_local_on_bridge_timeout(self) -> None:
        """When bridge times out, should fall back to local semaphore."""
        from code_puppy.concurrency_limits import acquire_file_ops_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                new_callable=AsyncMock,
            ) as mock_call:
                # Return timeout fallback response
                mock_call.return_value = {"status": "timeout", "fallback": True}

                with patch(
                    "code_puppy.concurrency_limits._get_file_ops_semaphore"
                ) as mock_get_sem:
                    mock_sem = AsyncMock()
                    mock_sem.acquire = AsyncMock()
                    mock_get_sem.return_value = mock_sem

                    await acquire_file_ops_slot()

        # Should call bridge first, then fall back to local
        mock_call.assert_called_once()
        mock_get_sem.assert_called_once()
        mock_sem.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_notifies_bridge_when_connected(self) -> None:
        """When connected, release should fire-and-forget notify bridge."""
        from code_puppy.concurrency_limits import release_file_ops_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                new_callable=AsyncMock,
            ) as mock_call:
                with patch(
                    "code_puppy.concurrency_limits._get_file_ops_semaphore"
                ) as mock_get_sem:
                    mock_sem = MagicMock()
                    mock_sem.release = MagicMock()
                    mock_get_sem.return_value = mock_sem

                    with patch("asyncio.create_task"):
                        release_file_ops_slot()

        # Should attempt fire-and-forget notification
        mock_call.assert_called_once()
        mock_sem.release.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_ignores_bridge_errors(self) -> None:
        """Release should ignore bridge errors and still release local semaphore."""
        from code_puppy.concurrency_limits import release_file_ops_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                side_effect=Exception("Bridge error"),
            ):
                with patch(
                    "code_puppy.concurrency_limits._get_file_ops_semaphore"
                ) as mock_get_sem:
                    mock_sem = MagicMock()
                    mock_sem.release = MagicMock()
                    mock_get_sem.return_value = mock_sem

                    # Should not raise
                    release_file_ops_slot()

        # Local semaphore should still be released
        mock_sem.release.assert_called_once()


class TestBridgeAwareAcquire:
    """Test bridge-aware acquire for all semaphore types."""

    @pytest.mark.asyncio
    async def test_api_calls_acquire_bridge_fallback(self) -> None:
        """api_calls acquire should fallback to local on bridge failure."""
        from code_puppy.concurrency_limits import acquire_api_call_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                new_callable=AsyncMock,
            ) as mock_call:
                mock_call.return_value = {"status": "timeout", "fallback": True}

                with patch(
                    "code_puppy.concurrency_limits._get_api_calls_semaphore"
                ) as mock_get_sem:
                    mock_sem = AsyncMock()
                    mock_sem.acquire = AsyncMock()
                    mock_get_sem.return_value = mock_sem

                    await acquire_api_call_slot()

        mock_call.assert_called_once_with("concurrency.acquire", {"type": "api_calls"})
        mock_sem.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_calls_acquire_bridge_success(self) -> None:
        """tool_calls acquire should use bridge when available."""
        from code_puppy.concurrency_limits import acquire_tool_call_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                new_callable=AsyncMock,
            ) as mock_call:
                mock_call.return_value = {"status": "ok"}

                with patch(
                    "code_puppy.concurrency_limits._get_tool_calls_semaphore"
                ) as mock_get_sem:
                    mock_sem = AsyncMock()
                    mock_sem.acquire = AsyncMock()
                    mock_get_sem.return_value = mock_sem

                    await acquire_tool_call_slot()

        # Should succeed via bridge, no need for local semaphore
        mock_call.assert_called_once()
        mock_sem.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_ops_acquire_bridge_error_fallback(self) -> None:
        """file_ops acquire should fallback when bridge returns error."""
        from code_puppy.concurrency_limits import acquire_file_ops_slot

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_elixir_concurrency",
                new_callable=AsyncMock,
            ) as mock_call:
                # Simulate bridge error (not ok status)
                mock_call.return_value = {"status": "error", "message": "Server busy"}

                with patch(
                    "code_puppy.concurrency_limits._get_file_ops_semaphore"
                ) as mock_get_sem:
                    mock_sem = AsyncMock()
                    mock_sem.acquire = AsyncMock()
                    mock_get_sem.return_value = mock_sem

                    await acquire_file_ops_slot()

        # Should fall back to local semaphore
        mock_call.assert_called_once()
        mock_sem.acquire.assert_called_once()


class TestCallElixirConcurrency:
    """Test call_elixir_concurrency function."""

    @pytest.mark.asyncio
    async def test_returns_fallback_on_timeout(self) -> None:
        """call_elixir_concurrency should return fallback on TimeoutError."""
        from code_puppy.plugins.elixir_bridge import call_elixir_concurrency

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_method",
                side_effect=TimeoutError("Connection timeout"),
            ):
                result = await call_elixir_concurrency(
                    "concurrency.acquire", {"type": "file_ops"}
                )

        assert result["status"] == "timeout"
        assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_raises_on_not_connected(self) -> None:
        """call_elixir_concurrency should raise ConnectionError when not connected."""
        from code_puppy.plugins.elixir_bridge import call_elixir_concurrency

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=False):
            with pytest.raises(ConnectionError):
                await call_elixir_concurrency(
                    "concurrency.acquire", {"type": "file_ops"}
                )

    @pytest.mark.asyncio
    async def test_returns_successful_result(self) -> None:
        """call_elixir_concurrency should return result on success."""
        from code_puppy.plugins.elixir_bridge import call_elixir_concurrency

        mock_result = {"status": "ok", "slot_id": "slot-123"}

        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            with patch(
                "code_puppy.plugins.elixir_bridge.call_method",
                return_value=mock_result,
            ):
                result = await call_elixir_concurrency(
                    "concurrency.acquire", {"type": "file_ops"}
                )

        assert result == mock_result


# =============================================================================
# End-to-End Integration Tests
# =============================================================================


class TestConcurrencyEndToEnd:
    """End-to-end tests for concurrency bridge flow."""

    @pytest.mark.asyncio
    async def test_full_acquire_release_cycle_via_dispatch(
        self, controller: BridgeController
    ) -> None:
        """Test complete acquire -> release cycle through dispatch."""
        # Acquire
        acquire_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "concurrency.acquire",
            "params": {"type": "file_ops"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
            new_callable=AsyncMock,
        ) as mock_acquire:
            acquire_result = await controller.dispatch(acquire_request)

        assert acquire_result["status"] == "ok"
        mock_acquire.assert_called_once()

        # Release
        release_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "concurrency.release",
            "params": {"type": "file_ops"},
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.release_file_ops_slot"
        ) as mock_release:
            release_result = await controller.dispatch(release_request)

        assert release_result["status"] == "ok"
        mock_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_check_via_dispatch(
        self, controller: BridgeController
    ) -> None:
        """Test status check through dispatch."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "concurrency.status",
            "params": {},
        }

        mock_status = {
            "file_ops_available": 3,
            "api_calls_available": 1,
            "tool_calls_available": 6,
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_concurrency_status",
            return_value=mock_status,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        assert result["concurrency"] == mock_status

    @pytest.mark.asyncio
    async def test_mixed_limiter_types(self, controller: BridgeController) -> None:
        """Test using different limiter types in sequence."""
        operations = [
            ("file_ops", "concurrency.acquire"),
            ("api_calls", "concurrency.acquire"),
            ("tool_calls", "concurrency.acquire"),
            ("file_ops", "concurrency.release"),
            ("api_calls", "concurrency.release"),
            ("tool_calls", "concurrency.release"),
        ]

        patches = {
            "file_ops": (
                "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_file_ops_slot",
                "code_puppy.plugins.elixir_bridge.bridge_controller.release_file_ops_slot",
            ),
            "api_calls": (
                "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_api_call_slot",
                "code_puppy.plugins.elixir_bridge.bridge_controller.release_api_call_slot",
            ),
            "tool_calls": (
                "code_puppy.plugins.elixir_bridge.bridge_controller.acquire_tool_call_slot",
                "code_puppy.plugins.elixir_bridge.bridge_controller.release_tool_call_slot",
            ),
        }

        for limiter_type, method in operations:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {"type": limiter_type},
            }

            acquire_patch, release_patch = patches[limiter_type]

            if "acquire" in method:
                with patch(acquire_patch, new_callable=AsyncMock) as mock_op:
                    result = await controller.dispatch(request)
                    mock_op.assert_called_once()
            else:
                with patch(release_patch) as mock_op:
                    result = await controller.dispatch(request)
                    mock_op.assert_called_once()

            assert result["status"] == "ok"
            assert result["type"] == limiter_type


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling in concurrency bridge."""

    @pytest.mark.asyncio
    async def test_acquire_propagates_wire_method_error(
        self, controller: BridgeController
    ) -> None:
        """Should properly raise WireMethodError for invalid params."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "concurrency.acquire",
            "params": {"type": "invalid_type"},
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_release_propagates_wire_method_error(
        self, controller: BridgeController
    ) -> None:
        """Should properly raise WireMethodError for invalid release params."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "concurrency.release",
            "params": {"type": "unknown_type"},
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == INVALID_PARAMS
