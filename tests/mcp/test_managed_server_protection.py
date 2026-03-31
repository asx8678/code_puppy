"""
Tests for ManagedMCPServer circuit-breaker + retry protection.

Covers:
- _get_circuit_breaker() lazy initialisation
- _protected_process_tool_call() happy path
- _protected_process_tool_call() retries on transient failure
- _protected_process_tool_call() raises CircuitOpenError when CB is open
- Circuit-breaker trips after failure_threshold consecutive failures
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from code_puppy.mcp_.circuit_breaker import CircuitBreaker, CircuitOpenError
from code_puppy.mcp_.managed_server import ManagedMCPServer, ServerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(server_type: str = "sse", extra_config: dict | None = None) -> ManagedMCPServer:
    """Create a ManagedMCPServer with a mocked underlying pydantic server."""
    cfg = {"url": "http://localhost:9999"}
    if extra_config:
        cfg.update(extra_config)
    config = ServerConfig(
        id="test-srv-1",
        name="test-server",
        type=server_type,
        config=cfg,
    )
    with patch("code_puppy.mcp_.managed_server.MCPServerSSE") as mock_sse:
        mock_sse.return_value = MagicMock()
        server = ManagedMCPServer(config)
    return server


def _make_ctx(deps=None):
    ctx = Mock()
    ctx.deps = deps
    return ctx


# ---------------------------------------------------------------------------
# _get_circuit_breaker
# ---------------------------------------------------------------------------


class TestGetCircuitBreaker:
    """Tests for lazy circuit-breaker initialisation."""

    def test_returns_circuit_breaker(self):
        server = _make_server()
        cb = server._get_circuit_breaker()
        assert isinstance(cb, CircuitBreaker)

    def test_returns_same_instance_on_repeated_calls(self):
        server = _make_server()
        cb1 = server._get_circuit_breaker()
        cb2 = server._get_circuit_breaker()
        assert cb1 is cb2

    def test_starts_with_no_circuit_breaker(self):
        server = _make_server()
        assert server._circuit_breaker is None

    def test_initialised_with_correct_threshold(self):
        server = _make_server()
        cb = server._get_circuit_breaker()
        assert cb.failure_threshold == 3

    def test_initialised_with_correct_timeout(self):
        server = _make_server()
        cb = server._get_circuit_breaker()
        assert cb.timeout == 30


# ---------------------------------------------------------------------------
# _protected_process_tool_call — happy path
# ---------------------------------------------------------------------------


class TestProtectedProcessToolCallSuccess:
    """Happy-path tests for protected tool calls."""

    @pytest.mark.asyncio
    async def test_returns_tool_result(self):
        server = _make_server()
        ctx = _make_ctx(deps={"key": "value"})
        mock_call_tool = AsyncMock(return_value="ok_result")

        with patch("rich.console.Console"):
            result = await server._protected_process_tool_call(
                ctx=ctx,
                call_tool=mock_call_tool,
                name="my_tool",
                tool_args={"a": 1},
            )

        assert result == "ok_result"

    @pytest.mark.asyncio
    async def test_forwards_correct_args_to_call_tool(self):
        server = _make_server()
        ctx = _make_ctx(deps="some-deps")
        mock_call_tool = AsyncMock(return_value="result")

        with patch("rich.console.Console"):
            await server._protected_process_tool_call(
                ctx=ctx,
                call_tool=mock_call_tool,
                name="search",
                tool_args={"query": "hello"},
            )

        mock_call_tool.assert_called_once_with(
            "search", {"query": "hello"}, {"deps": "some-deps"}
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_stays_closed_on_success(self):
        server = _make_server()
        ctx = _make_ctx()
        mock_call_tool = AsyncMock(return_value="ok")

        with patch("rich.console.Console"):
            await server._protected_process_tool_call(
                ctx=ctx, call_tool=mock_call_tool, name="t", tool_args={}
            )

        cb = server._get_circuit_breaker()
        assert cb.is_closed()


# ---------------------------------------------------------------------------
# _protected_process_tool_call — retry behaviour
# ---------------------------------------------------------------------------


class TestProtectedProcessToolCallRetry:
    """Tests that transient failures are retried."""

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """A ConnectionError on the first call should be retried."""
        server = _make_server()
        ctx = _make_ctx()

        call_count = 0

        async def flaky_call_tool(name, args, meta):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        with patch("rich.console.Console"):
            result = await server._protected_process_tool_call(
                ctx=ctx,
                call_tool=flaky_call_tool,
                name="tool",
                tool_args={},
            )

        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """If all retries fail the exception propagates."""
        server = _make_server()
        ctx = _make_ctx()
        always_fails = AsyncMock(side_effect=ConnectionError("permanent"))

        with patch("rich.console.Console"), pytest.raises(ConnectionError):
            await server._protected_process_tool_call(
                ctx=ctx,
                call_tool=always_fails,
                name="failing_tool",
                tool_args={},
            )

        # called once per attempt (3 by default)
        assert always_fails.call_count == 3


# ---------------------------------------------------------------------------
# _protected_process_tool_call — circuit-breaker integration
# ---------------------------------------------------------------------------


class TestProtectedProcessToolCallCircuitBreaker:
    """Tests for circuit-breaker tripping and blocking."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_after_threshold_failures(self):
        """After failure_threshold exhausted-retry calls, the CB should open."""
        server = _make_server()
        ctx = _make_ctx()
        always_fails = AsyncMock(side_effect=ConnectionError("boom"))

        # failure_threshold = 3 → need 3 failed top-level calls to open the CB
        for _ in range(3):
            with patch("rich.console.Console"), pytest.raises(Exception):
                await server._protected_process_tool_call(
                    ctx=ctx, call_tool=always_fails, name="t", tool_args={}
                )

        cb = server._get_circuit_breaker()
        assert cb.is_open(), "Circuit breaker should be OPEN after 3 consecutive failures"

    @pytest.mark.asyncio
    async def test_raises_circuit_open_error_when_cb_open(self):
        """Once the CB is open, subsequent calls should raise CircuitOpenError."""
        server = _make_server()
        ctx = _make_ctx()

        # Force CB open
        server._get_circuit_breaker().force_open()

        with patch("rich.console.Console"), pytest.raises(CircuitOpenError):
            await server._protected_process_tool_call(
                ctx=ctx,
                call_tool=AsyncMock(),
                name="blocked_tool",
                tool_args={},
            )

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovers_after_reset(self):
        """After a reset, calls should succeed again."""
        server = _make_server()
        ctx = _make_ctx()
        mock_call_tool = AsyncMock(return_value="ok")

        # Force CB open then close again
        server._get_circuit_breaker().force_open()
        server._get_circuit_breaker().force_close()

        with patch("rich.console.Console"):
            result = await server._protected_process_tool_call(
                ctx=ctx, call_tool=mock_call_tool, name="t", tool_args={}
            )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_circuit_open_error_is_logged(self):
        """CircuitOpenError should trigger a warning log."""
        server = _make_server()
        ctx = _make_ctx()
        server._get_circuit_breaker().force_open()

        with (
            patch("rich.console.Console"),
            patch("code_puppy.mcp_.managed_server.logger") as mock_logger,
            pytest.raises(CircuitOpenError),
        ):
            await server._protected_process_tool_call(
                ctx=ctx, call_tool=AsyncMock(), name="my_tool", tool_args={}
            )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert "my_tool" in call_args[2]


