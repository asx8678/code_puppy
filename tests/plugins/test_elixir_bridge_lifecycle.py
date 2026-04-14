"""Tests for Elixir Bridge lifecycle command handlers.

Tests the JSON-RPC method handlers for:
- run/start: Start a new agent run
- run/cancel: Cancel an in-progress run
- exit: Graceful shutdown
- initialize: Protocol handshake

See: docs/adr/ADR-002-python-elixir-event-protocol.md
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from code_puppy.plugins.elixir_bridge.bridge_controller import BridgeController
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    WireMethodError,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
)


@pytest.fixture
def controller() -> BridgeController:
    """Create a fresh bridge controller for each test."""
    return BridgeController()


class TestRunStartHandler:
    """Test run/start lifecycle command handler."""

    @pytest.mark.asyncio
    async def test_run_start_basic(self, controller: BridgeController) -> None:
        """run/start should start an agent run and return run info."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello, analyze this code",
                "session_id": "session-abc123",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ) as mock_execute:
            response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "started"
        assert response["agent_name"] == "code-puppy"
        assert response["session_id"] == "session-abc123"
        assert "run_id" in response
        # Run ID should be auto-generated
        assert response["run_id"].startswith("run-")

    @pytest.mark.asyncio
    async def test_run_start_with_explicit_run_id(self, controller: BridgeController) -> None:
        """run/start should accept explicit run_id parameter."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "turbo-executor",
                "prompt": "Analyze codebase",
                "run_id": "my-custom-run-id",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            response = await controller.dispatch(request)

        assert response is not None
        assert response["run_id"] == "my-custom-run-id"

    @pytest.mark.asyncio
    async def test_run_start_missing_agent_name(self, controller: BridgeController) -> None:
        """run/start should fail without agent_name."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "prompt": "Hello",
            },
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == INVALID_PARAMS
        assert "agent_name" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_start_missing_prompt(self, controller: BridgeController) -> None:
        """run/start should fail without prompt."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
            },
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == INVALID_PARAMS
        assert "prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_start_duplicate_run_id(self, controller: BridgeController) -> None:
        """run/start should reject duplicate run_id."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
                "run_id": "duplicate-run-id",
            },
        }

        # First call succeeds
        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            response1 = await controller.dispatch(request)
        assert response1 is not None
        assert response1["status"] == "started"

        # Second call with same run_id fails
        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == -32002  # Run already active
        assert "duplicate-run-id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_start_with_context(self, controller: BridgeController) -> None:
        """run/start should accept optional context parameter."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
                "context": {"files": ["main.py"], "line_count": 100},
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "started"

    @pytest.mark.asyncio
    async def test_run_start_dot_style_method(self, controller: BridgeController) -> None:
        """run.start (dot-style) should also work."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run.start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "started"


@pytest.fixture
async def controller_with_active_run(controller: BridgeController) -> BridgeController:
    """Create a controller with an active run for testing cancellation."""
    # Start a run first
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "run/start",
        "params": {
            "agent_name": "code-puppy",
            "prompt": "Hello",
            "run_id": "run-to-cancel",
        },
    }

    with patch.object(
        controller, "_execute_agent_run", new_callable=AsyncMock
    ):
        await controller.dispatch(request)

    return controller


