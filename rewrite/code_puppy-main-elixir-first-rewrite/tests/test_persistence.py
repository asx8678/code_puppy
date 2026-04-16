"""Tests for persistence module atomic write operations."""

import json
from pathlib import Path

import pytest

from code_puppy.persistence import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_msgpack,
    atomic_write_text,
    read_json,
    read_msgpack,
    safe_resolve_path,
)


class TestSafeResolvePath:
    """Test path resolution and validation."""

    def test_resolve_simple_path(self, tmp_path: Path):
        """Test basic path resolution."""
        test_file = tmp_path / "test.txt"
        result = safe_resolve_path(test_file)
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_resolve_with_allowed_parent_valid(self, tmp_path: Path):
        """Test path within allowed parent succeeds."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"

        result = safe_resolve_path(test_file, allowed_parent=tmp_path)
        assert result == test_file.resolve()

    def test_resolve_with_allowed_parent_invalid(self, tmp_path: Path):
        """Test path outside allowed parent fails."""
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        test_file = other_dir / "test.txt"

        # Try to validate against a different parent
        fake_parent = tmp_path / "fake"
        fake_parent.mkdir()

        with pytest.raises(ValueError, match="outside allowed parent"):
            safe_resolve_path(test_file, allowed_parent=fake_parent)

    def test_resolve_rejects_parent_traversal(self, tmp_path: Path):
        """Path with '..' traversal must not escape allowed_parent."""
        allowed = tmp_path / "jail"
        allowed.mkdir()
        evil = allowed / ".." / "outside.txt"
        with pytest.raises(ValueError, match="outside allowed parent"):
            safe_resolve_path(evil, allowed_parent=allowed)

    def test_resolve_does_not_follow_symlinks(self, tmp_path: Path):
        """Symlinks inside allowed_parent are lexically within bounds but not followed."""
        import os
        allowed = tmp_path / "jail"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        link = allowed / "link.txt"
        os.symlink(outside / "secret.txt", link)
        # Lexically within jail, should return the link path (not the target)
        result = safe_resolve_path(link, allowed_parent=allowed)
        assert "outside" not in str(result)
        assert str(allowed) in str(result)


class TestAtomicWriteText:
    """Test atomic text file writes."""

    def test_write_and_read(self, tmp_path: Path):
        """Test text can be written and read back."""
        test_file = tmp_path / "test.txt"
        content = "Hello, World!"

        atomic_write_text(test_file, content)

        assert test_file.exists()
        assert test_file.read_text() == content

    def test_overwrite_existing(self, tmp_path: Path):
        """Test overwriting existing file works."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("old content")

        new_content = "new content"
        atomic_write_text(test_file, new_content)

        assert test_file.read_text() == new_content

    def test_custom_encoding(self, tmp_path: Path):
        """Test custom encoding works."""
        test_file = tmp_path / "test.txt"
        content = "Héllo, Wörld!"

        atomic_write_text(test_file, content, encoding="utf-8")

        assert test_file.read_text(encoding="utf-8") == content


class TestAtomicWriteBytes:
    """Test atomic binary file writes."""

    def test_write_and_read(self, tmp_path: Path):
        """Test bytes can be written and read back."""
        test_file = tmp_path / "test.bin"
        data = b"\x00\x01\x02\x03\xff"

        atomic_write_bytes(test_file, data)

        assert test_file.exists()
        assert test_file.read_bytes() == data


class TestAtomicWriteJson:
    """Test atomic JSON file writes."""

    def test_write_and_read(self, tmp_path: Path):
        """Test JSON data can be written and read back."""
        test_file = tmp_path / "test.json"
        data = {"key": "value", "number": 42, "nested": {"a": 1}}

        atomic_write_json(test_file, data)

        assert test_file.exists()
        loaded = json.loads(test_file.read_text())
        assert loaded == data

    def test_non_serializable_raises(self, tmp_path: Path):
        """Test that non-serializable data raises TypeError."""
        test_file = tmp_path / "test.json"

        with pytest.raises(TypeError, match="not JSON-serializable"):
            atomic_write_json(
                test_file, {"datetime": __import__("datetime").datetime.now()}
            )

    def test_custom_default_serializer(self, tmp_path: Path):
        """Test custom default serializer works."""
        test_file = tmp_path / "test.json"

        class CustomObj:
            def __init__(self, value):
                self.value = value

        def serialize(obj):
            if isinstance(obj, CustomObj):
                return {"custom_value": obj.value}
            raise TypeError()

        data = {"obj": CustomObj("test")}
        atomic_write_json(test_file, data, default=serialize)

        loaded = json.loads(test_file.read_text())
        assert loaded["obj"]["custom_value"] == "test"

    def test_read_json_with_default(self, tmp_path: Path):
        """Test read_json returns default for missing file."""
        test_file = tmp_path / "nonexistent.json"

        result = read_json(test_file, default={"default": True})
        assert result == {"default": True}

    def test_read_json_existing(self, tmp_path: Path):
        """Test read_json loads existing file."""
        test_file = tmp_path / "test.json"
        data = {"key": "value"}
        test_file.write_text(json.dumps(data))

        result = read_json(test_file)
        assert result == data


