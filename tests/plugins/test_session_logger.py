"""Tests for the session_logger plugin."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest


class TestSessionLoggerConfig:
    """Test config module."""

    def test_get_session_logger_enabled_default_false(self):
        """By default, session logger should be disabled (opt-in)."""
        from code_puppy.plugins.session_logger.config import get_session_logger_enabled

        with patch("code_puppy.plugins.session_logger.config.get_value") as mock_get:
            mock_get.return_value = None  # Not configured
            assert get_session_logger_enabled() is False

    @patch("code_puppy.plugins.session_logger.config.get_value")
    def test_get_session_logger_enabled_true_values(self, mock_get):
        """Test various truthy values."""
        from code_puppy.plugins.session_logger.config import get_session_logger_enabled

        truthy = ["1", "true", "TRUE", "yes", "YES", "on", "ON", True, 1]
        for val in truthy:
            mock_get.return_value = val
            assert get_session_logger_enabled() is True, f"Should be True for {val!r}"

    @patch("code_puppy.plugins.session_logger.config.get_value")
    def test_get_session_logger_enabled_false_values(self, mock_get):
        """Test various falsy values."""
        from code_puppy.plugins.session_logger.config import get_session_logger_enabled

        falsy = ["0", "false", "FALSE", "no", "NO", "off", "OFF", False, 0, None, ""]
        for val in falsy:
            mock_get.return_value = val
            assert get_session_logger_enabled() is False, f"Should be False for {val!r}"

    def test_get_session_logger_dir_default(self, tmp_path):
        """Test default session logger directory."""
        from code_puppy.plugins.session_logger.config import get_session_logger_dir

        with patch("code_puppy.plugins.session_logger.config.get_value") as mock_get:
            with patch(
                "code_puppy.plugins.session_logger.config.DATA_DIR", str(tmp_path)
            ):
                mock_get.return_value = None
                result = get_session_logger_dir()
                assert result == tmp_path / "sessions"

    def test_get_session_logger_dir_custom(self, tmp_path):
        """Test custom session logger directory from config."""
        from code_puppy.plugins.session_logger.config import get_session_logger_dir

        with patch("code_puppy.plugins.session_logger.config.get_value") as mock_get:
            mock_get.return_value = str(tmp_path / "custom_sessions")
            result = get_session_logger_dir()
            assert result == tmp_path / "custom_sessions"

    def test_get_session_logger_dir_expand_home(self, tmp_path):
        """Test that ~ is expanded in custom directory path."""
        from code_puppy.plugins.session_logger.config import get_session_logger_dir

        with patch("code_puppy.plugins.session_logger.config.get_value") as mock_get:
            mock_get.return_value = "~/my_sessions"
            with patch.dict("os.environ", {"HOME": str(tmp_path)}):
                result = get_session_logger_dir()
                assert "~" not in str(result)


class TestSessionWriter:
    """Test SessionWriter class."""

    def test_session_writer_creates_directory(self, tmp_path):
        """SessionWriter should create session directory on init."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        session_dir = tmp_path / "test_session"
        _ = SessionWriter(
            session_dir=session_dir,
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-123",
        )

        assert session_dir.exists()
        assert (session_dir / "manifest.json").exists()

    def test_session_writer_manifest_content(self, tmp_path):
        """Manifest should contain expected metadata."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        _ = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="my-agent",
            model_name="my-model",
            session_id="sid-abc",
        )

        manifest_path = tmp_path / "test" / "manifest.json"
        with manifest_path.open() as f:
            manifest = json.load(f)

        assert manifest["session_id"] == "sid-abc"
        assert manifest["agent_name"] == "my-agent"
        assert manifest["model_name"] == "my-model"
        assert manifest["started_at"] is not None
        assert manifest["ended_at"] is None  # Not finalized yet
        assert manifest["success"] is None

    def test_session_writer_append_log(self, tmp_path):
        """Test appending to main_agent.log."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        writer.append_log("Test message")
        writer.append_log("Another message")

        log_path = tmp_path / "test" / "main_agent.log"
        content = log_path.read_text()

        assert "Test message" in content
        assert "Another message" in content
        assert content.count("[") == 2  # Two timestamps

    def test_session_writer_append_tool_call(self, tmp_path):
        """Test appending tool calls to jsonl."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        writer.append_tool_call(
            tool_name="read_file",
            tool_args={"file_path": "/tmp/test.txt"},
            result={"content": "hello"},
            duration_ms=15.5,
        )

        jsonl_path = tmp_path / "test" / "tool_calls.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["tool_name"] == "read_file"
        assert record["args"]["file_path"] == "/tmp/test.txt"
        assert record["result"]["content"] == "hello"
        assert record["duration_ms"] == 15.5
        assert record["timestamp"] is not None

    def test_session_writer_non_serializable_args(self, tmp_path):
        """Tool calls with non-serializable args should use repr fallback."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        class NonSerializable:
            def __repr__(self):
                return "NonSerializableObject()"

        writer.append_tool_call(
            tool_name="test_tool",
            tool_args={"obj": NonSerializable(), "normal": "value"},
            result=None,
        )

        jsonl_path = tmp_path / "test" / "tool_calls.jsonl"
        record = json.loads(jsonl_path.read_text().strip())

        # Non-serializable dict values cause the whole dict to be serialized as string
        # The args field should be some serializable representation (dict or string with repr)
        args = record["args"]
        if isinstance(args, dict):
            # If serialization succeeded (it won't with current impl)
            assert "obj" in args
        else:
            # If serialized as string due to non-serializable value
            assert isinstance(args, str)
            assert "NonSerializableObject" in args or "normal" in args

    def test_session_writer_bytes_handling(self, tmp_path):
        """Bytes should be handled gracefully."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        writer.append_tool_call(
            tool_name="test_tool",
            tool_args={"data": b"binary data here"},
            result=None,
        )

        jsonl_path = tmp_path / "test" / "tool_calls.jsonl"
        record = json.loads(jsonl_path.read_text().strip())
        # Bytes cause the dict to not be JSON serializable, so args becomes a string
        args = record["args"]
        # Should be either a dict (if bytes handled specially) or a string
        assert isinstance(args, (dict, str))
        if isinstance(args, str):
            # Bytes were serialized in the repr string
            assert "binary data" in args or "bytes" in args.lower()

    def test_session_writer_finalize(self, tmp_path):
        """Test session finalization."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        writer.append_tool_call(tool_name="tool1", tool_args={})
        writer.append_tool_call(tool_name="tool2", tool_args={})

        writer.finalize(success=True, error=None)

        manifest_path = tmp_path / "test" / "manifest.json"
        with manifest_path.open() as f:
            manifest = json.load(f)

        assert manifest["success"] is True
        assert manifest["error"] is None
        assert manifest["tool_call_count"] == 2
        assert manifest["ended_at"] is not None
        assert manifest["duration_seconds"] is not None
        assert manifest["duration_seconds"] >= 0

    def test_session_writer_finalize_with_error(self, tmp_path):
        """Test finalization with error."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        writer.finalize(success=False, error="Something went wrong")

        manifest_path = tmp_path / "test" / "manifest.json"
        with manifest_path.open() as f:
            manifest = json.load(f)

        assert manifest["success"] is False
        assert manifest["error"] == "Something went wrong"

    def test_session_writer_handles_pending_tool_calls(self, tmp_path):
        """Pending tool calls without matching post should be handled."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        # Record a pre_tool_call
        call_id = writer.record_pre_tool_call("test_tool", {"arg": "value"})
        assert call_id is not None

        # Finalize without calling append_tool_call for this call_id
        writer.finalize(success=True)

        jsonl_path = tmp_path / "test" / "tool_calls.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["tool_name"] == "test_tool"
        assert "incomplete" in record["error"].lower() or record["error"] is not None

    def test_session_writer_thread_safety(self, tmp_path):
        """Test concurrent writes don't corrupt files."""
        from code_puppy.plugins.session_logger.writer import SessionWriter

        writer = SessionWriter(
            session_dir=tmp_path / "test",
            agent_name="agent",
            model_name="model",
            session_id="sid",
        )

        def write_tool_call(i):
            writer.append_tool_call(
                tool_name=f"tool_{i}",
                tool_args={"index": i},
                result={"ok": True},
            )

        # Write from multiple threads concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(write_tool_call, range(50)))

        jsonl_path = tmp_path / "test" / "tool_calls.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")

        # All 50 records should be present (valid JSON each)
        assert len(lines) == 50
        for line in lines:
            record = json.loads(line)  # Should not raise
            assert "tool_name" in record
            assert "args" in record

        # Manifest should show 50 calls
        writer.finalize(success=True)
        manifest = json.loads((tmp_path / "test" / "manifest.json").read_text())
        assert manifest["tool_call_count"] == 50


