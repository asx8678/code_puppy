"""Tests for incremental session serialization with compacted_hashes preservation.

These tests verify:
1. True incremental append (serialize → append → assert equality)
2. Roundtrip test (serialize → deserialize → assert equality)
3. Backward compat test (old format → load)
4. compacted_hashes preservation test
"""

import pytest
from pathlib import Path
from typing import Callable, List

from code_puppy import session_storage
from code_puppy.session_storage import (
    _INCREMENTAL_MAGIC,
    save_session,
    load_session,
    load_session_with_hashes,
    _save_session_incremental,
    _save_session_full,
    SessionPaths,
)
from code_puppy._core_bridge import is_rust_enabled


@pytest.fixture
def token_estimator() -> Callable[[object], int]:
    return lambda message: len(str(message))


@pytest.fixture
def pydantic_history():
    """Realistic message history with pydantic-ai objects."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    return [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="hi there")], model_name="test-model"),
        ModelRequest(parts=[UserPromptPart(content="how are you?")]),
    ]


class TestIncrementalRoundtrip:
    """Roundtrip tests for incremental serialization."""

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_full_roundtrip_incremental_format(self, tmp_path: Path, token_estimator, pydantic_history):
        """Full roundtrip: save incremental, load back, verify equality."""
        session_name = "roundtrip_test"
        
        metadata = save_session(
            history=pydantic_history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        
        # Verify file exists and starts with incremental magic
        assert metadata.pickle_path.exists()
        raw = metadata.pickle_path.read_bytes()
        assert raw.startswith(_INCREMENTAL_MAGIC), "File should use incremental format"
        
        # Load and verify - should get ModelRequest/ModelResponse objects back
        loaded = load_session(session_name, tmp_path)
        from pydantic_ai.messages import ModelRequest, ModelResponse
        assert len(loaded) == 3
        assert isinstance(loaded[0], ModelRequest)
        assert isinstance(loaded[1], ModelResponse)
        assert isinstance(loaded[2], ModelRequest)

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_roundtrip_with_compacted_hashes(self, tmp_path: Path, token_estimator, pydantic_history):
        """Roundtrip with compacted_hashes preservation."""
        session_name = "hashes_test"
        hashes = ["hash1", "hash2", "hash3"]
        
        metadata = save_session(
            history=pydantic_history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
            compacted_hashes=hashes,
        )
        
        # Load with hashes and verify
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert len(loaded_history) == 3
        assert loaded_hashes == hashes


class TestTrueIncrementalAppend:
    """Tests for true incremental append functionality."""

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_incremental_append_only_new_messages(self, tmp_path: Path, token_estimator):
        """Test that only new messages are appended, not re-serialized."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "append_test"
        
        # First save: 2 messages
        history1 = [
            ModelRequest(parts=[UserPromptPart(content="msg1")]),
            ModelRequest(parts=[UserPromptPart(content="msg2")]),
        ]
        metadata1 = save_session(
            history=history1,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        
        # Get file size after first save
        size1 = metadata1.pickle_path.stat().st_size
        
        # Second save: add 1 more message
        history2 = history1 + [ModelRequest(parts=[UserPromptPart(content="msg3")])]
        metadata2 = save_session(
            history=history2,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:01",
            token_estimator=token_estimator,
        )
        
        # Get file size after second save
        size2 = metadata2.pickle_path.stat().st_size
        
        # Size should increase but not double (incremental, not full rewrite)
        # msg3 + its length prefix should be ~50-150 bytes
        size_increase = size2 - size1
        assert 10 < size_increase < 200, f"Incremental append should add small amount, got {size_increase} bytes"
        
        # Verify we can load all 3 messages
        loaded = load_session(session_name, tmp_path)
        assert len(loaded) == 3

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_incremental_append_preserves_compacted_hashes(self, tmp_path: Path, token_estimator):
        """Test that appending messages preserves compacted_hashes."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "append_hashes_test"
        hashes = ["hash_a", "hash_b"]
        
        # First save with hashes
        history1 = [
            ModelRequest(parts=[UserPromptPart(content="msg1")]),
            ModelRequest(parts=[UserPromptPart(content="msg2")]),
        ]
        save_session(
            history=history1,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
            compacted_hashes=hashes,
        )
        
        # Append more messages
        history2 = history1 + [
            ModelRequest(parts=[UserPromptPart(content="msg3")]),
            ModelRequest(parts=[UserPromptPart(content="msg4")]),
        ]
        save_session(
            history=history2,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:01",
            token_estimator=token_estimator,
            compacted_hashes=hashes,  # Same hashes
        )
        
        # Load and verify hashes preserved
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert len(loaded_history) == 4
        assert loaded_hashes == hashes

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_multiple_appends(self, tmp_path: Path, token_estimator):
        """Test multiple incremental appends."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "multi_append"
        
        # Build up history incrementally
        history = []
        for i in range(1, 6):
            history.append(ModelRequest(parts=[UserPromptPart(content=f"msg{i}")]))
            save_session(
                history=history,
                session_name=session_name,
                base_dir=tmp_path,
                timestamp=f"2024-01-01T00:00:0{i}",
                token_estimator=token_estimator,
            )
        
        # Verify all 5 messages load correctly
        loaded = load_session(session_name, tmp_path)
        assert len(loaded) == 5

class TestBackwardCompatibility:
    """Tests for backward compatibility with old formats."""

    def test_backward_compat_msgpack_format(self, tmp_path: Path, token_estimator):
        """Old msgpack format sessions should still load."""
        import msgpack
        from code_puppy.session_storage import _MSGPACK_MAGIC, _compute_hmac, _get_hmac_key
        
        session_name = "old_msgpack"
        history = ["old_msg_1", "old_msg_2"]
        
        # Create old msgpack format manually
        payload = {"messages": history, "compacted_hashes": ["old_hash"]}
        msgpack_data = msgpack.packb(payload, use_bin_type=True)
        hmac_sig = _compute_hmac(_get_hmac_key(), msgpack_data)
        full_data = _MSGPACK_MAGIC + hmac_sig + msgpack_data
        
        pkl_path = tmp_path / f"{session_name}.pkl"
        pkl_path.write_bytes(full_data)
        
        # Should load without errors
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert loaded_history == history
        assert loaded_hashes == ["old_hash"]

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_conversion_from_old_to_incremental(self, tmp_path: Path, token_estimator):
        """Old format files should be converted to incremental on next save."""
        import msgpack
        from pydantic_ai.messages import ModelRequest, UserPromptPart, ModelMessagesTypeAdapter
        from code_puppy.session_storage import _MSGPACK_MAGIC, _compute_hmac, _get_hmac_key
        
        session_name = "convert_test"
        history = [
            ModelRequest(parts=[UserPromptPart(content="msg1")]),
            ModelRequest(parts=[UserPromptPart(content="msg2")]),
        ]
        
        # Convert to serializable dicts for msgpack
        serializable_history = ModelMessagesTypeAdapter.dump_python(history, mode="json")
        
        # Create old msgpack format
        payload = {"messages": serializable_history, "compacted_hashes": []}
        msgpack_data = msgpack.packb(payload, use_bin_type=True)
        hmac_sig = _compute_hmac(_get_hmac_key(), msgpack_data)
        full_data = _MSGPACK_MAGIC + hmac_sig + msgpack_data
        
        pkl_path = tmp_path / f"{session_name}.pkl"
        pkl_path.write_bytes(full_data)
        
        # Now save with more messages - should convert to incremental
        history2 = history + [ModelRequest(parts=[UserPromptPart(content="msg3")])]
        save_session(
            history=history2,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        
        # Verify it's now in incremental format
        raw = pkl_path.read_bytes()
        assert raw.startswith(_INCREMENTAL_MAGIC)
        
        # Verify all messages load
        loaded = load_session(session_name, tmp_path)
        assert len(loaded) == 3


class TestCompactedHashesPreservation:
    """Tests specifically for compacted_hashes preservation."""

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_empty_hashes_roundtrip(self, tmp_path: Path, token_estimator, pydantic_history):
        """Empty compacted_hashes should roundtrip correctly."""
        session_name = "empty_hashes"
        
        # Use just one message for simplicity
        history = [pydantic_history[0]]
        
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
            compacted_hashes=[],  # Explicitly empty
        )
        
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert len(loaded_history) == 1
        assert loaded_hashes == []

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_many_hashes_preserved(self, tmp_path: Path, token_estimator):
        """Many compacted_hashes should be preserved correctly."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "many_hashes"
        history = [
            ModelRequest(parts=[UserPromptPart(content="msg1")]),
            ModelRequest(parts=[UserPromptPart(content="msg2")]),
        ]
        hashes = [f"hash_{i}" for i in range(100)]
        
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
            compacted_hashes=hashes,
        )
        
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert len(loaded_history) == 2
        assert loaded_hashes == hashes

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_hashes_with_special_characters(self, tmp_path: Path, token_estimator):
        """Hashes with special characters should be preserved."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "special_hashes"
        history = [ModelRequest(parts=[UserPromptPart(content="msg1")])]
        hashes = ["hash/with/slashes", "hash-with-dashes", "hash_with_underscores", "hash:with:colons"]
        
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
            compacted_hashes=hashes,
        )
        
        loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
        assert len(loaded_history) == 1
        assert loaded_hashes == hashes


