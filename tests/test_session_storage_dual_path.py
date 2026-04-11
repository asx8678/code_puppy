"""Tests for session_storage.py corruption & edge-case paths.

Covers the exception branches that the main test suite doesn't exercise:
- _deserialize_messages exception fallback
- save_session fallback when ModelMessagesTypeAdapter.dump_python fails
- _parse_session_payload with legacy list format
- load_session / load_session_with_hashes FileNotFoundError
- cleanup_sessions OSError on unlink
- restore_autosave_interactively exception paths
"""

import json
import sys
import pickle
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.session_storage import (
    _LEGACY_MSGPACK_MAGIC,
    _JSON_MAGIC,
    SessionMetadata,
    _compute_hmac,
    _get_hmac_key,
    _deserialize_messages,
    _load_raw_bytes,
    _parse_session_payload,
    cleanup_sessions,
    load_session,
    load_session_with_hashes,
    save_session,
)





# ---------------------------------------------------------------------------
# _deserialize_messages
# ---------------------------------------------------------------------------


class TestDeserializeMessages:
    def test_empty_list_returns_empty(self):
        assert _deserialize_messages([]) == []

    def test_plain_values_returned_as_is(self):
        result = _deserialize_messages(["hello", "world"])
        assert result == ["hello", "world"]

    def test_dict_without_kind_returned_as_is(self):
        data = [{"foo": "bar"}]
        assert _deserialize_messages(data) is data

    def test_dict_with_kind_but_validation_fails(self):
        """Lines 50-51: exception during validation returns raw input."""
        bad_data = [{"kind": "request", "invalid": True}]
        with patch(
            "code_puppy.session_storage.ModelMessagesTypeAdapter",
            create=True,
        ) as mock_adapter:
            # Make validate_python raise
            mock_adapter.validate_python.side_effect = ValueError("bad data")
            # Need to patch the import inside the function
            with patch.dict(
                "sys.modules",
                {
                    "pydantic_ai.messages": MagicMock(
                        ModelMessagesTypeAdapter=mock_adapter
                    )
                },
            ):
                result = _deserialize_messages(bad_data)
                # Falls back to returning raw data
                assert result == bad_data or result is bad_data


# ---------------------------------------------------------------------------
# _load_raw_bytes
# ---------------------------------------------------------------------------


class TestLoadRawBytes:
    def test_json_format(self, tmp_path):
        """Loading JSON format with valid HMAC succeeds."""
        payload = {"messages": [{"kind": "request", "content": "hi"}]}
        json_data = json.dumps(payload).encode("utf-8")
        hmac_sig = _compute_hmac(_get_hmac_key(), json_data)
        raw = _JSON_MAGIC + hmac_sig + json_data
        result = _load_raw_bytes(raw)
        assert isinstance(result, dict)
        assert "messages" in result

    def test_legacy_msgpack_format(self, tmp_path):
        """Loading legacy msgpack format still works for backward compat."""
        import msgpack
        payload = {"messages": [{"kind": "request", "content": "hi"}]}
        msgpack_data = msgpack.packb(payload, use_bin_type=True)
        hmac_sig = _compute_hmac(_get_hmac_key(), msgpack_data)
        raw = _LEGACY_MSGPACK_MAGIC + hmac_sig + msgpack_data
        result = _load_raw_bytes(raw)
        assert isinstance(result, dict)
        assert "messages" in result

    def test_plain_pickle(self, tmp_path):
        """Plain pickle format is rejected for security."""
        data = {"messages": ["hello"]}
        raw = pickle.dumps(data)
        with pytest.raises(ValueError, match="pickle|RCE|security|CVE"):
            _load_raw_bytes(raw)


# ---------------------------------------------------------------------------
# save_session – fallback for non-pydantic history
# ---------------------------------------------------------------------------


class TestSaveSessionFallback:
    def test_saves_plain_strings_as_history(self, tmp_path):
        """Lines 149-151: fallback when ModelMessagesTypeAdapter.dump_python fails."""
        history = ["plain", "string", "messages"]
        meta = save_session(
            history=history,
            session_name="test_fallback",
            base_dir=tmp_path,
            timestamp="2025-05-17T00:00:00",
            token_estimator=lambda m: len(str(m)),
        )
        assert isinstance(meta, SessionMetadata)
        assert meta.message_count == 3
        # Verify the file was actually written
        pkl_path = tmp_path / "test_fallback.pkl"
        assert pkl_path.exists()


# ---------------------------------------------------------------------------
# _parse_session_payload
# ---------------------------------------------------------------------------


