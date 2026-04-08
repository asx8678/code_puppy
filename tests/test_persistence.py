"""Tests for persistence module atomic write operations."""

import json
import tempfile
from pathlib import Path

import msgpack
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
    """Test atomic msgpack file writes."""

    def test_write_and_read(self, tmp_path: Path):
        """Test msgpack data can be written and read back."""
        test_file = tmp_path / "test.msgpack"
        data = {"key": "value", "number": 42, "binary": b"bytes"}

        atomic_write_msgpack(test_file, data)

        assert test_file.exists()
        loaded = msgpack.unpackb(test_file.read_bytes(), raw=False)
        assert loaded == data

    def test_non_serializable_raises(self, tmp_path: Path):
        """Test that non-serializable data raises TypeError."""
        test_file = tmp_path / "test.msgpack"

        with pytest.raises(TypeError, match="not msgpack-serializable"):
            atomic_write_msgpack(
                test_file, {"file": open(__file__)}
            )  # File objects can't be serialized

    def test_read_msgpack_with_default(self, tmp_path: Path):
        """Test read_msgpack returns default for missing file."""
        test_file = tmp_path / "nonexistent.msgpack"

        result = read_msgpack(test_file, default={"default": True})
        assert result == {"default": True}

    def test_read_msgpack_existing(self, tmp_path: Path):
        """Test read_msgpack loads existing file."""
        test_file = tmp_path / "test.msgpack"
        data = {"key": "value"}
        test_file.write_bytes(msgpack.packb(data, use_bin_type=True))

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
