from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, List

import msgpack
import pytest

from code_puppy.session_storage import (
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


@pytest.fixture()
def pydantic_history():
    """Realistic message history with pydantic-ai objects."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    return [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(
            parts=[
                TextPart(content="I'll read that file"),
                ToolCallPart(
                    tool_name="read_file",
                    args={"path": "foo.py"},
                    tool_call_id="tc-1",
                ),
            ],
            model_name="test-model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="print('hello')",
                    tool_call_id="tc-1",
                ),
            ]
        ),
        ModelResponse(
            parts=[TextPart(content="The file prints hello")],
            model_name="test-model",
        ),
    ]


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


# ---- New pydantic-ai tests ----


def test_save_session_with_pydantic_messages(
    tmp_path, pydantic_history, token_estimator
):
    """Verify that pydantic-ai ModelRequest/ModelResponse objects serialize correctly."""
    metadata = save_session(
        history=pydantic_history,
        session_name="pydantic_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    assert metadata.message_count == 4

    # Verify the on-disk bytes are valid msgpack (strip the magic header first)
    from code_puppy.session_storage import _MSGPACK_MAGIC

    raw = metadata.pickle_path.read_bytes()
    assert raw.startswith(_MSGPACK_MAGIC), "File should start with msgpack magic header"
    data = msgpack.unpackb(raw[len(_MSGPACK_MAGIC) :], raw=False)
    assert len(data["messages"]) == 4
    # Each message should be a dict with 'kind' field
    assert data["messages"][0]["kind"] == "request"
    assert data["messages"][1]["kind"] == "response"


def test_pydantic_messages_round_trip(tmp_path, pydantic_history, token_estimator):
    """Full round-trip: save pydantic objects, load them back, verify types and content."""
    from pydantic_ai.messages import ModelRequest, ModelResponse

    save_session(
        history=pydantic_history,
        session_name="rt_session",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
    )
    loaded = load_session("rt_session", tmp_path)
    assert len(loaded) == 4
    # Check types are reconstructed
    assert isinstance(loaded[0], ModelRequest)
    assert isinstance(loaded[1], ModelResponse)
    assert isinstance(loaded[2], ModelRequest)
    assert isinstance(loaded[3], ModelResponse)
    # Check content preserved
    assert loaded[0].parts[0].content == "hello"
    assert loaded[1].parts[0].content == "I'll read that file"
    assert loaded[1].parts[1].tool_name == "read_file"
    assert loaded[2].parts[0].tool_call_id == "tc-1"


def test_pydantic_messages_with_compacted_hashes(
    tmp_path, pydantic_history, token_estimator
):
    """Verify compacted hashes round-trip with pydantic message objects."""
    from pydantic_ai.messages import ModelRequest

    hashes = ["hash1", "hash2"]
    save_session(
        history=pydantic_history,
        session_name="hash_pydantic",
        base_dir=tmp_path,
        timestamp="2024-01-01T00:00:00",
        token_estimator=token_estimator,
        compacted_hashes=hashes,
    )
    loaded_history, loaded_hashes = load_session_with_hashes("hash_pydantic", tmp_path)
    assert len(loaded_history) == 4
    assert isinstance(loaded_history[0], ModelRequest)
    assert loaded_hashes == hashes

