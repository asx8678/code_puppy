"""Sessions API endpoints for retrieving subagent session data."""

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from code_puppy.api.schemas import PaginatedResponse
from code_puppy.api.security import require_api_access

logger = logging.getLogger(__name__)

VALID_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")


def _validate_session_id(session_id: str) -> str:
    """Validate session_id to prevent path traversal attacks.

    Allows: alphanumeric characters, hyphens, underscores.
    Must start with an alphanumeric character.
    Max length: 128 characters.

    Args:
        session_id: The session identifier to validate

    Returns:
        The validated session_id (unchanged).

    Raises:
        HTTPException: 400 if session_id is invalid.
    """
    if not VALID_SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid session_id: must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$",
        )
    return session_id


def _get_max_workers() -> int:
    """Get max workers for session I/O, configurable via env var.

    Returns:
        Number of workers for ThreadPoolExecutor (1-32 range)
    """
    env_val = os.getenv("PUP_SESSION_WORKERS")
    if env_val:
        try:
            return max(1, min(32, int(env_val)))
        except ValueError:
            pass
    # Default: scale with CPU count, minimum 4
    return max(4, min(16, (os.cpu_count() or 4) + 2))


# Thread pool for blocking file I/O (configurable worker count)
_executor = ThreadPoolExecutor(max_workers=_get_max_workers())

# Timeout for file operations (seconds)
FILE_IO_TIMEOUT = 10.0

router = APIRouter()


class SessionInfo(BaseModel):
    """Session metadata information."""

    session_id: str
    agent_name: str | None = None
    initial_prompt: str | None = None
    created_at: str | None = None
    last_updated: str | None = None
    message_count: int = 0


