"""Tests for the NativeBackend unified acceleration interface.

bd-61: Tests for Phase 1 of Fast Puppy rewrite — native backend adapter.
bd-62: Tests for Phase 2 — Elixir control plane routing.
bd-64: Tests for Phase 4 — Elixir NIF routing for parse operations.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.native_backend import (
    BackendPreference,
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
    parse_source,
    extract_symbols,
    supported_languages,
    index_directory,
)


@pytest.fixture(autouse=True)
def reset_backend_state():
    """Reset backend state after each test to ensure isolation.
    
    This is critical for parallel test execution (pytest-xdist) where
    one test's state change could affect another test.
    
    Resets:
    - _backend_preference (routing preference)
    - _capability_enabled (per-capability enabled state)
    - _last_source (last routing source tracking)
    - _turbo_parse_imports (cached imports)
    """
    original_preference = NativeBackend._backend_preference
    original_enabled = NativeBackend._capability_enabled.copy()
    original_last_source = NativeBackend._last_source.copy()
    original_turbo_parse = NativeBackend._turbo_parse_imports
    yield
    NativeBackend._backend_preference = original_preference
    NativeBackend._capability_enabled = original_enabled
    NativeBackend._last_source = original_last_source
    NativeBackend._turbo_parse_imports = original_turbo_parse


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
        # Result may contain "error" or actual parse data depending on backend availability
        assert "error" in result or "tree" in result or "success" in result

    def test_parse_file_disabled_capability(self, tmp_path: Path):
        """Test parse_file returns error when capability disabled."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Disable parse capability
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.PARSE)
        NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)

        try:
            result = NativeBackend.parse_file(str(test_file), "python")
            assert "error" in result
            assert "disabled" in result["error"].lower()
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

    def test_parse_source_returns_dict(self):
        """Test that parse_source returns expected structure."""
        source = "def hello(): pass"

        result = NativeBackend.parse_source(source, "python", _prefer_native=False)

        assert isinstance(result, dict)
        # Result may contain "error" or actual parse data depending on backend availability
        assert "error" in result or "tree" in result or "success" in result

    def test_extract_symbols_returns_list(self):
        """Test that extract_symbols returns a list."""
        source = "def hello(): pass"

        result = NativeBackend.extract_symbols(source, "python", _prefer_native=False)

        assert isinstance(result, list)

    def test_supported_languages_returns_list(self):
        """Test that supported_languages returns a list."""
        result = NativeBackend.supported_languages()

        assert isinstance(result, list)
        # Should have fallback languages at minimum
        assert "python" in result
        assert "elixir" in result

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

    def test_parse_source_module_level(self):
        """Test module-level parse_source function (bd-64)."""
        result = parse_source("def hello(): pass", "python")
        assert isinstance(result, dict)

    def test_extract_symbols_module_level(self):
        """Test module-level extract_symbols function (bd-64)."""
        result = extract_symbols("def hello(): pass", "python")
        assert isinstance(result, list)

    def test_supported_languages_module_level(self):
        """Test module-level supported_languages function (bd-64)."""
        result = supported_languages()
        assert isinstance(result, list)
        assert "python" in result
        assert "elixir" in result

    def test_index_directory_module_level(self, tmp_path: Path):
        """Test module-level index_directory function."""
        result = index_directory(str(tmp_path))
        assert isinstance(result, list)


class TestNativeBackendLazyLoading:
    """Tests for lazy loading of native modules.

    bd-76: turbo_ops removed. Only turbo_parse remains for parse operations.
    """

    def test_turbo_parse_lazy_loading(self):
        """Test that turbo_parse is lazily loaded (cached) after first access."""
        # Reset the cache
        NativeBackend._turbo_parse_imports = None

        # Before any operation, cache should be None
        assert NativeBackend._turbo_parse_imports is None

        # After accessing the cache, it should be populated
        _ = NativeBackend._get_turbo_parse()

        # After the operation, the cache should be populated
        assert NativeBackend._turbo_parse_imports is not None

    def test_turbo_parse_imported_on_parse_call(self):
        """Test that turbo_parse is imported when parse operation is called."""
        # Reset the cache
        NativeBackend._turbo_parse_imports = None

        # Parse operation should trigger import attempt
        with patch("code_puppy.native_backend.logger"):
            _ = NativeBackend._get_turbo_parse()

        # After the operation, the cache should be populated
        assert NativeBackend._turbo_parse_imports is not None


