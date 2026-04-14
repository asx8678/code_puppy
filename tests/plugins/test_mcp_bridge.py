"""Tests for MCP bridge functionality (bd-81).

Tests the bridge-aware MCP server management that coordinates between Python and Elixir:
1. Wire protocol emit methods for MCP messages
2. Bridge controller handlers for MCP operations
3. Fallback behavior when bridge is unavailable

See: docs/adr/ADR-002-python-elixir-event-protocol.md
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from code_puppy.plugins.elixir_bridge.bridge_controller import BridgeController
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    emit_mcp_register_server,
    emit_mcp_unregister_server,
    emit_mcp_list_servers,
    emit_mcp_get_status,
    emit_mcp_call_tool,
    emit_mcp_health_check,
    WireMethodError,
)
from code_puppy.mcp_ import ServerInfo, ServerState


# =============================================================================
# Wire Protocol Tests
# =============================================================================


class TestEmitMcpRegisterServer:
    """Test emit_mcp_register_server wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_register_server should return valid JSON-RPC request."""
        result = emit_mcp_register_server(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
        )

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.register"
        assert "params" in result
        assert result["params"]["name"] == "filesystem"
        assert result["params"]["command"] == "npx"
        assert result["params"]["args"] == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
        ]
        assert "timestamp" in result["params"]

    def test_with_env_variables(self) -> None:
        """emit_mcp_register_server should include env when provided."""
        env = {"API_KEY": "secret123", "DEBUG": "1"}
        result = emit_mcp_register_server(
            name="api-server",
            command="python",
            args=["server.py"],
            env=env,
        )

        assert "env" in result["params"]
        assert result["params"]["env"] == env

    def test_without_env_variables(self) -> None:
        """emit_mcp_register_server should not include env if None."""
        result = emit_mcp_register_server(
            name="simple-server",
            command="echo",
            args=["hello"],
        )

        assert "env" not in result["params"]

    def test_with_opts(self) -> None:
        """emit_mcp_register_server should include opts when provided."""
        opts = {"timeout": 30, "retry_count": 3}
        result = emit_mcp_register_server(
            name="custom-server",
            command="npm",
            args=["start"],
            opts=opts,
        )

        assert "opts" in result["params"]
        assert result["params"]["opts"] == opts

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_register_server should use provided timestamp."""
        custom_ts = "2024-01-15T10:30:00Z"
        result = emit_mcp_register_server(
            name="test-server",
            command="echo",
            args=["test"],
            timestamp=custom_ts,
        )

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_register_server should auto-generate timestamp if not provided."""
        result = emit_mcp_register_server(
            name="auto-server",
            command="cat",
            args=["/dev/null"],
        )

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        # Should be ISO 8601 format (contains T and Z)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitMcpUnregisterServer:
    """Test emit_mcp_unregister_server wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_unregister_server should return valid JSON-RPC request."""
        result = emit_mcp_unregister_server(server_id="server-123")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.unregister"
        assert "params" in result
        assert result["params"]["server_id"] == "server-123"
        assert "timestamp" in result["params"]

    def test_with_different_server_ids(self) -> None:
        """emit_mcp_unregister_server should work with various server IDs."""
        ids = ["server-abc", "uuid-1234-5678", "mcp-server-1"]

        for server_id in ids:
            result = emit_mcp_unregister_server(server_id=server_id)
            assert result["params"]["server_id"] == server_id

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_unregister_server should use provided timestamp."""
        custom_ts = "2024-01-15T10:45:00Z"
        result = emit_mcp_unregister_server(
            server_id="server-456",
            timestamp=custom_ts,
        )

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_unregister_server should auto-generate timestamp if not provided."""
        result = emit_mcp_unregister_server(server_id="server-789")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitMcpListServers:
    """Test emit_mcp_list_servers wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_list_servers should return valid JSON-RPC request."""
        result = emit_mcp_list_servers()

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.list"
        assert "params" in result
        assert "timestamp" in result["params"]

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_list_servers should use provided timestamp."""
        custom_ts = "2024-01-15T11:00:00Z"
        result = emit_mcp_list_servers(timestamp=custom_ts)

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_list_servers should auto-generate timestamp if not provided."""
        result = emit_mcp_list_servers()

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitMcpGetStatus:
    """Test emit_mcp_get_status wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_get_status should return valid JSON-RPC request."""
        result = emit_mcp_get_status(server_id="server-123")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.status"
        assert "params" in result
        assert result["params"]["server_id"] == "server-123"
        assert "timestamp" in result["params"]

    def test_with_different_server_ids(self) -> None:
        """emit_mcp_get_status should work with various server IDs."""
        ids = ["status-server-1", "check-uuid", "test-mcp-789"]

        for server_id in ids:
            result = emit_mcp_get_status(server_id=server_id)
            assert result["params"]["server_id"] == server_id

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_get_status should use provided timestamp."""
        custom_ts = "2024-01-15T11:15:00Z"
        result = emit_mcp_get_status(
            server_id="server-status-1",
            timestamp=custom_ts,
        )

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_get_status should auto-generate timestamp if not provided."""
        result = emit_mcp_get_status(server_id="auto-status-server")

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitMcpCallTool:
    """Test emit_mcp_call_tool wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_call_tool should return valid JSON-RPC request."""
        result = emit_mcp_call_tool(
            server_id="server-123",
            method="read_file",
            params={"path": "/tmp/test.txt"},
        )

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.call_tool"
        assert "params" in result
        assert result["params"]["server_id"] == "server-123"
        assert result["params"]["method"] == "read_file"
        assert result["params"]["params"] == {"path": "/tmp/test.txt"}
        assert "timestamp" in result["params"]

    def test_includes_default_timeout(self) -> None:
        """emit_mcp_call_tool should include default timeout of 30.0 seconds."""
        result = emit_mcp_call_tool(
            server_id="server-123",
            method="list_directory",
            params={"path": "/home"},
        )

        assert result["params"]["timeout"] == 30.0

    def test_accepts_custom_timeout(self) -> None:
        """emit_mcp_call_tool should accept custom timeout value."""
        result = emit_mcp_call_tool(
            server_id="server-123",
            method="search_files",
            params={"pattern": "*.py"},
            timeout=60.0,
        )

        assert result["params"]["timeout"] == 60.0

    def test_with_different_methods(self) -> None:
        """emit_mcp_call_tool should work with various method names."""
        methods = ["read_file", "write_file", "list_directory", "execute_command"]

        for method in methods:
            result = emit_mcp_call_tool(
                server_id="tool-server",
                method=method,
                params={},
            )
            assert result["params"]["method"] == method

    def test_with_complex_params(self) -> None:
        """emit_mcp_call_tool should handle complex nested params."""
        complex_params = {
            "files": ["a.txt", "b.txt"],
            "options": {"recursive": True, "follow_symlinks": False},
            "filters": {"min_size": 1024, "max_size": 1048576},
        }
        result = emit_mcp_call_tool(
            server_id="complex-server",
            method="batch_operation",
            params=complex_params,
        )

        assert result["params"]["params"] == complex_params

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_call_tool should use provided timestamp."""
        custom_ts = "2024-01-15T11:30:00Z"
        result = emit_mcp_call_tool(
            server_id="server-456",
            method="test",
            params={},
            timestamp=custom_ts,
        )

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_call_tool should auto-generate timestamp if not provided."""
        result = emit_mcp_call_tool(
            server_id="auto-tool-server",
            method="ping",
            params={},
        )

        timestamp = result["params"]["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp
        assert timestamp.endswith("Z")


class TestEmitMcpHealthCheck:
    """Test emit_mcp_health_check wire protocol function."""

    def test_returns_correct_json_rpc_structure(self) -> None:
        """emit_mcp_health_check should return valid JSON-RPC request."""
        result = emit_mcp_health_check()

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "mcp.health_check"
        assert "params" in result
        assert "timestamp" in result["params"]

    def test_with_custom_timestamp(self) -> None:
        """emit_mcp_health_check should use provided timestamp."""
        custom_ts = "2024-01-15T11:45:00Z"
        result = emit_mcp_health_check(timestamp=custom_ts)

        assert result["params"]["timestamp"] == custom_ts

    def test_auto_generates_timestamp(self) -> None:
        """emit_mcp_health_check should auto-generate timestamp if not provided."""
        result = emit_mcp_health_check()

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


class TestHandleMcpList:
    """Test _handle_mcp_list bridge controller method."""

    @pytest.mark.asyncio
    async def test_returns_serialized_server_info(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_list should return serialized ServerInfo objects."""
        # Mock ServerInfo objects
        mock_servers = [
            ServerInfo(
                id="server-1",
                name="filesystem",
                type="stdio",
                enabled=True,
                state=ServerState.RUNNING,
                quarantined=False,
                uptime_seconds=3600.5,
                error_message=None,
                health={"is_healthy": True},
                latency_ms=15.5,
            ),
            ServerInfo(
                id="server-2",
                name="api-server",
                type="sse",
                enabled=False,
                state=ServerState.STOPPED,
                quarantined=False,
                uptime_seconds=None,
                error_message=None,
                health=None,
                latency_ms=None,
            ),
        ]

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = mock_servers

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_list({})

        assert result["status"] == "ok"
        assert result["count"] == 2
        assert len(result["servers"]) == 2

        # Check first server serialization
        server_1 = result["servers"][0]
        assert server_1["id"] == "server-1"
        assert server_1["name"] == "filesystem"
        assert server_1["type"] == "stdio"
        assert server_1["enabled"] is True
        assert server_1["state"] == "running"
        assert server_1["quarantined"] is False
        assert server_1["uptime_seconds"] == 3600.5
        assert server_1["health"] == {"is_healthy": True}
        assert server_1["latency_ms"] == 15.5

        # Check second server serialization
        server_2 = result["servers"][1]
        assert server_2["id"] == "server-2"
        assert server_2["name"] == "api-server"
        assert server_2["type"] == "sse"
        assert server_2["enabled"] is False
        assert server_2["state"] == "stopped"

    @pytest.mark.asyncio
    async def test_empty_server_list(self, controller: BridgeController) -> None:
        """_handle_mcp_list should handle empty server list."""
        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = []

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_list({})

        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["servers"] == []

    @pytest.mark.asyncio
    async def test_server_with_error_state(self, controller: BridgeController) -> None:
        """_handle_mcp_list should properly serialize error state servers."""
        mock_servers = [
            ServerInfo(
                id="error-server",
                name="broken-server",
                type="stdio",
                enabled=True,
                state=ServerState.ERROR,
                quarantined=False,
                uptime_seconds=10.0,
                error_message="Connection refused",
                health={"is_healthy": False, "error": "Connection refused"},
                latency_ms=None,
            ),
        ]

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = mock_servers

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_list({})

        assert result["count"] == 1
        server = result["servers"][0]
        assert server["state"] == "error"
        assert server["error_message"] == "Connection refused"
        assert server["health"]["is_healthy"] is False

    @pytest.mark.asyncio
    async def test_quarantined_server(self, controller: BridgeController) -> None:
        """_handle_mcp_list should properly serialize quarantined servers."""
        mock_servers = [
            ServerInfo(
                id="quarantine-server",
                name="unstable-server",
                type="stdio",
                enabled=True,
                state=ServerState.QUARANTINED,
                quarantined=True,
                uptime_seconds=300.0,
                error_message=None,
                health={"is_healthy": False, "quarantine_reason": "too many errors"},
                latency_ms=100.0,
            ),
        ]

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = mock_servers

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_list({})

        server = result["servers"][0]
        assert server["state"] == "quarantined"
        assert server["quarantined"] is True


