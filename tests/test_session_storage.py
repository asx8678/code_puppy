from __future__ import annotations

import json
import os
import pickle
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy import session_storage
from code_puppy.session_storage import (
    _LEGACY_SIGNATURE_SIZE,
    _LEGACY_SIGNED_HEADER,
    _SIGNED_HEADER,
    SessionSecurityError,
    cleanup_sessions,
    list_sessions,
    load_session,
    restore_autosave_interactively,
    save_session,
)


@pytest.fixture()
def history() -> list[Any]:
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
    ]


@pytest.fixture()
def token_estimator() -> Callable[[Any], int]:
    return lambda message: len(str(message))


def _signed(history: Any) -> bytes:
    """Wrap a pickle payload in the legacy unauthenticated header format."""
    return (
        _LEGACY_SIGNED_HEADER + (b"x" * _LEGACY_SIGNATURE_SIZE) + pickle.dumps(history)
    )


def _save_signed_session(
    base_dir: Path,
    name: str,
    history: list[Any],
    *,
    timestamp: str = "2024-01-01T00:00:00",
) -> None:
    save_session(
        history=history,
        session_name=name,
        base_dir=base_dir,
        timestamp=timestamp,
        token_estimator=lambda message: len(str(message)),
    )


# ---------------------------------------------------------------------------
# save / load round-trip and metadata
# ---------------------------------------------------------------------------