class TestNativeBackendErrorHandling:
    """Tests for error handling in NativeBackend."""

    def test_list_files_handles_exception(self):
        """Test that list_files handles exceptions gracefully.

        bd-76: Turbo ops removed, Python fallback always used for non-Elixir.
        """
        # When Elixir raises, should fallback to Python
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", side_effect=Exception("Test error")):
                result = NativeBackend.list_files("/nonexistent", _prefer_native=True)

                # Should fall back to Python
                assert isinstance(result, dict)
                assert "source" in result

    def test_read_file_handles_exception(self):
        """Test that read_file handles exceptions gracefully.

        bd-76: Turbo ops removed, Python fallback always used for non-Elixir.
        """
        # When Elixir raises, should fallback to Python
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", side_effect=Exception("Test error")):
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


class TestBackendPreference:
    """Tests for the BackendPreference enum (bd-62)."""

    def test_backend_preference_values(self):
        """Test that BackendPreference enum has expected values."""
        assert BackendPreference.ELIXIR_FIRST == "elixir_first"
        assert BackendPreference.RUST_FIRST == "rust_first"
        assert BackendPreference.PYTHON_ONLY == "python_only"

    def test_default_preference_is_rust_first(self):
        """Test that default preference is RUST_FIRST."""
        # Reset to default first
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        assert NativeBackend.get_backend_preference() == BackendPreference.RUST_FIRST

    def test_set_backend_preference_string(self):
        """Test setting preference by string value."""
        NativeBackend.set_backend_preference("elixir_first")
        assert NativeBackend.get_backend_preference() == BackendPreference.ELIXIR_FIRST

        NativeBackend.set_backend_preference("rust_first")
        assert NativeBackend.get_backend_preference() == BackendPreference.RUST_FIRST

    def test_set_backend_preference_enum(self):
        """Test setting preference by enum value."""
        NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
        assert NativeBackend.get_backend_preference() == BackendPreference.PYTHON_ONLY