class TestParseSessionPayload:
    def test_dict_with_messages_key(self):
        data = {"messages": ["a", "b"], "compacted_hashes": ["h1"]}
        msgs, hashes = _parse_session_payload(data)
        assert msgs == ["a", "b"]
        assert hashes == ["h1"]

    def test_dict_without_compacted_hashes(self):
        data = {"messages": ["a"]}
        msgs, hashes = _parse_session_payload(data)
        assert hashes == []

    def test_legacy_list_format(self):
        """Line 201: plain list is treated as legacy format."""
        data = ["msg1", "msg2"]
        msgs, hashes = _parse_session_payload(data)
        assert msgs == ["msg1", "msg2"]
        assert hashes == []

    def test_unknown_type_returns_as_data(self):
        data = "some string"
        msgs, hashes = _parse_session_payload(data)
        assert msgs == "some string"
        assert hashes == []


# ---------------------------------------------------------------------------
# load_session / load_session_with_hashes – FileNotFoundError
# ---------------------------------------------------------------------------


class TestLoadSessionErrors:
    def test_load_session_file_not_found(self, tmp_path):
        """Line 236: raises FileNotFoundError when session file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_session("nonexistent", tmp_path)

    def test_load_session_with_hashes_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_session_with_hashes("nonexistent", tmp_path)


# ---------------------------------------------------------------------------
# cleanup_sessions – OSError on unlink
# ---------------------------------------------------------------------------


class TestCleanupSessionsOSError:
    def test_oserror_on_unlink_is_swallowed(self, tmp_path):
        """Lines 273-274: OSError during unlink is silently continued."""
        # Create 3 session files
        for i in range(3):
            (tmp_path / f"session_{i}.pkl").write_bytes(b"data")

        # Make unlink raise OSError
        original_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if self.suffix == ".pkl":
                raise OSError("permission denied")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", failing_unlink):
            result = cleanup_sessions(tmp_path, max_sessions=1)
        # OSError was swallowed – nothing removed
        assert result == []


# ---------------------------------------------------------------------------
# restore_autosave_interactively – exception paths
# ---------------------------------------------------------------------------


class TestRestoreAutosaveErrors:
    @pytest.mark.asyncio
    async def test_restore_file_not_found(self, tmp_path):
        """Line 408: autosave file disappeared between listing and loading."""
        from code_puppy.session_storage import restore_autosave_interactively

        async def fake_prompt(*args, **kwargs):
            return "1"  # select first session

        with patch(
            "code_puppy.session_storage.list_sessions", return_value=["autosave_01"]
        ):
            with patch(
                "code_puppy.session_storage.load_session_with_hashes",
                side_effect=FileNotFoundError("gone"),
            ):
                _PTK_KEY = "code_puppy.command_line.prompt_toolkit_completion"
                mock_ptk = ModuleType(_PTK_KEY)
                mock_ptk.get_input_with_combined_completion = AsyncMock(
                    side_effect=fake_prompt
                )
                _prev = sys.modules.get(_PTK_KEY)
                sys.modules[_PTK_KEY] = mock_ptk
                try:
                    with patch(
                        "code_puppy.agents.agent_manager.get_current_agent",
                        create=True,
                    ):
                        with patch("code_puppy.messaging.emit_warning"):
                            with patch("code_puppy.messaging.emit_system_message"):
                                await restore_autosave_interactively(tmp_path)
                finally:
                    if _prev is None:
                        sys.modules.pop(_PTK_KEY, None)
                    else:
                        sys.modules[_PTK_KEY] = _prev

    @pytest.mark.asyncio
    async def test_restore_load_exception(self, tmp_path):
        """Lines 428-429: generic exception during load shows warning."""
        from code_puppy.session_storage import restore_autosave_interactively

        async def fake_prompt(*args, **kwargs):
            return "1"  # select first session

        with patch(
            "code_puppy.session_storage.list_sessions", return_value=["autosave_01"]
        ):
            with patch(
                "code_puppy.session_storage.load_session_with_hashes",
                side_effect=ValueError("corrupt data"),
            ):
                _PTK_KEY = "code_puppy.command_line.prompt_toolkit_completion"
                mock_ptk = ModuleType(_PTK_KEY)
                mock_ptk.get_input_with_combined_completion = AsyncMock(
                    side_effect=fake_prompt
                )
                _prev = sys.modules.get(_PTK_KEY)
                sys.modules[_PTK_KEY] = mock_ptk
                try:
                    with patch(
                        "code_puppy.agents.agent_manager.get_current_agent",
                        create=True,
                    ):
                        with patch("code_puppy.messaging.emit_warning"):
                            with patch("code_puppy.messaging.emit_system_message"):
                                await restore_autosave_interactively(tmp_path)
                finally:
                    if _prev is None:
                        sys.modules.pop(_PTK_KEY, None)
                    else:
                        sys.modules[_PTK_KEY] = _prev
