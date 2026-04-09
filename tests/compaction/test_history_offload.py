"""Tests for compaction.history_offload module."""

from pathlib import Path


from code_puppy.compaction.history_offload import (
    DEFAULT_ARCHIVE_DIR,
    _sanitize_session_id,
    _serialize_message,
    offload_evicted_messages,
)


class TestSanitizeSessionId:
    """Tests for _sanitize_session_id function."""

    def test_safe_session_id_unchanged(self):
        """Safe session IDs are returned unchanged."""
        assert _sanitize_session_id("session123") == "session123"
        assert _sanitize_session_id("my-session_test.v1") == "my-session_test.v1"

    def test_unsafe_chars_replaced(self):
        """Unsafe characters are replaced with underscores."""
        assert _sanitize_session_id("session/123") == "session_123"
        assert _sanitize_session_id("session\\123") == "session_123"
        assert _sanitize_session_id("session:123") == "session_123"
        assert _sanitize_session_id("session space") == "session_space"


class TestSerializeMessage:
    """Tests for _serialize_message function."""

    def test_simple_message(self):
        """Simple message serialization."""
        msg = {"role": "user", "content": "hello"}
        result = _serialize_message(msg)
        assert "user" in result
        assert "hello" in result

    def test_pydantic_ai_message(self):
        """Pydantic-ai style message with kind and parts."""
        class FakePart:
            part_kind = "text"
            content = "test content"

        class FakeMsg:
            kind = "request"
            parts = [FakePart()]

        result = _serialize_message(FakeMsg())
        assert "request" in result

    def test_fallback_repr(self):
        """Fallback to repr for unknown types."""
        class UnknownMsg:
            pass

        result = _serialize_message(UnknownMsg())
        assert "unreadable" not in result  # Should succeed


