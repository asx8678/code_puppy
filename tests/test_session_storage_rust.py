"""Tests for Rust/MessagePack session serialization in session_storage.py.

These tests verify that:
- The Rust format is used when Rust is available and enabled.
- The pickle fallback is used when Rust is not available or fails.
- Files written in Rust format are correctly detected and decoded on load.
- Files written in pickle format are still correctly loaded (backward compat).
- Cross-format scenarios (Rust saved, Rust unavailable on load) raise cleanly.
"""

from __future__ import annotations

import json
import pickle
import struct
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.session_storage import (
    _RUST_SESSION_HEADER,
    _try_decode_rust_session,
    load_session,
    load_session_with_hashes,
    save_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_estimator(msg: Any) -> int:
    return len(str(msg))


def _make_history(n: int = 3) -> List[str]:
    """Return a simple history of plain strings (no Rust conversion needed)."""
    return [f"message_{i}" for i in range(n)]


def _make_bridge_dict_history(n: int = 2) -> List[dict]:
    """Return history already in bridge-dict format (what serialize_session expects)."""
    msgs = []
    for i in range(n):
        msgs.append(
            {
                "kind": "request",
                "role": "user",
                "instructions": None,
                "parts": [
                    {
                        "part_kind": "user-prompt",
                        "content": f"hello {i}",
                        "content_json": None,
                        "tool_call_id": None,
                        "tool_name": None,
                        "args": None,
                    }
                ],
            }
        )
    return msgs


# ---------------------------------------------------------------------------
# Tests for _try_decode_rust_session helper
# ---------------------------------------------------------------------------


class TestTryDecodeRustSession:
    """Unit tests for the _try_decode_rust_session internal helper."""

    def test_returns_none_for_non_rust_bytes(self):
        """Non-Rust bytes (e.g., pickle) should return None."""
        pickled = pickle.dumps({"messages": ["a", "b"], "compacted_hashes": []})
        result = _try_decode_rust_session(pickled)
        assert result is None

    def test_returns_none_for_empty_bytes(self):
        assert _try_decode_rust_session(b"") is None

    def test_raises_when_rust_header_present_but_rust_unavailable(self):
        """If the Rust header is present but the Rust extension is not available,
        a ValueError should be raised (not silently ignored)."""
        # Build a minimal valid Rust session payload
        msgpack_bytes = b"\x90"  # empty msgpack array
        compacted_json = b"[]"
        raw = (
            _RUST_SESSION_HEADER
            + struct.pack(">I", len(msgpack_bytes))
            + msgpack_bytes
            + compacted_json
        )

        with (
            patch("code_puppy.session_storage.deserialize_session", None),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            with pytest.raises(ValueError, match="Rust is not available"):
                _try_decode_rust_session(raw)

    def test_raises_when_rust_disabled_by_user(self):
        """Even if Rust extension is installed, if user disabled it via
        /fast_puppy disable, treat as unavailable."""
        msgpack_bytes = b"\x90"
        compacted_json = b"[]"
        raw = (
            _RUST_SESSION_HEADER
            + struct.pack(">I", len(msgpack_bytes))
            + msgpack_bytes
            + compacted_json
        )

        mock_deser = MagicMock(return_value=[])
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            with pytest.raises(ValueError, match="Rust is not available"):
                _try_decode_rust_session(raw)

    def test_raises_on_corrupted_rust_payload(self):
        """A valid header but corrupted payload raises a ValueError."""
        raw = _RUST_SESSION_HEADER + b"\x00\x00\x00\x05" + b"\xff\xfe"  # truncated

        mock_deser = MagicMock(side_effect=Exception("bad msgpack"))
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
        ):
            with pytest.raises(ValueError, match="Failed to decode Rust session"):
                _try_decode_rust_session(raw)

    def test_decodes_valid_rust_payload(self):
        """A properly encoded Rust payload should be decoded correctly."""
        messages = [{"kind": "request", "role": "user", "parts": []}]
        compacted_hashes = ["hash1", "hash2"]

        msgpack_bytes = b"\x91\x01"  # placeholder; mocked deserializer ignores it
        compacted_json = json.dumps(compacted_hashes).encode("utf-8")
        raw = (
            _RUST_SESSION_HEADER
            + struct.pack(">I", len(msgpack_bytes))
            + msgpack_bytes
            + compacted_json
        )

        mock_deser = MagicMock(return_value=messages)
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
        ):
            result = _try_decode_rust_session(raw)

        assert result is not None
        decoded_messages, decoded_hashes = result
        assert decoded_messages == messages
        assert decoded_hashes == compacted_hashes

    def test_decodes_rust_payload_with_empty_compacted_hashes(self):
        """A Rust payload with empty compacted hashes bytes (legacy) uses []."""
        msgpack_bytes = b"\x90"
        raw = (
            _RUST_SESSION_HEADER + struct.pack(">I", len(msgpack_bytes)) + msgpack_bytes
            # No compacted hashes section
        )

        mock_deser = MagicMock(return_value=[])
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
        ):
            result = _try_decode_rust_session(raw)

        assert result is not None
        msgs, hashes = result
        assert msgs == []
        assert hashes == []


