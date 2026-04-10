"""Tests for code_puppy.utils.peek_file module."""

import asyncio
import os
import tempfile

import pytest

from code_puppy.utils.peek_file import peek_file, peek_file_sync, reset_pools


@pytest.fixture(autouse=True)
def _reset():
    """Reset buffer pools before each test."""
    reset_pools()
    yield
    reset_pools()


@pytest.fixture
def sample_file():
    """Create a temporary file with known content."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
        content = b"Hello, World! " * 100  # 1400 bytes
        f.write(content)
        f.flush()
        yield f.name, content
    os.unlink(f.name)


@pytest.fixture
def binary_file():
    """Create a temporary file with binary content (contains null bytes)."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
        content = b"\x00\x01\x02\x03\xff\xfe\xfd" * 50
        f.write(content)
        f.flush()
        yield f.name, content
    os.unlink(f.name)


@pytest.fixture
def empty_file():
    """Create an empty temporary file."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        yield f.name
    os.unlink(f.name)


class TestPeekFileSync:
    def test_reads_header(self, sample_file):
        path, content = sample_file
        result = peek_file_sync(path, 10, lambda h: h)
        assert result == content[:10]

    def test_reads_full_small_file(self, sample_file):
        path, content = sample_file
        result = peek_file_sync(path, 10000, lambda h: h)
        assert result == content

    def test_zero_bytes_returns_empty(self, sample_file):
        path, _ = sample_file
        result = peek_file_sync(path, 0, lambda h: h)
        assert result == b""

    def test_negative_bytes_returns_empty(self, sample_file):
        path, _ = sample_file
        result = peek_file_sync(path, -1, lambda h: h)
        assert result == b""

    def test_empty_file(self, empty_file):
        result = peek_file_sync(empty_file, 100, lambda h: h)
        assert result == b""

    def test_binary_detection(self, binary_file):
        path, _ = binary_file
        is_binary = peek_file_sync(path, 512, lambda h: b"\x00" in h)
        assert is_binary is True

    def test_text_detection(self, sample_file):
        path, _ = sample_file
        is_binary = peek_file_sync(path, 512, lambda h: b"\x00" in h)
        assert is_binary is False

    def test_op_return_value(self, sample_file):
        path, _ = sample_file
        length = peek_file_sync(path, 100, lambda h: len(h))
        assert length == 100

    def test_nonexistent_file_raises(self):
        with pytest.raises(OSError):
            peek_file_sync("/nonexistent/file.txt", 10, lambda h: h)

    def test_large_read_grows_buffer(self, sample_file):
        """Buffer should grow for reads larger than initial size."""
        path, content = sample_file
        result = peek_file_sync(path, 2000, lambda h: len(h))
        assert result == len(content)  # File is 1400 bytes


class TestPeekFileAsync:
    def test_reads_header(self, sample_file):
        path, content = sample_file
        result = asyncio.run(peek_file(path, 10, lambda h: h))
        assert result == content[:10]

    def test_zero_bytes(self, sample_file):
        path, _ = sample_file
        result = asyncio.run(peek_file(path, 0, lambda h: h))
        assert result == b""

    def test_binary_detection(self, binary_file):
        path, _ = binary_file
        is_binary = asyncio.run(peek_file(path, 512, lambda h: b"\x00" in h))
        assert is_binary is True

    def test_concurrent_reads(self, sample_file):
        """Multiple concurrent reads should work with pool."""
        path, content = sample_file

        async def _run():
            tasks = [peek_file(path, 10, lambda h: h) for _ in range(20)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run())
        assert all(r == content[:10] for r in results)

    def test_large_read_bypasses_pool(self, sample_file):
        """Reads larger than pool slot size should allocate ad hoc."""
        path, content = sample_file
        result = asyncio.run(peek_file(path, 1000, lambda h: len(h)))
        assert result == 1000

    def test_nonexistent_file_raises(self):
        with pytest.raises(OSError):
            asyncio.run(peek_file("/nonexistent/file.txt", 10, lambda h: h))
