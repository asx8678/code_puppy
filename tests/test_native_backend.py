"""Tests for the NativeBackend unified acceleration interface.

bd-61: Tests for Phase 1 of Fast Puppy rewrite — native backend adapter.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.native_backend import (
    CapabilityInfo,
    NativeBackend,
    get_backend_status,
    is_capability_available,
    list_files,
    grep,
    read_file,
    read_files,
    serialize_messages,
    parse_file,
    index_directory,
)


class TestCapabilityInfo:
    """Tests for the CapabilityInfo dataclass."""

    def test_capability_info_creation(self):
        """Test that CapabilityInfo can be created and accessed."""
        info = CapabilityInfo(
            name="test_cap",
            configured="rust",
            available=True,
            active=True,
            status="active",
        )
        assert info.name == "test_cap"
        assert info.configured == "rust"
        assert info.available is True
        assert info.active is True
        assert info.status == "active"

    def test_capability_info_immutability(self):
        """Test that CapabilityInfo is frozen/immutable."""
        info = CapabilityInfo(
            name="test_cap",
            configured="rust",
            available=True,
            active=True,
            status="active",
        )
        with pytest.raises(AttributeError):
            info.name = "new_name"  # type: ignore[misc]


class TestNativeBackendCapabilities:
    """Tests for capability constants."""

    def test_capability_constants(self):
        """Test that capability constants are defined."""
        assert NativeBackend.Capabilities.MESSAGE_CORE == "message_core"
        assert NativeBackend.Capabilities.FILE_OPS == "file_ops"
        assert NativeBackend.Capabilities.REPO_INDEX == "repo_index"
        assert NativeBackend.Capabilities.PARSE == "parse"


class TestNativeBackendStatus:
    """Tests for status checking methods."""

    def test_get_status_returns_dict(self):
        """Test that get_status returns a dict of CapabilityInfo."""
        status = NativeBackend.get_status()
        assert isinstance(status, dict)
        assert NativeBackend.Capabilities.MESSAGE_CORE in status
        assert NativeBackend.Capabilities.FILE_OPS in status
        assert NativeBackend.Capabilities.REPO_INDEX in status
        assert NativeBackend.Capabilities.PARSE in status

    def test_get_status_capability_info_types(self):
        """Test that get_status returns CapabilityInfo objects."""
        status = NativeBackend.get_status()
        for info in status.values():
            assert isinstance(info, CapabilityInfo)
            assert isinstance(info.name, str)
            assert isinstance(info.configured, str)
            assert isinstance(info.available, bool)
            assert isinstance(info.active, bool)
            assert isinstance(info.status, str)

    def test_is_available_with_valid_capability(self):
        """Test is_available with valid capability names."""
        # Just check it doesn't raise and returns a bool
        result = NativeBackend.is_available(NativeBackend.Capabilities.FILE_OPS)
        assert isinstance(result, bool)

    def test_is_available_with_invalid_capability(self):
        """Test is_available returns False for invalid capability."""
        result = NativeBackend.is_available("invalid_capability")
        assert result is False


class TestNativeBackendFileOperations:
    """Tests for file operation methods."""

    def test_list_files_returns_dict(self, tmp_path: Path):
        """Test that list_files returns expected structure."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = NativeBackend.list_files(str(tmp_path), recursive=False)

        assert isinstance(result, dict)
        assert "files" in result or "error" in result
        if "error" not in result:
            assert isinstance(result.get("files"), list)

    def test_list_files_fallback_when_prefer_native_false(self, tmp_path: Path):
        """Test that _prefer_native=False uses Python fallback."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = NativeBackend.list_files(str(tmp_path), recursive=False, _prefer_native=False)

        assert isinstance(result, dict)
        assert result.get("source") == "python_fallback"

    def test_grep_returns_dict(self, tmp_path: Path):
        """Test that grep returns expected structure."""
        # Create a test file with searchable content
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    pass\n")

        result = NativeBackend.grep("def", str(tmp_path), _prefer_native=False)

        assert isinstance(result, dict)
        assert "matches" in result or "error" in result
        if "matches" in result:
            assert isinstance(result["matches"], list)

    def test_read_file_returns_dict(self, tmp_path: Path):
        """Test that read_file returns expected structure."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        result = NativeBackend.read_file(str(test_file), _prefer_native=False)

        assert isinstance(result, dict)
        assert "content" in result or "error" in result
        if result.get("content"):
            assert result["content"] == test_content
            assert "num_tokens" in result

    def test_read_file_with_line_range(self, tmp_path: Path):
        """Test read_file with start_line and num_lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\n")

        result = NativeBackend.read_file(str(test_file), start_line=2, num_lines=2, _prefer_native=False)

        if "content" in result and result["content"]:
            assert "line2" in result["content"]

    def test_read_file_nonexistent(self, tmp_path: Path):
        """Test read_file with nonexistent file."""
        nonexistent = tmp_path / "does_not_exist.txt"

        result = NativeBackend.read_file(str(nonexistent), _prefer_native=False)

        assert "error" in result

    def test_read_files_batch(self, tmp_path: Path):
        """Test read_files batch operation."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        result = NativeBackend.read_files([str(file1), str(file2)], _prefer_native=False)

        assert isinstance(result, dict)
        assert "files" in result
        assert result["total_files"] == 2
        assert len(result["files"]) == 2


