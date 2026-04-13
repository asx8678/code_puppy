"""Tests for list_files performance optimizations."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.tools.file_operations import _list_files, MAX_LIST_FILES_ENTRIES


def _make_context():
    return MagicMock()


@pytest.mark.asyncio
async def test_list_files_constant_exists_and_is_reasonable():
    """MAX_LIST_FILES_ENTRIES should exist and have a reasonable value."""
    assert MAX_LIST_FILES_ENTRIES > 0
    assert MAX_LIST_FILES_ENTRIES <= 50000  # Sanity check upper bound


@pytest.mark.asyncio
async def test_list_files_shows_truncation_warning_when_ripgrep_returns_too_many():
    """list_files should warn when ripgrep output exceeds MAX_LIST_FILES_ENTRIES."""
    # Mock ripgrep to return more files than the limit
    fake_files = "\n".join([f"/fake/path/file{i}.txt" for i in range(MAX_LIST_FILES_ENTRIES + 100)])

    mock_result = MagicMock()
    mock_result.stdout = fake_files
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("code_puppy.tools.file_operations.subprocess.run", return_value=mock_result):
        with patch("code_puppy.tools.file_operations.os.stat") as mock_stat:
            # Make stat return a dummy result
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 100
            mock_stat_result.st_mode = 0o100644  # Regular file
            mock_stat.return_value = mock_stat_result

            with patch("code_puppy.tools.file_operations.os.path.exists", return_value=True):
                with patch("code_puppy.tools.file_operations.os.path.isdir", return_value=True):
                    result = await _list_files(_make_context(), "/fake/path", recursive=True)

    # Should contain truncation warning
    assert "TRUNCATED" in result.content or "truncated" in result.content.lower()


@pytest.mark.asyncio
async def test_list_files_limits_file_entries_in_structured_message():
    """list_files should cap file_entries before emitting FileListingMessage."""
    from code_puppy.tools.file_operations import FileListingMessage

    # Mock ripgrep to return many files
    fake_files = "\n".join([f"/fake/path/file{i}.txt" for i in range(MAX_LIST_FILES_ENTRIES + 50)])

    mock_result = MagicMock()
    mock_result.stdout = fake_files
    mock_result.stderr = ""
    mock_result.returncode = 0

    emitted_messages = []

    def capture_emit(msg):
        emitted_messages.append(msg)

    # Create a mock message bus
    mock_message_bus = MagicMock()
    mock_message_bus.emit = capture_emit

    with patch("code_puppy.tools.file_operations.subprocess.run", return_value=mock_result):
        with patch("code_puppy.tools.file_operations.os.stat") as mock_stat:
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 100
            mock_stat_result.st_mode = 0o100644
            mock_stat.return_value = mock_stat_result

            with patch("code_puppy.tools.file_operations.os.path.exists", return_value=True):
                with patch("code_puppy.tools.file_operations.os.path.isdir", return_value=True):
                    with patch("code_puppy.tools.file_operations.get_message_bus", return_value=mock_message_bus):
                        await _list_files(_make_context(), "/fake/path", recursive=True)

    # Find the FileListingMessage
    file_listing_msgs = [m for m in emitted_messages if isinstance(m, FileListingMessage)]
    assert len(file_listing_msgs) == 1

    # Verify file entries are capped
    msg = file_listing_msgs[0]
    assert len(msg.files) <= MAX_LIST_FILES_ENTRIES


@pytest.mark.asyncio
async def test_list_files_no_truncation_when_under_limit():
    """list_files should not show truncation warning when under limit."""
    # Mock ripgrep to return fewer files than the limit
    fake_files = "\n".join([f"/fake/path/file{i}.txt" for i in range(10)])

    mock_result = MagicMock()
    mock_result.stdout = fake_files
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("code_puppy.tools.file_operations.subprocess.run", return_value=mock_result):
        with patch("code_puppy.tools.file_operations.os.stat") as mock_stat:
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 100
            mock_stat_result.st_mode = 0o100644
            mock_stat.return_value = mock_stat_result

            with patch("code_puppy.tools.file_operations.os.path.exists", return_value=True):
                with patch("code_puppy.tools.file_operations.os.path.isdir", return_value=True):
                    result = await _list_files(_make_context(), "/fake/path", recursive=True)

    # Should NOT contain truncation warning
    assert "TRUNCATED" not in result.content
    assert "truncated" not in result.content.lower()
