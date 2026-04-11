"""Sessions API endpoints for retrieving subagent session data."""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")


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
    if not _VALID_SESSION_ID_RE.match(session_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid session_id: must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$",
        )
    return session_id


# Thread pool for blocking file I/O
_executor = ThreadPoolExecutor(max_workers=2)

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


class MessageContent(BaseModel):
    """Message content with role and optional timestamp."""

    role: str
    content: Any
    timestamp: str | None = None


class SessionDetail(SessionInfo):
    """Session info with full message history."""

    messages: list[dict[str, Any]] = []


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
async def list_sessions() -> list[SessionInfo]:
    """List all available sessions.

    Returns:
        List of SessionInfo objects for each session found
    """
    sessions_dir = _get_sessions_dir()
    if not sessions_dir.exists():
        return []

    loop = asyncio.get_running_loop()
    sessions = []

    for txt_file in sessions_dir.glob("*.txt"):
        session_id = txt_file.stem
        try:
            # Run blocking I/O in thread pool with timeout
            metadata = await asyncio.wait_for(
                loop.run_in_executor(_executor, _load_json_sync, txt_file),
                timeout=FILE_IO_TIMEOUT,
            )
            sessions.append(
                SessionInfo(
                    session_id=session_id,
                    agent_name=metadata.get("agent_name"),
                    initial_prompt=metadata.get("initial_prompt"),
                    created_at=metadata.get("created_at"),
                    last_updated=metadata.get("last_updated"),
                    message_count=metadata.get("message_count", 0),
                )
            )
        except asyncio.TimeoutError:
            # Timed out reading file, include basic info
            sessions.append(SessionInfo(session_id=session_id))
        except Exception:
            # If we can't parse metadata, still include basic session info
            sessions.append(SessionInfo(session_id=session_id))

    return sessions


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
async def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Get the full message history for a session.

    Args:
        session_id: The session identifier

    Returns:
        List of serialized message dictionaries

    Raises:
        HTTPException: 404 if session messages not found, 500 on load error, 504 on timeout
    """
    session_id = _validate_session_id(session_id)
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
        return [_serialize_message(msg) for msg in messages]
    except asyncio.TimeoutError:
        raise HTTPException(
            504, f"Timeout loading session '{session_id}' messages"
        ) from None
    except Exception as e:
        raise HTTPException(500, f"Error loading session messages: {e}") from e


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a session and its data.

    Args:
        session_id: The session identifier

    Returns:
        Success message dict

    Raises:
        HTTPException: 404 if session not found
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