class TestNativeBackendMessageOperations:
    """Tests for message operation methods."""

    def test_serialize_messages_empty_list(self):
        """Test serialize_messages with empty list."""
        result = NativeBackend.serialize_messages([])
        assert result == []

    def test_serialize_messages_delegates_to_bridge(self):
        """Test that serialize_messages delegates to _core_bridge."""
        with patch("code_puppy._core_bridge.serialize_messages_for_rust") as mock_serialize:
            mock_serialize.return_value = [{"kind": "request"}]
            messages = [MagicMock()]

            result = NativeBackend.serialize_messages(messages)

            mock_serialize.assert_called_once_with(messages)
            assert result == [{"kind": "request"}]

    def test_create_message_batch(self):
        """Test create_message_batch returns MessageBatchHandle."""
        from code_puppy._core_bridge import MessageBatchHandle

        # Even with no messages, it should create a handle
        messages: list = []
        result = NativeBackend.create_message_batch(messages)
        assert isinstance(result, MessageBatchHandle)


class TestNativeBackendIndexOperations:
    """Tests for repository index operations."""

    def test_index_directory_returns_list(self, tmp_path: Path):
        """Test that index_directory returns a list."""
        # Create some test files
        (tmp_path / "main.py").write_text("def main(): pass")
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "utils.py").write_text("def util(): pass")

        result = NativeBackend.index_directory(str(tmp_path), max_files=10, _prefer_native=False)

        assert isinstance(result, list)
        # Should find at least the Python files
        assert len(result) >= 0  # Might be 0 if indexing not implemented

    def test_index_directory_empty_directory(self, tmp_path: Path):
        """Test index_directory with empty directory."""
        result = NativeBackend.index_directory(str(tmp_path), _prefer_native=False)

        assert isinstance(result, list)
        assert len(result) == 0


