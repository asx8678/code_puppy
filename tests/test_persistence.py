"""Tests for code_puppy.persistence atomic write helpers."""

import json
import os
from pathlib import Path

import pytest
import msgpack

from code_puppy.persistence import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_msgpack,
    atomic_write_text,
    safe_resolve_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Return a fresh temp directory for each test."""
    return tmp_path


# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------

class TestAtomicWriteText:
    def test_successful_write(self, tmp_dir: Path) -> None:
        target = tmp_dir / "hello.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_encoding_parameter(self, tmp_dir: Path) -> None:
        target = tmp_dir / "latin.txt"
        atomic_write_text(target, "café", encoding="latin-1")
        assert target.read_text(encoding="latin-1") == "café"

    def test_creates_parent_dirs(self, tmp_dir: Path) -> None:
        target = tmp_dir / "a" / "b" / "c.txt"
        atomic_write_text(target, "deep")
        assert target.read_text() == "deep"

    def test_overwrites_existing(self, tmp_dir: Path) -> None:
        target = tmp_dir / "overwrite.txt"
        target.write_text("old")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------

class TestAtomicWriteJson:
    def test_round_trip(self, tmp_dir: Path) -> None:
        target = tmp_dir / "data.json"
        original = {"name": "test", "values": [1, 2, 3]}
        atomic_write_json(target, original)
        restored = json.loads(target.read_text())
        assert restored == original

    def test_indent(self, tmp_dir: Path) -> None:
        target = tmp_dir / "indented.json"
        atomic_write_json(target, {"a": 1}, indent=4)
        # Default indent is 2; explicit indent=4 should produce longer output
        text = target.read_text()
        assert "    " in text  # 4-space indent

    def test_creates_parent_dirs(self, tmp_dir: Path) -> None:
        target = tmp_dir / "deep" / "file.json"
        atomic_write_json(target, {"ok": True})
        assert json.loads(target.read_text()) == {"ok": True}


# ---------------------------------------------------------------------------
# atomic_write_bytes
# ---------------------------------------------------------------------------

class TestAtomicWriteBytes:
    def test_successful_write(self, tmp_dir: Path) -> None:
        target = tmp_dir / "bin.dat"
        data = b"\x00\x01\x02\xff"
        atomic_write_bytes(target, data)
        assert target.read_bytes() == data

    def test_overwrites(self, tmp_dir: Path) -> None:
        target = tmp_dir / "bin.dat"
        target.write_bytes(b"old")
        atomic_write_bytes(target, b"new")
        assert target.read_bytes() == b"new"


# ---------------------------------------------------------------------------
# atomic_write_msgpack
# ---------------------------------------------------------------------------

class TestAtomicWriteMsgpack:
    def test_round_trip(self, tmp_dir: Path) -> None:
        target = tmp_dir / "data.msgpack"
        original = {"key": "value", "nums": [1, 2, 3]}
        atomic_write_msgpack(target, original)
        raw = target.read_bytes()
        restored = msgpack.unpackb(raw, raw=False)
        assert restored == original

    def test_binary_payload_round_trip(self, tmp_dir: Path) -> None:
        target = tmp_dir / "binary.msgpack"
        original = {"format": "pydantic-ai-json", "payload": b'[{"role":"user"}]'}
        atomic_write_msgpack(target, original)
        raw = target.read_bytes()
        restored = msgpack.unpackb(raw, raw=False)
        assert restored == original

    def test_custom_default(self, tmp_dir: Path) -> None:
        target = tmp_dir / "custom.msgpack"

        def _default(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError(f"Cannot serialize {type(obj)}")

        data = {"items": {1, 2, 3}}
        atomic_write_msgpack(target, data, default=_default)
        raw = target.read_bytes()
        restored = msgpack.unpackb(raw, raw=False)
        assert sorted(restored["items"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Partial-write safety (no corrupt leftovers)
# ---------------------------------------------------------------------------

class TestPartialWriteSafety:
    def test_no_temp_file_left_on_success(self, tmp_dir: Path) -> None:
        target = tmp_dir / "clean.txt"
        atomic_write_text(target, "ok")
        # Only the target file should exist; no *.tmp stragglers
        tmp_files = list(tmp_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_text_no_corrupt_file(self, tmp_dir: Path) -> None:
        """Simulate failure mid-write — the original content should remain."""
        target = tmp_dir / "important.txt"
        target.write_text("original content")

        # Monkey-patch os.replace to raise on the first call
        original_replace = os.replace
        call_count = 0

        def _failing_replace(src, dst):
            nonlocal call_count
            call_count += 1
            raise OSError("simulated disk error")

        os.replace = _failing_replace
        try:
            with pytest.raises(OSError):
                atomic_write_text(target, "new content")
        finally:
            os.replace = original_replace

        # The original file must still be intact
        assert target.read_text() == "original content"

    def test_atomic_write_json_no_corrupt_file(self, tmp_dir: Path) -> None:
        target = tmp_dir / "data.json"
        atomic_write_json(target, {"v": 1})
        original_text = target.read_text()

        original_replace = os.replace

        def _failing_replace(src, dst):
            raise OSError("simulated failure")

        os.replace = _failing_replace
        try:
            with pytest.raises(OSError):
                atomic_write_json(target, {"v": 2})
        finally:
            os.replace = original_replace

        # File still has the first version's content
        assert target.read_text() == original_text
        assert json.loads(target.read_text())["v"] == 1

    def test_atomic_write_msgpack_no_corrupt_file(self, tmp_dir: Path) -> None:
        target = tmp_dir / "data.msgpack"
        original_data = {"v": "first"}
        atomic_write_msgpack(target, original_data)
        original_bytes = target.read_bytes()

        original_replace = os.replace

        def _failing_replace(src, dst):
            raise OSError("simulated failure")

        os.replace = _failing_replace
        try:
            with pytest.raises(OSError):
                atomic_write_msgpack(target, {"v": "second"})
        finally:
            os.replace = original_replace

        # Original msgpack data intact
        assert target.read_bytes() == original_bytes
        assert msgpack.unpackb(target.read_bytes(), raw=False) == original_data


# ---------------------------------------------------------------------------
# safe_resolve_path
# ---------------------------------------------------------------------------

class TestSafeResolvePath:
    def test_resolves_relative(self, tmp_dir: Path) -> None:
        child = tmp_dir / "subdir" / "file.txt"
        child.parent.mkdir(parents=True)
        resolved = safe_resolve_path(child)
        assert resolved == child.resolve()

    def test_valid_within_parent(self, tmp_dir: Path) -> None:
        child = tmp_dir / "ok.txt"
        resolved = safe_resolve_path(child, allowed_parent=tmp_dir)
        assert resolved == child.resolve()

    def test_invalid_outside_parent(self, tmp_dir: Path) -> None:
        outside = tmp_dir / ".." / "outside.txt"
        with pytest.raises(ValueError, match="outside allowed parent"):
            safe_resolve_path(outside, allowed_parent=tmp_dir)

    def test_symlink_traversal_blocked(self, tmp_dir: Path) -> None:
        # Create a directory outside allowed_parent with a symlink pointing in
        outside_dir = tmp_dir / ".." / "evil"
        outside_dir.mkdir(parents=True, exist_ok=True)
        # Make it absolute so resolve doesn't canonicalise back
        outside_dir = outside_dir.resolve()

        link = tmp_dir / "escape_link"
        link.symlink_to(outside_dir)

        with pytest.raises(ValueError, match="outside allowed parent"):
            safe_resolve_path(link / "payload.txt", allowed_parent=tmp_dir)

    def test_no_parent_constraint(self, tmp_dir: Path) -> None:
        """Without allowed_parent, any path is fine."""
        anywhere = Path("/tmp/anywhere.txt")
        resolved = safe_resolve_path(anywhere)
        assert resolved.is_absolute()
