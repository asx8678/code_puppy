"""Tests for HMAC-SHA256 integrity check on session files (msgpack format)."""

import hmac
import pickle
import warnings
from pathlib import Path

import msgpack
import pytest

from unittest.mock import patch

from code_puppy.session_storage import (
    _MSGPACK_MAGIC,
    _compute_hmac,
    _load_raw_bytes,
    load_session,
    save_session,
)

# Fixed 32-byte test key used to mock the per-install HMAC key
_TEST_HMAC_KEY = b"a" * 32


@pytest.fixture(autouse=True)
def _mock_hmac_key():
    """Patch _get_hmac_key so tests don't touch the real filesystem key."""
    with patch("code_puppy.session_storage._get_hmac_key", return_value=_TEST_HMAC_KEY):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_estimator(msg: object) -> int:
    return len(str(msg))


def _make_msgpack_data(data: dict) -> bytes:
    """Create properly formatted msgpack session data with HMAC."""
    msgpack_bytes = msgpack.packb(data, use_bin_type=True)
    hmac_sig = _compute_hmac(_TEST_HMAC_KEY, msgpack_bytes)
    return _MSGPACK_MAGIC + hmac_sig + msgpack_bytes


# ---------------------------------------------------------------------------
# _compute_hmac
# ---------------------------------------------------------------------------


class TestComputeHmac:
    def test_returns_32_bytes(self) -> None:
        """HMAC-SHA256 should return 32 bytes."""
        data = b"test data"
        result = _compute_hmac(b"key", data)
        assert len(result) == 32
        assert isinstance(result, bytes)

    def test_same_input_same_output(self) -> None:
        """HMAC should be deterministic for same input."""
        data = b"consistent"
        hmac1 = _compute_hmac(b"key", data)
        hmac2 = _compute_hmac(b"key", data)
        assert hmac1 == hmac2

    def test_different_key_different_hmac(self) -> None:
        """Different keys should produce different HMACs."""
        data = b"test"
        hmac1 = _compute_hmac(b"key1", data)
        hmac2 = _compute_hmac(b"key2", data)
        assert hmac1 != hmac2


# ---------------------------------------------------------------------------
# _load_raw_bytes
# ---------------------------------------------------------------------------


class TestLoadRawBytes:
    def test_loads_valid_msgpack_with_hmac(self) -> None:
        """Valid msgpack format with correct HMAC loads successfully."""
        original = {"messages": [1, 2, 3], "compacted_hashes": []}
        raw = _make_msgpack_data(original)
        result = _load_raw_bytes(raw)
        assert result == original

    def test_rejects_tampered_payload(self) -> None:
        """Tampering with payload bytes should raise ValueError."""
        original = {"secret": "data"}
        raw = bytearray(_make_msgpack_data(original))
        # Flip a byte in the payload area (after magic + hmac)
        raw[-1] ^= 0xFF
        with pytest.raises(ValueError, match="HMAC integrity check failed"):
            _load_raw_bytes(bytes(raw))

    def test_rejects_tampered_hmac(self) -> None:
        """Tampering with HMAC bytes should raise ValueError."""
        original = {"secret": "data"}
        raw = bytearray(_make_msgpack_data(original))
        # Flip a byte in the HMAC area (after magic, before payload)
        raw[len(_MSGPACK_MAGIC)] ^= 0xFF
        with pytest.raises(ValueError, match="HMAC integrity check failed"):
            _load_raw_bytes(bytes(raw))

    def test_loads_legacy_signed_format_raises_error(self) -> None:
        """Legacy CPSESSION format is rejected for security (RCE vulnerability fix #zvx9)."""
        from code_puppy.session_storage import _LEGACY_SIGNED_HEADER

        original = {"messages": ["legacy"], "compacted_hashes": []}
        pickle_data = pickle.dumps(original)
        legacy_sig = _compute_hmac(b"", pickle_data)
        raw = _LEGACY_SIGNED_HEADER + legacy_sig + pickle_data

        with pytest.raises(ValueError, match="Legacy pickle session format is no longer supported"):
            _load_raw_bytes(raw)

    def test_loads_plain_pickle_raises_error(self) -> None:
        """Plain pickle format is rejected for security (RCE vulnerability fix #zvx9)."""
        original = ["plain", "pickle"]
        raw = pickle.dumps(original)

        with pytest.raises(ValueError, match="Legacy pickle session format is no longer supported"):
            _load_raw_bytes(raw)


# ---------------------------------------------------------------------------
# Integration: save_session writes HMAC data; load_session reads it back
# ---------------------------------------------------------------------------