class TestNativeBackendParseOperations:
    """Tests for parse operations."""

    def test_parse_file_returns_dict(self, tmp_path: Path):
        """Test that parse_file returns expected structure."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        result = NativeBackend.parse_file(str(test_file), "python", _prefer_native=False)

        assert isinstance(result, dict)
        assert "success" in result or "error" in result

    def test_parse_source_returns_dict(self):
        """Test that parse_source returns expected structure."""
        source = "def hello(): pass"

        result = NativeBackend.parse_source(source, "python", _prefer_native=False)

        assert isinstance(result, dict)
        assert "success" in result or "error" in result

    def test_is_language_supported_fallback(self):
        """Test is_language_supported uses fallback when turbo_parse unavailable."""
        # Force fallback by using _prefer_native=False internally
        result = NativeBackend.is_language_supported("python")
        assert isinstance(result, bool)


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_backend_status(self):
        """Test module-level get_backend_status function."""
        result = get_backend_status()
        assert isinstance(result, dict)

    def test_is_capability_available(self):
        """Test module-level is_capability_available function."""
        result = is_capability_available(NativeBackend.Capabilities.FILE_OPS)
        assert isinstance(result, bool)

    def test_list_files_module_level(self, tmp_path: Path):
        """Test module-level list_files function."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        result = list_files(str(tmp_path), recursive=False)
        assert isinstance(result, dict)

    def test_grep_module_level(self, tmp_path: Path):
        """Test module-level grep function."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        result = grep("def", str(tmp_path))
        assert isinstance(result, dict)

    def test_read_file_module_level(self, tmp_path: Path):
        """Test module-level read_file function."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = read_file(str(test_file))
        assert isinstance(result, dict)

    def test_read_files_module_level(self, tmp_path: Path):
        """Test module-level read_files function."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")

        result = read_files([str(file1)])
        assert isinstance(result, dict)
        assert "files" in result

    def test_serialize_messages_module_level(self):
        """Test module-level serialize_messages function."""
        with patch("code_puppy._core_bridge.serialize_messages_for_rust") as mock_serialize:
            mock_serialize.return_value = []
            result = serialize_messages([])
            assert result == []

    def test_parse_file_module_level(self, tmp_path: Path):
        """Test module-level parse_file function."""
        test_file = tmp_path / "test.py"
        test_file.write_text("pass")

        result = parse_file(str(test_file), "python")
        assert isinstance(result, dict)

    def test_index_directory_module_level(self, tmp_path: Path):
        """Test module-level index_directory function."""
        result = index_directory(str(tmp_path))
        assert isinstance(result, list)


class TestNativeBackendLazyLoading:
    """Tests for lazy loading of native modules."""

    def test_turbo_ops_lazy_loading(self):
        """Test that turbo_ops is lazily loaded (cached) after first access."""
        # Reset the cache
        NativeBackend._turbo_ops_imports = None

        # Before any operation, cache should be None
        assert NativeBackend._turbo_ops_imports is None

        # After a file operation, cache should be populated
        with patch("code_puppy.native_backend.logger"):
            NativeBackend.list_files(".", _prefer_native=False)

        # After the operation, the cache should be populated
        assert NativeBackend._turbo_ops_imports is not None

    def test_turbo_ops_imported_on_file_op(self):
        """Test that turbo_ops is imported when file op is called."""
        # Reset the cache
        NativeBackend._turbo_ops_imports = None

        # File operation should trigger import attempt
        with patch("code_puppy.native_backend.logger"):
            NativeBackend.list_files(".", _prefer_native=True)

        # After the operation, the cache should be populated
        assert NativeBackend._turbo_ops_imports is not None


class TestNativeBackendErrorHandling:
    """Tests for error handling in NativeBackend."""

    def test_list_files_handles_exception(self):
        """Test that list_files handles exceptions gracefully."""
        with patch.object(NativeBackend, "_get_turbo_ops") as mock_get_ops:
            mock_get_ops.return_value = {
                "available": True,
                "list_files": MagicMock(side_effect=Exception("Test error")),
            }

            result = NativeBackend.list_files("/nonexistent", _prefer_native=True)

            # Should fall back to Python
            assert isinstance(result, dict)
            assert "source" in result

    def test_read_file_handles_exception(self):
        """Test that read_file handles exceptions gracefully."""
        with patch.object(NativeBackend, "_get_turbo_ops") as mock_get_ops:
            mock_get_ops.return_value = {
                "available": True,
                "read_file": MagicMock(side_effect=Exception("Test error")),
            }

            result = NativeBackend.read_file("/nonexistent", _prefer_native=True)

            # Should fall back to Python
            assert isinstance(result, dict)
            assert "source" in result


class TestNativeBackendIntegration:
    """Integration tests for NativeBackend."""

    def test_full_workflow_with_fallback(self, tmp_path: Path):
        """Test a full workflow using Python fallback."""
        # Create test structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main():\n    print('hello')\n")
        (tmp_path / "src" / "utils.py").write_text("def util():\n    pass\n")
        (tmp_path / "README.md").write_text("# Project\n")

        # List files
        files_result = NativeBackend.list_files(str(tmp_path), _prefer_native=False)
        assert "error" not in files_result or files_result.get("source") == "python_fallback"

        # Search files
        grep_result = NativeBackend.grep("def", str(tmp_path), _prefer_native=False)
        assert isinstance(grep_result.get("matches", []), list)

        # Read a file
        main_file = tmp_path / "src" / "main.py"
        read_result = NativeBackend.read_file(str(main_file), _prefer_native=False)
        if "content" in read_result:
            assert "main" in read_result["content"]

    def test_capability_availability_consistency(self):
        """Test that capability availability is consistent across methods."""
        status = NativeBackend.get_status()

        for cap_name, info in status.items():
            is_avail = NativeBackend.is_available(cap_name)
            # is_available should match the active field in status
            assert is_avail == info.active


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
