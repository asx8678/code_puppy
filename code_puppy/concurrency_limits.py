"""Concurrency limiters for file operations and API calls.

This module provides configurable semaphores for controlling concurrent:
- File operations (read/write/edit)
- API calls (outbound model requests)
- Tool executions

Configuration is read from ~/.code_puppy/concurrency.toml with sensible defaults.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default concurrency limits
DEFAULT_FILE_OPS_LIMIT = 4  # Max concurrent file read/write operations
DEFAULT_API_CALLS_LIMIT = 2  # Max concurrent outbound API requests
DEFAULT_TOOL_CALLS_LIMIT = 8  # Max concurrent tool executions

_CONFIG_PATH = Path.home() / ".code_puppy" / "concurrency.toml"

# Global semaphores (initialized lazily)
_file_ops_semaphore: asyncio.Semaphore | None = None
_api_calls_semaphore: asyncio.Semaphore | None = None
_tool_calls_semaphore: asyncio.Semaphore | None = None

# Cached config
_cached_config: ConcurrencyConfig | None = None

# Lock for thread-safe semaphore initialization
_semaphore_init_lock = threading.Lock()


@dataclass(frozen=True)
class ConcurrencyConfig:
    """Configuration for concurrency limits."""

    file_ops_limit: int = DEFAULT_FILE_OPS_LIMIT
    api_calls_limit: int = DEFAULT_API_CALLS_LIMIT
    tool_calls_limit: int = DEFAULT_TOOL_CALLS_LIMIT

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConcurrencyConfig":
        """Create config from dictionary with validation."""
        return cls(
            file_ops_limit=max(
                1, int(data.get("file_ops_limit", DEFAULT_FILE_OPS_LIMIT))
            ),
            api_calls_limit=max(
                1, int(data.get("api_calls_limit", DEFAULT_API_CALLS_LIMIT))
            ),
            tool_calls_limit=max(
                1, int(data.get("tool_calls_limit", DEFAULT_TOOL_CALLS_LIMIT))
            ),
        )


def _read_config() -> ConcurrencyConfig:
    """Read concurrency configuration from TOML file."""
    global _cached_config

    if _cached_config is not None:
        return _cached_config

    if not _CONFIG_PATH.exists():
        _cached_config = ConcurrencyConfig()
        return _cached_config

    try:
        import tomllib  # Python 3.11+

        with open(_CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)

        _cached_config = ConcurrencyConfig.from_dict(data.get("concurrency", {}))
        return _cached_config

    except Exception as exc:
        logger.warning("Failed to read concurrency config %s: %s", _CONFIG_PATH, exc)
        _cached_config = ConcurrencyConfig()
        return _cached_config


def _get_file_ops_semaphore() -> asyncio.Semaphore:
    """Get or create the file operations semaphore."""
    global _file_ops_semaphore
    if _file_ops_semaphore is None:
        with _semaphore_init_lock:
            if _file_ops_semaphore is None:  # Double-checked locking
                config = _read_config()
                _file_ops_semaphore = asyncio.Semaphore(config.file_ops_limit)
                logger.debug(
                    "File ops semaphore initialized with limit %d",
                    config.file_ops_limit,
                )
    return _file_ops_semaphore


def _get_api_calls_semaphore() -> asyncio.Semaphore:
    """Get or create the API calls semaphore."""
    global _api_calls_semaphore
    if _api_calls_semaphore is None:
        with _semaphore_init_lock:
            if _api_calls_semaphore is None:  # Double-checked locking
                config = _read_config()
                _api_calls_semaphore = asyncio.Semaphore(config.api_calls_limit)
                logger.debug(
                    "API calls semaphore initialized with limit %d",
                    config.api_calls_limit,
                )
    return _api_calls_semaphore


def _get_tool_calls_semaphore() -> asyncio.Semaphore:
    """Get or create the tool calls semaphore."""
    global _tool_calls_semaphore
    if _tool_calls_semaphore is None:
        with _semaphore_init_lock:
            if _tool_calls_semaphore is None:  # Double-checked locking
                config = _read_config()
                _tool_calls_semaphore = asyncio.Semaphore(config.tool_calls_limit)
                logger.debug(
                    "Tool calls semaphore initialized with limit %d",
                    config.tool_calls_limit,
                )
    return _tool_calls_semaphore


async def acquire_file_ops_slot() -> None:
    """Acquire a slot for file operations."""
    sem = _get_file_ops_semaphore()
    await sem.acquire()


def release_file_ops_slot() -> None:
    """Release a file operations slot."""
    sem = _get_file_ops_semaphore()
    sem.release()


async def acquire_api_call_slot() -> None:
    """Acquire a slot for API calls."""
    sem = _get_api_calls_semaphore()
    await sem.acquire()


def release_api_call_slot() -> None:
    """Release an API call slot."""
    sem = _get_api_calls_semaphore()
    sem.release()


async def acquire_tool_call_slot() -> None:
    """Acquire a slot for tool calls."""
    sem = _get_tool_calls_semaphore()
    await sem.acquire()


def release_tool_call_slot() -> None:
    """Release a tool call slot."""
    sem = _get_tool_calls_semaphore()
    sem.release()


# Context managers for cleaner usage


class Limiter:
    """Generic context manager for concurrency limiting.

    Usage:
        async with Limiter(_get_file_ops_semaphore):
            # do file operation
            pass
    """

    def __init__(self, semaphore_getter):
        self._get_sem = semaphore_getter
        self._sem = None

    async def __aenter__(self):
        self._sem = self._get_sem()
        await self._sem.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._sem:
            self._sem.release()
        return False


# Convenience factory functions for specific limiter types
def FileOpsLimiter():
    """Context manager for file operations concurrency limiting."""
    return Limiter(_get_file_ops_semaphore)


def ApiCallsLimiter():
    """Context manager for API calls concurrency limiting."""
    return Limiter(_get_api_calls_semaphore)


def ToolCallsLimiter():
    """Context manager for tool calls concurrency limiting."""
    return Limiter(_get_tool_calls_semaphore)


def get_concurrency_status() -> dict[str, int]:
    """Get current semaphore status (for monitoring)."""
    return {
        "file_ops_limit": _get_file_ops_semaphore()._value,
        "file_ops_available": getattr(
            _file_ops_semaphore, "_value", DEFAULT_FILE_OPS_LIMIT
        )
        if _file_ops_semaphore
        else DEFAULT_FILE_OPS_LIMIT,
        "api_calls_limit": _get_api_calls_semaphore()._value,
        "api_calls_available": getattr(
            _api_calls_semaphore, "_value", DEFAULT_API_CALLS_LIMIT
        )
        if _api_calls_semaphore
        else DEFAULT_API_CALLS_LIMIT,
        "tool_calls_limit": _get_tool_calls_semaphore()._value,
        "tool_calls_available": getattr(
            _tool_calls_semaphore, "_value", DEFAULT_TOOL_CALLS_LIMIT
        )
        if _tool_calls_semaphore
        else DEFAULT_TOOL_CALLS_LIMIT,
    }


def reload_concurrency_config() -> None:
    """Reload concurrency configuration from disk."""
    global \
        _cached_config, \
        _file_ops_semaphore, \
        _api_calls_semaphore, \
        _tool_calls_semaphore

    global _cached_config
    _cached_config = None
    _file_ops_semaphore = None
    _api_calls_semaphore = None
    _tool_calls_semaphore = None

    # Force re-initialization
    _ = _get_file_ops_semaphore()
    _ = _get_api_calls_semaphore()
    _ = _get_tool_calls_semaphore()

    logger.info("Concurrency configuration reloaded")


def create_default_config() -> str:
    """Create default configuration file content."""
    return """# Code Puppy Concurrency Configuration
# Adjust these values based on your system and API rate limits

[concurrency]
# Maximum concurrent file read/write operations
# Higher values speed up file analysis but use more disk I/O
file_ops_limit = 4

# Maximum concurrent outbound API requests
# Lower this if you're hitting rate limits from providers
api_calls_limit = 2

# Maximum concurrent tool executions (includes file ops + shell commands)
# This is a broader limit for all tool calls
tool_calls_limit = 8
"""


def ensure_config_file() -> Path:
    """Ensure the configuration file exists with defaults."""
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(create_default_config())
        logger.info("Created default concurrency config at %s", _CONFIG_PATH)
    return _CONFIG_PATH