class TestRunCancelHandler:
    """Test run/cancel lifecycle command handler."""

    @pytest.mark.asyncio
    async def test_run_cancel_success(self, controller_with_active_run: BridgeController) -> None:
        """run/cancel should cancel an active run."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {
                "run_id": "run-to-cancel",
                "reason": "user_requested",
            },
        }

        response = await controller_with_active_run.dispatch(request)

        assert response is not None
        assert response["status"] == "cancelled"
        assert response["run_id"] == "run-to-cancel"
        assert response["reason"] == "user_requested"

    @pytest.mark.asyncio
    async def test_run_cancel_default_reason(self, controller_with_active_run: BridgeController) -> None:
        """run/cancel should use default reason when not provided."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {
                "run_id": "run-to-cancel",
            },
        }

        response = await controller_with_active_run.dispatch(request)

        assert response is not None
        assert response["reason"] == "user_requested"

    @pytest.mark.asyncio
    async def test_run_cancel_unknown_run(self, controller: BridgeController) -> None:
        """run/cancel should fail for unknown run_id."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {
                "run_id": "non-existent-run",
            },
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == -32001  # Run not found
        assert "non-existent-run" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_cancel_missing_run_id(self, controller: BridgeController) -> None:
        """run/cancel should fail without run_id."""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {},
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == INVALID_PARAMS
        assert "run_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_cancel_dot_style_method(self, controller_with_active_run: BridgeController) -> None:
        """run.cancel (dot-style) should also work."""
        # Start another run for dot-style test
        start_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run.start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
                "run_id": "dot-style-run",
            },
        }

        with patch.object(
            controller_with_active_run, "_execute_agent_run", new_callable=AsyncMock
        ):
            await controller_with_active_run.dispatch(start_request)

        cancel_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run.cancel",
            "params": {
                "run_id": "dot-style-run",
            },
        }

        response = await controller_with_active_run.dispatch(cancel_request)

        assert response is not None
        assert response["status"] == "cancelled"


class TestExitHandler:
    """Test exit lifecycle command handler."""

    @pytest.mark.asyncio
    async def test_exit_basic(self, controller: BridgeController) -> None:
        """exit should initiate graceful shutdown."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {
                "reason": "shutdown",
            },
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "exiting"
        assert response["reason"] == "shutdown"
        assert "timeout_ms" in response

    @pytest.mark.asyncio
    async def test_exit_with_custom_reason(self, controller: BridgeController) -> None:
        """exit should accept custom reason."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {
                "reason": "upgrade",
                "timeout_ms": 10000,
            },
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["reason"] == "upgrade"
        assert response["timeout_ms"] == 10000

    @pytest.mark.asyncio
    async def test_exit_default_params(self, controller: BridgeController) -> None:
        """exit should use default params when not provided."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {},
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["reason"] == "shutdown"
        assert response["timeout_ms"] == 5000

    @pytest.mark.asyncio
    async def test_exit_sets_running_false(self, controller: BridgeController) -> None:
        """exit should set _running to False."""
        assert controller._running is True

        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {"reason": "test"},
        }

        await controller.dispatch(request)

        assert controller._running is False


class TestInitializeHandler:
    """Test initialize lifecycle command handler."""

    @pytest.mark.asyncio
    async def test_initialize_basic(self, controller: BridgeController) -> None:
        """initialize should complete protocol handshake."""
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "version": "1.0",
            },
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "initialized"
        assert "capabilities" in response
        assert "version" in response

    @pytest.mark.asyncio
    async def test_initialize_capabilities(self, controller: BridgeController) -> None:
        """initialize should return supported capabilities."""
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {},
        }

        response = await controller.dispatch(request)

        assert response is not None
        capabilities = response["capabilities"]
        assert isinstance(capabilities, list)
        # Should include expected capabilities
        assert "shell" in capabilities
        assert "file_ops" in capabilities
        assert "agents" in capabilities
        assert "event_stream" in capabilities

    @pytest.mark.asyncio
    async def test_initialize_version(self, controller: BridgeController) -> None:
        """initialize should return bridge version."""
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {},
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_initialize_with_capabilities_request(self, controller: BridgeController) -> None:
        """initialize should accept requested capabilities (future use)."""
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "capabilities": ["shell", "agents"],
                "config": {"timeout": 30},
            },
        }

        response = await controller.dispatch(request)

        assert response is not None
        assert response["status"] == "initialized"
        # Currently returns all capabilities regardless of request
        assert "shell" in response["capabilities"]


