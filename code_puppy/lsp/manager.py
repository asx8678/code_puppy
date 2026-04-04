"""LSP server lifecycle management.

Manages multiple language server connections with lazy startup,
auto-detection of project types, and connection pooling.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from code_puppy.lsp.client import LspClient

logger = logging.getLogger(__name__)

# Server configurations for supported languages
SERVER_CONFIGS: dict[str, dict[str, Any]] = {
    "python": {
        "command": "pyright-langserver",
        "args": ["--stdio"],
        "extensions": [".py", ".pyi"],
        "config_files": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"],
    },
    "typescript": {
        "command": "typescript-language-server",
        "args": ["--stdio"],
        "extensions": [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"],
        "config_files": ["tsconfig.json", "package.json"],
    },
    "javascript": {
        "command": "typescript-language-server",
        "args": ["--stdio"],
        "extensions": [".js", ".jsx", ".mjs", ".cjs"],
        "config_files": ["package.json", "jsconfig.json"],
    },
    "rust": {
        "command": "rust-analyzer",
        "args": [],
        "extensions": [".rs"],
        "config_files": ["Cargo.toml"],
    },
    "go": {
        "command": "gopls",
        "args": [],
        "extensions": [".go"],
        "config_files": ["go.mod", "go.sum"],
    },
}

# Global manager instance
_manager_instance: "LspServerManager | None" = None
_manager_lock = asyncio.Lock()


async def get_server_manager() -> "LspServerManager":
    """Get or create the global LSP server manager.

    Returns:
        The global LspServerManager instance.
    """
    global _manager_instance
    if _manager_instance is None:
        async with _manager_lock:
            if _manager_instance is None:
                _manager_instance = LspServerManager()
    return _manager_instance


class LspServerManager:
    """Manages LSP server instances with lazy startup.

    Handles:
    - Auto-detection of project type from file paths
    - Lazy server startup on first query
    - Connection pooling and reuse
    - Graceful handling of missing servers

    Example:
        manager = LspServerManager()
        client = await manager.get_client_for_file("src/main.py")
        if client:
            response = await client.request(...)
    """

    def __init__(self, workspace_path: str = "."):
        """Initialize the server manager.

        Args:
            workspace_path: Root workspace path for all servers.
        """
        self.workspace_path = workspace_path
        self._clients: dict[str, LspClient] = {}
        self._available_servers: dict[str, bool] = {}
        self._lock = asyncio.Lock()
        self._last_used: dict[str, float] = {}
        self._cleanup_task: asyncio.Task | None = None

    async def _detect_language(self, file_path: str) -> str | None:
        """Detect language from file extension and project structure.

        Args:
            file_path: Path to the file.

        Returns:
            Language identifier or None if can't detect.
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        # First check by extension
        for lang, config in SERVER_CONFIGS.items():
            if ext in config["extensions"]:
                return lang

        # Then check by project structure
        for lang, config in SERVER_CONFIGS.items():
            for config_file in config["config_files"]:
                config_path = Path(self.workspace_path) / config_file
                if config_path.exists():
                    return lang

        return None

    async def _check_server_available(self, lang: str) -> bool:
        """Check if a language server binary is installed.

        Args:
            lang: Language identifier.

        Returns:
            True if server binary is available.
        """
        if lang in self._available_servers:
            return self._available_servers[lang]

        config = SERVER_CONFIGS.get(lang)
        if not config:
            self._available_servers[lang] = False
            return False

        available = shutil.which(config["command"]) is not None
        self._available_servers[lang] = available

        if not available:
            logger.debug(f"LSP server {config['command']} not found for {lang}")

        return available

    async def get_client_for_file(self, file_path: str) -> LspClient | None:
        """Get or create LSP client for a file.

        Uses lazy initialization - server is only started when first needed.
        Returns existing connection if available.

        Args:
            file_path: Path to the file to get client for.

        Returns:
            LspClient if available, None otherwise.
        """
        lang = await self._detect_language(file_path)
        if not lang:
            logger.debug(f"Could not detect language for {file_path}")
            return None

        return await self._get_client_for_language(lang)

    async def _get_client_for_language(self, lang: str) -> LspClient | None:
        """Get or create client for a specific language.

        Args:
            lang: Language identifier.

        Returns:
            LspClient if available, None otherwise.
        """
        # Check if server is available
        if not await self._check_server_available(lang):
            return None

        async with self._lock:
            # Return existing client if connected
            if lang in self._clients:
                client = self._clients[lang]
                if client.is_connected():
                    self._last_used[lang] = asyncio.get_event_loop().time()
                    return client
                # Client disconnected, remove it
                del self._clients[lang]

            # Create new client
            config = SERVER_CONFIGS[lang]
            client = LspClient(
                server_command=config["command"],
                server_args=config["args"],
                workspace_path=self.workspace_path,
            )

            # Try to connect
            if await client.connect():
                self._clients[lang] = client
                self._last_used[lang] = asyncio.get_event_loop().time()
                logger.info(f"LSP client connected for {lang}")
                return client
            else:
                logger.warning(f"Failed to connect LSP client for {lang}")
                return None

    async def get_client_for_language(self, lang: str) -> LspClient | None:
        """Get client by language identifier.

        Args:
            lang: Language identifier (python, typescript, rust, go).

        Returns:
            LspClient if available, None otherwise.
        """
        if lang not in SERVER_CONFIGS:
            return None
        return await self._get_client_for_language(lang)

    def get_supported_languages(self) -> list[str]:
        """Get list of supported language identifiers."""
        return list(SERVER_CONFIGS.keys())

    def get_available_languages(self) -> list[str]:
        """Get list of languages with available server binaries."""
        return [
            lang for lang in SERVER_CONFIGS.keys()
            if self._available_servers.get(lang, False)
        ]

    async def close_client(self, lang: str) -> None:
        """Close a specific language client.

        Args:
            lang: Language identifier.
        """
        async with self._lock:
            if lang in self._clients:
                client = self._clients.pop(lang)
                self._last_used.pop(lang, None)
                await client.close()

    async def close_all(self) -> None:
        """Close all LSP connections."""
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            self._last_used.clear()

        for client in clients:
            await client.close()

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_idle_connections(self, max_idle_seconds: float = 300.0) -> None:
        """Background task to clean up idle connections.

        Args:
            max_idle_seconds: Maximum idle time before closing.
        """
        while True:
            try:
                await asyncio.sleep(60.0)  # Check every minute

                current_time = asyncio.get_event_loop().time()
                to_close = []

                async with self._lock:
                    for lang, last_used in list(self._last_used.items()):
                        if current_time - last_used > max_idle_seconds:
                            to_close.append(lang)
                            if lang in self._clients:
                                client = self._clients.pop(lang)
                                await client.close()
                            del self._last_used[lang]

                if to_close:
                    logger.debug(f"Closed idle LSP connections: {to_close}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in LSP cleanup: {e}")

    def start_cleanup_task(self) -> None:
        """Start background cleanup task for idle connections."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_idle_connections())

    def get_status(self) -> dict[str, Any]:
        """Get current manager status.

        Returns:
            Dict with connection status for each language.
        """
        return {
            "workspace": self.workspace_path,
            "connected": {
                lang: client.is_connected()
                for lang, client in self._clients.items()
            },
            "available": self._available_servers.copy(),
            "supported": list(SERVER_CONFIGS.keys()),
        }