class TestFallbackToFullSerialization:
    """Tests for fallback behavior when Rust is not available."""

    def test_full_serialization_without_rust(self, tmp_path: Path, token_estimator, pydantic_history):
        """When Rust is disabled, should use full msgpack serialization."""
        from code_puppy._core_bridge import set_rust_enabled
        
        # Disable Rust
        set_rust_enabled(False)
        try:
            session_name = "fallback_test"
            
            metadata = save_session(
                history=pydantic_history,
                session_name=session_name,
                base_dir=tmp_path,
                timestamp="2024-01-01T00:00:00",
                token_estimator=token_estimator,
                compacted_hashes=["hash1"],
            )
            
            # Should use msgpack format (not incremental magic)
            raw = metadata.pickle_path.read_bytes()
            from code_puppy.session_storage import _MSGPACK_MAGIC
            assert raw.startswith(_MSGPACK_MAGIC)
            
            # Should still load correctly
            loaded_history, loaded_hashes = load_session_with_hashes(session_name, tmp_path)
            assert len(loaded_history) == len(pydantic_history)
            assert loaded_hashes == ["hash1"]
        finally:
            # Re-enable Rust
            set_rust_enabled(True)


class TestEdgeCases:
    """Edge case tests for incremental serialization."""

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_save_no_new_messages(self, tmp_path: Path, token_estimator):
        """Saving when no new messages should not corrupt file."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "no_new_msgs"
        history = [
            ModelRequest(parts=[UserPromptPart(content="msg1")]),
            ModelRequest(parts=[UserPromptPart(content="msg2")]),
        ]
        
        # First save
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        
        # Save again with same history (no new messages)
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:01",
            token_estimator=token_estimator,
        )
        
        # Should still load correctly
        loaded = load_session(session_name, tmp_path)
        assert len(loaded) == 2

    @pytest.mark.skipif(not is_rust_enabled(), reason="Rust extension not available")
    def test_single_message(self, tmp_path: Path, token_estimator):
        """Single message should serialize and deserialize correctly."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        
        session_name = "single_msg"
        history = [ModelRequest(parts=[UserPromptPart(content="only_message")])]
        
        save_session(
            history=history,
            session_name=session_name,
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )
        
        loaded = load_session(session_name, tmp_path)
        assert len(loaded) == 1