def test_save_and_load_session(tmp_path: Path, history, token_estimator):
    metadata = save_session(
        history=history,
        session_name="demo_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )

    assert metadata.session_name == "demo_session"
    assert metadata.message_count == len(history)
    assert metadata.total_tokens == sum(token_estimator(m) for m in history)
    assert metadata.auto_saved is False
    assert metadata.pickle_path.exists()
    assert metadata.metadata_path.exists()

    with metadata.metadata_path.open(encoding="utf-8") as meta_file:
        stored = json.load(meta_file)
    assert stored["session_name"] == "demo_session"
    assert stored["timestamp"] == "2024-01-01T00:00:00"
    assert stored["message_count"] == len(history)
    assert stored["total_tokens"] == metadata.total_tokens
    assert stored["auto_saved"] is False

    assert metadata.pickle_path.read_bytes().startswith(_SIGNED_HEADER)
    assert load_session("demo_session", tmp_path) == history


def test_save_session_auto_saved_flag(tmp_path: Path, history, token_estimator):
    metadata = save_session(
        history=history,
        session_name="auto",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
        auto_saved=True,
    )
    assert metadata.auto_saved is True
    with metadata.metadata_path.open(encoding="utf-8") as f:
        assert json.load(f)["auto_saved"] is True


def test_save_empty_session(tmp_path: Path, token_estimator):
    metadata = save_session(
        history=[],
        session_name="empty",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    assert metadata.message_count == 0
    assert metadata.total_tokens == 0
    assert metadata.pickle_path.exists()
    assert load_session("empty", tmp_path) == []


def test_save_session_token_total(tmp_path: Path):
    history = [{"role": "user", "content": "x" * 10000}]
    metadata = save_session(
        history=history,
        session_name="large",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=lambda msg: len(msg.get("content", "")),
    )
    assert metadata.message_count == 1
    assert metadata.total_tokens == 10000


def test_overwrite_existing_session(tmp_path: Path, history, token_estimator):
    save_session(
        history=["initial"],
        session_name="overwrite",
        base_dir=tmp_path,
        timestamp="2024-01-01T10:00:00",
        token_estimator=token_estimator,
    )
    new_metadata = save_session(
        history=history,
        session_name="overwrite",
        base_dir=tmp_path,
        timestamp="2024-01-01T12:00:00",
        token_estimator=token_estimator,
    )
    assert load_session("overwrite", tmp_path) == history
    assert new_metadata.timestamp == "2024-01-01T12:00:00"


@pytest.mark.parametrize(
    "payload",
    [
        # complex nested objects
        [
            {
                "role": "user",
                "content": "hello",
                "metadata": {
                    "nested": {"deeply": {"structured": "data"}},
                    "list": [1, 2, 3, {"key": "value"}],
                },
            }
        ],
        # mixed types including None, string, list, int, tuple
        [
            {"id": 1, "data": [1, 2, 3]},
            ["list", "of", "items"],
            42,
            None,
            ("tuple", "data"),
        ],
        # unicode / emoji content
        ["Hello 🐕", "Café crème", "Привет мир", "🎉 Emoji test"],
        # large history
        [f"message_{i}" for i in range(1000)],
    ],
    ids=["nested", "mixed_types", "unicode", "large"],
)
def test_save_load_preserves_data(tmp_path: Path, token_estimator, payload):
    metadata = save_session(
        history=payload,
        session_name="roundtrip",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    assert metadata.message_count == len(payload)
    assert load_session("roundtrip", tmp_path) == payload


def test_multiple_sessions_independent(tmp_path: Path, token_estimator):
    save_session(
        history=[{"content": "Session 1"}],
        session_name="session_1",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    save_session(
        history=[{"content": "Session 2"}],
        session_name="session_2",
        base_dir=tmp_path,
        timestamp="2024-01-02T00:00:00",
        token_estimator=token_estimator,
    )
    assert load_session("session_1", tmp_path)[0]["content"] == "Session 1"
    assert load_session("session_2", tmp_path)[0]["content"] == "Session 2"


def test_nested_directories_created(tmp_path: Path, history, token_estimator):
    nested_dir = tmp_path / "level1" / "level2" / "sessions"
    save_session(
        history=history,
        session_name="nested",
        base_dir=nested_dir,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    assert nested_dir.is_dir()
    assert load_session("nested", nested_dir) == history


@pytest.mark.parametrize(
    "session_name",
    ["simple", "with-dashes", "with_underscores", "with.dots", "with spaces"],
)
def test_session_name_variations(tmp_path: Path, token_estimator, session_name):
    metadata = save_session(
        history=["data"],
        session_name=session_name,
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    assert metadata.pickle_path == tmp_path / f"{session_name}.pkl"
    assert metadata.metadata_path == tmp_path / f"{session_name}_meta.json"
    assert load_session(session_name, tmp_path) == ["data"]
    assert session_name in list_sessions(tmp_path)


def test_permission_error_on_save(tmp_path: Path, history, token_estimator):
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o444)
    try:
        with pytest.raises((PermissionError, OSError)):
            save_session(
                history=history,
                session_name="perm",
                base_dir=readonly_dir,
                timestamp="2024-01-01T00:00:00",
                token_estimator=token_estimator,
            )
    finally:
        readonly_dir.chmod(0o755)


# ---------------------------------------------------------------------------
# load error handling
# ---------------------------------------------------------------------------


def test_load_corrupted_pickle_raises(tmp_path: Path):
    (tmp_path / "corrupted.pkl").write_bytes(b"this is not valid pickle data")
    with pytest.raises((ValueError, pickle.UnpicklingError, EOFError, TypeError)):
        load_session("corrupted", tmp_path)


def test_load_missing_session_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_session("nonexistent", tmp_path)


def test_load_empty_signed_pickle(tmp_path: Path):
    (tmp_path / "empty.pkl").write_bytes(_signed([]))
    assert load_session("empty", tmp_path, allow_legacy=True) == []


def test_load_signed_history_exact(tmp_path: Path):
    original = [{"id": 1, "data": [1, 2, 3]}, None, "string"]
    (tmp_path / "test.pkl").write_bytes(_signed(original))
    assert load_session("test", tmp_path, allow_legacy=True) == original


def test_legacy_signed_session_rejected_by_default(tmp_path: Path):
    (tmp_path / "legacy.pkl").write_bytes(_signed(["old"]))
    with pytest.raises(SessionSecurityError):
        load_session("legacy", tmp_path)


def test_unsigned_raw_pickle_rejected_by_default(tmp_path: Path):
    (tmp_path / "raw.pkl").write_bytes(pickle.dumps(["old"]))
    with pytest.raises(SessionSecurityError):
        load_session("raw", tmp_path)
    assert load_session("raw", tmp_path, allow_legacy=True) == ["old"]


def test_tampered_signed_session_rejected(tmp_path: Path, history, token_estimator):
    metadata = save_session(
        history=history,
        session_name="tampered",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    raw = bytearray(metadata.pickle_path.read_bytes())
    raw[-1] ^= 1
    metadata.pickle_path.write_bytes(bytes(raw))

    with pytest.raises(SessionSecurityError):
        load_session("tampered", tmp_path)


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty_and_nonexistent(tmp_path: Path):
    assert list_sessions(tmp_path) == []
    assert list_sessions(tmp_path / "nonexistent") == []


def test_list_sessions_sorted_and_ignores_non_pkl(tmp_path: Path):
    for name in ["z_session", "a_session", "m_session"]:
        (tmp_path / f"{name}.pkl").touch()
    (tmp_path / "a_session_meta.json").touch()
    (tmp_path / "random.txt").touch()
    (tmp_path / "z_session.bak").touch()

    assert list_sessions(tmp_path) == ["a_session", "m_session", "z_session"]


# ---------------------------------------------------------------------------
# cleanup_sessions
# ---------------------------------------------------------------------------


def test_cleanup_sessions_removes_oldest(tmp_path: Path, token_estimator):
    names = ["earliest", "middle", "latest"]
    for index, name in enumerate(names):
        metadata = save_session(
            history=["data"],
            session_name=name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        os.utime(metadata.pickle_path, (0, index))

    removed = cleanup_sessions(tmp_path, 2)
    assert removed == ["earliest"]
    assert sorted(list_sessions(tmp_path)) == ["latest", "middle"]


def test_cleanup_sessions_respects_max_limit(tmp_path: Path):
    for i in range(10):
        p = tmp_path / f"session_{i:02d}.pkl"
        p.touch()
        os.utime(p, (i, i))
    removed = cleanup_sessions(tmp_path, max_sessions=3)
    assert len(removed) == 7
    assert len(list_sessions(tmp_path)) == 3


def test_cleanup_removes_metadata_files(tmp_path: Path):
    (tmp_path / "old.pkl").touch()
    (tmp_path / "old_meta.json").touch()
    (tmp_path / "new.pkl").touch()
    os.utime(tmp_path / "old.pkl", (1, 1))
    os.utime(tmp_path / "old_meta.json", (1, 1))
    os.utime(tmp_path / "new.pkl", (999, 999))

    removed = cleanup_sessions(tmp_path, max_sessions=1)
    assert "old" in removed


@pytest.mark.parametrize("max_sessions", [0, -1, -5])
def test_cleanup_nonpositive_max_returns_empty(tmp_path: Path, max_sessions):
    (tmp_path / "session.pkl").write_bytes(b"dummy")
    assert cleanup_sessions(tmp_path, max_sessions) == []


def test_cleanup_nonexistent_directory(tmp_path: Path):
    assert cleanup_sessions(tmp_path / "does_not_exist", max_sessions=5) == []


def test_cleanup_fewer_than_max(tmp_path: Path):
    (tmp_path / "session1.pkl").write_bytes(b"dummy")
    (tmp_path / "session2.pkl").write_bytes(b"dummy")
    assert cleanup_sessions(tmp_path, max_sessions=10) == []
    assert len(list_sessions(tmp_path)) == 2


def test_cleanup_handles_unlink_errors(tmp_path: Path):
    # max_sessions=1 with 2 sessions forces a delete attempt; OSError must be swallowed.
    (tmp_path / "session.pkl").touch()
    (tmp_path / "other.pkl").touch()
    os.utime(tmp_path / "session.pkl", (1, 1))
    os.utime(tmp_path / "other.pkl", (999, 999))
    with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
        removed = cleanup_sessions(tmp_path, max_sessions=1)
        assert removed == []
    assert "session" in list_sessions(tmp_path)


# ---------------------------------------------------------------------------
# dataclasses / paths
# ---------------------------------------------------------------------------


def test_build_session_paths(tmp_path: Path):
    name = "session-with_special.chars"
    paths = session_storage.build_session_paths(tmp_path, name)
    assert paths.pickle_path == tmp_path / f"{name}.pkl"
    assert paths.metadata_path == tmp_path / f"{name}_meta.json"


@pytest.mark.parametrize(
    "session_name", ["../escape", "nested/name", "nested\\name", ""]
)
def test_build_session_paths_rejects_path_traversal(tmp_path: Path, session_name: str):
    with pytest.raises(ValueError):
        session_storage.build_session_paths(tmp_path, session_name)


def test_ensure_directory_creates_nested(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c" / "d"
    assert not nested.exists()
    assert session_storage.ensure_directory(nested) == nested
    assert nested.exists()


def test_session_paths_dataclass(tmp_path: Path):
    paths = session_storage.SessionPaths(
        pickle_path=tmp_path / "test.pkl",
        metadata_path=tmp_path / "test_meta.json",
    )
    assert paths.pickle_path == tmp_path / "test.pkl"
    assert paths.metadata_path == tmp_path / "test_meta.json"


def test_session_metadata_serialisation():
    metadata = session_storage.SessionMetadata(
        session_name="comprehensive_test",
        timestamp="2024-06-15T12:30:45.123456",
        message_count=42,
        total_tokens=9999,
        pickle_path=Path("/tmp/test.pkl"),
        metadata_path=Path("/tmp/test_meta.json"),
        auto_saved=True,
    )
    serialized = metadata.as_serialisable()
    assert serialized["session_name"] == "comprehensive_test"
    assert serialized["timestamp"] == "2024-06-15T12:30:45.123456"
    assert serialized["message_count"] == 42
    assert serialized["total_tokens"] == 9999
    assert serialized["auto_saved"] is True
    assert serialized["file_path"] == "/tmp/test.pkl"
    assert "metadata_path" not in serialized


# ---------------------------------------------------------------------------
# restore_autosave_interactively
# ---------------------------------------------------------------------------


def mock_interactive_imports(
    mock_input_return=None,
    mock_input_side_effect=None,
    mock_agent=None,
    capture_system=None,
    capture_warning=None,
    capture_success=None,
    mock_load_session=None,
):
    """Async context manager mocking imports used by restore_autosave_interactively."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _manager():
        mock_input = AsyncMock()
        if mock_input_side_effect:
            mock_input.side_effect = mock_input_side_effect
        elif mock_input_return is not None:
            mock_input.return_value = mock_input_return
        else:
            mock_input.return_value = ""

        agent = mock_agent or MagicMock()
        if mock_agent is None:
            agent.estimate_tokens_for_message.return_value = 10

        system_msgs = [] if capture_system is None else capture_system
        warning_msgs = [] if capture_warning is None else capture_warning
        success_msgs = [] if capture_success is None else capture_success

        patches = [
            patch(
                "code_puppy.command_line.prompt_toolkit_completion.get_input_with_combined_completion",
                mock_input,
            ),
            patch(
                "code_puppy.messaging.emit_system_message",
                side_effect=lambda msg: system_msgs.append(msg),
            ),
            patch(
                "code_puppy.messaging.emit_warning",
                side_effect=lambda msg: warning_msgs.append(msg),
            ),
            patch(
                "code_puppy.messaging.emit_success",
                side_effect=lambda msg: success_msgs.append(msg),
            ),
            patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=agent,
            ),
            patch(
                "code_puppy.config.set_current_autosave_from_session_name",
                MagicMock(),
            ),
        ]
        if mock_load_session is not None:
            patches.append(
                patch("code_puppy.session_storage.load_session", mock_load_session)
            )

        for p in patches:
            p.start()
        try:
            yield {
                "mock_input": mock_input,
                "agent": agent,
                "system_msgs": system_msgs,
                "warning_msgs": warning_msgs,
                "success_msgs": success_msgs,
            }
        finally:
            for p in patches:
                p.stop()

    return _manager()


def _write_meta_session(tmp_path: Path, name: str, meta: dict | None = None):
    (tmp_path / f"{name}.pkl").write_bytes(b"dummy")
    if meta is not None:
        (tmp_path / f"{name}_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _input_sequence(*returns):
    """Build a side_effect callable returning the given values then '' forever."""
    state = {"i": 0}

    def _fn(*args, **kwargs):
        i = state["i"]
        state["i"] += 1
        return returns[i] if i < len(returns) else ""

    return _fn


@pytest.mark.asyncio
async def test_restore_returns_early_when_no_sessions(tmp_path):
    assert await restore_autosave_interactively(tmp_path) is None


@pytest.mark.asyncio
async def test_restore_returns_early_when_directory_missing(tmp_path):
    assert await restore_autosave_interactively(tmp_path / "nope" / "path") is None


@pytest.mark.parametrize(
    "meta",
    [
        None,  # missing metadata file
        "corrupt",  # corrupted json
        {"session_name": "x"},  # missing timestamp/message_count
        {"timestamp": "not-a-valid-timestamp", "message_count": 1},  # bad timestamp
        {"timestamp": None, "message_count": 1},  # null timestamp
    ],
    ids=["missing", "corrupt", "missing_fields", "bad_timestamp", "null_timestamp"],
)
@pytest.mark.asyncio
async def test_restore_handles_metadata_edge_cases(tmp_path, meta):
    (tmp_path / "s.pkl").write_bytes(b"dummy")
    if meta == "corrupt":
        (tmp_path / "s_meta.json").write_text("not valid json{{{", encoding="utf-8")
    elif meta is not None:
        (tmp_path / "s_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    async with mock_interactive_imports(mock_input_return=""):
        assert await restore_autosave_interactively(tmp_path) is None


@pytest.mark.asyncio
async def test_restore_sorts_descending_by_timestamp(tmp_path):
    for name, ts in [
        ("old_session", "2024-01-01T00:00:00"),
        ("middle_session", "2024-06-15T12:00:00"),
        ("new_session", "2024-12-31T23:59:59"),
    ]:
        _write_meta_session(tmp_path, name, {"timestamp": ts, "message_count": 5})

    displayed = []
    async with mock_interactive_imports(mock_input_return="", capture_system=displayed):
        await restore_autosave_interactively(tmp_path)

    session_lines = [s for s in displayed if "[" in s and "]" in s]
    assert any("new_session" in line for line in session_lines[:3])


@pytest.mark.asyncio
async def test_restore_displays_count_and_timestamp(tmp_path):
    _write_meta_session(
        tmp_path, "formatted", {"timestamp": "2024-06-15T14:30:00", "message_count": 42}
    )
    displayed = []
    async with mock_interactive_imports(mock_input_return="", capture_system=displayed):
        await restore_autosave_interactively(tmp_path)
    combined = " ".join(displayed)
    assert "42 messages" in combined
    assert "2024-06-15T14:30:00" in combined


@pytest.mark.asyncio
async def test_restore_displays_unknown_for_missing_metadata(tmp_path):
    (tmp_path / "missing_info.pkl").write_bytes(b"dummy")
    displayed = []
    async with mock_interactive_imports(mock_input_return="", capture_system=displayed):
        await restore_autosave_interactively(tmp_path)
    assert "unknown" in " ".join(displayed).lower()


@pytest.mark.asyncio
async def test_restore_shows_pagination_for_more_than_five(tmp_path):
    for i in range(8):
        _write_meta_session(
            tmp_path,
            f"session_{i}",
            {"timestamp": f"2024-01-0{i + 1}T00:00:00", "message_count": i},
        )
    displayed = []
    async with mock_interactive_imports(mock_input_return="", capture_system=displayed):
        await restore_autosave_interactively(tmp_path)
    assert "[6]" in " ".join(displayed)


@pytest.mark.asyncio
async def test_restore_no_pagination_for_five_or_fewer(tmp_path):
    for i in range(5):
        _write_meta_session(
            tmp_path,
            f"session_{i}",
            {"timestamp": f"2024-01-0{i + 1}T00:00:00", "message_count": i},
        )
    displayed = []
    async with mock_interactive_imports(mock_input_return="", capture_system=displayed):
        await restore_autosave_interactively(tmp_path)
    assert not [m for m in displayed if "[6]" in m]


@pytest.mark.asyncio
async def test_restore_page_navigation_cycles(tmp_path):
    for i in range(8):
        _write_meta_session(
            tmp_path,
            f"session_{i}",
            {"timestamp": f"2024-01-{i + 1:02d}T00:00:00", "message_count": i},
        )
    seq = _input_sequence("6", "6")  # next page, then wrap, then skip
    async with mock_interactive_imports(mock_input_side_effect=seq):
        result = await restore_autosave_interactively(tmp_path)
    assert result is None


@pytest.mark.asyncio
async def test_restore_last_page_shows_return_to_first(tmp_path):
    for i in range(7):
        _write_meta_session(
            tmp_path,
            f"session_{i}",
            {"timestamp": f"2024-01-{i + 1:02d}T00:00:00", "message_count": i},
        )
    displayed = []
    async with mock_interactive_imports(
        mock_input_side_effect=_input_sequence("6"), capture_system=displayed
    ):
        await restore_autosave_interactively(tmp_path)
    assert "Return to first page" in " ".join(displayed)


@pytest.mark.parametrize("selection", ["1", "my_specific_session"])
@pytest.mark.asyncio
async def test_restore_numeric_and_name_selection_loads(tmp_path, selection):
    history = [{"role": "user", "content": "test message"}]
    _save_signed_session(tmp_path, "my_specific_session", history)
    (tmp_path / "my_specific_session_meta.json").write_text(
        json.dumps({"timestamp": "2024-01-01T00:00:00", "message_count": 1}),
        encoding="utf-8",
    )
    mock_agent = MagicMock()
    mock_agent.estimate_tokens_for_message.return_value = 10
    async with mock_interactive_imports(
        mock_input_return=selection, mock_agent=mock_agent
    ):
        await restore_autosave_interactively(tmp_path)
    mock_agent.set_message_history.assert_called_once_with(history)


@pytest.mark.asyncio
async def test_restore_empty_selection_skips(tmp_path):
    _write_meta_session(
        tmp_path, "session", {"timestamp": "2024-01-01T00:00:00", "message_count": 1}
    )
    async with mock_interactive_imports(mock_input_return=""):
        assert await restore_autosave_interactively(tmp_path) is None


@pytest.mark.parametrize(
    "setup_count,seq",
    [
        # invalid numeric selection out of listing range
        (1, ["9"]),
        # invalid name
        (1, ["nonexistent_session"]),
        # 6 invalid when no more pages
        (3, ["6"]),
        # 5 invalid on partial second page (7 sessions -> page 2 has 2)
        (7, ["6", "5"]),
    ],
    ids=["bad_numeric", "bad_name", "page6_no_pages", "out_of_range_partial_page"],
)
@pytest.mark.asyncio
async def test_restore_invalid_selections_warn(tmp_path, setup_count, seq):
    for i in range(setup_count):
        _write_meta_session(
            tmp_path,
            f"session_{i}" if setup_count > 1 else "session",
            {"timestamp": f"2024-01-{i + 1:02d}T00:00:00", "message_count": i},
        )
    warnings = []
    async with mock_interactive_imports(
        mock_input_side_effect=_input_sequence(*seq), capture_warning=warnings
    ):
        await restore_autosave_interactively(tmp_path)
    assert any("invalid" in w.lower() for w in warnings)


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), EOFError()])
@pytest.mark.asyncio
async def test_restore_interrupt_cancels(tmp_path, exc):
    _write_meta_session(
        tmp_path, "session", {"timestamp": "2024-01-01T00:00:00", "message_count": 1}
    )
    warnings = []
    async with mock_interactive_imports(
        mock_input_side_effect=exc, capture_warning=warnings
    ):
        result = await restore_autosave_interactively(tmp_path)
    assert result is None
    assert any("cancelled" in w.lower() for w in warnings)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (FileNotFoundError("Session file deleted"), "could not be found"),
        (Exception("Corrupted pickle"), "Failed to load"),
    ],
    ids=["file_not_found", "generic_exception"],
)
@pytest.mark.asyncio
async def test_restore_load_errors_warn(tmp_path, exc, expected):
    _write_meta_session(
        tmp_path, "session", {"timestamp": "2024-01-01T00:00:00", "message_count": 1}
    )
    warnings = []
    async with mock_interactive_imports(
        mock_input_return="1",
        capture_warning=warnings,
        mock_load_session=MagicMock(side_effect=exc),
    ):
        result = await restore_autosave_interactively(tmp_path)
    assert result is None
    assert any(expected.lower() in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_restore_set_autosave_id_failure_ignored(tmp_path):
    history = [{"role": "user", "content": "test"}]
    _save_signed_session(tmp_path, "session", history)
    (tmp_path / "session_meta.json").write_text(
        json.dumps({"timestamp": "2024-01-01T00:00:00", "message_count": 1}),
        encoding="utf-8",
    )
    mock_agent = MagicMock()
    mock_agent.estimate_tokens_for_message.return_value = 5
    with patch(
        "code_puppy.config.set_current_autosave_from_session_name",
        side_effect=Exception("Config error"),
    ):
        async with mock_interactive_imports(
            mock_input_return="1", mock_agent=mock_agent
        ):
            await restore_autosave_interactively(tmp_path)
    mock_agent.set_message_history.assert_called_once()


@pytest.mark.asyncio
async def test_restore_success_emits_message(tmp_path):
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    _save_signed_session(tmp_path, "success", history)
    (tmp_path / "success_meta.json").write_text(
        json.dumps({"timestamp": "2024-01-01T00:00:00", "message_count": 2}),
        encoding="utf-8",
    )
    mock_agent = MagicMock()
    mock_agent.estimate_tokens_for_message.return_value = 10
    success_messages = []
    async with mock_interactive_imports(
        mock_input_return="1", mock_agent=mock_agent, capture_success=success_messages
    ):
        await restore_autosave_interactively(tmp_path)
    assert len(success_messages) == 1
    msg = success_messages[0]
    assert "2 messages" in msg
    assert "20 tokens" in msg
    assert "✅" in msg
