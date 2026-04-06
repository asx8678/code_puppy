"""Shared helpers for persisting and restoring chat sessions.

This module centralises the msgpack + metadata handling that used to live in
both the CLI command handler and the auto-save feature. Keeping it here helps
us avoid duplication while staying inside the Zen-of-Python sweet spot: simple
is better than complex, nested side effects are worse than deliberate helpers.
"""

import hashlib
import hmac
import json
import os
import logging

# SECURITY FIX #zvx9: Pickle has been completely removed to prevent RCE attacks.
# Session files now use only secure msgpack serialization with HMAC integrity.
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import msgpack

# ----- msgpack helpers -----

# Magic header that marks files written in the new msgpack format.
_MSGPACK_MAGIC = b"MSGPACK\x01"

logger = logging.getLogger(__name__)


def _msgpack_default(obj: Any) -> Any:
    """Handle types that msgpack can't serialize natively."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"can not serialize '{type(obj).__name__}' object")


def _deserialize_messages(raw_messages: list) -> list:
    """Restore serialized dicts back to pydantic-ai message objects.

    Handles two cases:
    - dicts with 'kind' key: new msgpack format, validate via TypeAdapter
    - plain values (e.g. strings in tests): return as-is

    SECURITY FIX #zvx9: Legacy pickle format support has been removed.
    """
    if not raw_messages:
        return raw_messages
    first = raw_messages[0]
    # New format: list of dicts with 'kind' discriminator
    if isinstance(first, dict) and "kind" in first:
        try:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            return list(ModelMessagesTypeAdapter.validate_python(raw_messages))
        except Exception:
            return raw_messages
    return raw_messages


# ----- HMAC helpers for integrity -----

# Legacy signed header for backward compatibility reading
_LEGACY_SIGNED_HEADER = b"CPSESSION\x01"
_LEGACY_SIGNATURE_SIZE = 32  # legacy signature bytes, retained only for backward-compat


def _compute_hmac(key: bytes, data: bytes) -> bytes:
    """Compute HMAC-SHA256 signature for data integrity."""
    return hmac.new(key, data, hashlib.sha256).digest()


def _get_or_create_hmac_key() -> bytes:
    """Get or create a per-installation HMAC key for session integrity.

    Uses atomic file creation (O_CREAT|O_EXCL via open mode 'xb') to prevent
    TOCTOU races when multiple processes start simultaneously. The key is
    stored at DATA_DIR/.session_hmac_key with chmod 0o600.
    """
    from code_puppy import config  # local import to avoid circular deps

    key_path = Path(config.DATA_DIR) / ".session_hmac_key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with key_path.open("xb") as f:  # O_CREAT|O_EXCL — atomic, prevents TOCTOU
            key = os.urandom(32)
            f.write(key)
        key_path.chmod(0o600)
        return key
    except FileExistsError:
        key = key_path.read_bytes()
        if len(key) != 32:
            logger.warning(
                "HMAC key file at %s is corrupted (%d bytes, expected 32), regenerating",
                key_path,
                len(key),
            )
            key = os.urandom(32)
            key_path.write_bytes(key)
            key_path.chmod(0o600)
        return key


_HMAC_KEY: bytes | None = None  # lazily populated on first call


def _get_hmac_key() -> bytes:
    """Return cached HMAC key, initializing on first call."""
    global _HMAC_KEY
    if _HMAC_KEY is None:
        _HMAC_KEY = _get_or_create_hmac_key()
    return _HMAC_KEY


def _load_raw_bytes(raw: bytes) -> Any:
    """Deserialize session file bytes, handling msgpack and legacy-signed formats.

    SECURITY FIX #zvx9: Pickle deserialization has been removed to prevent RCE attacks.
    Legacy pickle sessions will return an error message and empty data.
    """
    # New msgpack format: magic header followed by HMAC + msgpack payload
    if raw.startswith(_MSGPACK_MAGIC):
        # Format: MAGIC (8 bytes) + HMAC (32 bytes) + msgpack payload
        offset = len(_MSGPACK_MAGIC)
        stored_hmac = raw[offset : offset + 32]
        msgpack_data = raw[offset + 32 :]

        # Verify HMAC integrity using per-install secret key
        expected_hmac = _compute_hmac(_get_hmac_key(), msgpack_data)
        if not hmac.compare_digest(stored_hmac, expected_hmac):
            # Backward compat: files saved after msgpack migration but
            # before HMAC was added have format MAGIC + raw msgpack (no HMAC).
            # Try loading from offset 8 as plain msgpack.
            try:
                data = msgpack.unpackb(raw[offset:], raw=False)
            except Exception:
                raise ValueError(
                    "Session file HMAC integrity check failed — file may be corrupted or tampered"
                )
            warnings.warn(
                "Loading session from pre-HMAC msgpack format. "
                "Re-save this session to add integrity protection. "
                "Pre-HMAC msgpack support will be removed in a future version.",
                DeprecationWarning,
                stacklevel=2,
            )
            return data
        return msgpack.unpackb(msgpack_data, raw=False)

    # Legacy signed format: CPSESSION\x01 + 32-byte signature + pickle
    # SECURITY FIX #zvx9: Pickle deserialization removed - RCE vulnerability
    if raw.startswith(_LEGACY_SIGNED_HEADER):
        logger.error(
            "Session file uses legacy pickle format (CPSESSION). "
            "This format is no longer supported due to security vulnerabilities (RCE risk). "
            "Please remove this session file and start a new session. "
            "Session file location: See error details below."
        )
        raise ValueError(
            "Legacy pickle session format is no longer supported due to security "
            "vulnerabilities (RCE risk - CVE-class). This session file uses the old "
            "CPSESSION format with pickle deserialization which allows arbitrary "
            "code execution. Please delete this session file and create a new session. "
            "See https://docs.python.org/3/library/pickle.html#security for details."
        )

    # Plain pickle (original format) - SECURITY FIX #zvx9: Removed
    # SECURITY: This would be an RCE vulnerability if pickle.loads() was used
    logger.error(
        "Session file uses legacy pickle format. "
        "This format is no longer supported due to security vulnerabilities (RCE risk). "
        "Please remove this session file and start a new session."
    )
    raise ValueError(
        "Legacy pickle session format is no longer supported due to security "
        "vulnerabilities (RCE risk - CVE-class). This session file uses pickle "
        "deserialization which allows arbitrary code execution. Please delete this "
        "session file and create a new session. "
        "See https://docs.python.org/3/library/pickle.html#security for details."
    )


SessionHistory = list[Any]
TokenEstimator = Callable[[Any], int]


@dataclass(slots=True)
class SessionPaths:
    pickle_path: Path  # Historical name; now stores msgpack data (*.pkl extension kept for compat)
    metadata_path: Path


@dataclass(slots=True)
class SessionMetadata:
    session_name: str
    timestamp: str
    message_count: int
    total_tokens: int
    pickle_path: Path
    metadata_path: Path
    auto_saved: bool = False

    def as_serialisable(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "timestamp": self.timestamp,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "file_path": str(self.pickle_path),
            "auto_saved": self.auto_saved,
        }


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_session_paths(base_dir: Path, session_name: str) -> SessionPaths:
    pickle_path = base_dir / f"{session_name}.pkl"
    metadata_path = base_dir / f"{session_name}_meta.json"
    return SessionPaths(pickle_path=pickle_path, metadata_path=metadata_path)


def save_session(
    *,
    history: SessionHistory,
    session_name: str,
    base_dir: Path,
    timestamp: str,
    token_estimator: TokenEstimator,
    auto_saved: bool = False,
    compacted_hashes: list | None = None,
    precomputed_total: int | None = None,
) -> SessionMetadata:
    ensure_directory(base_dir)
    paths = build_session_paths(base_dir, session_name)

    # Convert pydantic-ai message objects to msgpack-serializable dicts.
    # ModelMessagesTypeAdapter handles ModelRequest/ModelResponse dataclasses
    # that msgpack cannot serialize natively.
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        # Sanitize messages to remove non-serializable objects (coroutines, etc.)
        # that may have been captured in message metadata during tool execution.
        # DBOS uses pickle for workflow durability, which cannot serialize coroutines.
        try:
            json_data = ModelMessagesTypeAdapter.dump_json(history)
            sanitized_history = ModelMessagesTypeAdapter.validate_json(json_data)
        except Exception as e:
            # Log the sanitization failure so we can track if this becomes a recurring issue
            logger.warning(f"Message sanitization failed in save_session: {e}. Using original history.")
            sanitized_history = history

        serializable_history = ModelMessagesTypeAdapter.dump_python(
            sanitized_history, mode="json"
        )
    except Exception:
        # Fallback for non-pydantic history (e.g. tests with plain strings)
        serializable_history = history

    payload: dict = {
        "messages": serializable_history,
        "compacted_hashes": list(compacted_hashes)
        if compacted_hashes is not None
        else [],
    }
    msgpack_data = msgpack.packb(payload, use_bin_type=True, default=_msgpack_default)

    # Compute HMAC for integrity using per-install secret key
    hmac_signature = _compute_hmac(_get_hmac_key(), msgpack_data)

    tmp_session = paths.pickle_path.with_suffix(".tmp")
    with tmp_session.open("wb") as session_file:
        session_file.write(_MSGPACK_MAGIC + hmac_signature + msgpack_data)
    tmp_session.replace(paths.pickle_path)

    total_tokens = (
        precomputed_total
        if (precomputed_total is not None and precomputed_total >= 0)
        else sum(token_estimator(message) for message in history)
    )
    metadata = SessionMetadata(
        session_name=session_name,
        timestamp=timestamp,
        message_count=len(history),
        total_tokens=total_tokens,
        pickle_path=paths.pickle_path,
        metadata_path=paths.metadata_path,
        auto_saved=auto_saved,
    )

    tmp_metadata = paths.metadata_path.with_suffix(".tmp")
    with tmp_metadata.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata.as_serialisable(), metadata_file, indent=2)
    tmp_metadata.replace(paths.metadata_path)

    return metadata


def _parse_session_payload(data: Any) -> tuple[SessionHistory]:
    """Parse session payload into ``(messages, compacted_hashes)``.

    Handles two on-disk formats:

    * **New format** – ``dict`` with ``"messages"`` and ``"compacted_hashes"``
      keys (written by this module from the point of this change onward).
    * **Legacy format** – plain ``list`` of messages; ``compacted_hashes``
      is returned as an empty list so callers don't need special-casing.
    """
    if isinstance(data, dict) and "messages" in data:
        messages = _deserialize_messages(data["messages"])
        return messages, data.get("compacted_hashes", [])
    # Legacy format: raw list only
    if isinstance(data, list):
        return _deserialize_messages(data), []
    return data, []


def load_session(
    session_name: str, base_dir: Path, *, allow_legacy: bool = False
) -> SessionHistory:
    """Load message history from a session file.

    Returns only the message list.  Use :func:`load_session_with_hashes` when
    you also need the persisted compacted-message hashes.
    """
    # Kept for API compatibility; legacy loading is always supported now.
    _ = allow_legacy

    paths = build_session_paths(base_dir, session_name)
    if not paths.pickle_path.exists():
        raise FileNotFoundError(paths.pickle_path)

    raw = paths.pickle_path.read_bytes()
    data = _load_raw_bytes(raw)
    messages, _ = _parse_session_payload(data)
    return messages


def load_session_with_hashes(
    session_name: str, base_dir: Path
) -> tuple[SessionHistory]:
    """Load message history *and* compacted-message hashes from a session file.

    Returns:
        ``(messages, compacted_hashes)`` tuple.  For legacy session files that
        contain only the message list, ``compacted_hashes`` will be ``[]``.

    On corruption or deserialisation errors a user-visible warning is emitted
    (via ``code_puppy.messaging.emit_warning``) and ``([], [])`` is returned
    so callers get an empty session rather than an unhandled exception.
    """
    paths = build_session_paths(base_dir, session_name)
    if not paths.pickle_path.exists():
        raise FileNotFoundError(paths.pickle_path)

    # --- 1. Read raw bytes from disk ---
    try:
        raw = paths.pickle_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "Session '%s' could not be read from disk: %s: %s",
            session_name,
            type(exc).__name__,
            exc,
        )
        from code_puppy.messaging import (
            emit_warning,
        )  # lazy import – avoids circular deps

        emit_warning(
            f"Session '{session_name}' could not be loaded: {type(exc).__name__}: {exc}"
        )
        return [], []

    # --- 2. Deserialize bytes ---
    try:
        data = _load_raw_bytes(raw)
    except (ValueError, Exception) as exc:  # Exception covers pickle.UnpicklingError
        logger.warning(
            "Session '%s' deserialization failed: %s: %s",
            session_name,
            type(exc).__name__,
            exc,
        )
        from code_puppy.messaging import emit_warning

        emit_warning(
            f"Session '{session_name}' could not be loaded: {type(exc).__name__}: {exc}"
        )
        return [], []

    # --- 3. Parse the deserialized payload into (messages, hashes) ---
    try:
        return _parse_session_payload(data)
    except Exception as exc:
        logger.warning(
            "Session '%s' payload parse failed: %s: %s",
            session_name,
            type(exc).__name__,
            exc,
        )
        from code_puppy.messaging import emit_warning

        emit_warning(
            f"Session '{session_name}' could not be loaded: {type(exc).__name__}: {exc}"
        )
        return [], []


def list_sessions(base_dir: Path) -> list[str]:
    if not base_dir.exists():
        return []
    return sorted(path.stem for path in base_dir.glob("*.pkl"))


def cleanup_sessions(base_dir: Path, max_sessions: int) -> list[str]:
    if max_sessions <= 0:
        return []

    if not base_dir.exists():
        return []

    candidate_paths = list(base_dir.glob("*.pkl"))
    if len(candidate_paths) <= max_sessions:
        return []

    sorted_candidates = sorted(
        ((path.stat().st_mtime, path) for path in candidate_paths),
        key=lambda item: item[0],
    )

    stale_entries = sorted_candidates[:-max_sessions]
    removed_sessions: list[str] = []
    for _, pickle_path in stale_entries:
        metadata_path = base_dir / f"{pickle_path.stem}_meta.json"
        try:
            pickle_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            removed_sessions.append(pickle_path.stem)
        except OSError:
            continue

    return removed_sessions


async def restore_autosave_interactively(base_dir: Path) -> None:
    """Prompt the user to load an autosave session from base_dir, if any exist.

    This helper is deliberately placed in session_storage to keep autosave
    restoration close to the persistence layer. It uses the same public APIs
    (list_sessions, load_session) and mirrors the interactive behaviours from
    the command handler.
    """
    sessions = list_sessions(base_dir)
    if not sessions:
        return

    # Import locally to avoid pulling the messaging layer into storage modules
    # These are legacy prompt_toolkit imports; not available if prompt_toolkit removed
    try:
        from prompt_toolkit.formatted_text import FormattedText
        from code_puppy.command_line.prompt_toolkit_completion import (
            get_input_with_combined_completion,
        )
    except ImportError:
        # prompt_toolkit not available (Textual mode); skip interactive restore
        return

    from code_puppy.agents.agent_manager import get_current_agent
    from code_puppy.messaging import emit_success, emit_system_message, emit_warning

    entries = []
    for name in sessions:
        meta_path = base_dir / f"{name}_meta.json"
        try:
            with meta_path.open("r", encoding="utf-8") as meta_file:
                data = json.load(meta_file)
            timestamp = data.get("timestamp")
            message_count = data.get("message_count")
        except Exception:
            timestamp = None
            message_count = None
        entries.append((name, timestamp, message_count))

    def sort_key(entry):
        _, timestamp, _ = entry
        if timestamp:
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                return datetime.min
        return datetime.min

    entries.sort(key=sort_key, reverse=True)

    PAGE_SIZE = 5
    total = len(entries)
    page = 0

    def render_page() -> None:
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_entries = entries[start:end]
        emit_system_message("Autosave Sessions Available:")
        for idx, (name, timestamp, message_count) in enumerate(page_entries, start=1):
            timestamp_display = timestamp or "unknown time"
            message_display = (
                f"{message_count} messages"
                if message_count is not None
                else "unknown size"
            )
            emit_system_message(
                f"  [{idx}] {name} ({message_display}, saved at {timestamp_display})"
            )
        # If there are more pages, offer next-page; show 'Return to first page' on last page
        if total > PAGE_SIZE:
            page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
            is_last_page = (page + 1) >= page_count
            remaining = total - (page * PAGE_SIZE + len(page_entries))
            summary = (
                f" and {remaining} more" if (remaining > 0 and not is_last_page) else ""
            )
            label = "Return to first page" if is_last_page else f"Next page{summary}"
            emit_system_message(f"  [6] {label}")
        emit_system_message("  [Enter] Skip loading autosave")

    chosen_name: str | None = None

    while True:
        render_page()
        try:
            selection = await get_input_with_combined_completion(
                FormattedText(
                    [("class:prompt", "Pick 1-5 to load, 6 for next, or name/Enter: ")]
                )
            )
        except (KeyboardInterrupt, EOFError):
            emit_warning("Autosave selection cancelled")
            return

        selection = (selection or "").strip()
        if not selection:
            return

        # Numeric choice: 1-5 select within current page; 6 advances page
        if selection.isdigit():
            num = int(selection)
            if num == 6 and total > PAGE_SIZE:
                page = (page + 1) % ((total + PAGE_SIZE - 1) // PAGE_SIZE)
                # loop and re-render next page
                continue
            if 1 <= num <= 5:
                start = page * PAGE_SIZE
                idx = start + (num - 1)
                if 0 <= idx < total:
                    chosen_name = entries[idx][0]
                    break
                else:
                    emit_warning("Invalid selection for this page")
                    continue
            emit_warning("Invalid selection; choose 1-5 or 6 for next")
            continue

        # Allow direct typing by exact session name
        for name, _ts, _mc in entries:
            if name == selection:
                chosen_name = name
                break
        if chosen_name:
            break
        emit_warning("No autosave loaded (invalid selection)")
        # keep looping and allow another try

    if not chosen_name:
        return

    try:
        history, compacted_hashes = load_session_with_hashes(chosen_name, base_dir)
    except FileNotFoundError:
        emit_warning(f"Autosave '{chosen_name}' could not be found")
        return
    except Exception as exc:
        emit_warning(f"Failed to load autosave '{chosen_name}': {exc}")
        return

    agent = get_current_agent()
    agent.set_message_history(history)
    agent.restore_compacted_hashes(compacted_hashes)

    # Set current autosave session id so subsequent autosaves overwrite this session
    try:
        from code_puppy.config import set_current_autosave_from_session_name

        set_current_autosave_from_session_name(chosen_name)
    except Exception:
        pass

    total_tokens = sum(agent.estimate_tokens_for_message(msg) for msg in history)

    session_path = base_dir / f"{chosen_name}.pkl"
    emit_success(
        f"✅ Autosave loaded: {len(history)} messages ({total_tokens} tokens)\n"
        f"📁 From: {session_path}"
    )

    # Display recent message history for context
    try:
        from code_puppy.command_line.autosave_menu import display_resumed_history

        display_resumed_history(history)
    except Exception:
        pass  # Don't fail if display doesn't work in non-TTY environment
