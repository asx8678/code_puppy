"""Native backend adapter — unified interface for native acceleration capabilities.

This module provides a single entry point for all native acceleration:
- MESSAGE_CORE: code_puppy_core (message serialization)
- FILE_OPS: turbo_ops (file operations - list_files, grep, read_file)
- REPO_INDEX: turbo_ops indexer (repository structure indexing)
- PARSE: turbo_parse (tree-sitter parsing)

All methods gracefully fall back to Python implementations when native modules
are unavailable, ensuring the system works regardless of Rust build status.

bd-61: Phase 1 of Fast Puppy rewrite — native backend adapter.
bd-62: Phase 2 — Add Elixir control plane routing for file operations.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from code_puppy.config import get_acceleration_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityInfo:
    """Information about a native capability."""

    name: str
    configured: str  # "rust", "python", or "elixir"
    available: bool
    active: bool
    status: str  # "active", "disabled", "unavailable"


class BackendPreference(str, Enum):
    """Backend preference for file operations.

    bd-62: Controls the priority order for file operation backends.
    """

    ELIXIR_FIRST = "elixir_first"  # Try Elixir, fall back to Rust/Python
    RUST_FIRST = "rust_first"  # Try Rust, fall back to Elixir/Python (default)
    PYTHON_ONLY = "python_only"  # Only use Python fallbacks


class NativeBackend:
    """Unified interface for native acceleration capabilities.

    This class provides a single entry point for all native acceleration,
    with automatic fallback to Python implementations when native modules
    are unavailable.

    Example:
        # Check what's available
        status = NativeBackend.get_status()

        # Use file operations (auto-fallback to Python)
        files = await NativeBackend.list_files(".")
        matches = await NativeBackend.grep("def ", "src")
        content = await NativeBackend.read_file("main.py")

        # Use message core
        serialized = NativeBackend.serialize_messages(messages)

        # Use parsing (stub for now)
        ast = NativeBackend.parse_file("main.py", "python")
    """

    # Capability categories
    class Capabilities:
        """Capability names as constants."""

        MESSAGE_CORE = "message_core"  # code_puppy_core
        FILE_OPS = "file_ops"  # turbo_ops
        REPO_INDEX = "repo_index"  # turbo_ops indexer
        PARSE = "parse"  # turbo_parse

    # Internal cache for turbo_ops imports (lazy loaded)
    _turbo_ops_imports: dict[str, Any] | None = None
    _turbo_parse_imports: dict[str, Any] | None = None

    # bd-62: Backend preference for routing decisions
    _backend_preference: BackendPreference = BackendPreference.RUST_FIRST

    # -------------------------------------------------------------------------
    # Elixir Bridge Integration (bd-62)
    # -------------------------------------------------------------------------

    @classmethod
    def _is_elixir_available(cls) -> bool:
        """Check if Elixir control plane is connected and available.

        Returns:
            True if Elixir control plane can be used for file operations.
        """
        try:
            from code_puppy.plugins.elixir_bridge import is_connected

            return is_connected()
        except ImportError:
            return False

    @classmethod
    def _call_elixir(cls, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make JSON-RPC call to Elixir control plane.

        Args:
            method: JSON-RPC method name (e.g., "file_list")
            params: Method parameters dict

        Returns:
            Response dict from Elixir

        Raises:
            ConnectionError: If Elixir is not connected
            Exception: If the call fails
        """
        from code_puppy.plugins.elixir_bridge import call_method

        return call_method(method, params)

    @classmethod
    def set_backend_preference(cls, preference: str | BackendPreference) -> None:
        """Set the backend preference for file operations.

        bd-62: Controls the priority order for routing file operations.

        Args:
            preference: One of "elixir_first", "rust_first", or "python_only"

        Example:
            NativeBackend.set_backend_preference("elixir_first")
            # Now Elixir will be tried first, with Rust/Python fallback
        """
        if isinstance(preference, str):
            cls._backend_preference = BackendPreference(preference)
        else:
            cls._backend_preference = preference

    @classmethod
    def get_backend_preference(cls) -> BackendPreference:
        """Get the current backend preference.

        Returns:
            Current BackendPreference value.
        """
        return cls._backend_preference

    @classmethod
    def _should_use_elixir(cls, capability: str) -> bool:
        """Determine if Elixir should be used for a capability.

        bd-62: Routing logic based on backend preference and availability.

        Args:
            capability: Capability name (e.g., "file_ops")

        Returns:
            True if Elixir should be tried for this capability.
        """
        if cls._backend_preference == BackendPreference.PYTHON_ONLY:
            return False

        if cls._backend_preference == BackendPreference.ELIXIR_FIRST:
            return cls._is_elixir_available()

        # RUST_FIRST: only use Elixir if Rust is unavailable
        if not cls.is_available(capability):
            return cls._is_elixir_available()

        return False

    # -------------------------------------------------------------------------
    # Native Module Loading
    # -------------------------------------------------------------------------

    @classmethod
    def _get_turbo_ops(cls) -> dict[str, Any]:
        """Lazy-load turbo_ops imports with fallback handling."""
        if cls._turbo_ops_imports is None:
            imports: dict[str, Any] = {
                "available": False,
                "list_files": None,
                "grep": None,
                "read_file": None,
                "index_directory": None,
                "FileSummary": None,
            }
            try:
                from turbo_ops import list_files, grep, read_file

                imports["list_files"] = list_files
                imports["grep"] = grep
                imports["read_file"] = read_file
                imports["available"] = True

                # Also try to load indexer components
                try:
                    from turbo_ops import index_directory, FileSummary

                    imports["index_directory"] = index_directory
                    imports["FileSummary"] = FileSummary
                except (ImportError, SystemError):
                    logger.debug("turbo_ops indexer not available")

            except (ImportError, SystemError):
                logger.debug("turbo_ops not available, will use Python fallbacks")

            cls._turbo_ops_imports = imports

        return cls._turbo_ops_imports

    @classmethod
    def _get_turbo_parse(cls) -> dict[str, Any]:
        """Lazy-load turbo_parse imports with fallback handling."""
        if cls._turbo_parse_imports is None:
            imports: dict[str, Any] = {"available": False, "parse_file": None, "parse_source": None, "extract_symbols": None}
            try:
                from turbo_parse import parse_file, parse_source, extract_symbols

                imports["parse_file"] = parse_file
                imports["parse_source"] = parse_source
                imports["extract_symbols"] = extract_symbols
                imports["available"] = True
            except (ImportError, SystemError):
                logger.debug("turbo_parse not available, will use Python fallbacks")

            cls._turbo_parse_imports = imports

        return cls._turbo_parse_imports

    @classmethod
    def get_status(cls) -> dict[str, CapabilityInfo]:
        """Return status of all capabilities.

        Returns:
            Dict mapping capability names to CapabilityInfo objects.
        """
        config = get_acceleration_config()

        # Import bridge modules to check their status
        from code_puppy._core_bridge import RUST_AVAILABLE, is_rust_enabled
        from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE, is_turbo_parse_enabled

        turbo_ops = cls._get_turbo_ops()
        turbo_parse = cls._get_turbo_parse()

        # bd-62: Check Elixir availability
        elixir_available = cls._is_elixir_available()

        # Determine file_ops source based on availability and preference
        file_ops_available = turbo_ops["available"] or elixir_available
        file_ops_active = turbo_ops["available"] or elixir_available

        return {
            cls.Capabilities.MESSAGE_CORE: CapabilityInfo(
                name=cls.Capabilities.MESSAGE_CORE,
                configured=config.get("puppy_core", "python"),
                available=RUST_AVAILABLE,
                active=RUST_AVAILABLE and is_rust_enabled(),
                status="active" if (RUST_AVAILABLE and is_rust_enabled()) else "disabled",
            ),
            cls.Capabilities.FILE_OPS: CapabilityInfo(
                name=cls.Capabilities.FILE_OPS,
                configured=config.get("turbo_ops", "python"),
                available=file_ops_available,
                active=file_ops_active,
                status="active" if file_ops_active else "unavailable",
            ),
            cls.Capabilities.REPO_INDEX: CapabilityInfo(
                name=cls.Capabilities.REPO_INDEX,
                configured=config.get("turbo_ops", "python"),
                available=turbo_ops["available"] and turbo_ops.get("index_directory") is not None,
                active=turbo_ops["available"] and turbo_ops.get("index_directory") is not None,
                status=(
                    "active"
                    if turbo_ops["available"] and turbo_ops.get("index_directory") is not None
                    else "unavailable"
                ),
            ),
            cls.Capabilities.PARSE: CapabilityInfo(
                name=cls.Capabilities.PARSE,
                configured=config.get("turbo_parse", "python"),
                available=TURBO_PARSE_AVAILABLE,
                active=turbo_parse.get("available", False) and is_turbo_parse_enabled(),
                status="active" if (turbo_parse.get("available", False) and is_turbo_parse_enabled()) else "disabled",
            ),
        }

    @classmethod
    def get_detailed_status(cls) -> dict[str, Any]:
        """Return detailed status including all backend sources.

        bd-62: Extended status with Elixir and backend preference info.

        Returns:
            Dict with detailed capability status and backend info.
        """
        turbo_ops = cls._get_turbo_ops()

        return {
            "message_core": {
                "available": True,  # Python implementation always available
                "rust_available": False,  # Will be set by _core_bridge
                "source": "rust" if False else "python",  # TODO: check _core_bridge
            },
            "file_ops": {
                "available": turbo_ops["available"] or cls._is_elixir_available(),
                "rust_available": turbo_ops["available"],
                "elixir_available": cls._is_elixir_available(),
                "source": cls._get_file_ops_source(),
                "backend_preference": cls._backend_preference.value,
            },
            "repo_index": {
                "available": turbo_ops["available"] and turbo_ops["index_directory"] is not None,
                "rust_available": turbo_ops["available"] and turbo_ops["index_directory"] is not None,
                "source": "turbo_ops" if (turbo_ops["available"] and turbo_ops["index_directory"]) else "python",
            },
            "parse": {
                "available": False,  # Will be set by turbo_parse_bridge
                "rust_available": False,  # TODO: check turbo_parse_bridge
                "source": "turbo_parse" if False else "python",
            },
        }

    @classmethod
    def _get_file_ops_source(cls) -> str:
        """Determine the effective file_ops source based on routing logic.

        bd-62: Returns the actual source that will be used for file operations.

        Returns:
            One of "turbo_ops", "elixir", or "python".
        """
        turbo_ops = cls._get_turbo_ops()

        # Check routing logic
        if cls._backend_preference == BackendPreference.ELIXIR_FIRST:
            if cls._is_elixir_available():
                return "elixir"
            if turbo_ops["available"]:
                return "turbo_ops"
            return "python"

        if cls._backend_preference == BackendPreference.RUST_FIRST:
            if turbo_ops["available"]:
                return "turbo_ops"
            if cls._is_elixir_available():
                return "elixir"
            return "python"

        # PYTHON_ONLY
        return "python"

    @classmethod
    def is_available(cls, capability: str) -> bool:
        """Check if a specific capability is available.

        Args:
            capability: One of the Capability constants.

        Returns:
            True if the capability is available and active.
        """
        status = cls.get_status()
        info = status.get(capability)
        return info.active if info else False

    @classmethod
    def _run_with_fallback(
        cls,
        native_func: Callable | None,
        fallback_func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute native function with fallback to Python on failure.

        Args:
            native_func: The native (Rust) function to try first.
            fallback_func: The Python fallback function.
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            Result from either native or fallback function.
        """
        if native_func is not None:
            try:
                return native_func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Native operation failed, using fallback: {e}")

        return fallback_func(*args, **kwargs)

    @classmethod
    def _async_run_with_fallback(
        cls,
        native_func: Callable | None,
        fallback_func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute native function in thread pool with fallback to async Python.

        Args:
            native_func: The native (Rust) function to try first (runs in thread pool).
            fallback_func: The async Python fallback function.
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            Result from either native or fallback function.
        """
        if native_func is not None:
            try:
                # Run native function in thread pool (Rust functions are usually sync)
                return asyncio.to_thread(native_func, *args, **kwargs)
            except Exception as e:
                logger.debug(f"Native operation failed, using fallback: {e}")

        return fallback_func(*args, **kwargs)

    # -------------------------------------------------------------------------
    # File Operations (from turbo_ops with Python fallbacks)
    # -------------------------------------------------------------------------

    @classmethod
    def list_files(
        cls,
        directory: str = ".",
        recursive: bool = True,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """List files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            directory: Directory to list.
            recursive: Whether to list recursively.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "files" key containing list of file paths,
            or "error" key if listing failed.
        """
        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                result = cls._call_elixir("file_list", {
                    "directory": directory,
                    "recursive": recursive,
                })
                # Normalize Elixir response format
                if result.get("success", True):
                    return {
                        "files": [f.get("path", f) if isinstance(f, dict) else f for f in result.get("files", [])],
                        "count": result.get("file_count", len(result.get("files", []))),
                        "total_size": result.get("total_size", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(f"Elixir file_list returned error: {result.get('error')}")
            except NotImplementedError:
                # Elixir transport not yet implemented, fall through
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir file_list failed, falling back: {e}")

        # Try Rust turbo_ops
        turbo_ops = cls._get_turbo_ops()
        native_func = turbo_ops["list_files"] if (_prefer_native and turbo_ops["available"]) else None

        def _python_fallback(dir_path: str, rec: bool) -> dict[str, Any]:
            """Python fallback using standard library with proper error handling."""
            import os

            dir_path = os.path.abspath(os.path.expanduser(dir_path))

            # Check if directory exists
            if not os.path.exists(dir_path):
                return {"error": f"Directory '{dir_path}' does not exist", "files": [], "count": 0, "source": "python_fallback"}
            if not os.path.isdir(dir_path):
                return {"error": f"'{dir_path}' is not a directory", "files": [], "count": 0, "source": "python_fallback"}

            try:
                files = []
                if rec:
                    for root, _dirs, filenames in os.walk(dir_path):
                        for filename in filenames:
                            full_path = os.path.join(root, filename)
                            rel_path = os.path.relpath(full_path, dir_path)
                            files.append(rel_path)
                else:
                    for entry in os.listdir(dir_path):
                        full_path = os.path.join(dir_path, entry)
                        if os.path.isfile(full_path):
                            files.append(entry)

                return {"files": files, "count": len(files), "source": "python_fallback"}
            except Exception as e:
                return {"error": str(e), "files": [], "count": 0, "source": "python_fallback"}

        if native_func:
            try:
                result = native_func(directory, recursive)
                if isinstance(result, list):
                    return {"files": result, "count": len(result), "source": "turbo_ops"}
                return {**result, "source": "turbo_ops"}
            except Exception as e:
                logger.debug(f"turbo_ops list_files failed: {e}")

        return _python_fallback(directory, recursive)

    @classmethod
    def grep(
        cls,
        pattern: str,
        directory: str = ".",
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Search files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            pattern: Search pattern (regex supported).
            directory: Directory to search in.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "matches" key containing list of match dicts,
            or "error" key if search failed.
        """
        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                result = cls._call_elixir("grep_search", {
                    "search_string": pattern,
                    "directory": directory,
                })
                # Normalize Elixir response format
                if result.get("success", True):
                    matches = result.get("matches", [])
                    return {
                        "matches": matches,
                        "total_matches": len(matches),
                        "files_searched": result.get("files_searched", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(f"Elixir grep_search returned error: {result.get('error')}")
            except NotImplementedError:
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir grep_search failed, falling back: {e}")

        # Try Rust turbo_ops
        turbo_ops = cls._get_turbo_ops()
        native_func = turbo_ops["grep"] if (_prefer_native and turbo_ops["available"]) else None

        def _python_fallback(pat: str, dir_path: str) -> dict[str, Any]:
            """Python fallback using re module."""
            import os
            import re

            matches = []
            try:
                regex = re.compile(pat)
                for root, _dirs, files in os.walk(dir_path):
                    for filename in files:
                        if filename.endswith(('.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.rs', '.go', '.rb')):
                            filepath = os.path.join(root, filename)
                            try:
                                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                    for line_num, line in enumerate(f, 1):
                                        if regex.search(line):
                                            matches.append({
                                                "file_path": filepath,
                                                "line_number": line_num,
                                                "line_content": line.strip()[:200],  # Limit line length
                                            })
                            except Exception:
                                continue

                return {"matches": matches, "total_matches": len(matches), "source": "python_fallback"}
            except Exception as e:
                return {"error": str(e), "matches": [], "total_matches": 0, "source": "python_fallback"}

        if native_func:
            try:
                result = native_func(pattern, directory)
                if isinstance(result, dict):
                    return {**result, "source": "turbo_ops"}
                return {"matches": result, "total_matches": len(result) if isinstance(result, list) else 0, "source": "turbo_ops"}
            except Exception as e:
                logger.debug(f"turbo_ops grep failed: {e}")

        return _python_fallback(pattern, directory)

    @classmethod
    def read_file(
        cls,
        path: str,
        start_line: int | None = None,
        num_lines: int | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Read file with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            path: Path to file.
            start_line: Optional 1-based starting line number.
            num_lines: Optional number of lines to read.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "content" key containing file content,
            "num_tokens" with token estimate, or "error" key if read failed.
        """
        import os

        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                params: dict[str, Any] = {"path": path}
                if start_line is not None:
                    params["start_line"] = start_line
                if num_lines is not None:
                    params["num_lines"] = num_lines

                result = cls._call_elixir("file_read", params)
                # Normalize Elixir response format
                if result.get("success", True):
                    content = result.get("content", "")
                    return {
                        "content": content,
                        "num_tokens": len(content) // 4,  # Rough estimate
                        "total_lines": result.get("total_lines", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(f"Elixir file_read returned error: {result.get('error')}")
            except NotImplementedError:
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir file_read failed, falling back: {e}")

        # Try Rust turbo_ops
        turbo_ops = cls._get_turbo_ops()
        native_func = turbo_ops["read_file"] if (_prefer_native and turbo_ops["available"]) else None

        def _python_fallback(
            file_path: str, start: int | None, num: int | None
        ) -> dict[str, Any]:
            """Python fallback using standard file operations."""
            try:
                file_path = os.path.abspath(os.path.expanduser(file_path))

                if not os.path.exists(file_path):
                    return {"error": f"File not found: {file_path}", "content": None, "num_tokens": 0, "source": "python_fallback"}

                with open(file_path, 'r', encoding='utf-8', errors='surrogateescape') as f:
                    if start is not None and num is not None:
                        import itertools

                        start_idx = start - 1
                        lines = list(itertools.islice(f, start_idx, start_idx + num))
                        content = ''.join(lines)
                    else:
                        content = f.read()

                # Estimate tokens (rough approximation: 4 chars ≈ 1 token)
                num_tokens = len(content) // 4

                return {"content": content, "num_tokens": num_tokens, "source": "python_fallback"}
            except Exception as e:
                return {"error": str(e), "content": None, "num_tokens": 0, "source": "python_fallback"}

        if native_func:
            try:
                # Convert 0/None to proper None for Rust
                start = start_line if start_line and start_line > 0 else None
                num = num_lines if num_lines and num_lines > 0 else None
                result = native_func(path, start, num)
                if isinstance(result, dict):
                    return {**result, "source": "turbo_ops"}
                return {"content": result, "num_tokens": len(result) // 4, "source": "turbo_ops"}
            except Exception as e:
                logger.debug(f"turbo_ops read_file failed: {e}")

        return _python_fallback(path, start_line, num_lines)

    @classmethod
    def read_files(
        cls,
        paths: list[str],
        start_line: int | None = None,
        num_lines: int | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Batch read files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            paths: List of file paths to read.
            start_line: Optional 1-based starting line number (applied to all files).
            num_lines: Optional number of lines to read (applied to all files).
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "files" key containing list of file result dicts,
            each with "file_path", "content", "num_tokens", "error", "success" keys.
        """
        # bd-62: Try Elixir batch read if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                params: dict[str, Any] = {"paths": paths}
                if start_line is not None:
                    params["start_line"] = start_line
                if num_lines is not None:
                    params["num_lines"] = num_lines

                result = cls._call_elixir("file_read_batch", params)
                # Normalize Elixir response format
                if result.get("success", True):
                    files = result.get("files", [])
                    return {
                        "files": files,
                        "total_files": len(paths),
                        "successful_reads": sum(1 for f in files if f.get("success", False)),
                        "source": "elixir",
                    }
                else:
                    logger.debug(f"Elixir file_read_batch returned error: {result.get('error')}")
            except NotImplementedError:
                logger.debug("Elixir transport not implemented, falling back to sequential")
            except Exception as e:
                logger.debug(f"Elixir file_read_batch failed, falling back: {e}")

        # Fall back to sequential reads (Rust or Python per file)
        results = []
        for path in paths:
            result = cls.read_file(path, start_line, num_lines, _prefer_native=_prefer_native)
            results.append({
                "file_path": path,
                "content": result.get("content"),
                "num_tokens": result.get("num_tokens", 0),
                "error": result.get("error"),
                "success": result.get("error") is None and result.get("content") is not None,
            })

        return {
            "files": results,
            "total_files": len(paths),
            "successful_reads": sum(1 for r in results if r["success"]),
            "source": "native_backend",
        }

    # -------------------------------------------------------------------------
    # Message Core (from code_puppy_core)
    # -------------------------------------------------------------------------

    @classmethod
    def serialize_messages(cls, messages: list) -> list[dict]:
        """Serialize messages for API calls.

        This delegates to _core_bridge for the actual serialization,
        which handles pydantic-ai message objects.

        Args:
            messages: List of pydantic-ai ModelMessage objects.

        Returns:
            List of serialized message dicts.
        """
        from code_puppy._core_bridge import serialize_messages_for_rust

        return serialize_messages_for_rust(messages)

    @classmethod
    def create_message_batch(cls, messages: list) -> Any:
        """Create a MessageBatchHandle for efficient batch operations.

        Args:
            messages: List of pydantic-ai ModelMessage objects.

        Returns:
            MessageBatchHandle for batch operations.
        """
        from code_puppy._core_bridge import MessageBatchHandle

        return MessageBatchHandle(messages)

    # -------------------------------------------------------------------------
    # Repository Index (from turbo_ops indexer)
    # -------------------------------------------------------------------------

    @classmethod
    def index_directory(
        cls,
        root: str,
        max_files: int = 40,
        max_symbols_per_file: int = 8,
        *,
        _prefer_native: bool = True,
    ) -> list[dict[str, Any]]:
        """Index directory for repository structure.

        Args:
            root: Root directory to index.
            max_files: Maximum number of files to include.
            max_symbols_per_file: Maximum symbols to extract per file.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            List of file summary dicts with "path", "kind", "symbols" keys.
        """
        turbo_ops = cls._get_turbo_ops()
        native_index = turbo_ops.get("index_directory") if (_prefer_native and turbo_ops["available"]) else None

        if native_index:
            try:
                rust_results = native_index(root, max_files, max_symbols_per_file, [])
                return [
                    {
                        "path": getattr(r, "path", str(r)),
                        "kind": getattr(r, "kind", "unknown"),
                        "symbols": list(getattr(r, "symbols", [])),
                    }
                    for r in rust_results
                ]
            except Exception as e:
                logger.debug(f"turbo_ops index_directory failed: {e}")

        # Fallback to Python indexer from repo_compass
        try:
            from pathlib import Path

            from code_puppy.plugins.repo_compass.indexer import (
                build_structure_map as python_build_structure_map,
            )

            py_results = python_build_structure_map(Path(root), max_files, max_symbols_per_file)
            return [
                {
                    "path": r.path,
                    "kind": r.kind,
                    "symbols": list(r.symbols),
                }
                for r in py_results
            ]
        except Exception as e:
            logger.warning(f"Python fallback index_directory failed: {e}")
            return []

    # -------------------------------------------------------------------------
    # Parse (from turbo_parse) — can be stubbed for now
    # -------------------------------------------------------------------------

    @classmethod
    def parse_file(
        cls,
        path: str,
        language: str | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Parse file for symbols/AST.

        Args:
            path: Path to file to parse.
            language: Optional language hint (auto-detected if None).
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with parse results or error.
        """
        turbo_parse = cls._get_turbo_parse()
        native_func = turbo_parse["parse_file"] if (_prefer_native and turbo_parse["available"]) else None

        if native_func:
            try:
                return native_func(path, language)
            except Exception as e:
                logger.debug(f"turbo_parse parse_file failed: {e}")

        # Fallback to Python (simplified)
        return {
            "success": False,
            "error": "turbo_parse not available",
            "tree": None,
            "language": language or "unknown",
        }

    @classmethod
    def parse_source(
        cls,
        source: str,
        language: str,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Parse source code for symbols/AST.

        Args:
            source: Source code string to parse.
            language: Language identifier.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with parse results or error.
        """
        turbo_parse = cls._get_turbo_parse()
        native_func = turbo_parse["parse_source"] if (_prefer_native and turbo_parse["available"]) else None

        if native_func:
            try:
                return native_func(source, language)
            except Exception as e:
                logger.debug(f"turbo_parse parse_source failed: {e}")

        # Fallback to Python (simplified)
        return {
            "success": False,
            "error": "turbo_parse not available",
            "tree": None,
            "language": language,
        }

    @classmethod
    def is_language_supported(cls, language: str) -> bool:
        """Check if a language is supported for parsing.

        Args:
            language: Language identifier to check.

        Returns:
            True if the language is supported.
        """
        turbo_parse = cls._get_turbo_parse()

        if turbo_parse["available"]:
            try:
                from turbo_parse import is_language_supported as turbo_is_supported

                return turbo_is_supported(language)
            except Exception:
                pass

        # Basic fallback for common languages
        supported = {"python", "javascript", "typescript", "rust", "go", "c", "cpp", "java", "ruby"}
        return language.lower() in supported


# Convenience module-level functions for direct import
def get_backend_status() -> dict[str, CapabilityInfo]:
    """Get status of all native backend capabilities."""
    return NativeBackend.get_status()


def is_capability_available(capability: str) -> bool:
    """Check if a specific capability is available."""
    return NativeBackend.is_available(capability)


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files (convenience function)."""
    return NativeBackend.list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files (convenience function)."""
    return NativeBackend.grep(pattern, directory)


def read_file(path: str, start_line: int | None = None, num_lines: int | None = None) -> dict[str, Any]:
    """Read file (convenience function)."""
    return NativeBackend.read_file(path, start_line, num_lines)


def read_files(
    paths: list[str], start_line: int | None = None, num_lines: int | None = None
) -> dict[str, Any]:
    """Batch read files (convenience function)."""
    return NativeBackend.read_files(paths, start_line, num_lines)


def serialize_messages(messages: list) -> list[dict]:
    """Serialize messages (convenience function)."""
    return NativeBackend.serialize_messages(messages)


def parse_file(path: str, language: str | None = None) -> dict[str, Any]:
    """Parse file (convenience function)."""
    return NativeBackend.parse_file(path, language)


def index_directory(
    root: str, max_files: int = 40, max_symbols_per_file: int = 8
) -> list[dict[str, Any]]:
    """Index directory (convenience function)."""
    return NativeBackend.index_directory(root, max_files, max_symbols_per_file)


__all__ = [
    # Main class
    "NativeBackend",
    "CapabilityInfo",
    "BackendPreference",
    # Status functions
    "get_backend_status",
    "is_capability_available",
    # File operations
    "list_files",
    "grep",
    "read_file",
    "read_files",
    # Message operations
    "serialize_messages",
    # Parse operations
    "parse_file",
    # Index operations
    "index_directory",
]
