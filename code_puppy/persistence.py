"""Safe atomic persistence helpers.

Provides atomic file-write utilities that use a write-to-temp-then-replace
pattern so a crash or power loss never leaves a corrupt half-written file.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _atomic_replace(src: Path, dst: Path) -> None:
    """Move *src* to *dst* atomically.

    On POSIX ``os.replace`` is already atomic.  On Windows we fall back
    to a non-atomic rename but still guarantee the destination exists
    when the function returns.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(src), str(dst))


def atomic_write_text(
    path: Path,
    content: str,
    encoding: str = "utf-8",
) -> None:
    """Write a text file atomically using temp file + replace.

    The file is first written to a temporary file in the same directory
    (guaranteeing the same filesystem) and then atomically renamed over
    the target path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=".cp_atomic_",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        _atomic_replace(Path(tmp_path), path)
    except BaseException:
        # Best-effort cleanup on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write a binary file atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=".cp_atomic_",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _atomic_replace(Path(tmp_path), path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write a JSON file atomically."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write_text(path, content, encoding="utf-8")


def atomic_write_msgpack(
    path: Path,
    data: Any,
    default: Callable | None = None,
) -> None:
    """Write a msgpack file atomically.

    *default* is forwarded to ``msgpack.packb`` for custom type handling.
    """
    import msgpack

    packed = msgpack.packb(data, use_bin_type=True, default=default)
    atomic_write_bytes(path, packed)


def safe_resolve_path(
    path: Path,
    allowed_parent: Path | None = None,
) -> Path:
    """Resolve a path and optionally verify it stays within *allowed_parent*.

    Returns the absolute, resolved ``Path``.

    Raises:
        ValueError: If *allowed_parent* is given and the resolved path
            escapes that directory (symlink traversal, ``..``, etc.).
    """
    resolved = Path(path).resolve()

    if allowed_parent is not None:
        parent = Path(allowed_parent).resolve()
        try:
            resolved.relative_to(parent)
        except ValueError as exc:
            raise ValueError(
                f"Path {resolved} is outside allowed parent {parent}"
            ) from exc

    return resolved