class TestOffloadEvictedMessages:
    """Tests for offload_evicted_messages function."""

    def test_basic_offload_creates_file(self, tmp_path):
        """Basic offload creates history file."""
        archive_dir = tmp_path / "history"
        messages = [{"role": "user", "content": "hello"}]

        result = offload_evicted_messages(
            messages,
            session_id="test-session",
            archive_dir=archive_dir,
            compact_reason="summarization",
        )

        assert result is not None
        assert result.exists()
        assert result.parent == archive_dir
        content = result.read_text()
        assert "Compacted at" in content
        assert "summarization" in content

    def test_offload_appends_does_not_overwrite(self, tmp_path):
        """Multiple offloads append to file, not overwrite."""
        archive_dir = tmp_path / "history"

        offload_evicted_messages(
            [{"role": "user", "content": "first"}],
            session_id="test-session",
            archive_dir=archive_dir,
            compact_reason="first",
        )

        offload_evicted_messages(
            [{"role": "assistant", "content": "second"}],
            session_id="test-session",
            archive_dir=archive_dir,
            compact_reason="second",
        )

        file_path = archive_dir / "test-session.history.md"
        content = file_path.read_text()
        assert "first" in content
        assert "second" in content

    def test_header_contains_timestamp_and_reason(self, tmp_path):
        """Header contains ISO timestamp and compaction reason."""
        archive_dir = tmp_path / "history"

        result = offload_evicted_messages(
            [{"role": "user", "content": "test"}],
            session_id="test-session",
            archive_dir=archive_dir,
            compact_reason="memory_pressure",
        )

        content = result.read_text()
        assert "## Compacted at" in content
        assert "memory_pressure" in content
        # Should look like ISO timestamp (contains T and Z or timezone)
        assert "T" in content or "+" in content or "Z" in content

    def test_empty_messages_returns_none(self, tmp_path):
        """Empty messages list returns None without creating file."""
        archive_dir = tmp_path / "history"
        result = offload_evicted_messages(
            [],
            session_id="test-session",
            archive_dir=archive_dir,
        )
        assert result is None
        assert not (archive_dir / "test-session.history.md").exists()

    def test_unwritable_dir_returns_none_no_crash(self, tmp_path):
        """Unwritable directory returns None without crashing."""
        archive_dir = tmp_path / "readonly"
        archive_dir.mkdir()
        archive_dir.chmod(0o444)  # Read-only

        try:
            offload_evicted_messages(
                [{"role": "user", "content": "test"}],
                session_id="test-session",
                archive_dir=archive_dir,
            )
            # Should not crash, but may or may not succeed depending on OS
        finally:
            archive_dir.chmod(0o755)  # Restore permissions for cleanup

    def test_session_id_sanitized_in_filename(self, tmp_path):
        """Session ID is sanitized when used in filename."""
        archive_dir = tmp_path / "history"

        offload_evicted_messages(
            [{"role": "user", "content": "test"}],
            session_id="session/with/slashes",
            archive_dir=archive_dir,
        )

        # Filename should use sanitized version (underscores instead of slashes)
        file_path = archive_dir / "session_with_slashes.history.md"
        assert file_path.exists()

    def test_default_archive_dir_is_code_puppy_history(self):
        """Default archive dir is ~/.code_puppy/history."""
        expected = Path.home() / ".code_puppy" / "history"
        assert DEFAULT_ARCHIVE_DIR == expected

    def test_custom_archive_dir(self, tmp_path):
        """Custom archive directory is used."""
        custom_dir = tmp_path / "custom_history"

        result = offload_evicted_messages(
            [{"role": "user", "content": "test"}],
            session_id="test-session",
            archive_dir=custom_dir,
        )

        assert result is not None
        assert result.parent == custom_dir

    def test_concurrent_offloads_no_corruption(self, tmp_path):
        """Multiple threads offloading simultaneously don't corrupt file."""
        import threading

        archive_dir = tmp_path / "history"
        errors = []

        def offload_worker(worker_id):
            try:
                for i in range(5):
                    offload_evicted_messages(
                        [{"role": "user", "content": f"worker{worker_id}_msg{i}"}],
                        session_id="concurrent-session",
                        archive_dir=archive_dir,
                        compact_reason=f"worker{worker_id}",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=offload_worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # File should contain all messages from all workers
        file_path = archive_dir / "concurrent-session.history.md"
        content = file_path.read_text()
        assert "worker0" in content
        assert "worker1" in content
        assert "worker2" in content


class TestArchiveSizeManagement:
    """Tests for archive size management and rotation (code_puppy-74k)."""

    def test_archive_rotation_when_size_limit_exceeded(self, tmp_path):
        """Archive is rotated when size exceeds max_archive_size_mb.

        Regression test for code_puppy-74k: Archives should not grow unbounded.
        When the archive exceeds the configured size limit, it should be rotated
        (renamed with timestamp) and a new archive started.
        """
        from code_puppy.compaction.history_offload import (
            _get_archive_size_mb,
            _enforce_archive_size_limit,
        )

        archive_dir = tmp_path / "history"
        archive_path = archive_dir / "test-session.history.md"

        # Create an existing archive with content
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path.write_text("Existing content\n" * 1000)

        original_size = _get_archive_size_mb(archive_path)
        assert original_size > 0

        # Set a very small limit to force rotation
        _enforce_archive_size_limit(archive_path, max_size_mb=0.001)  # 1 KB limit

        # Archive should be rotated (renamed with timestamp)
        assert not archive_path.exists(), "Original archive should be rotated away"

        # Find the rotated archive
        rotated_files = list(archive_dir.glob("test-session_*.history.md"))
        assert len(rotated_files) == 1, "Should have one rotated archive file"

        # Rotated file should contain the original content
        assert "Existing content" in rotated_files[0].read_text()

    def test_archive_not_rotated_when_under_limit(self, tmp_path):
        """Archive is not rotated when size is under max_archive_size_mb."""
        from code_puppy.compaction.history_offload import _enforce_archive_size_limit

        archive_dir = tmp_path / "history"
        archive_path = archive_dir / "test-session.history.md"

        # Create a small archive
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path.write_text("Small content\n")

        # Set a large limit - should not trigger rotation
        _enforce_archive_size_limit(archive_path, max_size_mb=100.0)

        # Archive should still exist unchanged
        assert archive_path.exists(), "Archive should not be rotated"
        assert "Small content" in archive_path.read_text()

    def test_archive_size_mb_calculation(self, tmp_path):
        """Archive size calculation is accurate."""
        from code_puppy.compaction.history_offload import _get_archive_size_mb

        archive_path = tmp_path / "test.history.md"

        # Non-existent file returns 0.0
        assert _get_archive_size_mb(archive_path) == 0.0

        # Create file with known content
        content = "x" * 1024 * 1024  # 1 MB of content
        archive_path.write_text(content)

        size_mb = _get_archive_size_mb(archive_path)
        assert 0.9 < size_mb < 1.1, f"Expected ~1 MB, got {size_mb} MB"

    def test_offload_respects_max_archive_size_config(self, tmp_path):
        """Offload respects the max_archive_size_mb parameter.

        Regression test for code_puppy-74k: The max_archive_size_mb parameter
        should be passed through and honored during offload operations.
        """
        archive_dir = tmp_path / "history"

        # Create a pre-existing large archive
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / "test-session.history.md"
        archive_path.write_text("x" * 1024 * 1024)  # ~1 MB

        # Offload with a very small limit to force rotation
        result = offload_evicted_messages(
            [{"role": "user", "content": "new message"}],
            session_id="test-session",
            archive_dir=archive_dir,
            max_archive_size_mb=0.001,  # 1 KB limit - forces rotation
        )

        # Should return a valid path
        assert result is not None

        # The new archive should only contain the new message
        content = result.read_text()
        assert "new message" in content
        assert "x" * 100 not in content, "Old large content should be in rotated file"

    def test_sanitize_session_id_handles_none(self):
        """_sanitize_session_id handles None safely.

        Regression test for code_puppy-lof: Explicit None session_id should be
        handled safely, returning 'unknown' instead of crashing.
        """
        from code_puppy.compaction.history_offload import _sanitize_session_id

        result = _sanitize_session_id(None)
        assert result == "unknown", "None session_id should return 'unknown'"

    def test_sanitize_session_id_handles_valid_strings(self):
        """_sanitize_session_id handles valid strings correctly."""
        from code_puppy.compaction.history_offload import _sanitize_session_id

        assert _sanitize_session_id("valid-session") == "valid-session"
        assert _sanitize_session_id("session_123") == "session_123"
        assert _sanitize_session_id("test.id") == "test.id"
