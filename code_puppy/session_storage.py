"""Shared helpers for persisting and restoring chat sessions.

This module centralises the pickle + metadata handling that used to live in
both the CLI command handler and the auto-save feature. Keeping it here helps
us avoid duplication while staying inside the Zen-of-Python sweet spot: simple
is better than complex, nested side effects are worse than deliberate helpers.
"""

from __future__ import annotations

import json
import pickle
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from code_puppy._core_bridge import (
    deserialize_session,
    is_rust_enabled,
    serialize_messages_for_rust,
    serialize_session,
)


def _safe_loads(data: bytes) -> Any:
    """Deserialize pickle data."""
    return pickle.loads(data)  # noqa: S301


_LEGACY_SIGNED_HEADER = b"CPSESSION\x01"
_LEGACY_SIGNATURE_SIZE = (
    32  # legacy signature bytes, retained only for backward-compat parsing
)

# Rust/MessagePack session format header.
# Format: header (8 bytes) + uint32 BE (msgpack length) + msgpack bytes + json(compacted_hashes)
_RUST_SESSION_HEADER = b"CPRSESS\x01"


SessionHistory = List[Any]
TokenEstimator = Callable[[Any], int]


@dataclass(slots=True)
class SessionPaths:
    pickle_path: Path
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


def _extract_pickle_payload(raw: bytes) -> bytes:
    """Return the pickle payload from raw session file bytes.

    New format is raw pickle bytes.
    Legacy format was: header + 32-byte signature + pickle payload.
    We no longer verify or generate signatures.
    """
    if raw.startswith(_LEGACY_SIGNED_HEADER):
        offset = len(_LEGACY_SIGNED_HEADER) + _LEGACY_SIGNATURE_SIZE
        return raw[offset:]
    return raw


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
    compacted_hashes: Optional[List] = None,
) -> SessionMetadata:
    ensure_directory(base_dir)
    paths = build_session_paths(base_dir, session_name)

    # Always save in the new dict format so compacted hashes are preserved.
    # Legacy session files (plain list) are still handled gracefully on load.
    compacted_list = list(compacted_hashes) if compacted_hashes is not None else []
    if serialize_session is not None and is_rust_enabled():
        try:
            messages_as_dicts = serialize_messages_for_rust(history)
            msgpack_bytes = serialize_session(messages_as_dicts)
            compacted_encoded = json.dumps(compacted_list).encode("utf-8")
            pickle_data = (
                _RUST_SESSION_HEADER
                + struct.pack(">I", len(msgpack_bytes))
                + msgpack_bytes
                + compacted_encoded
            )
        except Exception:
            payload: dict = {
                "messages": history,
                "compacted_hashes": compacted_list,
            }
            pickle_data = pickle.dumps(payload)
    else:
        payload = {
            "messages": history,
            "compacted_hashes": compacted_list,
        }
        pickle_data = pickle.dumps(payload)
    tmp_pickle = paths.pickle_path.with_suffix(".tmp")
    with tmp_pickle.open("wb") as pickle_file:
        pickle_file.write(pickle_data)
    tmp_pickle.replace(paths.pickle_path)

    total_tokens = sum(token_estimator(message) for message in history)
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


def _parse_session_payload(data: Any) -> Tuple[SessionHistory, List]:
    """Parse session pickle payload into ``(messages, compacted_hashes)``.

    Handles two on-disk formats:

    * **New format** – ``dict`` with ``"messages"`` and ``"compacted_hashes"``
      keys (written by this module from the point of this change onward).
    * **Legacy format** – plain ``list`` of messages; ``compacted_hashes``
      is returned as an empty list so callers don't need special-casing.
    """
    if isinstance(data, dict) and "messages" in data:
        return data["messages"], data.get("compacted_hashes", [])
    # Legacy format: raw list only
    return data, []


def _try_decode_rust_session(raw: bytes) -> Optional[Tuple[SessionHistory, List]]:
    """Attempt to decode a Rust/MessagePack session file.

    Returns (messages, compacted_hashes) if the file is in Rust format and
    can be decoded, or None if decoding is not possible (Rust unavailable
    or format not recognised).

    Raises ValueError if the header is present but decoding fails and there
    is no fallback possible (so callers can propagate a useful error).
    """
    if not raw.startswith(_RUST_SESSION_HEADER):
        return None

    if deserialize_session is None or not is_rust_enabled():
        raise ValueError(
            "Session was saved with Rust serialization but Rust is not available. "
            "Install the code_puppy_core extension to load this session."
        )

    try:
        offset = len(_RUST_SESSION_HEADER)
        (msgpack_len,) = struct.unpack(">I", raw[offset : offset + 4])
        offset += 4
        msgpack_bytes = raw[offset : offset + msgpack_len]
        compacted_bytes = raw[offset + msgpack_len :]
        messages = list(deserialize_session(msgpack_bytes))
        compacted_hashes: List = (
            json.loads(compacted_bytes.decode("utf-8")) if compacted_bytes else []
        )
        return messages, compacted_hashes
    except Exception as exc:
        raise ValueError(
            f"Failed to decode Rust session format: {exc}. "
            "The file may be corrupted."
        ) from exc


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

    # Try Rust/MessagePack format first.
    rust_result = _try_decode_rust_session(raw)
    if rust_result is not None:
        messages, _ = rust_result
        return messages

    # Fall back to pickle (new dict format or legacy plain list).
    pickle_data = _extract_pickle_payload(raw)
    data = _safe_loads(pickle_data)
    messages, _ = _parse_session_payload(data)
    return messages


def load_session_with_hashes(
    session_name: str, base_dir: Path
) -> Tuple[SessionHistory, List]:
    """Load message history *and* compacted-message hashes from a session file.

    Returns:
        (messages, compacted_hashes) tuple.  For legacy session files that
        contain only the message list, compacted_hashes will be [].
    """
    paths = build_session_paths(base_dir, session_name)
    if not paths.pickle_path.exists():
        raise FileNotFoundError(paths.pickle_path)

    raw = paths.pickle_path.read_bytes()

    # Try Rust/MessagePack format first.
    rust_result = _try_decode_rust_session(raw)
    if rust_result is not None:
        return rust_result

    # Fall back to pickle (new dict format or legacy plain list).
    pickle_data = _extract_pickle_payload(raw)
    data = _safe_loads(pickle_data)
    return _parse_session_payload(data)


def list_sessions(base_dir: Path) -> List[str]:
    if not base_dir.exists():
        return []
    return sorted(path.stem for path in base_dir.glob("*.pkl"))


def cleanup_sessions(base_dir: Path, max_sessions: int) -> List[str]:
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
    removed_sessions: List[str] = []
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
    from datetime import datetime

    from prompt_toolkit.formatted_text import FormattedText

    from code_puppy.agents.agent_manager import get_current_agent
    from code_puppy.command_line.prompt_toolkit_completion import (
        get_input_with_combined_completion,
    )
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
                    [
                        (
                            "class:prompt",
                            "Pick 1-5 to load, 6 for next, or name/Enter: ",
                        )
                    ]
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