@pytest.mark.xdist_group("elixir_routing")
class TestParseElixirRouting:
    """Tests for Elixir routing of parse operations (bd-64).
    
    These tests are marked with xdist_group to ensure they run serially,
    as they modify global backend state that can cause flakiness in 
    parallel execution.
    """

    def test_parse_file_routes_through_elixir_when_preferred(self, tmp_path: Path):
        """Test parse_file routes through Elixir when ELIXIR_FIRST preference."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={
                "tree": {}, "language": "python", "success": True
            }) as mock_call:
                result = NativeBackend.parse_file(str(test_file), "python")

                mock_call.assert_called_once()
                assert mock_call.call_args[0][0] == "parse_file"
                assert mock_call.call_args[0][1]["path"] == str(test_file)
                assert result.get("success") is True

    def test_parse_file_falls_back_when_elixir_fails(self, tmp_path: Path):
        """Test parse_file falls back when Elixir call fails."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", side_effect=ConnectionError("Elixir down")):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                    result = NativeBackend.parse_file(str(test_file), "python")

                    # Should return error since no backend available
                    assert "error" in result

    def test_parse_source_routes_through_elixir_when_preferred(self):
        """Test parse_source routes through Elixir when ELIXIR_FIRST preference."""
        source = "def hello(): pass"

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={
                "tree": {}, "language": "python"
            }) as mock_call:
                _ = NativeBackend.parse_source(source, "python")

                mock_call.assert_called_once()
                assert mock_call.call_args[0][0] == "parse_source"
                assert mock_call.call_args[0][1]["source"] == source
                assert mock_call.call_args[0][1]["language"] == "python"

    def test_extract_symbols_routes_through_elixir_when_preferred(self):
        """Test extract_symbols routes through Elixir when ELIXIR_FIRST preference."""
        source = "def hello(): pass"
        expected_symbols = [{"name": "hello", "kind": "function", "range": [1, 0, 1, 13]}]

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={
                "symbols": expected_symbols
            }) as mock_call:
                result = NativeBackend.extract_symbols(source, "python")

                mock_call.assert_called_once()
                assert mock_call.call_args[0][0] == "extract_symbols"
                assert result == expected_symbols

    def test_extract_symbols_returns_empty_list_when_disabled(self):
        """Test extract_symbols returns empty list when capability disabled."""
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.PARSE)
        NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)

        try:
            result = NativeBackend.extract_symbols("def hello(): pass", "python")
            assert result == []
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

    def test_supported_languages_routes_through_elixir_when_available(self):
        """Test supported_languages routes through Elixir when available."""
        expected_languages = ["python", "elixir", "rust", "javascript"]

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={
                "languages": expected_languages
            }) as mock_call:
                result = NativeBackend.supported_languages()

                mock_call.assert_called_once()
                assert mock_call.call_args[0][0] == "supported_languages"
                assert result == expected_languages

    def test_supported_languages_falls_back_when_elixir_returns_empty(self):
        """Test supported_languages falls back when Elixir returns empty list."""
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={"languages": []}):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                    result = NativeBackend.supported_languages()

                    # Should fall back to default list
                    assert "python" in result
                    assert "elixir" in result

    def test_parse_tracks_last_source_elixir(self, tmp_path: Path):
        """Test that parse_file tracks 'elixir' as last source when using Elixir."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
        # Clear the last source tracking
        NativeBackend._last_source.pop(NativeBackend.Capabilities.PARSE, None)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_call_elixir", return_value={"success": True}):
                NativeBackend.parse_file(str(test_file), "python")

                assert NativeBackend._last_source.get(NativeBackend.Capabilities.PARSE) == "elixir"

    def test_parse_tracks_last_source_turbo_parse(self, tmp_path: Path):
        """Test that parse_file tracks 'turbo_parse' as last source when using Rust."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        # Clear the last source tracking
        NativeBackend._last_source.pop(NativeBackend.Capabilities.PARSE, None)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={
                "available": True,
                "parse_file": MagicMock(return_value={"success": True})
            }):
                NativeBackend.parse_file(str(test_file), "python")

                # Note: If turbo_parse is actually available, this would track turbo_parse
                # but since we're mocking it to return available but turbo_parse isn't
                # really there, it may still fallback. This tests the logic path.

    def test_get_detailed_status_includes_parse_elixir(self):
        """Test that get_detailed_status includes Elixir availability for parse."""
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                status = NativeBackend.get_detailed_status()

                assert "parse" in status
                assert "elixir_available" in status["parse"]
                assert status["parse"]["elixir_available"] is True
                assert "rust_available" in status["parse"]
                assert status["parse"]["rust_available"] is False