# ---------------------------------------------------------------------------
# Tests for save_session with Rust path
# ---------------------------------------------------------------------------


class TestSaveSessionRustPath:
    """Test save_session behaviour when Rust is available."""

    def test_save_uses_rust_format_when_available(self, tmp_path: Path):
        """When Rust is available, the saved file should start with the Rust header."""
        history = _make_bridge_dict_history(2)
        msgpack_bytes = b"\x92\xde\xad\xbe"
        mock_ser = MagicMock(return_value=msgpack_bytes)

        with (
            patch("code_puppy.session_storage.serialize_session", mock_ser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
            patch(
                "code_puppy.session_storage.serialize_messages_for_rust",
                return_value=history,
            ),
        ):
            save_session(
                history=history,
                session_name="test",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
            )

        saved_bytes = (tmp_path / "test.pkl").read_bytes()
        assert saved_bytes.startswith(_RUST_SESSION_HEADER)

    def test_save_rust_format_encodes_compacted_hashes(self, tmp_path: Path):
        """The Rust-format file should include the compacted hashes as JSON."""
        history = _make_bridge_dict_history(1)
        compacted_hashes = ["abc", "def"]
        msgpack_bytes = b"\x91\x01"
        mock_ser = MagicMock(return_value=msgpack_bytes)

        with (
            patch("code_puppy.session_storage.serialize_session", mock_ser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
            patch(
                "code_puppy.session_storage.serialize_messages_for_rust",
                return_value=history,
            ),
        ):
            save_session(
                history=history,
                session_name="with_hashes",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
                compacted_hashes=compacted_hashes,
            )

        raw = (tmp_path / "with_hashes.pkl").read_bytes()
        assert raw.startswith(_RUST_SESSION_HEADER)

        offset = len(_RUST_SESSION_HEADER)
        (msgpack_len,) = struct.unpack(">I", raw[offset : offset + 4])
        offset += 4
        embedded_hashes = json.loads(raw[offset + msgpack_len :].decode("utf-8"))
        assert embedded_hashes == compacted_hashes

    def test_save_falls_back_to_pickle_when_rust_unavailable(self, tmp_path: Path):
        """When serialize_session is None, fall back to pickle format."""
        history = _make_history(3)

        with (
            patch("code_puppy.session_storage.serialize_session", None),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            save_session(
                history=history,
                session_name="pickle_session",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
            )

        raw = (tmp_path / "pickle_session.pkl").read_bytes()
        assert not raw.startswith(_RUST_SESSION_HEADER)
        # Should be valid pickle
        payload = pickle.loads(raw)  # noqa: S301
        assert "messages" in payload
        assert payload["messages"] == history

    def test_save_falls_back_to_pickle_on_serialization_error(self, tmp_path: Path):
        """If Rust serialization raises, the pickle fallback must be used."""
        history = _make_history(2)

        mock_ser = MagicMock(side_effect=RuntimeError("boom"))
        with (
            patch("code_puppy.session_storage.serialize_session", mock_ser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
            patch(
                "code_puppy.session_storage.serialize_messages_for_rust",
                side_effect=RuntimeError("conversion boom"),
            ),
        ):
            # Should NOT raise — fallback to pickle
            save_session(
                history=history,
                session_name="fallback",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
            )

        raw = (tmp_path / "fallback.pkl").read_bytes()
        assert not raw.startswith(_RUST_SESSION_HEADER)
        payload = pickle.loads(raw)  # noqa: S301
        assert payload["messages"] == history

    def test_save_disabled_rust_uses_pickle(self, tmp_path: Path):
        """When is_rust_enabled() returns False, pickle is used even if Rust installed."""
        history = _make_history(2)
        mock_ser = MagicMock()

        with (
            patch("code_puppy.session_storage.serialize_session", mock_ser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            save_session(
                history=history,
                session_name="disabled_rust",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
            )

        mock_ser.assert_not_called()
        raw = (tmp_path / "disabled_rust.pkl").read_bytes()
        assert not raw.startswith(_RUST_SESSION_HEADER)


# ---------------------------------------------------------------------------
# Tests for load_session / load_session_with_hashes
# ---------------------------------------------------------------------------


def _write_rust_session(
    path: Path,
    messages: List[Any],
    compacted_hashes: List,
    msgpack_bytes: bytes,
) -> None:
    """Write a Rust-format session file directly."""
    compacted_json = json.dumps(compacted_hashes).encode("utf-8")
    raw = (
        _RUST_SESSION_HEADER
        + struct.pack(">I", len(msgpack_bytes))
        + msgpack_bytes
        + compacted_json
    )
    path.write_bytes(raw)


class TestLoadSessionRustFormat:
    """Test load_session / load_session_with_hashes with Rust-format files."""

    def test_load_session_reads_rust_format(self, tmp_path: Path):
        """load_session should decode a Rust-format file when Rust is available."""
        messages = [{"kind": "request", "role": "user", "parts": []}]
        msgpack_bytes = b"\x91\x01"
        session_path = tmp_path / "rust_session.pkl"
        _write_rust_session(session_path, messages, [], msgpack_bytes)

        mock_deser = MagicMock(return_value=messages)
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
        ):
            result = load_session("rust_session", tmp_path)

        assert result == messages

    def test_load_session_with_hashes_reads_rust_format(self, tmp_path: Path):
        """load_session_with_hashes should return both messages and hashes."""
        messages = [{"kind": "response", "parts": []}]
        compacted_hashes = ["h1", "h2", "h3"]
        msgpack_bytes = b"\x91\x01"
        session_path = tmp_path / "rust_hashes.pkl"
        _write_rust_session(session_path, messages, compacted_hashes, msgpack_bytes)

        mock_deser = MagicMock(return_value=messages)
        with (
            patch("code_puppy.session_storage.deserialize_session", mock_deser),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
        ):
            loaded_messages, loaded_hashes = load_session_with_hashes(
                "rust_hashes", tmp_path
            )

        assert loaded_messages == messages
        assert loaded_hashes == compacted_hashes

    def test_load_session_rust_format_rust_unavailable_raises(self, tmp_path: Path):
        """If a Rust-format file is loaded without Rust, ValueError should be raised."""
        msgpack_bytes = b"\x90"
        session_path = tmp_path / "rust_only.pkl"
        _write_rust_session(session_path, [], [], msgpack_bytes)

        with (
            patch("code_puppy.session_storage.deserialize_session", None),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            with pytest.raises(ValueError, match="Rust is not available"):
                load_session("rust_only", tmp_path)

    def test_load_session_pickle_format_still_works(self, tmp_path: Path):
        """Existing pickle-format sessions should load correctly (backward compat)."""
        history = ["a", "b", "c"]
        payload = {"messages": history, "compacted_hashes": []}
        (tmp_path / "pkl_session.pkl").write_bytes(pickle.dumps(payload))

        with (
            patch("code_puppy.session_storage.serialize_session", None),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=False),
        ):
            result = load_session("pkl_session", tmp_path)

        assert result == history

    def test_load_session_legacy_list_format_still_works(self, tmp_path: Path):
        """Plain list (very old) pickle sessions should still load."""
        history = ["x", "y"]
        (tmp_path / "legacy.pkl").write_bytes(pickle.dumps(history))

        result = load_session("legacy", tmp_path)
        assert result == history

    def test_load_nonexistent_session_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_session("doesnotexist", tmp_path)


# ---------------------------------------------------------------------------
# Integration: save-then-load round-trip with mocked Rust
# ---------------------------------------------------------------------------


class TestRustRoundTrip:
    """End-to-end save→load round-trip using mocked Rust serialization."""

    def test_round_trip_with_mocked_rust(self, tmp_path: Path):
        """Save with Rust, load with Rust; verify messages and hashes survive."""
        history = _make_bridge_dict_history(3)
        compacted_hashes = ["ch1", "ch2"]

        # Use a simple deterministic 'msgpack': just pickle the data (for mock purposes)
        def fake_serialize(msgs):
            return pickle.dumps(msgs)

        def fake_deserialize(data):
            return pickle.loads(data)  # noqa: S301

        with (
            patch(
                "code_puppy.session_storage.serialize_session",
                side_effect=fake_serialize,
            ),
            patch(
                "code_puppy.session_storage.deserialize_session",
                side_effect=fake_deserialize,
            ),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
            patch(
                "code_puppy.session_storage.serialize_messages_for_rust",
                side_effect=lambda h: h,  # identity — already dicts
            ),
        ):
            save_session(
                history=history,
                session_name="roundtrip",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
                compacted_hashes=compacted_hashes,
            )
            loaded_messages, loaded_hashes = load_session_with_hashes(
                "roundtrip", tmp_path
            )

        assert loaded_messages == history
        assert loaded_hashes == compacted_hashes

    def test_round_trip_empty_history(self, tmp_path: Path):
        """Empty history survives the Rust round-trip."""

        def fake_serialize(msgs):
            return pickle.dumps(msgs)

        def fake_deserialize(data):
            return pickle.loads(data)  # noqa: S301

        with (
            patch(
                "code_puppy.session_storage.serialize_session",
                side_effect=fake_serialize,
            ),
            patch(
                "code_puppy.session_storage.deserialize_session",
                side_effect=fake_deserialize,
            ),
            patch("code_puppy.session_storage.is_rust_enabled", return_value=True),
            patch(
                "code_puppy.session_storage.serialize_messages_for_rust",
                side_effect=lambda h: h,
            ),
        ):
            save_session(
                history=[],
                session_name="empty",
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=_token_estimator,
            )
            loaded_messages, loaded_hashes = load_session_with_hashes("empty", tmp_path)

        assert loaded_messages == []
        assert loaded_hashes == []