def _get_sessions_dir() -> Path:
    """Get the subagent sessions directory.

    Returns:
        Path to the subagent sessions directory
    """
    from code_puppy.config import DATA_DIR

    return Path(DATA_DIR) / "subagent_sessions"


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a pydantic-ai message to a JSON-safe dict.

    Handles various pydantic-ai message types that may be stored
    in the pickle files.

    Args:
        msg: A pydantic-ai message object

    Returns:
        JSON-serializable dictionary representation of the message
    """
    # Handle pydantic v2 models with model_dump
    if hasattr(msg, "model_dump"):
        return msg.model_dump(mode="json")
    # Handle objects with __dict__ (convert values to strings for safety)
    elif hasattr(msg, "__dict__"):
        return {k: str(v) for k, v in msg.__dict__.items()}
    # Fallback: wrap in a content dict
    else:
        return {"content": str(msg)}


def _load_json_sync(file_path: Path) -> dict:
    """Synchronous JSON file load (for use in executor)."""
    with open(file_path, "r") as f:
        return json.load(f)


async def _load_all_session_metadata() -> list["SessionInfo"]:
    """Load metadata for all sessions efficiently.

    Uses parallel loading with increased concurrency to handle
    large numbers of sessions.

    Returns:
        List of SessionInfo objects for all valid sessions
    """
    sessions_dir = _get_sessions_dir()
    if not sessions_dir.exists():
        return []

    # Find all .txt metadata files
    metadata_files = list(sessions_dir.glob("*.txt"))

    if not metadata_files:
        return []

    # Load in parallel with increased concurrency
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=_get_max_workers()) as executor:
        tasks = [
            loop.run_in_executor(executor, _load_session_metadata_sync, f)
            for f in metadata_files
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out failures and None results
    sessions = []
    for result in results:
        if isinstance(result, SessionInfo):
            sessions.append(result)

    return sessions


def _load_session_metadata_sync(txt_file: Path) -> "SessionInfo | None":
    """Synchronous metadata load for a single session.

    Args:
        txt_file: Path to the metadata .txt file

    Returns:
        SessionInfo if valid, None if invalid or error
    """
    session_id = txt_file.stem

    # Validate session_id to skip files with invalid names
    if not VALID_SESSION_ID_PATTERN.match(session_id):
        return None

    try:
        with open(txt_file, "r") as f:
            metadata = json.load(f)

        return SessionInfo(
            session_id=session_id,
            agent_name=metadata.get("agent_name"),
            initial_prompt=metadata.get("initial_prompt"),
            created_at=metadata.get("created_at"),
            last_updated=metadata.get("last_updated"),
            message_count=metadata.get("message_count", 0),
        )
    except Exception:
        # If we can't parse metadata, still include basic session info
        return SessionInfo(session_id=session_id)


def _load_session_sync(file_path: Path) -> Any:
    """Synchronous session load.

    Delegates to :func:`code_puppy.session_storage._load_raw_bytes` so that
    the API loader stays in sync with the on-disk format actually written by
    :func:`session_storage.save_session`. That format is
    ``JSONV\\x01\\x00\\x00 + HMAC + JSON`` stored in the ``.pkl`` file itself —
    not a ``.msgpack`` sidecar. The previous implementation only looked at a
    sidecar that save_session never creates, so freshly-saved sessions
    appeared as "legacy pickle" and failed to load.
    """
    from code_puppy.session_storage import (
        _JSON_MAGIC,
        _LEGACY_MSGPACK_MAGIC,
        _LEGACY_SIGNED_HEADER,
        _load_raw_bytes,
        _parse_session_payload,
    )

    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    raw = file_path.read_bytes()

    # Accept current JSON format or legacy msgpack format for backward compatibility.
    # Reject legacy pickle formats for RCE safety.
    if not (
        raw.startswith(_JSON_MAGIC)
        or raw.startswith(_LEGACY_MSGPACK_MAGIC)
        or raw.startswith(_LEGACY_SIGNED_HEADER)
    ):
        # Probably a raw pickle file from a pre-migration install. Be
        # explicit about why we won't load it.
        raise ValueError(
            "Session file is not in the expected JSON+HMAC format. "
            "Legacy pickle sessions are no longer supported (RCE risk)."
        )

    data = _load_raw_bytes(raw)
    messages, _ = _parse_session_payload(data)
    return messages


@router.get("/")
async def list_sessions(
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
    limit: int = Query(50, ge=1, le=200, description="Max sessions to return"),
    sort_by: str = Query(
        "last_updated", pattern="^(last_updated|created_at|session_id)$"
    ),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> PaginatedResponse[SessionInfo]:
    """List all sessions with pagination.

    Args:
        offset: Number of sessions to skip (0-indexed)
        limit: Maximum number of sessions to return (1-200)
        sort_by: Field to sort by (last_updated, created_at, session_id)
        order: Sort order (asc or desc)

    Returns:
        PaginatedResponse containing the session list and pagination metadata
    """
    # Load all session metadata (we need total count)
    all_sessions = await _load_all_session_metadata()

    # Sort
    reverse = order == "desc"
    all_sessions.sort(key=lambda s: getattr(s, sort_by, "") or "", reverse=reverse)

    # Paginate
    total = len(all_sessions)
    paginated = all_sessions[offset : offset + limit]

    return PaginatedResponse(
        items=paginated,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(paginated) < total,
    )


@router.get("/{session_id}")
async def get_session(session_id: str) -> SessionInfo:
    """Get session metadata.

    Args:
        session_id: The session identifier

    Returns:
        SessionInfo with metadata for the specified session

    Raises:
        HTTPException: 404 if session not found, 504 on timeout
    """
    session_id = _validate_session_id(session_id)
    sessions_dir = _get_sessions_dir()
    txt_file = sessions_dir / f"{session_id}.txt"

    if not txt_file.exists():
        raise HTTPException(404, f"Session '{session_id}' not found")

    loop = asyncio.get_running_loop()

    try:
        metadata = await asyncio.wait_for(
            loop.run_in_executor(_executor, _load_json_sync, txt_file),
            timeout=FILE_IO_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, f"Timeout reading session '{session_id}'") from None

    return SessionInfo(
        session_id=session_id,
        agent_name=metadata.get("agent_name"),
        initial_prompt=metadata.get("initial_prompt"),
        created_at=metadata.get("created_at"),
        last_updated=metadata.get("last_updated"),
        message_count=metadata.get("message_count", 0),
    )


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max messages to return"),
) -> PaginatedResponse[dict[str, Any]]:
    """Get messages for a session with pagination.

    Args:
        session_id: The session identifier
        offset: Number of messages to skip (0-indexed)
        limit: Maximum number of messages to return (1-500)

    Returns:
        PaginatedResponse containing the message list and pagination metadata

    Raises:
        HTTPException: 400 if session_id is invalid, 404 if session not found,
                     504 on timeout, 500 on load error
    """
    # Validate session_id
    if not VALID_SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    sessions_dir = _get_sessions_dir()
    pkl_file = sessions_dir / f"{session_id}.pkl"

    if not pkl_file.exists():
        raise HTTPException(404, f"Session '{session_id}' messages not found")

    loop = asyncio.get_running_loop()

    try:
        messages = await asyncio.wait_for(
            loop.run_in_executor(_executor, _load_session_sync, pkl_file),
            timeout=FILE_IO_TIMEOUT,
        )

        # Paginate
        total = len(messages)
        paginated = messages[offset : offset + limit]

        return PaginatedResponse(
            items=[_serialize_message(msg) for msg in paginated],
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(paginated) < total,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            504, f"Timeout loading session '{session_id}' messages"
        ) from None
    except Exception as e:
        logger.error("Error loading session '%s' messages: %s", session_id, e)
        raise HTTPException(500, "Error loading session messages") from e


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    _auth: None = Depends(require_api_access),
) -> dict[str, str]:
    """Delete a session and its data.

    Requires authentication for non-loopback clients or when
    CODE_PUPPY_REQUIRE_TOKEN is set.

    Args:
        session_id: The session identifier.
        _auth: Authentication dependency (injected, not used directly).

    Returns:
        dict[str, str]: Success message.

    Raises:
        HTTPException: 404 if session not found.
    """
    session_id = _validate_session_id(session_id)
    sessions_dir = _get_sessions_dir()
    txt_file = sessions_dir / f"{session_id}.txt"
    pkl_file = sessions_dir / f"{session_id}.pkl"

    if not txt_file.exists() and not pkl_file.exists():
        raise HTTPException(404, f"Session '{session_id}' not found")

    if txt_file.exists():
        txt_file.unlink()
    if pkl_file.exists():
        pkl_file.unlink()

    return {"message": f"Session '{session_id}' deleted"}
