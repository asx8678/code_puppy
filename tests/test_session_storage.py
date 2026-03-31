from __future__ import annotations

import json
import os
import pickle
import warnings
from pathlib import Path
from typing import Callable, List

import msgpack
import pytest

from code_puppy.session_storage import (
    _safe_loads,
    cleanup_sessions,
    list_sessions,
    load_session,
    load_session_with_hashes,
    save_session,
)


@pytest.fixture()
def history() -> List[str]:
    return ["one", "two", "three"]


@pytest.fixture()
def token_estimator() -> Callable[[object], int]:
    return lambda message: len(str(message))


def test_save_and_load_session(tmp_path: Path, history: List[str], token_estimator):
    session_name = "demo_session"
    timestamp = "2024-01-01T00:00:00"
    metadata = save_session(
        history=history,
        session_name=session_name,
        base_dir=tmp_path,
        timestamp=timestamp,
        token_estimator=token_estimator,
    )

    assert metadata.session_name == session_name
    assert metadata.message_count == len(history)
    assert metadata.total_tokens == sum(token_estimator(m) for m in history)
    assert metadata.pickle_path.exists()
    assert metadata.metadata_path.exists()

    with metadata.metadata_path.open() as meta_file:
        stored = json.load(meta_file)
    assert stored["session_name"] == session_name
    assert stored["auto_saved"] is False

    loaded_history = load_session(session_name, tmp_path)
    assert loaded_history == history


def test_list_sessions(tmp_path: Path, history: List[str], token_estimator):
    names = ["beta", "alpha", "gamma"]
    for name in names:
        save_session(
            history=history,
            session_name=name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

    assert list_sessions(tmp_path) == sorted(names)


def test_cleanup_sessions(tmp_path: Path, history: List[str], token_estimator):
    session_names = ["session_earliest", "session_middle", "session_latest"]
    for index, name in enumerate(session_names):
        metadata = save_session(
            history=history,
            session_name=name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        os.utime(metadata.pickle_path, (0, index))

    removed = cleanup_sessions(tmp_path, 2)
    assert removed == ["session_earliest"]
    remaining = list_sessions(tmp_path)
    assert sorted(remaining) == sorted(["session_middle", "session_latest"])


# ---------------------------------------------------------------------------
# MessagePack format tests
# ---------------------------------------------------------------------------

def test_save_session_writes_msgpack_format(tmp_path: Path, history: List[str], token_estimator):
    """Verify that save_session writes MessagePack data, not pickle."""
    metadata = save_session(
        history=history,
        session_name="msgpack_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    raw = metadata.pickle_path.read_bytes()
    # Should be valid MessagePack
    data = msgpack.unpackb(raw, raw=False)
    assert "messages" in data
    assert data["messages"] == history
    # Should NOT be a pickle (pickle files start with specific opcodes)
    assert not raw.startswith(b"\x80")  # pickle protocol magic byte


def test_save_session_writes_compacted_hashes(tmp_path: Path, history: List[str], token_estimator):
    """Verify that compacted_hashes are preserved across save/load."""
    hashes = ["abc123", "def456"]
    save_session(
        history=history,
        session_name="hash_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
        compacted_hashes=hashes,
    )
    loaded_history, loaded_hashes = load_session_with_hashes("hash_session", tmp_path)
    assert loaded_history == history
    assert loaded_hashes == hashes


def test_load_session_msgpack_round_trip(tmp_path: Path, history: List[str], token_estimator):
    """Full round-trip: save with MessagePack, load back, check equality."""
    save_session(
        history=history,
        session_name="roundtrip_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    loaded = load_session("roundtrip_session", tmp_path)
    assert loaded == history


# ---------------------------------------------------------------------------
# Legacy pickle fallback tests
# ---------------------------------------------------------------------------

def test_safe_loads_falls_back_to_pickle_with_warning():
    """_safe_loads() should fall back to pickle and emit a DeprecationWarning."""
    payload = {"messages": ["hello", "world"], "compacted_hashes": []}
    legacy_bytes = pickle.dumps(payload)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _safe_loads(legacy_bytes)

    assert result == payload
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1
    assert "pickle" in str(deprecation_warnings[0].message).lower()


def test_safe_loads_prefers_msgpack():
    """_safe_loads() should use MessagePack without any warning for new data."""
    payload = {"messages": ["a", "b"], "compacted_hashes": ["x"]}
    msgpack_bytes = msgpack.packb(payload, use_bin_type=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _safe_loads(msgpack_bytes)

    assert result == payload
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 0


def test_load_session_legacy_pickle_file(tmp_path: Path, token_estimator):
    """Loading a .pkl file that contains pickle bytes should work with a warning."""
    history = ["msg1", "msg2"]
    payload = {"messages": history, "compacted_hashes": []}
    pkl_path = tmp_path / "legacy_session.pkl"
    pkl_path.write_bytes(pickle.dumps(payload))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loaded = load_session("legacy_session", tmp_path)

    assert loaded == history
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecation_warnings) == 1


def test_load_session_legacy_pickle_list_format(tmp_path: Path):
    """Legacy sessions that stored a plain list (not dict) should also load."""
    history = ["old_msg_1", "old_msg_2"]
    pkl_path = tmp_path / "plain_list_session.pkl"
    pkl_path.write_bytes(pickle.dumps(history))

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        loaded = load_session("plain_list_session", tmp_path)

    assert loaded == history
