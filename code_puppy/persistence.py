"""Safe atomic persistence helpers for file operations.

This module provides atomic file write operations to prevent partial/corrupt
files on crash or interruption. All writes use temp-file + atomic replace.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Callable

import msgpack

logger = logging.getLogger(__name__)


def safe_resolve_path(path: Path, allowed_parent: Path | None = None) -> Path:
    """Resolve path to absolute and optionally verify it's within allowed_parent.

    Args:
        path: The path to resolve
        allowed_parent: Optional parent directory that path must be within

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path resolves outside allowed_parent
        OSError: If path resolution fails
    """
    try:
        resolved = path.absolute()
    except (OSError, RuntimeError) as e:
        raise OSError(f"Failed to resolve path {path}: {e}") from e

    if allowed_parent is not None:
        try:
            resolved.relative_to(allowed_parent.absolute())
        except ValueError:
            raise ValueError(
                f"Path {resolved} is outside allowed parent {allowed_parent}"
            )

    return resolved


def _atomic_replace(tmp_path: Path, target_path: Path) -> None:
    """Atomically replace target with tmp file.

    Handles cross-platform differences in atomic rename.
    """
    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # On Windows, replace may fail if target is open; we accept that risk
    # On Unix, this is truly atomic
    tmp_path.replace(target_path)


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text file atomically using temp file + replace.

    Args:
        path: Target file path
        content: Text content to write
        encoding: Text encoding (default: utf-8)

    Raises:
        OSError: If write fails
    """
    path = safe_resolve_path(path)

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory for atomic move
    fd = None
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        tmp_path = Path(tmp_name)

        with open(fd, "w", encoding=encoding) as f:
            f.write(content)

        _atomic_replace(tmp_path, path)

    except Exception:
        # Clean up temp file on any error
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write binary file atomically using temp file + replace.

    Args:
        path: Target file path
        data: Binary data to write

    Raises:
        OSError: If write fails
    """
    path = safe_resolve_path(path)

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = None
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        tmp_path = Path(tmp_name)

        with open(fd, "wb") as f:
            f.write(data)

        _atomic_replace(tmp_path, path)

    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise


def atomic_write_json(
    path: Path, data: Any, indent: int = 2, default: Callable[[Any], Any] | None = None
) -> None:
    """Write JSON file atomically.

    Args:
        path: Target file path
        data: JSON-serializable data
        indent: JSON indentation (default: 2)
        default: Optional JSON serializer for custom types

    Raises:
        OSError: If write fails
        TypeError: If data is not JSON-serializable
    """
    try:
        content = json.dumps(data, indent=indent, default=default)
    except (TypeError, ValueError) as e:
        raise TypeError(f"Data is not JSON-serializable: {e}") from e

    atomic_write_text(path, content)


def atomic_write_msgpack(
    path: Path, data: Any, default: Callable[[Any], Any] | None = None
) -> None:
    """Write msgpack file atomically.

    Args:
        path: Target file path
        data: msgpack-serializable data
        default: Optional serializer for custom types

    Raises:
        OSError: If write fails
        TypeError: If data is not msgpack-serializable
    """
    try:
        packed = msgpack.packb(data, use_bin_type=True, default=default)
    except (TypeError, ValueError) as e:
        raise TypeError(f"Data is not msgpack-serializable: {e}") from e

    atomic_write_bytes(path, packed)


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON file safely.

    Args:
        path: File path to read
        default: Value to return if file doesn't exist or is invalid

    Returns:
        Parsed JSON data or default value
    """
    path = safe_resolve_path(path)

    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning(f"Failed to read JSON from {path}: {e}")
        return default


def read_msgpack(path: Path, default: Any = None) -> Any:
    """Read msgpack file safely.

    Args:
        path: File path to read
        default: Value to return if file doesn't exist or is invalid

    Returns:
        Parsed msgpack data or default value
    """
    path = safe_resolve_path(path)

    if not path.exists():
        return default

    try:
        raw = path.read_bytes()
        return msgpack.unpackb(raw, raw=False)
    except (msgpack.ExtraData, msgpack.OutOfData, OSError, ValueError) as e:
        logger.warning(f"Failed to read msgpack from {path}: {e}")
        return default