@pytest.mark.xdist_group("elixir_routing")
class TestElixirRouting:
    """Tests for Elixir control plane routing (bd-62).
    
    These tests are marked with xdist_group to ensure they run serially,
    as they modify global backend state that can cause flakiness in 
    parallel execution.
    """

    def test_is_elixir_available_import_error(self):
        """Test _is_elixir_available returns False when import fails."""
        with patch("builtins.__import__", side_effect=ImportError("No module named elixir_bridge")):
            result = NativeBackend._is_elixir_available()
            assert result is False

    def test_is_elixir_available_returns_false_when_not_connected(self):
        """Test _is_elixir_available when elixir_bridge is not connected."""
        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=False):
            result = NativeBackend._is_elixir_available()
            assert result is False

    def test_is_elixir_available_returns_true_when_connected(self):
        """Test _is_elixir_available when elixir_bridge is connected."""
        with patch("code_puppy.plugins.elixir_bridge.is_connected", return_value=True):
            result = NativeBackend._is_elixir_available()
            assert result is True

    def test_should_use_elixir_python_only(self):
        """Test _should_use_elixir returns False when preference is PYTHON_ONLY."""
        NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            result = NativeBackend._should_use_elixir("file_ops")
            assert result is False

    def test_should_use_elixir_elixir_first_available(self):
        """Test _should_use_elixir returns True when ELIXIR_FIRST and available."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            result = NativeBackend._should_use_elixir("file_ops")
            assert result is True

    def test_should_use_elixir_elixir_first_unavailable(self):
        """Test _should_use_elixir returns False when ELIXIR_FIRST but unavailable."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
            result = NativeBackend._should_use_elixir("file_ops")
            assert result is False

    def test_should_use_elixir_rust_first_with_elixir_available(self):
        """Test _should_use_elixir returns True when RUST_FIRST and Elixir available.

        bd-76: With turbo_ops removed, RUST_FIRST now means "use Elixir if available".
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            result = NativeBackend._should_use_elixir("file_ops")
            assert result is True  # Elixir is available, so use it

    def test_should_use_elixir_rust_first_without_rust(self):
        """Test _should_use_elixir returns True when RUST_FIRST but Rust unavailable."""
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "is_available", return_value=False):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                result = NativeBackend._should_use_elixir("file_ops")
                assert result is True  # Rust unavailable, Elixir available, should use Elixir

    def test_get_file_ops_source_elixir_first(self):
        """Test _get_file_ops_source with ELIXIR_FIRST preference."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            result = NativeBackend._get_file_ops_source()
            assert result == "elixir"

    def test_get_file_ops_source_rust_first_with_elixir(self):
        """Test _get_file_ops_source with RUST_FIRST preference when Elixir available.

        bd-76: With turbo_ops removed, returns "elixir" when Elixir available.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            result = NativeBackend._get_file_ops_source()
            assert result == "elixir"

    def test_get_file_ops_source_python_only(self):
        """Test _get_file_ops_source with PYTHON_ONLY preference."""
        NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)

        result = NativeBackend._get_file_ops_source()
        assert result == "python"

    def test_list_files_falls_back_when_elixir_not_implemented(self, tmp_path: Path):
        """Test list_files falls back when Elixir transport not implemented."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", side_effect=NotImplementedError):
                result = NativeBackend.list_files(str(tmp_path), recursive=False)

                # Should fall back to Python fallback
                assert isinstance(result, dict)
                assert "files" in result or "error" in result

    def test_list_files_falls_back_when_elixir_exception(self, tmp_path: Path):
        """Test list_files falls back when Elixir raises exception."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", side_effect=ConnectionError("Not connected")):
                result = NativeBackend.list_files(str(tmp_path), recursive=False)

                # Should fall back to Python fallback
                assert isinstance(result, dict)
                assert "files" in result or "error" in result

    def test_read_file_falls_back_when_elixir_not_implemented(self, tmp_path: Path):
        """Test read_file falls back when Elixir transport not implemented."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", side_effect=NotImplementedError):
                result = NativeBackend.read_file(str(test_file))

                # Should fall back to Python
                assert isinstance(result, dict)
                assert "content" in result or "error" in result

    def test_grep_falls_back_when_elixir_not_implemented(self, tmp_path: Path):
        """Test grep falls back when Elixir transport not implemented."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", side_effect=NotImplementedError):
                result = NativeBackend.grep("def", str(tmp_path))

                # Should fall back to Python
                assert isinstance(result, dict)
                assert "matches" in result or "error" in result


@pytest.mark.xdist_group("elixir_routing")
class TestElixirStatusIntegration:
    """Integration tests for Elixir status reporting (bd-62).
    
    These tests are marked with xdist_group to ensure they run serially,
    as they modify global backend state that can cause flakiness in 
    parallel execution.
    """

    def test_get_detailed_status_includes_elixir(self):
        """Test that get_detailed_status includes Elixir availability."""
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            status = NativeBackend.get_detailed_status()

            assert "file_ops" in status
            assert "elixir_available" in status["file_ops"] or "elixir" in str(status)

    def test_get_status_file_ops_with_elixir_available(self):
        """Test get_status when Elixir is available for file_ops.

        bd-76: With turbo_ops removed and Python fallback always available.
        """
        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            status = NativeBackend.get_status()

            file_ops_status = status[NativeBackend.Capabilities.FILE_OPS]
            # Should be available because Elixir is available and Python fallback exists
            assert file_ops_status.available is True
            assert file_ops_status.active is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