# ---------------------------------------------------------------------------
# Server creation wires _protected_process_tool_call
# ---------------------------------------------------------------------------


class TestServerCreationWiresProtection:
    """Verify that _create_server passes _protected_process_tool_call."""

    def test_sse_server_uses_protected_callback(self):
        config = ServerConfig(
            id="s1", name="sse-srv", type="sse", config={"url": "http://localhost"}
        )
        with patch("code_puppy.mcp_.managed_server.MCPServerSSE") as mock_sse:
            mock_sse.return_value = MagicMock()
            server = ManagedMCPServer(config)

        kwargs = mock_sse.call_args.kwargs
        # Bound methods create a new object on every attribute access; compare
        # the underlying __func__ to confirm the correct method was wired.
        assert (
            kwargs["process_tool_call"].__func__
            is ManagedMCPServer._protected_process_tool_call
        )
        assert kwargs["process_tool_call"].__self__ is server

    def test_http_server_uses_protected_callback(self):
        config = ServerConfig(
            id="s2", name="http-srv", type="http", config={"url": "http://localhost"}
        )
        with patch(
            "code_puppy.mcp_.managed_server.MCPServerStreamableHTTP"
        ) as mock_http:
            mock_http.return_value = MagicMock()
            server = ManagedMCPServer(config)

        kwargs = mock_http.call_args.kwargs
        assert (
            kwargs["process_tool_call"].__func__
            is ManagedMCPServer._protected_process_tool_call
        )
        assert kwargs["process_tool_call"].__self__ is server

    def test_stdio_server_uses_protected_callback(self):
        config = ServerConfig(
            id="s3",
            name="stdio-srv",
            type="stdio",
            config={"command": "python"},
        )
        with patch(
            "code_puppy.mcp_.managed_server.BlockingMCPServerStdio"
        ) as mock_stdio:
            mock_stdio.return_value = MagicMock()
            server = ManagedMCPServer(config)

        kwargs = mock_stdio.call_args.kwargs
        assert (
            kwargs["process_tool_call"].__func__
            is ManagedMCPServer._protected_process_tool_call
        )
        assert kwargs["process_tool_call"].__self__ is server
