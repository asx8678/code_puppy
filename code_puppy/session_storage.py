"""Shared helpers for persisting and restoring chat sessions.

This module centralises the pickle + metadata handling that used to live in
both the CLI command handler and the auto-save feature. Keeping it here helps
us avoid duplication while staying inside the Zen-of-Python sweet spot: simple
is better than complex, nested side effects are worse than deliberate helpers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pickle
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LEGACY_SIGNED_HEADER = b"CPSESSION\x01"
_LEGACY_SIGNATURE_SIZE = (
    32  # legacy signature bytes, retained only for backward-compat parsing
)
_SIGNED_HEADER = b"CPSESSION\x02"
_SIGNATURE_SIZE = 32


class SessionSecurityError(ValueError):
    """Raised when a session file fails path or signature validation."""


def _safe_loads(data: bytes) -> Any:
    """Deserialize authenticated pickle data."""
    return pickle.loads(data)  # noqa: S301


SessionHistory = list[Any]
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


def _validate_session_name(session_name: str) -> str:
    if not isinstance(session_name, str):
        raise TypeError("session_name must be a string")

    name = session_name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("session_name must be a non-empty leaf filename")

    if "\x00" in name or "/" in name or "\\" in name:
        raise ValueError("session_name must not contain path separators")

    return name


def _session_signing_key_path() -> Path:
    from code_puppy import config as cp_config

    return Path(cp_config.CONFIG_DIR) / "session_signing.key"


def _load_session_signing_key() -> bytes:
    path = _session_signing_key_path()
    try:
        key = path.read_bytes()
        if len(key) >= 32:
            return key
        raise SessionSecurityError("Session signing key is invalid")
    except FileNotFoundError:
        pass

    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        with tmp_path.open("wb") as key_file:
            key_file.write(key)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        tmp_path.replace(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _sign_payload(payload: bytes) -> bytes:
    signature = hmac.new(_load_session_signing_key(), payload, hashlib.sha256).digest()
    return _SIGNED_HEADER + signature + payload


def _extract_pickle_payload(raw: bytes, *, allow_legacy: bool = False) -> bytes:
    """Return the pickle payload from raw session file bytes.

    New format is HMAC-authenticated pickle bytes.
    Legacy format was: header + 32-byte signature + pickle payload.
    Raw and legacy payloads are only accepted with explicit legacy opt-in.
    """
    if raw.startswith(_SIGNED_HEADER):
        offset = len(_SIGNED_HEADER) + _SIGNATURE_SIZE
        if len(raw) < offset:
            raise SessionSecurityError("Session file is truncated")
        signature = raw[len(_SIGNED_HEADER) : offset]
        payload = raw[offset:]
        expected = hmac.new(
            _load_session_signing_key(), payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise SessionSecurityError("Session signature verification failed")
        return payload

    if raw.startswith(_LEGACY_SIGNED_HEADER):
        if not allow_legacy:
            raise SessionSecurityError(
                "Legacy unsigned session requires explicit allow_legacy=True"
            )
        offset = len(_LEGACY_SIGNED_HEADER) + _LEGACY_SIGNATURE_SIZE
        return raw[offset:]

    if allow_legacy:
        return raw

    raise SessionSecurityError("Unsigned session file rejected")


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_session_paths(base_dir: Path, session_name: str) -> SessionPaths:
    safe_name = _validate_session_name(session_name)
    pickle_path = base_dir / f"{safe_name}.pkl"
    metadata_path = base_dir / f"{safe_name}_meta.json"
    return SessionPaths(pickle_path=pickle_path, metadata_path=metadata_path)


def save_session(
    *,
    history: SessionHistory,
    session_name: str,
    base_dir: Path,
    timestamp: str,
    token_estimator: TokenEstimator,
    auto_saved: bool = False,
) -> SessionMetadata:
    ensure_directory(base_dir)
    paths = build_session_paths(base_dir, session_name)

    pickle_data = _sign_payload(pickle.dumps(history))
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


def load_session(
    session_name: str, base_dir: Path, *, allow_legacy: bool = False
) -> SessionHistory:
    paths = build_session_paths(base_dir, session_name)
    if not paths.pickle_path.exists():
        raise FileNotFoundError(paths.pickle_path)

    raw = paths.pickle_path.read_bytes()
    pickle_data = _extract_pickle_payload(raw, allow_legacy=allow_legacy)
    return _safe_loads(pickle_data)


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
        except KeyboardInterrupt, EOFError:
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
        history = load_session(chosen_name, base_dir)
    except FileNotFoundError:
        emit_warning(f"Autosave '{chosen_name}' could not be found")
        return
    except Exception as exc:
        emit_warning(f"Failed to load autosave '{chosen_name}': {exc}")
        return

    agent = get_current_agent()
    agent.set_message_history(history)

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