class TestHandleMcpStatus:
    """Test _handle_mcp_status bridge controller method."""

    @pytest.mark.asyncio
    async def test_returns_server_status(self, controller: BridgeController) -> None:
        """_handle_mcp_status should return comprehensive server status."""
        mock_status = {
            "server_id": "server-123",
            "exists": True,
            "state": "running",
            "enabled": True,
            "uptime_seconds": 7200.0,
            "tools_count": 5,
        }

        mock_manager = MagicMock()
        mock_manager.get_server_status.return_value = mock_status

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_status({"server_id": "server-123"})

        mock_manager.get_server_status.assert_called_once_with("server-123")
        assert result["status"] == "ok"
        assert result["exists"] is True
        assert result["state"] == "running"

    @pytest.mark.asyncio
    async def test_raises_error_for_nonexistent_server(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_status should raise WireMethodError for unknown server."""
        mock_status = {"exists": False}

        mock_manager = MagicMock()
        mock_manager.get_server_status.return_value = mock_status

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            with pytest.raises(WireMethodError) as exc_info:
                await controller._handle_mcp_status({"server_id": "nonexistent"})

        assert exc_info.value.code == -32001  # Server not found
        assert "nonexistent" in str(exc_info.value)


class TestHandleMcpHealthCheck:
    """Test _handle_mcp_health_check bridge controller method."""

    @pytest.mark.asyncio
    async def test_returns_health_data(self, controller: BridgeController) -> None:
        """_handle_mcp_health_check should return health data for all servers."""
        mock_servers = [
            ServerInfo(
                id="healthy-server",
                name="good-server",
                type="stdio",
                enabled=True,
                state=ServerState.RUNNING,
                quarantined=False,
                uptime_seconds=3600.0,
                error_message=None,
                health={"is_healthy": True, "last_check": "2024-01-15T10:00:00Z"},
                latency_ms=10.0,
            ),
            ServerInfo(
                id="unhealthy-server",
                name="bad-server",
                type="sse",
                enabled=True,
                state=ServerState.ERROR,
                quarantined=False,
                uptime_seconds=60.0,
                error_message="Connection timeout",
                health={"is_healthy": False, "error": "Connection timeout"},
                latency_ms=None,
            ),
        ]

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = mock_servers

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_health_check({})

        assert result["status"] == "ok"
        assert result["total"] == 2
        assert result["healthy"] == 1
        assert result["unhealthy"] == 1
        assert len(result["servers"]) == 2

        # Check healthy server
        healthy = result["servers"][0]
        assert healthy["id"] == "healthy-server"
        assert healthy["is_healthy"] is True
        assert healthy["latency_ms"] == 10.0

        # Check unhealthy server
        unhealthy = result["servers"][1]
        assert unhealthy["id"] == "unhealthy-server"
        assert unhealthy["is_healthy"] is False
        assert unhealthy["error"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_empty_health_check(self, controller: BridgeController) -> None:
        """_handle_mcp_health_check should handle no servers."""
        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = []

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_health_check({})

        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["healthy"] == 0
        assert result["unhealthy"] == 0


class TestHandleMcpCallTool:
    """Test _handle_mcp_call_tool bridge controller method."""

    @pytest.mark.asyncio
    async def test_returns_not_implemented_error(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_call_tool should return not-implemented error."""
        params = {
            "server_id": "server-123",
            "method": "read_file",
            "params": {"path": "/tmp/test.txt"},
            "timeout": 30.0,
        }

        result = await controller._handle_mcp_call_tool(params)

        assert result["status"] == "error"
        assert "not supported" in result["error"].lower()
        assert result["fallback"] == "local"
        assert "local" in result["message"].lower()


class TestHandleMcpRegister:
    """Test _handle_mcp_register bridge controller method."""

    @pytest.mark.asyncio
    async def test_registers_server_successfully(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_register should register server and return ID."""
        params = {
            "name": "test-server",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        }

        mock_manager = MagicMock()
        mock_manager.register_server.return_value = "registered-server-id"

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_register(params)

        assert result["status"] == "registered"
        assert result["server_id"] == "registered-server-id"
        assert result["name"] == "test-server"

    @pytest.mark.asyncio
    async def test_registers_with_env_and_opts(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_register should handle env and opts parameters."""
        params = {
            "name": "env-server",
            "command": "python",
            "args": ["server.py"],
            "env": {"DEBUG": "1"},
            "opts": {"timeout": 60},
        }

        mock_manager = MagicMock()
        mock_manager.register_server.return_value = "env-server-id"

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            await controller._handle_mcp_register(params)

        # Verify ServerConfig was created with merged env/opts
        call_args = mock_manager.register_server.call_args[0][0]
        assert call_args.config["DEBUG"] == "1"
        assert call_args.config["timeout"] == 60


class TestHandleMcpUnregister:
    """Test _handle_mcp_unregister bridge controller method."""

    @pytest.mark.asyncio
    async def test_unregisters_server_successfully(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_unregister should remove server and return success."""
        params = {"server_id": "server-to-remove"}

        mock_manager = MagicMock()
        mock_manager.remove_server.return_value = True

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller._handle_mcp_unregister(params)

        mock_manager.remove_server.assert_called_once_with("server-to-remove")
        assert result["status"] == "unregistered"
        assert result["server_id"] == "server-to-remove"

    @pytest.mark.asyncio
    async def test_raises_error_for_missing_server(
        self, controller: BridgeController
    ) -> None:
        """_handle_mcp_unregister should raise error if server not found."""
        params = {"server_id": "nonexistent-server"}

        mock_manager = MagicMock()
        mock_manager.remove_server.return_value = False

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            with pytest.raises(WireMethodError) as exc_info:
                await controller._handle_mcp_unregister(params)

        assert exc_info.value.code == -32001  # Server not found
        assert "nonexistent-server" in str(exc_info.value)


# =============================================================================
# Dispatch Integration Tests
# =============================================================================


class TestMcpDispatch:
    """Test that MCP methods are properly dispatched."""

    @pytest.mark.asyncio
    async def test_dispatch_mcp_list(self, controller: BridgeController) -> None:
        """dispatch should route mcp.list to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "mcp.list",
            "params": {},
        }

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = []

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_dispatch_mcp_status(self, controller: BridgeController) -> None:
        """dispatch should route mcp.status to handler."""
        request = {
            "jsonjsonrpc": "2.0",
            "id": 2,
            "method": "mcp.status",
            "params": {"server_id": "test-server"},
        }

        mock_manager = MagicMock()
        mock_manager.get_server_status.return_value = {
            "exists": True,
            "state": "running",
        }

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller.dispatch(request)

        assert result["exists"] is True

    @pytest.mark.asyncio
    async def test_dispatch_mcp_health_check(
        self, controller: BridgeController
    ) -> None:
        """dispatch should route mcp.health_check to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "mcp.health_check",
            "params": {},
        }

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = []

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            result = await controller.dispatch(request)

        assert result["status"] == "ok"
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_dispatch_mcp_call_tool(self, controller: BridgeController) -> None:
        """dispatch should route mcp.call_tool to handler."""
        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "mcp.call_tool",
            "params": {
                "server_id": "server-123",
                "method": "read_file",
                "params": {"path": "/tmp/test.txt"},
            },
        }

        result = await controller.dispatch(request)

        assert result["status"] == "error"
        assert "not supported" in result["error"].lower()


# =============================================================================
# Fallback Behavior Tests
# =============================================================================


class TestMcpFallbackBehavior:
    """Test fallback to local MCP manager when bridge is unavailable."""

    def test_list_servers_uses_local_when_not_connected(self) -> None:
        """When is_connected() returns False, list_servers() uses local implementation."""
        from code_puppy.mcp_.manager import MCPManager

        manager = MCPManager.__new__(MCPManager)
        manager._managed_servers = {}
        manager.status_tracker = MagicMock()

        with patch(
            "code_puppy.mcp_.manager._get_elixir_bridge",
            return_value=None,  # Bridge not available
        ):
            result = manager.list_servers(use_bridge=True)

        # Should return empty list from local implementation
        assert isinstance(result, list)

    def test_list_servers_with_use_bridge_false(self) -> None:
        """use_bridge=False should force local implementation."""
        from code_puppy.mcp_.manager import MCPManager

        manager = MCPManager.__new__(MCPManager)
        manager._managed_servers = {}
        manager.status_tracker = MagicMock()

        # Even with bridge available
        mock_bridge = MagicMock()
        mock_bridge.is_connected.return_value = True

        with patch(
            "code_puppy.mcp_.manager._get_elixir_bridge",
            return_value=mock_bridge,
        ):
            result = manager.list_servers(use_bridge=False)

        # Should use local implementation, not call bridge
        mock_bridge.is_connected.assert_not_called()
        assert isinstance(result, list)

    def test_get_server_status_uses_local_when_not_connected(self) -> None:
        """When is_connected() returns False, get_server_status() uses local."""
        from code_puppy.mcp_.manager import MCPManager

        manager = MCPManager.__new__(MCPManager)
        manager._managed_servers = {}
        manager.status_tracker = MagicMock()

        with patch(
            "code_puppy.mcp_.manager._get_elixir_bridge",
            return_value=None,  # Bridge not available
        ):
            result = manager.get_server_status("test-server", use_bridge=True)

        # Should return not-found from local implementation
        assert result["exists"] is False

    def test_get_server_status_with_use_bridge_false(self) -> None:
        """use_bridge=False should force local implementation for get_server_status."""
        from code_puppy.mcp_.manager import MCPManager

        manager = MCPManager.__new__(MCPManager)
        manager._managed_servers = {}
        manager.status_tracker = MagicMock()

        # Even with bridge available
        mock_bridge = MagicMock()
        mock_bridge.is_connected.return_value = True

        with patch(
            "code_puppy.mcp_.manager._get_elixir_bridge",
            return_value=mock_bridge,
        ):
            manager.get_server_status("test-server", use_bridge=False)

        # Should use local implementation, not call bridge
        mock_bridge.is_connected.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_servers_falls_back_on_bridge_timeout(self) -> None:
        """When bridge times out, list_servers() falls back to local."""
        from code_puppy.mcp_.manager import MCPManager

        manager = MCPManager.__new__(MCPManager)
        manager._managed_servers = {}
        manager.status_tracker = MagicMock()

        mock_bridge = MagicMock()
        mock_bridge.is_connected.return_value = True
        mock_bridge.call_elixir_mcp.side_effect = TimeoutError("Bridge timeout")

        with patch(
            "code_puppy.mcp_.manager._get_elixir_bridge",
            return_value=mock_bridge,
        ):
            result = manager.list_servers(use_bridge=True)

        # Bridge was attempted
        mock_bridge.is_connected.assert_called_once()
        # But fallback to local should still work
        assert isinstance(result, list)


# =============================================================================
# End-to-End Integration Tests
# =============================================================================


class TestMcpEndToEnd:
    """End-to-end tests for MCP bridge flow."""

    @pytest.mark.asyncio
    async def test_full_register_unregister_cycle_via_dispatch(
        self, controller: BridgeController
    ) -> None:
        """Test complete register -> unregister cycle through dispatch."""
        mock_manager = MagicMock()
        mock_manager.register_server.return_value = "e2e-server-id"
        mock_manager.remove_server.return_value = True

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            # Register
            register_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "mcp.register",
                "params": {
                    "name": "test-e2e-server",
                    "command": "echo",
                    "args": ["hello"],
                },
            }

            register_result = await controller.dispatch(register_request)
            assert register_result["status"] == "registered"
            server_id = register_result["server_id"]

            # Unregister
            unregister_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "mcp.unregister",
                "params": {"server_id": server_id},
            }

            unregister_result = await controller.dispatch(unregister_request)
            assert unregister_result["status"] == "unregistered"

    @pytest.mark.asyncio
    async def test_list_health_check_sequence(
        self, controller: BridgeController
    ) -> None:
        """Test list -> health_check sequence."""
        mock_servers = [
            ServerInfo(
                id="seq-server-1",
                name="sequence-server",
                type="stdio",
                enabled=True,
                state=ServerState.RUNNING,
                quarantined=False,
                uptime_seconds=1800.0,
                error_message=None,
                health={"is_healthy": True},
                latency_ms=20.0,
            ),
        ]

        mock_manager = MagicMock()
        mock_manager.list_servers.return_value = mock_servers

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            # List servers
            list_result = await controller._handle_mcp_list({})
            assert list_result["count"] == 1

            # Health check
            health_result = await controller._handle_mcp_health_check({})
            assert health_result["total"] == 1
            assert health_result["healthy"] == 1


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestMcpErrorHandling:
    """Test error handling in MCP bridge."""

    @pytest.mark.asyncio
    async def test_list_propagates_wire_method_error(
        self, controller: BridgeController
    ) -> None:
        """Should properly raise WireMethodError for manager errors."""
        mock_manager = MagicMock()
        mock_manager.list_servers.side_effect = Exception("Database error")

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            with pytest.raises(WireMethodError) as exc_info:
                await controller._handle_mcp_list({})

        assert exc_info.value.code == -32000  # Server error

    @pytest.mark.asyncio
    async def test_status_propagates_not_found_error(
        self, controller: BridgeController
    ) -> None:
        """Should raise proper WireMethodError for missing server."""
        mock_manager = MagicMock()
        mock_manager.get_server_status.return_value = {"exists": False}

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            with pytest.raises(WireMethodError) as exc_info:
                await controller._handle_mcp_status({"server_id": "missing"})

        assert exc_info.value.code == -32001  # Server not found

    @pytest.mark.asyncio
    async def test_register_propagates_error(
        self, controller: BridgeController
    ) -> None:
        """Should raise WireMethodError when register fails."""
        params = {
            "name": "fail-server",
            "command": "invalid",
            "args": [],
        }

        mock_manager = MagicMock()
        mock_manager.register_server.side_effect = RuntimeError("Config invalid")

        with patch(
            "code_puppy.plugins.elixir_bridge.bridge_controller.get_mcp_manager",
            return_value=mock_manager,
        ):
            with pytest.raises(WireMethodError) as exc_info:
                await controller._handle_mcp_register(params)

        assert exc_info.value.code == -32000


# =============================================================================
# Wire Protocol Constants Tests
# =============================================================================


class TestWireProtocolConstants:
    """Test wire protocol error code constants."""

    def test_error_codes_defined(self) -> None:
        """JSON-RPC error codes should be properly defined."""
        from code_puppy.plugins.elixir_bridge.wire_protocol import (
            PARSE_ERROR,
            INVALID_REQUEST,
            METHOD_NOT_FOUND,
            INVALID_PARAMS,
            INTERNAL_ERROR,
            SERVER_ERROR_MIN,
            SERVER_ERROR_MAX,
        )

        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602
        assert INTERNAL_ERROR == -32603
        assert SERVER_ERROR_MIN == -32000
        assert SERVER_ERROR_MAX == -32099

    def test_legacy_aliases(self) -> None:
        """Legacy JSON-RPC error code aliases should work."""
        from code_puppy.plugins.elixir_bridge.wire_protocol import (
            JSONRPC_PARSE_ERROR,
            JSONRPC_INVALID_REQUEST,
            JSONRPC_METHOD_NOT_FOUND,
            JSONRPC_INVALID_PARAMS,
            JSONRPC_INTERNAL_ERROR,
        )
        from code_puppy.plugins.elixir_bridge.wire_protocol import (
            PARSE_ERROR,
            INVALID_REQUEST,
            METHOD_NOT_FOUND,
            INVALID_PARAMS,
            INTERNAL_ERROR,
        )

        assert JSONRPC_PARSE_ERROR == PARSE_ERROR
        assert JSONRPC_INVALID_REQUEST == INVALID_REQUEST
        assert JSONRPC_METHOD_NOT_FOUND == METHOD_NOT_FOUND
        assert JSONRPC_INVALID_PARAMS == INVALID_PARAMS
        assert JSONRPC_INTERNAL_ERROR == INTERNAL_ERROR
