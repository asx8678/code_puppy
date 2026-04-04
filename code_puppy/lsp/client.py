"""LSP JSON-RPC client implementation.

Provides low-level communication with LSP servers using JSON-RPC over stdio.
Uses asyncio for async communication with proper request/response matching.
"""

import asyncio
import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class LspClient:
    """LSP client for JSON-RPC communication with language servers.

    Manages the connection to a language server via stdin/stdout, handling:
    - Request/response correlation via message IDs
    - Server notification handling
    - Graceful shutdown
    - Connection health checking

    Example:
        client = LspClient("pyright-langserver", ["--stdio"])
        await client.connect()
        response = await client.request("textDocument/hover", {...})
        await client.close()
    """

    def __init__(
        self,
        server_command: str,
        server_args: list[str] | None = None,
        workspace_path: str = ".",
    ):
        """Initialize LSP client.

        Args:
            server_command: The language server executable name.
            server_args: Arguments to pass to the server. Defaults to ["--stdio"].
            workspace_path: Workspace root path for the LSP server.
        """
        self.server_command = server_command
        self.server_args = server_args or ["--stdio"]
        self.workspace_path = workspace_path

        self._process: subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._notification_handlers: list = []
        self._message_id = 0
        self._lock = asyncio.Lock()
        self._connected = False
        self._server_capabilities: dict[str, Any] = {}

    async def connect(self) -> bool:
        """Start the language server and establish connection.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.server_command,
                *self.server_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Start reader task to handle incoming messages
            self._reader_task = asyncio.create_task(self._read_messages())

            # Initialize LSP session
            init_result = await self._initialize()
            if init_result:
                self._connected = True
                logger.debug(f"LSP client connected to {self.server_command}")
            return init_result

        except Exception as e:
            logger.warning(f"Failed to connect to LSP server {self.server_command}: {e}")
            return False

    async def _initialize(self) -> bool:
        """Send LSP initialize request and wait for response.

        Returns:
            True if initialization successful, False otherwise.
        """
        try:
            import os

            root_uri = f"file://{os.path.abspath(self.workspace_path)}"

            result = await self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": root_uri,
                    "capabilities": {
                        "textDocument": {
                            "hover": {"contentFormat": ["plaintext", "markdown"]},
                            "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                            "publishDiagnostics": {"relatedInformation": True},
                        },
                        "workspace": {
                            "workspaceFolders": True,
                            "configuration": True,
                        },
                    },
                    "workspaceFolders": [{"uri": root_uri, "name": "workspace"}],
                },
            )

            if result and "capabilities" in result:
                self._server_capabilities = result["capabilities"]
                # Send initialized notification
                await self.notify("initialized", {})
                return True
            return False

        except Exception as e:
            logger.warning(f"LSP initialization failed: {e}")
            return False

    async def _read_messages(self) -> None:
        """Background task to read and dispatch messages from server."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                # Read Content-Length header
                header_line = await self._process.stdout.readline()
                if not header_line:
                    break  # EOF

                header = header_line.decode("utf-8").strip()
                if not header.startswith("Content-Length:"):
                    continue

                content_length = int(header.split(":")[1].strip())

                # Read empty line after header
                await self._process.stdout.readline()

                # Read message content
                content = await self._process.stdout.read(content_length)
                message = json.loads(content.decode("utf-8"))

                # Handle message
                await self._handle_message(message)

        except asyncio.CancelledError:
            logger.debug("LSP reader task cancelled")
        except Exception as e:
            logger.debug(f"LSP reader error: {e}")
        finally:
            self._connected = False

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Dispatch incoming LSP message.

        Args:
            message: The parsed JSON-RPC message.
        """
        msg_id = message.get("id")

        if "result" in message or "error" in message:
            # Response to a request
            if msg_id and msg_id in self._pending_requests:
                future = self._pending_requests.pop(msg_id)
                if "error" in message:
                    future.set_exception(LspError(message["error"]))
                else:
                    future.set_result(message.get("result"))
        else:
            # Server notification
            method = message.get("method", "")
            params = message.get("params", {})
            for handler in self._notification_handlers:
                try:
                    handler(method, params)
                except Exception as e:
                    logger.debug(f"Notification handler error: {e}")

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: The LSP method to call.
            params: Parameters for the method.

        Returns:
            The response result from the server.

        Raises:
            LspError: If the server returns an error.
            ConnectionError: If not connected.
        """
        if not self._connected or not self._process or not self._process.stdin:
            raise ConnectionError("LSP client not connected")

        async with self._lock:
            self._message_id += 1
            msg_id = str(self._message_id)

        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future

        # Send message
        content = json.dumps(message, separators=(",", ":"))
        header = f"Content-Length: {len(content)}\r\n\r\n"
        data = (header + content).encode("utf-8")

        try:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
        except Exception as e:
            self._pending_requests.pop(msg_id, None)
            raise ConnectionError(f"Failed to send LSP request: {e}")

        # Wait for response with timeout
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise LspError({"code": -32603, "message": "Request timeout"})

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The LSP method to call.
            params: Parameters for the method.
        """
        if not self._connected or not self._process or not self._process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        content = json.dumps(message, separators=(",", ":"))
        header = f"Content-Length: {len(content)}\r\n\r\n"
        data = (header + content).encode("utf-8")

        try:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
        except Exception as e:
            logger.debug(f"Failed to send LSP notification: {e}")

    async def close(self) -> None:
        """Shutdown the language server and close connection."""
        if not self._process:
            return

        try:
            # Send shutdown request
            if self._connected:
                try:
                    await asyncio.wait_for(
                        self.request("shutdown", {}),
                        timeout=5.0
                    )
                except Exception:
                    pass
                # Send exit notification
                await self.notify("exit", {})

            # Cancel reader task
            if self._reader_task:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass

            # Terminate process
            if self._process.returncode is None:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()

        except Exception as e:
            logger.debug(f"Error during LSP client close: {e}")
        finally:
            self._connected = False
            self._pending_requests.clear()
            self._process = None
            self._reader_task = None

    def is_connected(self) -> bool:
        """Check if client is connected and ready."""
        return self._connected and self._process is not None

    def get_capabilities(self) -> dict[str, Any]:
        """Get server capabilities from initialization."""
        return self._server_capabilities.copy()

    def add_notification_handler(self, handler) -> None:
        """Add handler for server notifications.

        Args:
            handler: Callback function receiving (method, params).
        """
        self._notification_handlers.append(handler)


class LspError(Exception):
    """LSP server error."""

    def __init__(self, error_data: dict[str, Any]):
        self.code = error_data.get("code", 0)
        self.message = error_data.get("message", "Unknown LSP error")
        super().__init__(f"LSP Error {self.code}: {self.message}")