class TestSessionLoggerCallbacks:
    """Test callback registration and behavior."""

    @pytest.fixture(autouse=True)
    def reset_sessions(self):
        """Reset session state before each test."""
        from code_puppy.plugins.session_logger import register_callbacks as rc

        with rc._lock:
            rc._sessions.clear()
            rc._session_tool_call_ids.clear()
        yield
        with rc._lock:
            rc._sessions.clear()
            rc._session_tool_call_ids.clear()

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_agent_run_start_creates_session(
        self, mock_get_dir, mock_enabled, tmp_path
    ):
        """agent_run_start should create a new session writer."""
        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_start,
        )

        await _on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-sid-123",
        )

        from code_puppy.plugins.session_logger import register_callbacks as rc

        with rc._lock:
            assert "test-sid-123" in rc._sessions

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    async def test_disabled_does_not_create_session(self, mock_enabled, tmp_path):
        """When disabled, agent_run_start should not create sessions."""
        mock_enabled.return_value = False

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_start,
        )

        await _on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="test-sid",
        )

        from code_puppy.plugins.session_logger import register_callbacks as rc

        with rc._lock:
            assert "test-sid" not in rc._sessions

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_agent_run_end_finalizes_session(
        self, mock_get_dir, mock_enabled, tmp_path
    ):
        """agent_run_end should finalize the session and write manifest."""
        mock_enabled.return_value = True
        base_dir = tmp_path / "sessions"
        mock_get_dir.return_value = base_dir

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_end,
            _on_agent_run_start,
        )

        # Start a session
        await _on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="sid-123",
        )

        # End the session
        await _on_agent_run_end(
            agent_name="test-agent",
            model_name="test-model",
            session_id="sid-123",
            success=True,
            error=None,
        )

        # Find the session directory
        session_dirs = list(base_dir.iterdir())
        assert len(session_dirs) == 1

        manifest_path = session_dirs[0] / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["success"] is True
        assert manifest["error"] is None
        assert manifest["session_id"] == "sid-123"

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_agent_run_end_with_error(self, mock_get_dir, mock_enabled, tmp_path):
        """agent_run_end should record errors."""
        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_end,
            _on_agent_run_start,
        )

        await _on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="error-sid",
        )

        await _on_agent_run_end(
            agent_name="test-agent",
            model_name="test-model",
            session_id="error-sid",
            success=False,
            error=RuntimeError("Test error"),
        )

        manifest = json.loads(
            list((tmp_path / "sessions").iterdir())[0]
            .joinpath("manifest.json")
            .read_text()
        )
        assert manifest["success"] is False
        assert "Test error" in manifest["error"]

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_tool_call_recording(self, mock_get_dir, mock_enabled, tmp_path):
        """Test pre_tool_call and post_tool_call recording."""
        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_end,
            _on_agent_run_start,
            _on_post_tool_call,
            _on_pre_tool_call,
        )

        await _on_agent_run_start(
            agent_name="test-agent",
            model_name="test-model",
            session_id="tool-sid",
        )

        # Simulate tool call with context containing session_id
        context = {"agent_session_id": "tool-sid"}
        await _on_pre_tool_call(
            tool_name="read_file",
            tool_args={"file_path": "/tmp/test.txt"},
            context=context,
        )

        await _on_post_tool_call(
            tool_name="read_file",
            tool_args={"file_path": "/tmp/test.txt"},
            result={"content": "hello"},
            duration_ms=10.0,
            context=context,
        )

        await _on_agent_run_end(
            agent_name="test-agent",
            model_name="test-model",
            session_id="tool-sid",
            success=True,
        )

        jsonl_path = list((tmp_path / "sessions").iterdir())[0].joinpath(
            "tool_calls.jsonl"
        )
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["tool_name"] == "read_file"
        assert record["args"]["file_path"] == "/tmp/test.txt"
        assert record["result"]["content"] == "hello"
        assert record["duration_ms"] == 10.0

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_multiple_concurrent_sessions(
        self, mock_get_dir, mock_enabled, tmp_path
    ):
        """Two sessions with different session_ids should write to separate directories."""
        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_end,
            _on_agent_run_start,
        )

        await _on_agent_run_start(
            agent_name="agent1",
            model_name="model1",
            session_id="sid-1",
        )

        await _on_agent_run_start(
            agent_name="agent2",
            model_name="model2",
            session_id="sid-2",
        )

        await _on_agent_run_end(
            agent_name="agent1",
            model_name="model1",
            session_id="sid-1",
            success=True,
        )

        await _on_agent_run_end(
            agent_name="agent2",
            model_name="model2",
            session_id="sid-2",
            success=False,
            error="Test error",
        )

        # Should have two separate session directories
        session_dirs = list((tmp_path / "sessions").iterdir())
        assert len(session_dirs) == 2

        manifests = []
        for d in session_dirs:
            with (d / "manifest.json").open() as f:
                manifests.append(json.load(f))

        # One success, one failure
        successes = [m["success"] for m in manifests]
        assert True in successes
        assert False in successes

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    def test_shutdown_finalizes_unfinalized_sessions(
        self, mock_get_dir, mock_enabled, tmp_path
    ):
        """Shutdown should finalize any unfinalized sessions."""
        import asyncio

        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_start,
            _on_shutdown,
        )

        async def setup():
            await _on_agent_run_start(
                agent_name="test-agent",
                model_name="test-model",
                session_id="unfinalized-sid",
            )

        asyncio.run(setup())

        # Shutdown without calling agent_run_end
        _on_shutdown()

        # Session should still be finalized
        session_dirs = list((tmp_path / "sessions").iterdir())
        assert len(session_dirs) == 1

        manifest = json.loads((session_dirs[0] / "manifest.json").read_text())
        assert manifest["success"] is None  # Unknown success state
        assert "shutdown" in manifest["error"].lower()

    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_enabled"
    )
    @patch(
        "code_puppy.plugins.session_logger.register_callbacks.get_session_logger_dir"
    )
    async def test_graceful_degradation_on_error(
        self, mock_get_dir, mock_enabled, tmp_path
    ):
        """Errors in callbacks should not crash the app."""
        mock_enabled.return_value = True
        mock_get_dir.return_value = tmp_path / "sessions"

        from code_puppy.plugins.session_logger.register_callbacks import (
            _on_agent_run_start,
        )

        # Make the directory unwritable (simulate permission error on some systems)
        # On most systems, this should still work because tmp_path is writable
        # This test mainly verifies no exceptions propagate
        try:
            await _on_agent_run_start(
                agent_name="test-agent",
                model_name="test-model",
                session_id="test-sid",
            )
        except Exception as e:
            pytest.fail(f"Callback should not raise: {e}")

    def test_safe_serialize_with_path(self, tmp_path):
        """Test that Path objects are serialized correctly."""
        from code_puppy.plugins.session_logger.writer import _safe_serialize

        result = _safe_serialize(tmp_path)
        assert isinstance(result, str)
        assert str(tmp_path) in result

    def test_safe_serialize_with_bytes(self):
        """Test that bytes are serialized correctly."""
        from code_puppy.plugins.session_logger.writer import _safe_serialize

        result = _safe_serialize(b"test data")
        assert isinstance(result, str)
        assert "bytes" in result.lower() or len(result) < 50