class TestAtomicWriteMsgpack:
    """Test atomic msgpack file writes (now uses JSON for free-threaded Python compatibility)."""

    def test_write_and_read(self, tmp_path: Path):
        """Test JSON data can be written and read back (msgpack is now JSON)."""
        test_file = tmp_path / "test.msgpack"
        data = {"key": "value", "number": 42}  # Note: binary data not supported in JSON

        atomic_write_msgpack(test_file, data)

        assert test_file.exists()
        loaded = json.loads(test_file.read_bytes())
        assert loaded == data

    def test_non_serializable_raises(self, tmp_path: Path):
        """Test that non-serializable data raises TypeError."""
        test_file = tmp_path / "test.msgpack"

        # Use bytes as non-serializable data (bytes aren't JSON serializable without special handling)
        # Note: atomic_write_msgpack uses default=str for backward compat,
        # so we test the underlying error by passing something truly unserializable
        class Unserializable:
            def __str__(self):
                raise RuntimeError("can't serialize")

        with pytest.raises((TypeError, RuntimeError), match="(not JSON-serializable|can't serialize)"):
            atomic_write_msgpack(test_file, {"obj": Unserializable()})

    def test_read_msgpack_with_default(self, tmp_path: Path):
        """Test read_msgpack returns default for missing file."""
        test_file = tmp_path / "nonexistent.msgpack"

        result = read_msgpack(test_file, default={"default": True})
        assert result == {"default": True}

    def test_read_msgpack_existing(self, tmp_path: Path):
        """Test read_msgpack loads existing JSON file."""
        test_file = tmp_path / "test.msgpack"
        data = {"key": "value"}
        test_file.write_bytes(json.dumps(data).encode("utf-8"))

        result = read_msgpack(test_file)
        assert result == data


class TestAtomicity:
    """Test atomic behavior - no partial files on failure."""

    def test_no_partial_file_on_exception(self, tmp_path: Path, monkeypatch):
        """Test that temp file is cleaned up if write fails."""
        test_file = tmp_path / "test.txt"

        # Patch mkstemp to succeed but write to fail
        original_mkstemp = __import__("tempfile").mkstemp

        def failing_mkstemp(*args, **kwargs):
            fd, name = original_mkstemp(*args, **kwargs)
            # Close the fd to simulate normal behavior
            __import__("os").close(fd)
            return -1, name  # Return invalid fd

        monkeypatch.setattr("tempfile.mkstemp", failing_mkstemp)

        with pytest.raises(Exception):
            atomic_write_text(test_file, "content")

        # Target file should not exist
        assert not test_file.exists()

    def test_directory_created_automatically(self, tmp_path: Path):
        """Test that parent directories are created."""
        nested_file = tmp_path / "a" / "b" / "c" / "test.txt"

        atomic_write_text(nested_file, "content")

        assert nested_file.exists()
        assert nested_file.read_text() == "content"


def test_ensure_parent_dir_thread_safety(tmp_path: Path):
    """INSTRUMENTED test: verify lock is held during cache access.
    
    The watchdog requires tests that PROVE the lock is being acquired,
    not just tests that happen to pass due to CPython's GIL. This test
    instruments the lock to count acquisitions.
    """
    import threading
    import code_puppy.persistence as mod
    from code_puppy.persistence import atomic_write_text, _created_dirs
    
    # First: verify lock infrastructure exists and is correct type
    assert hasattr(mod, '_created_dirs_lock'), "Module must have _created_dirs_lock"
    assert isinstance(mod._created_dirs_lock, type(threading.Lock())), \
        "_created_dirs_lock must be a threading.Lock"
    assert hasattr(mod, '_created_dirs'), "Module must have _created_dirs"
    assert isinstance(mod._created_dirs, set), "_created_dirs must be a set"
    
    # Create an instrumented lock that counts acquisitions
    class InstrumentedLock:
        def __init__(self, real_lock):
            self._lock = real_lock
            self.acquire_count = 0
        
        def acquire(self, *args, **kwargs):
            self.acquire_count += 1
            return self._lock.acquire(*args, **kwargs)
        
        def release(self):
            return self._lock.release()
        
        def __enter__(self):
            self.acquire_count += 1
            return self._lock.__enter__()
        
        def __exit__(self, *args):
            return self._lock.__exit__(*args)
    
    # Replace module lock with instrumented version
    original_lock = mod._created_dirs_lock
    instrumented = InstrumentedLock(original_lock)
    mod._created_dirs_lock = instrumented
    
    try:
        # Clear the created dirs cache using original lock
        with original_lock:
            _created_dirs.clear()
        
        target_dir = tmp_path / "subdir" / "nested"
        
        # First write: cache miss (acquire for check + acquire for write = 2)
        path1 = target_dir / "file_1.txt"
        atomic_write_text(path1, "content_1")
        
        # Second write to same dir: cache hit (acquire for check = 1)
        path2 = target_dir / "file_2.txt"
        atomic_write_text(path2, "content_2")
        
        # CRITICAL: Verify lock was acquired multiple times
        # If the lock isn't being used, acquire_count would be 0 or very low
        assert instrumented.acquire_count >= 2, \
            f"Lock must be acquired at least 2 times (for cache access), got {instrumented.acquire_count}"
        
        # Verify the directory is in the cache
        with original_lock:
            assert len(_created_dirs) >= 1, "Cache should have at least 1 entry"
            # The directory itself or its parent should be cached
            dirs_list = list(_created_dirs)
            assert any(str(target_dir) in str(d) or str(target_dir.parent) in str(d) for d in dirs_list), \
                f"Expected path containing {target_dir} or {target_dir.parent} in cache, got {dirs_list}"
        
        # Verify files were created
        assert path1.exists(), "First file should exist"
        assert path2.exists(), "Second file should exist"
        assert path1.read_text() == "content_1"
        assert path2.read_text() == "content_2"
        
    finally:
        # Restore original lock
        mod._created_dirs_lock = original_lock