class TestSaveLoadIntegration:
    def test_saved_file_has_msgpack_magic(self, tmp_path: Path) -> None:
        """Saved file must begin with MSGPACK magic header."""
        history = ["msg1", "msg2"]
        save_session(
            history=history,
            session_name="test_sig",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=_token_estimator,
        )
        raw = (tmp_path / "test_sig.pkl").read_bytes()
        assert raw.startswith(_MSGPACK_MAGIC), (
            "Saved file must begin with MSGPACK magic header"
        )

    def test_saved_file_has_valid_hmac(self, tmp_path: Path) -> None:
        """Saved file must have valid HMAC that verifies."""
        history = ["msg1", "msg2"]
        save_session(
            history=history,
            session_name="test_hmac",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=_token_estimator,
        )
        raw = (tmp_path / "test_hmac.pkl").read_bytes()

        # Verify structure: MAGIC + HMAC(32) + msgpack
        assert raw.startswith(_MSGPACK_MAGIC)
        offset = len(_MSGPACK_MAGIC)
        stored_hmac = raw[offset : offset + 32]
        msgpack_data = raw[offset + 32 :]

        # Verify HMAC
        expected_hmac = _compute_hmac(_TEST_HMAC_KEY, msgpack_data)
        assert hmac.compare_digest(stored_hmac, expected_hmac)

    def test_load_session_round_trip(self, tmp_path: Path) -> None:
        """Save and load should preserve history."""
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
        """Tampered file should raise ValueError on load."""
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

        with pytest.raises(ValueError, match="HMAC integrity check failed"):
            load_session("tampered", tmp_path)

    def test_legacy_unsigned_file_raises_error(self, tmp_path: Path) -> None:
        """Files without HMAC (legacy pickle) are rejected for security (RCE vulnerability fix #zvx9)."""
        history = ["old", "session"]
        pkl_path = tmp_path / "legacy.pkl"
        # Write plain pickle data (legacy format)
        pkl_path.write_bytes(
            pickle.dumps({"messages": history, "compacted_hashes": []})
        )
        # Create a dummy metadata file so load_session can find it
        meta = {
            "session_name": "legacy",
            "timestamp": "2024-01-01T00:00:00",
            "message_count": len(history),
            "total_tokens": 0,
            "file_path": str(pkl_path),
            "auto_saved": False,
        }
        (tmp_path / "legacy_meta.json").write_text(__import__("json").dumps(meta))

        with pytest.raises(ValueError, match="Legacy pickle session format is no longer supported"):
            load_session("legacy", tmp_path)


class TestPreHmacMsgpackCompat:
    """Tests for backward compatibility with pre-HMAC msgpack session files."""

    def test_loads_pre_hmac_msgpack_with_warning(self) -> None:
        """Pre-HMAC msgpack files (MAGIC + raw msgpack, no HMAC) load with deprecation warning."""
        original = {"messages": ["old", "session"], "compacted_hashes": []}
        # Build pre-HMAC format: MAGIC + msgpack (no HMAC)
        msgpack_bytes = msgpack.packb(original, use_bin_type=True)
        raw = _MSGPACK_MAGIC + msgpack_bytes

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _load_raw_bytes(raw)
            assert result == original
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "pre-hmac" in str(w[0].message).lower()

    def test_pre_hmac_msgpack_preserves_complex_data(self) -> None:
        """Pre-HMAC fallback correctly deserializes non-trivial payloads."""
        original = {
            "messages": [
                {"kind": "request", "parts": [{"content": "hello"}]},
                {"kind": "response", "parts": [{"content": "world"}]},
            ],
            "compacted_hashes": ["abc123", "def456"],
        }
        msgpack_bytes = msgpack.packb(original, use_bin_type=True)
        raw = _MSGPACK_MAGIC + msgpack_bytes

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = _load_raw_bytes(raw)
            assert result == original

    def test_rejects_corrupted_pre_hmac_msgpack(self) -> None:
        """Corrupted pre-HMAC msgpack files still raise ValueError."""
        # Build something that starts with MAGIC but has garbage after
        raw = _MSGPACK_MAGIC + b"\xff\xfe\xfd" * 20
        with pytest.raises(ValueError, match="HMAC integrity check failed"):
            _load_raw_bytes(raw)

    def test_valid_hmac_still_preferred_over_fallback(self) -> None:
        """Files with valid HMAC load via the primary path, not the fallback."""
        original = {"messages": ["new"], "compacted_hashes": []}
        raw = _make_msgpack_data(original)

        # Should load without any deprecation warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _load_raw_bytes(raw)
            assert result == original
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0


# ---------------------------------------------------------------------------
# delete_hmac_key tests
# ---------------------------------------------------------------------------
# NOTE: delete_hmac_key function does not exist in the current implementation.
# These tests are disabled until the feature is implemented.
# See issue: security key rotation/deletion functionality


@pytest.mark.skip(reason="delete_hmac_key function not implemented")
class TestDeleteHmacKey:
    """Tests for secure HMAC key deletion with fsync'd overwrite."""

    def test_delete_hmac_key_returns_false_when_file_does_not_exist(
        self, tmp_path: Path
    ) -> None:
        """delete_hmac_key() returns False when key file doesn't exist."""
        from code_puppy.session_storage import delete_hmac_key
        from unittest.mock import patch

        # Patch DATA_DIR to use a temp directory where the key doesn't exist
        with patch("code_puppy.config.DATA_DIR", str(tmp_path)):
            result = delete_hmac_key()
            assert result is False

    def test_delete_hmac_key_returns_true_and_file_is_gone_after_deletion(
        self, tmp_path: Path
    ) -> None:
        """delete_hmac_key() returns True and the file is actually deleted."""
        from code_puppy.session_storage import delete_hmac_key
        from unittest.mock import patch

        # Create a key file in the temp directory
        key_path = tmp_path / ".session_hmac_key"
        key_path.write_bytes(b"x" * 32)
        assert key_path.exists()

        # Patch DATA_DIR to use the temp directory
        with patch("code_puppy.config.DATA_DIR", str(tmp_path)):
            result = delete_hmac_key()
            assert result is True
            assert not key_path.exists(), "Key file should be deleted"
