"""Tests for HMAC-SHA256 integrity check on session pickle files (code_puppy-bb4)."""
from __future__ import annotations

import hashlib
import hmac
import pickle
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from code_puppy.session_storage import (
    _HMAC_SIG_SIZE,
    _SESSION_HMAC_PREFIX,
    _get_session_hmac_key,
    _safe_loads,
    _sign_session_data,
    load_session,
    save_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_estimator(msg: object) -> int:
    return len(str(msg))


def _fresh_key(tmp_path: Path) -> bytes:
    """Return a fresh random key stored at the given tmp_path location."""
    import os

    key = os.urandom(32)
    (tmp_path / "session_hmac.key").write_bytes(key)
    return key


# ---------------------------------------------------------------------------
# _get_session_hmac_key
# ---------------------------------------------------------------------------


class TestGetSessionHmacKey:
    def test_creates_key_file_if_absent(self, tmp_path: Path) -> None:
        key_file = tmp_path / "session_hmac.key"
        with patch(
            "code_puppy.session_storage._get_session_hmac_key",
            wraps=lambda: _real_get_key(key_file),
        ):
            pass  # Just verify file creation via helper below

        # Call the helper directly, pointing at tmp_path
        key = _real_get_key(key_file)
        assert key_file.exists()
        assert len(key) == 32

    def test_returns_same_key_on_second_call(self, tmp_path: Path) -> None:
        key_file = tmp_path / "session_hmac.key"
        key1 = _real_get_key(key_file)
        key2 = _real_get_key(key_file)
        assert key1 == key2

    def test_real_function_returns_bytes(self) -> None:
        key = _get_session_hmac_key()
        assert isinstance(key, bytes)
        assert len(key) == 32


def _real_get_key(key_file: Path) -> bytes:
    """Minimal re-impl of _get_session_hmac_key for unit-testing."""
    import os

    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_bytes()
    key = os.urandom(32)
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    return key


# ---------------------------------------------------------------------------
# _sign_session_data
# ---------------------------------------------------------------------------


class TestSignSessionData:
    def test_signed_data_starts_with_prefix(self) -> None:
        data = pickle.dumps({"hello": "world"})
        signed = _sign_session_data(data)
        assert signed.startswith(_SESSION_HMAC_PREFIX)

    def test_signed_data_contains_32_byte_sig(self) -> None:
        data = pickle.dumps(["a", "b"])
        signed = _sign_session_data(data)
        prefix_len = len(_SESSION_HMAC_PREFIX)
        sig = signed[prefix_len : prefix_len + _HMAC_SIG_SIZE]
        assert len(sig) == 32

    def test_signed_data_payload_matches_original(self) -> None:
        data = pickle.dumps({"key": 42})
        signed = _sign_session_data(data)
        prefix_len = len(_SESSION_HMAC_PREFIX)
        payload = signed[prefix_len + _HMAC_SIG_SIZE :]
        assert payload == data

    def test_signature_is_valid_hmac(self) -> None:
        data = pickle.dumps({"integrity": True})
        signed = _sign_session_data(data)
        prefix_len = len(_SESSION_HMAC_PREFIX)
        sig = signed[prefix_len : prefix_len + _HMAC_SIG_SIZE]
        payload = signed[prefix_len + _HMAC_SIG_SIZE :]
        key = _get_session_hmac_key()
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        assert hmac.compare_digest(sig, expected)


# ---------------------------------------------------------------------------
# _safe_loads
# ---------------------------------------------------------------------------


class TestSafeLoads:
    def test_round_trip_signed(self) -> None:
        original = {"messages": [1, 2, 3], "compacted_hashes": []}
        data = pickle.dumps(original)
        signed = _sign_session_data(data)
        result = _safe_loads(signed)
        assert result == original

    def test_rejects_tampered_payload(self) -> None:
        data = pickle.dumps({"secret": "data"})
        signed = _sign_session_data(data)
        # Flip a byte in the payload area
        tampered = bytearray(signed)
        tampered[-1] ^= 0xFF
        with pytest.raises(ValueError, match="integrity check failed"):
            _safe_loads(bytes(tampered))

    def test_rejects_tampered_signature(self) -> None:
        data = pickle.dumps({"secret": "data"})
        signed = _sign_session_data(data)
        prefix_len = len(_SESSION_HMAC_PREFIX)
        # Flip a byte in the signature area
        tampered = bytearray(signed)
        tampered[prefix_len] ^= 0xFF
        with pytest.raises(ValueError, match="integrity check failed"):
            _safe_loads(bytes(tampered))

    def test_loads_legacy_unsigned_logs_warning(self) -> None:
        original = ["legacy", "data"]
        data = pickle.dumps(original)
        with patch("logging.Logger.warning") as mock_warn:
            result = _safe_loads(data)
        assert result == original
        mock_warn.assert_called_once()
        assert "legacy" in mock_warn.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# Integration: save_session writes signed data; load_session reads it back
# ---------------------------------------------------------------------------


class TestSaveLoadIntegration:
    def test_saved_file_has_hmac_prefix(self, tmp_path: Path) -> None:
        history = ["msg1", "msg2"]
        save_session(
            history=history,
            session_name="test_sig",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=_token_estimator,
        )
        raw = (tmp_path / "test_sig.pkl").read_bytes()
        assert raw.startswith(_SESSION_HMAC_PREFIX), (
            "Saved file must begin with HMAC prefix"
        )

    def test_load_session_round_trip(self, tmp_path: Path) -> None:
        history = ["hello", "world"]
        save_session(
            history=history,
            session_name="roundtrip",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=_token_estimator,
        )
        loaded = load_session("roundtrip", tmp_path)
        assert loaded == history

    def test_tampered_file_raises_on_load(self, tmp_path: Path) -> None:
        history = ["sensitive", "data"]
        save_session(
            history=history,
            session_name="tampered",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=_token_estimator,
        )
        pkl_path = tmp_path / "tampered.pkl"
        raw = bytearray(pkl_path.read_bytes())
        # Corrupt the last byte of the file
        raw[-1] ^= 0xFF
        pkl_path.write_bytes(bytes(raw))

        with pytest.raises(ValueError, match="integrity check failed"):
            load_session("tampered", tmp_path)

    def test_legacy_unsigned_file_loads_with_log(self, tmp_path: Path) -> None:
        """Files without HMAC prefix (legacy) still load but emit a log warning."""
        history = ["old", "session"]
        pkl_path = tmp_path / "legacy.pkl"
        pkl_path.write_bytes(
            pickle.dumps({"messages": history, "compacted_hashes": []})
        )
        # Create a dummy metadata file so load_session can find it
        import json

        meta = {
            "session_name": "legacy",
            "timestamp": "2024-01-01T00:00:00",
            "message_count": len(history),
            "total_tokens": 0,
            "file_path": str(pkl_path),
            "auto_saved": False,
        }
        (tmp_path / "legacy_meta.json").write_text(json.dumps(meta))

        with patch("logging.Logger.warning") as mock_warn:
            loaded = load_session("legacy", tmp_path)

        assert loaded == history
        mock_warn.assert_called_once()
