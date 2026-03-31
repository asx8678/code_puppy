"""Shared helpers for persisting and restoring chat sessions.

This module centralises the msgpack + metadata handling that used to live in
both the CLI command handler and the auto-save feature. Keeping it here helps
us avoid duplication while staying inside the Zen-of-Python sweet spot: simple
is better than complex, nested side effects are worse than deliberate helpers.
"""

from __future__ import annotations

import dataclasses
import json
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import msgpack
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage

# ----- msgpack helpers -----

# Magic header that marks files written in the new msgpack format.
_MSGPACK_MAGIC = b"MSGPACK\x01"

_message_adapter: TypeAdapter[ModelMessage] = TypeAdapter(ModelMessage)


def _msgpack_default(obj: Any) -> Any:
    """Handle types that msgpack can't serialize natively."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"can not serialize '{type(obj).__name__}' object")


def _deserialize_messages(raw_messages: list) -> list:
    """Convert dicts back to pydantic-ai message objects.

    If messages are already pydantic-ai objects (e.g. from legacy pickle),
    return them as-is.
    """
    result = []
    for m in raw_messages:
        if isinstance(m, dict) and "kind" in m:
            result.append(_message_adapter.validate_python(m))
        else:
            result.append(m)  # Already a proper object (legacy pickle path)
    return result


# ----- legacy pickle helpers (load path only) -----


def _safe_loads(data: bytes) -> Any:
    """Deserialize pickle data."""
    return pickle.loads(data)  # noqa: S301


_LEGACY_SIGNED_HEADER = b"CPSESSION\x01"
_LEGACY_SIGNATURE_SIZE = (
    32  # legacy signature bytes, retained only for backward-compat parsing
)


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


def _load_raw_bytes(raw: bytes) -> Any:
    """Deserialize session file bytes, handling msgpack, legacy-signed, and plain pickle."""
    # New msgpack format: magic header followed by msgpack payload
    if raw.startswith(_MSGPACK_MAGIC):
        payload = raw[len(_MSGPACK_MAGIC) :]
        return msgpack.unpackb(payload, raw=False)

    # Legacy signed format: CPSESSION\x01 + 32-byte signature + pickle
    if raw.startswith(_LEGACY_SIGNED_HEADER):
        offset = len(_LEGACY_SIGNED_HEADER) + _LEGACY_SIGNATURE_SIZE
        return _safe_loads(raw[offset:])

    # Plain pickle (original format)
    return _safe_loads(raw)


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

    # Convert pydantic-ai message objects to plain dicts so msgpack can handle them.
    # Plain strings / ints / etc. pass through dataclasses.asdict() unchanged because
    # they are not dataclasses – we guard with dataclasses.is_dataclass().
    serializable_history = [
        dataclasses.asdict(m)
        if dataclasses.is_dataclass(m) and not isinstance(m, type)
        else m
        for m in history
    ]

    payload: dict = {
        "messages": serializable_history,
        "compacted_hashes": list(compacted_hashes)
        if compacted_hashes is not None
        else [],
    }
    msgpack_data = msgpack.packb(payload, use_bin_type=True, default=_msgpack_default)

    tmp_pickle = paths.pickle_path.with_suffix(".tmp")
    with tmp_pickle.open("wb") as pickle_file:
        pickle_file.write(_MSGPACK_MAGIC + msgpack_data)
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
    # Legacy format: raw list only (already objects from pickle)
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
) -> Tuple[SessionHistory, List]:
    """Load message history *and* compacted-message hashes from a session file.

    Returns:
        ``(messages, compacted_hashes)`` tuple.  For legacy session files that
        contain only the message list, ``compacted_hashes`` will be ``[]``.
    """
    paths = build_session_paths(base_dir, session_name)
    if not paths.pickle_path.exists():
        raise FileNotFoundError(paths.pickle_path)

    raw = paths.pickle_path.read_bytes()
    data = _load_raw_bytes(raw)
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