class TestDispatchMechanism:
    """Test the dispatch mechanism for routing commands to handlers."""

    @pytest.mark.asyncio
    async def test_dispatch_unknown_method(self, controller: BridgeController) -> None:
        """dispatch should raise error for unknown methods."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method",
            "params": {},
        }

        with pytest.raises(WireMethodError) as exc_info:
            await controller.dispatch(request)

        assert exc_info.value.code == METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_dispatch_increments_counter(self, controller: BridgeController) -> None:
        """dispatch should increment command counter."""
        assert controller._command_count == 0

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
            "params": {},
        }

        await controller.dispatch(request)

        assert controller._command_count == 1

    @pytest.mark.asyncio
    async def test_dispatch_returns_none_for_notifications(self, controller: BridgeController) -> None:
        """dispatch can return None for notifications (requests without id)."""
        # Note: Currently all methods return responses, but test that None is handled
        request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
        }

        response = await controller.dispatch(request)
        # ping returns a response, but the mechanism supports None
        assert response is not None  # ping specifically returns a result


class TestLifecycleIntegration:
    """Integration tests for lifecycle command sequences."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_sequence(self, controller: BridgeController) -> None:
        """Test complete lifecycle: initialize -> run/start -> run/cancel -> exit."""

        # 1. Initialize
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"version": "1.0"},
        }
        init_response = await controller.dispatch(init_request)
        assert init_response["status"] == "initialized"

        # 2. Start a run
        start_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Test prompt",
                "run_id": "lifecycle-test-run",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            start_response = await controller.dispatch(start_request)

        assert start_response["status"] == "started"
        run_id = start_response["run_id"]

        # 3. Cancel the run
        cancel_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {"run_id": run_id},
        }
        cancel_response = await controller.dispatch(cancel_request)
        assert cancel_response["status"] == "cancelled"

        # 4. Exit
        exit_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {"reason": "test_complete"},
        }
        exit_response = await controller.dispatch(exit_request)
        assert exit_response["status"] == "exiting"
        assert controller._running is False

    @pytest.mark.asyncio
    async def test_dot_and_slash_style_methods_both_work(self, controller: BridgeController) -> None:
        """Both dot-style and slash-style method names should work."""

        # Test slash-style (as specified in task)
        slash_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",  # slash-style
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
                "run_id": "slash-style-run",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            slash_response = await controller.dispatch(slash_request)

        assert slash_response["status"] == "started"

        # Test dot-style (also supported)
        dot_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run.start",  # dot-style
            "params": {
                "agent_name": "turbo-executor",
                "prompt": "World",
                "run_id": "dot-style-run",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            dot_response = await controller.dispatch(dot_request)

        assert dot_response["status"] == "started"


class TestJsonRpcResponseFormat:
    """Test that handlers return proper JSON-RPC response format."""

    @pytest.mark.asyncio
    async def test_run_start_response_format(self, controller: BridgeController) -> None:
        """run/start response should have required fields."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            response = await controller.dispatch(request)

        # Response should be a dict with specific fields
        assert isinstance(response, dict)
        assert "status" in response
        assert "run_id" in response
        assert "agent_name" in response

    @pytest.mark.asyncio
    async def test_run_cancel_response_format(self, controller: BridgeController) -> None:
        """run/cancel response should have required fields."""
        # Start a run first
        start_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "run/start",
            "params": {
                "agent_name": "code-puppy",
                "prompt": "Hello",
                "run_id": "cancel-format-test",
            },
        }

        with patch.object(
            controller, "_execute_agent_run", new_callable=AsyncMock
        ):
            await controller.dispatch(start_request)

        # Cancel it
        cancel_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "run/cancel",
            "params": {"run_id": "cancel-format-test"},
        }
        response = await controller.dispatch(cancel_request)

        assert isinstance(response, dict)
        assert "status" in response
        assert "run_id" in response
        assert "reason" in response

    @pytest.mark.asyncio
    async def test_exit_response_format(self, controller: BridgeController) -> None:
        """exit response should have required fields."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "exit",
            "params": {"reason": "test"},
        }

        response = await controller.dispatch(request)

        assert isinstance(response, dict)
        assert "status" in response
        assert "reason" in response
        assert "timeout_ms" in response

    @pytest.mark.asyncio
    async def test_initialize_response_format(self, controller: BridgeController) -> None:
        """initialize response should have required fields."""
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"version": "1.0"},
        }

        response = await controller.dispatch(request)

        assert isinstance(response, dict)
        assert "status" in response
        assert "capabilities" in response
        assert "version" in response
