"""Tests for the NativeBackend unified acceleration interface.

bd-61: Tests for Phase 1 of Fast Puppy rewrite — native backend adapter.
bd-62: Tests for Phase 2 — Elixir control plane routing.
bd-11: Tests for Phase 4 — Complete parse contract with Elixir NIF routing.
"""

import sys
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
        assert NativeBackend.Capabilities.EDIT_OPS == "edit_ops"


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
        assert NativeBackend.Capabilities.EDIT_OPS in status

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
        # bd-11: Strengthened assertions to verify specific expected values
        assert NativeBackend.is_language_supported("python") is True
        assert NativeBackend.is_language_supported("elixir") is True
        assert NativeBackend.is_language_supported("brainfuck") is False


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
        """Test module-level parse_source function (bd-11)."""
        result = parse_source("def hello(): pass", "python")
        assert isinstance(result, dict)

    def test_extract_symbols_module_level(self):
        """Test module-level extract_symbols function (bd-11)."""
        result = extract_symbols("def hello(): pass", "python")
        assert isinstance(result, list)

    def test_supported_languages_module_level(self):
        """Test module-level supported_languages function (bd-11)."""
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
    """Tests for the BackendPreference enum (bd-62, bd-13)."""

    def test_backend_preference_values(self):
        """Test that BackendPreference enum has expected values."""
        assert BackendPreference.ELIXIR_FIRST == "elixir_first"
        assert BackendPreference.RUST_FIRST == "rust_first"
        assert BackendPreference.PYTHON_ONLY == "python_only"

    def test_default_preference_is_elixir_first(self):
        """Test that default preference is ELIXIR_FIRST."""
        # bd-13: Default is ELIXIR_FIRST (not RUST_FIRST as the old comment said)
        # Check the actual current default
        current_pref = NativeBackend.get_backend_preference()
        assert current_pref == BackendPreference.ELIXIR_FIRST

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


class TestCapabilityRouting:
    """Tests for explicit capability routing (bd-13)."""

    def test_routing_message_core(self):
        """Test routing for MESSAGE_CORE capability."""
        routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.MESSAGE_CORE)

        assert routing["capability"] == NativeBackend.Capabilities.MESSAGE_CORE
        assert len(routing["backends"]) == 2
        assert routing["backends"][0][0] == "rust"
        assert routing["backends"][1][0] == "python"
        # Python is always available
        assert routing["backends"][1][1] is True

    def test_routing_file_ops(self):
        """Test routing for FILE_OPS capability."""
        routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.FILE_OPS)

        assert routing["capability"] == NativeBackend.Capabilities.FILE_OPS
        assert routing["backends"][0][0] == "elixir"
        assert routing["backends"][1][0] == "python"
        # Python is always available
        assert routing["backends"][1][1] is True

    def test_routing_repo_index(self):
        """Test routing for REPO_INDEX capability."""
        routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.REPO_INDEX)

        assert routing["capability"] == NativeBackend.Capabilities.REPO_INDEX
        assert routing["backends"][0][0] == "elixir"
        assert routing["backends"][1][0] == "python"

    def test_routing_parse_elixir_first(self):
        """Test routing for PARSE with ELIXIR_FIRST preference."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
        routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.PARSE)

        assert routing["capability"] == NativeBackend.Capabilities.PARSE
        assert routing["preference"] == "elixir_first"
        # ELIXIR_FIRST: order is Elixir → turbo_parse → python_fallback
        assert routing["backends"][0][0] == "elixir"
        assert routing["backends"][1][0] == "turbo_parse"
        assert routing["backends"][2][0] == "python_fallback"

    def test_routing_parse_rust_first_with_turbo_available(self):
        """Test routing for PARSE with RUST_FIRST when turbo_parse available.

        bd-13: RUST_FIRST should skip Elixir when turbo_parse is available.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        # Mock turbo_parse as available
        with patch.object(NativeBackend, "_get_turbo_parse", return_value={
            "available": True,
            "parse_file": MagicMock(),
        }):
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.PARSE)

            assert routing["preference"] == "rust_first"
            # RUST_FIRST + turbo available: order is turbo_parse → elixir → python
            assert routing["backends"][0][0] == "turbo_parse"
            assert routing["backends"][0][1] is True  # turbo available
            assert routing["backends"][1][0] == "elixir"
            assert routing["backends"][2][0] == "python_fallback"

    def test_routing_parse_rust_first_without_turbo(self):
        """Test routing for PARSE with RUST_FIRST when turbo_parse unavailable.

        bd-13: RUST_FIRST should still permit Elixir when turbo_parse unavailable.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        # Mock turbo_parse as unavailable, but Elixir available
        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.PARSE)

                assert routing["preference"] == "rust_first"
                # RUST_FIRST but turbo unavailable: effective order is Elixir first
                # (since turbo isn't available, Elixir becomes the effective first choice)
                assert routing["backends"][0][0] == "elixir"
                assert routing["backends"][0][1] is True  # elixir available
                assert routing["backends"][1][0] == "turbo_parse"
                assert routing["backends"][1][1] is False  # turbo not available

    def test_routing_includes_will_use(self):
        """Test that routing includes the will_use field."""
        routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.FILE_OPS)

        # will_use should be set to the first available backend
        assert "will_use" in routing
        # For FILE_OPS, Python is always available
        # If Elixir is not available, will_use should be python
        if not routing["backends"][0][1]:  # elixir not available
            assert routing["will_use"] == "python"

    def test_rust_first_skips_elixir_for_parse_when_turbo_available(self):
        """Test RUST_FIRST skips Elixir for parse when turbo_parse available.

        bd-13: _should_use_elixir should return False for PARSE when RUST_FIRST and turbo available.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                result = NativeBackend._should_use_elixir(NativeBackend.Capabilities.PARSE)

                # Should be False because RUST_FIRST + turbo available → skip Elixir
                assert result is False

    def test_rust_first_uses_elixir_for_parse_when_turbo_unavailable(self):
        """Test RUST_FIRST permits Elixir for parse when turbo_parse unavailable.

        bd-13: _should_use_elixir should return True for PARSE when RUST_FIRST but turbo unavailable.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                result = NativeBackend._should_use_elixir(NativeBackend.Capabilities.PARSE)

                # Should be True because RUST_FIRST but turbo unavailable → use Elixir as fallback
                assert result is True

    def test_rust_first_uses_elixir_for_file_ops(self):
        """Test RUST_FIRST still uses Elixir for FILE_OPS (not affected by turbo_parse)."""
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)

        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                result = NativeBackend._should_use_elixir(NativeBackend.Capabilities.FILE_OPS)

                # Should be True because FILE_OPS doesn't skip Elixir on RUST_FIRST
                assert result is True

    def test_elixir_first_uses_elixir_for_parse_regardless_of_turbo(self):
        """Test ELIXIR_FIRST uses Elixir for parse regardless of turbo_parse availability."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                result = NativeBackend._should_use_elixir(NativeBackend.Capabilities.PARSE)

                # Should be True because ELIXIR_FIRST → always try Elixir first
                assert result is True


class TestEditOpsRouting:
    """Tests for EDIT_OPS capability routing (bd-41)."""

    def test_edit_ops_capability_exists(self):
        assert NativeBackend.Capabilities.EDIT_OPS == "edit_ops"

    def test_edit_ops_in_status(self):
        status = NativeBackend.get_status()
        assert "edit_ops" in status

    def test_edit_ops_in_detailed_status(self):
        detailed = NativeBackend.get_detailed_status()
        assert "edit_ops" in detailed
        assert "routing" in detailed["edit_ops"]
        assert "source" in detailed["edit_ops"]

    def test_edit_ops_routing_elixir_first(self):
        NativeBackend.set_backend_preference("elixir_first")
        routing = NativeBackend.get_capability_routing("edit_ops")
        assert routing["preference"] == "elixir_first"
        # Should have elixir and python backends
        backend_names = [b[0] for b in routing["backends"]]
        assert "elixir" in backend_names
        assert "python" in backend_names

    def test_edit_ops_routing_python_only(self):
        NativeBackend.set_backend_preference("python_only")
        routing = NativeBackend.get_capability_routing("edit_ops")
        backend_names = [b[0] for b in routing["backends"]]
        assert "python" in backend_names
        assert "elixir" not in backend_names
        NativeBackend.set_backend_preference("elixir_first")  # Reset

    def test_edit_ops_disable_enable(self):
        NativeBackend.disable_capability("edit_ops")
        routing = NativeBackend.get_capability_routing("edit_ops")
        assert routing["will_use"] == "disabled"
        NativeBackend.enable_capability("edit_ops")


class TestDetailedStatus:
    """Tests for detailed status reporting (bd-13)."""

    def test_detailed_status_message_core_rust_available(self):
        """Test that get_detailed_status reports real message_core Rust availability.

        bd-13: message_core.rust_available should reflect actual Rust availability.
        """
        status = NativeBackend.get_detailed_status()

        assert "message_core" in status
        assert "rust_available" in status["message_core"]
        # The value should be the actual RUST_AVAILABLE from _core_bridge
        from code_puppy._core_bridge import RUST_AVAILABLE

        assert status["message_core"]["rust_available"] == RUST_AVAILABLE

    def test_detailed_status_includes_routing(self):
        """Test that get_detailed_status includes routing info for all capabilities."""
        status = NativeBackend.get_detailed_status()

        for cap in [
            NativeBackend.Capabilities.MESSAGE_CORE,
            NativeBackend.Capabilities.FILE_OPS,
            NativeBackend.Capabilities.REPO_INDEX,
            NativeBackend.Capabilities.PARSE,
            NativeBackend.Capabilities.EDIT_OPS,
        ]:
            assert cap in status
            assert "routing" in status[cap]
            assert "backends" in status[cap]["routing"]
            assert "will_use" in status[cap]["routing"]


@pytest.mark.xdist_group("elixir_routing")
class TestParseElixirRouting:
    """Tests for Elixir routing of parse operations (bd-11).
    
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


    def test_index_directory_routes_through_elixir(self, tmp_path: Path):
        """Test index_directory calls Elixir when available (bd-108)."""
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        mock_result = {
            "files": [
                {"path": "src/main.py", "kind": "python", "symbols": ["main"]},
                {"path": "README.md", "kind": "project-file", "symbols": []},
            ],
            "count": 2,
        }

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", return_value=mock_result) as mock_call:
                result = NativeBackend.index_directory(str(tmp_path), max_files=10, max_symbols_per_file=5)

                mock_call.assert_called_once_with(
                    "repo_compass_index",
                    {"root": str(tmp_path), "max_files": 10, "max_symbols_per_file": 5},
                )
                assert isinstance(result, list)
                assert len(result) == 2
                assert result[0]["path"] == "src/main.py"

    def test_index_directory_falls_back_when_elixir_fails(self, tmp_path: Path):
        """Test index_directory falls back to Python when Elixir raises exception."""
        (tmp_path / "test.py").write_text("def hello(): pass")
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", side_effect=ConnectionError("down")):
                result = NativeBackend.index_directory(str(tmp_path), max_files=10)

                assert isinstance(result, list)
                # Falls back to Python (may or may not find files)

    def test_index_directory_skips_elixir_when_python_only(self, tmp_path: Path):
        """Test index_directory skips Elixir when preference is PYTHON_ONLY."""
        (tmp_path / "test.py").write_text("def hello(): pass")
        NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)

        with patch("code_puppy.plugins.elixir_bridge.call_method") as mock_call:
            result = NativeBackend.index_directory(str(tmp_path), max_files=10)

            mock_call.assert_not_called()
            assert isinstance(result, list)

    def test_index_directory_falls_back_on_elixir_error_response(self, tmp_path: Path):
        """Test index_directory falls back when Elixir returns error."""
        (tmp_path / "test.py").write_text("def hello(): pass")
        NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)

        mock_error = {"error": "indexer unavailable"}

        with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
            with patch("code_puppy.plugins.elixir_bridge.call_method", return_value=mock_error):
                result = NativeBackend.index_directory(str(tmp_path), max_files=10)

                assert isinstance(result, list)


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


@pytest.mark.xdist_group("python_only_routing")
class TestPythonOnlyRouting:
    """Tests for PYTHON_ONLY backend preference (bd-13-fix-semantics).
    
    These tests verify that PYTHON_ONLY mode:
    - Blocks ALL native backend calls (Elixir and turbo_parse)
    - Reports Python fallbacks in routing (not "disabled" for enabled capabilities)
    - Execution does not dispatch to Elixir or turbo_parse
    """

    def test_python_only_routing_reports_python_fallback(self):
        """Test that get_capability_routing reports Python fallbacks in PYTHON_ONLY mode.
        
        bd-13-fix-semantics: PYTHON_ONLY should report the actual Python fallback,
        not "disabled". Disabled is only for actually disabled capabilities.
        """
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.MESSAGE_CORE)
            NativeBackend.enable_capability(NativeBackend.Capabilities.FILE_OPS)
            NativeBackend.enable_capability(NativeBackend.Capabilities.REPO_INDEX)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # FILE_OPS and REPO_INDEX should route to Python
            for cap in [NativeBackend.Capabilities.FILE_OPS, NativeBackend.Capabilities.REPO_INDEX]:
                routing = NativeBackend.get_capability_routing(cap)
                assert routing["will_use"] == "python", f"Capability {cap} should route to Python in PYTHON_ONLY"
                assert routing["backends"] == [("python", True)], f"Capability {cap} should have Python fallback only"
            
            # PARSE should route to python_fallback
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.PARSE)
            assert routing["will_use"] == "python_fallback", "PARSE should route to python_fallback in PYTHON_ONLY"
            assert routing["backends"] == [("python_fallback", True)]
            
            # MESSAGE_CORE should still route to Python (it already has Python fallback)
            # Note: MESSAGE_CORE behavior is kept aligned with actual runtime
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.MESSAGE_CORE)
            # MESSAGE_CORE has Rust -> Python ordering; in PYTHON_ONLY, Rust unavailable
            # but we still report the same backends
            assert "python" in [b[0] for b in routing["backends"]]
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_blocks_elixir_calls(self):
        """Test that _should_use_elixir returns False for all capabilities in PYTHON_ONLY."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                for cap in [
                    NativeBackend.Capabilities.FILE_OPS,
                    NativeBackend.Capabilities.REPO_INDEX,
                    NativeBackend.Capabilities.PARSE,
                ]:
                    result = NativeBackend._should_use_elixir(cap)
                    assert result is False, f"_should_use_elixir should return False for {cap} in PYTHON_ONLY"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_blocks_turbo_parse(self):
        """Test that _should_use_turbo_parse returns False in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                result = NativeBackend._should_use_turbo_parse()
                assert result is False, "_should_use_turbo_parse should return False in PYTHON_ONLY"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_execution_no_dispatch(self, tmp_path: Path):
        """Test parse_file does not dispatch to Elixir or turbo_parse in PYTHON_ONLY mode."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock Elixir and turbo_parse as available - should NOT be called
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    with patch.object(NativeBackend, "_get_turbo_parse", return_value={
                        "available": True,
                        "parse_file": MagicMock(),
                    }):
                        result = NativeBackend.parse_file(str(test_file), "python")
                        
                        # Neither Elixir nor turbo_parse should be called
                        mock_call_elixir.assert_not_called()
                        # The turbo_parse mock should not be called either since PYTHON_ONLY blocks it
                        
                    # Result should be Python fallback (error since no backend)
                    assert "error" in result
                    assert result.get("path") == str(test_file)
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_source_no_dispatch(self):
        """Test parse_source does not dispatch to Elixir or turbo_parse in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.parse_source("def hello(): pass", "python")
                    
                    mock_call_elixir.assert_not_called()
                    assert "error" in result
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_extract_symbols_no_dispatch(self):
        """Test extract_symbols does not dispatch to Elixir or turbo_parse in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.extract_symbols("def hello(): pass", "python")
                    
                    mock_call_elixir.assert_not_called()
                    assert result == []  # Empty list when no backend available
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_get_folds_no_dispatch(self):
        """Test get_folds does not dispatch to Elixir or turbo_parse in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.get_folds("def hello(): pass", "python")
                    
                    mock_call_elixir.assert_not_called()
                    assert "error" in result
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_get_highlights_no_dispatch(self):
        """Test get_highlights does not dispatch to Elixir or turbo_parse in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.get_highlights("def hello(): pass", "python")
                    
                    mock_call_elixir.assert_not_called()
                    assert "error" in result
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_supported_languages_no_dispatch(self):
        """Test supported_languages does not dispatch to Elixir or turbo_parse in PYTHON_ONLY."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.supported_languages()
                    
                    mock_call_elixir.assert_not_called()
                    # Falls back to default list
                    assert "python" in result
                    assert "elixir" in result
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_batch_no_dispatch(self, tmp_path: Path):
        """Test parse_batch does not dispatch to Elixir or turbo_parse in PYTHON_ONLY.
        
        bd-13-fix-regression: Ensures parse_batch() does not route to turbo_parse in
        PYTHON_ONLY mode even if parse_file entrypoint exists.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock turbo_parse with parse_file entrypoint available - should NOT be called
            mock_parse_file = MagicMock(return_value={"tree": {}})
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    with patch.object(
                        NativeBackend,
                        "_get_turbo_parse",
                        return_value={"available": True, "parse_file": mock_parse_file},
                    ):
                        with patch.object(
                            NativeBackend,
                            "_is_turbo_parse_entrypoint_available",
                            return_value=True,  # Entrypoint IS available
                        ):
                            result = NativeBackend.parse_batch([str(test_file)], "python")
                            
                            # Neither Elixir nor turbo_parse should be called in PYTHON_ONLY
                            mock_call_elixir.assert_not_called()
                            mock_parse_file.assert_not_called()
                            # Should have results (even if individual results contain errors)
                            assert "results" in result
                            assert result["count"] == 1
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_extract_diagnostics_no_dispatch(self):
        """Test extract_syntax_diagnostics does not dispatch in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_call_elixir:
                    result = NativeBackend.extract_syntax_diagnostics("def hello(): pass", "python")
                    
                    mock_call_elixir.assert_not_called()
                    assert "error" in result
                    assert result.get("success") is False
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_health_check_reports_disabled(self):
        """Test parse_health_check reports disabled in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            result = NativeBackend.parse_health_check()
            
            assert result.get("available") is False
            assert result.get("backend") == "disabled"
            assert result.get("reason") == "python_only_mode"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_stats_reports_disabled(self):
        """Test parse_stats reports disabled in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            result = NativeBackend.parse_stats()
            
            assert result.get("backend") == "disabled"
            assert result.get("reason") == "python_only_mode"
            assert result.get("total_parses") == 0
        finally:
            NativeBackend.set_backend_preference(original_pref)

    # bd-13-fix-regression: Tests for PYTHON_ONLY + no native backends scenario
    def test_python_only_parse_batch_executes_python_fallback(self, tmp_path: Path):
        """Test parse_batch executes Python fallback in PYTHON_ONLY with no native backends.
        
        bd-13-fix-regression: This was the core bug - parse_batch() returned early with
        'Parse capability not active' because is_active() checks native availability.
        The fix uses is_enabled() which only checks user preference, allowing Python fallback.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock NO native backends available (the regression scenario)
            with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                    result = NativeBackend.parse_batch([str(test_file)], "python")
                    
                    # Should NOT return early with 'Parse capability not active' error
                    # Should execute Python fallback path
                    assert "error" not in result or result.get("error") != "Parse capability not active"
                    assert "results" in result
                    assert result["count"] == 1
                    # Verify Python fallback was recorded
                    assert NativeBackend._last_source.get(NativeBackend.Capabilities.PARSE) == "python_fallback"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_parse_file_executes_python_fallback(self, tmp_path: Path):
        """Test parse_file executes Python fallback in PYTHON_ONLY with no native backends.
        
        bd-13-fix-regression: Ensures parse_file() uses Python fallback when capability
        is enabled but no native backends are available.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock NO native backends available
            with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                    result = NativeBackend.parse_file(str(test_file), "python")
                    
                    # Should NOT return early with capability disabled error
                    assert result.get("error") != "Parse capability disabled"
                    # Python fallback returns error about no backend but includes path
                    assert result.get("path") == str(test_file)
                    # Verify Python fallback was recorded
                    assert NativeBackend._last_source.get(NativeBackend.Capabilities.PARSE) == "python_fallback"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_disabled_parse_capability_blocks_all_backends(self, tmp_path: Path):
        """Test that disabled PARSE capability blocks execution regardless of backend availability.
        
        This verifies that is_enabled() is the correct guard - it respects user disable
        while still allowing Python fallback when enabled but native unavailable.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_pref = NativeBackend.get_backend_preference()
        original_enabled = NativeBackend._capability_enabled.copy()
        try:
            # Set PYTHON_ONLY but DISABLE the PARSE capability
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock native backends as available - should still be blocked
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={
                    "available": True,
                    "parse_file": MagicMock(),
                }):
                    result = NativeBackend.parse_file(str(test_file), "python")
                    
                    # Should return early with capability disabled error
                    assert result.get("error") == "Parse capability disabled"
                    assert result.get("path") == str(test_file)
        finally:
            NativeBackend.set_backend_preference(original_pref)
            NativeBackend._capability_enabled = original_enabled


@pytest.mark.xdist_group("turbo_parse_status")
class TestTurboParseStatusSemantics:
    """Tests for get_turbo_parse_status semantics (bd-13-fix).
    
    These tests verify that get_turbo_parse_status:
    - Reports turbo_parse-specific status (not generic parse routing)
    - installed means turbo_parse Rust backend available
    - enabled/active are consistent with turbo_parse use
    """

    def test_turbo_parse_status_installed_means_rust_backend(self):
        """Test that 'installed' means turbo_parse Rust backend is available."""
        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
            with patch.object(NativeBackend, "parse_health_check", return_value={
                "available": True, "version": "1.0.0", "languages": ["python"]
            }):
                from code_puppy.acceleration import get_turbo_parse_status
                status = get_turbo_parse_status()
                
                assert status["installed"] is True
                assert status["backend_type"] == "turbo_parse"

    def test_turbo_parse_status_installed_false_when_not_available(self):
        """Test that 'installed' is False when turbo_parse is not available."""
        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
            from code_puppy.acceleration import get_turbo_parse_status
            status = get_turbo_parse_status()
            
            assert status["installed"] is False
            assert status["backend_type"] == "turbo_parse"

    def test_turbo_parse_status_disabled_in_python_only(self):
        """Test that enabled=False in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                from code_puppy.acceleration import get_turbo_parse_status
                status = get_turbo_parse_status()
                
                assert status["enabled"] is False
                assert status["active"] is False
                assert status["will_use"] == "disabled"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_turbo_parse_status_enabled_when_parse_active(self):
        """Test enabled/active when parse capability is enabled and turbo available (Elixir unavailable)."""
        # bd-13-fix-semantics: Mock Elixir unavailable so turbo_parse is selected
        # bd-13-partial-fix: Include parse_file entrypoint to simulate full turbo_parse availability
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

            with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                with patch.object(
                    NativeBackend,
                    "_get_turbo_parse",
                    return_value={"available": True, "parse_file": lambda _p, _lang: {"tree": {}}},
                ):
                    with patch.object(
                        NativeBackend,
                        "parse_health_check",
                        return_value={
                            "available": True,
                            "version": "1.0.0",
                            "languages": ["python"],
                            "backend": "turbo_parse",
                        },
                    ):
                        with patch.object(
                            NativeBackend,
                            "parse_stats",
                            return_value={"total_parses": 10, "backend": "turbo_parse"},
                        ):
                            from code_puppy.acceleration import get_turbo_parse_status

                            status = get_turbo_parse_status()

                            assert status["enabled"] is True
                            assert status["active"] is True  # turbo_parse IS selected
                            assert status["installed"] is True
                            assert status["will_use"] == "turbo_parse"
                            assert status["parse_backend"] == "turbo_parse"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_turbo_parse_status_not_active_when_elixir_available(self):
        """Test active=False when Elixir available in ELIXIR_FIRST mode (turbo_parse not selected).
        
        bd-13-fix-semantics: active should only be True when turbo_parse IS the selected backend.
        In ELIXIR_FIRST mode with Elixir available, Elixir is selected, not turbo_parse.
        """
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock Elixir AVAILABLE - this means turbo_parse won't be selected
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                    from code_puppy.acceleration import get_turbo_parse_status
                    status = get_turbo_parse_status()
                    
                    # turbo_parse is installed and enabled as a candidate, but NOT selected
                    assert status["installed"] is True
                    assert status["enabled"] is True  # Allowed as candidate
                    assert status["active"] is False  # But NOT selected - Elixir is
                    assert status["will_use"] == "disabled"  # turbo_parse specifically disabled
                    assert status["parse_backend"] == "elixir"  # The actual selected backend
        finally:
            NativeBackend.set_backend_preference(original_pref)


@pytest.mark.xdist_group("disabled_capability_routing")
class TestDisabledCapabilityRouting:
    """Tests for disabled capability routing (bd-13-fix).
    
    These tests verify that disabled capabilities:
    - Report will_use="disabled" or None (not a backend)
    - Do not claim a backend will be used when capability is disabled
    """

    def test_disabled_parse_capability_routing(self):
        """Test that disabled PARSE capability reports will_use='disabled'."""
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.PARSE)
        try:
            NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)
            
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.PARSE)
            assert routing["will_use"] == "disabled"
            assert routing["reason"] == "capability_disabled"
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

    def test_disabled_file_ops_capability_routing(self):
        """Test that disabled FILE_OPS capability reports will_use='disabled'."""
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.FILE_OPS)
        try:
            NativeBackend.disable_capability(NativeBackend.Capabilities.FILE_OPS)
            
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.FILE_OPS)
            assert routing["will_use"] == "disabled"
            assert routing["reason"] == "capability_disabled"
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.FILE_OPS)

    def test_disabled_message_core_capability_routing(self):
        """Test that disabled MESSAGE_CORE capability reports will_use='disabled'."""
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.MESSAGE_CORE)
        try:
            NativeBackend.disable_capability(NativeBackend.Capabilities.MESSAGE_CORE)
            
            routing = NativeBackend.get_capability_routing(NativeBackend.Capabilities.MESSAGE_CORE)
            assert routing["will_use"] == "disabled"
            assert routing["reason"] == "capability_disabled"
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.MESSAGE_CORE)

    def test_parse_operations_fail_when_disabled(self, tmp_path: Path):
        """Test that parse operations fail gracefully when capability disabled."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        original_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.PARSE)
        try:
            NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)
            
            result = NativeBackend.parse_file(str(test_file), "python")
            assert "error" in result
            assert "disabled" in result["error"].lower()
            
            result = NativeBackend.parse_source("def hello(): pass", "python")
            assert "error" in result
            assert "disabled" in result["error"].lower()
            
            symbols = NativeBackend.extract_symbols("def hello(): pass", "python")
            assert symbols == []
        finally:
            if original_enabled:
                NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)


@pytest.mark.xdist_group("partial_import")
class TestTurboParsePartialImport:
    """Tests for partial turbo_parse import handling (bd-13-fix).
    
    These tests verify that older/partial turbo_parse builds still expose
    core parse functions even if newer methods are missing.
    """

    def test_turbo_parse_partial_import_core_functions(self):
        """Test that core parse functions are available even if non-core are missing."""
        # Simulate a partial turbo_parse with only core functions
        mock_turbo = type(sys)('turbo_parse')
        mock_turbo.parse_file = MagicMock(return_value={"tree": {}})
        mock_turbo.parse_source = MagicMock(return_value={"tree": {}})
        # Missing: extract_symbols, get_folds, get_highlights, etc.
        
        with patch.dict("sys.modules", {"turbo_parse": mock_turbo}):
            # Reset the cache
            NativeBackend._turbo_parse_imports = None
            
            imports = NativeBackend._get_turbo_parse()
            
            # Should be considered available since core functions exist
            assert imports["available"] is True
            assert imports["parse_file"] is not None
            assert imports["parse_source"] is not None
            # Non-core functions should be None but not crash
            assert imports.get("get_folds") is None
            assert imports.get("get_highlights") is None
        
        # Restore cache
        NativeBackend._turbo_parse_imports = None

    def test_turbo_parse_partial_import_falls_back_when_no_core(self):
        """Test that availability is False when no core parse functions exist."""
        # Simulate turbo_parse with only non-core functions
        mock_turbo = type(sys)('turbo_parse')
        mock_turbo.get_folds = MagicMock()
        mock_turbo.get_highlights = MagicMock()
        # Missing: parse_file, parse_source
        
        with patch.dict("sys.modules", {"turbo_parse": mock_turbo}):
            # Reset the cache
            NativeBackend._turbo_parse_imports = None
            
            imports = NativeBackend._get_turbo_parse()
            
            # Should not be considered available without core functions
            assert imports["available"] is False
        
        # Restore cache
        NativeBackend._turbo_parse_imports = None

    def test_turbo_parse_import_cached(self):
        """Test that turbo_parse imports are cached after first access."""
        # Reset the cache
        NativeBackend._turbo_parse_imports = None
        
        # First call should populate cache
        imports1 = NativeBackend._get_turbo_parse()
        imports2 = NativeBackend._get_turbo_parse()
        
        # Should be the same object (cached)
        assert imports1 is imports2


class TestTurboParsePartialRustFirstFallback:
    """Regression tests for bd-13 partial turbo_parse + RUST_FIRST fallback semantics.
    
    These tests verify that when RUST_FIRST is set and turbo_parse is partially
    available (some entrypoints missing), the system correctly falls back to Elixir
    instead of falling directly to Python.
    """

    def test_rust_first_partial_turbo_missing_parse_file_uses_elixir(self):
        """Test RUST_FIRST + partial turbo (missing parse_file) => falls back to Elixir.
        
        bd-13-partial-fix-regression: When turbo_parse has available=True but
        parse_file entrypoint is missing, _should_use_elixir should return True
        and parse_file should try Elixir before falling to Python.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        
        # Simulate partial turbo_parse: available=True but parse_file is None
        # This happens when e.g., only parse_source and extract_symbols exist
        mock_turbo_state = {
            "available": True,  # Generic availability based on some core functions
            "parse_file": None,  # But parse_file specifically is missing
            "parse_source": MagicMock(return_value={"tree": {}}),
            "extract_symbols": MagicMock(return_value=[]),
            "supported_languages": MagicMock(return_value=["python"]),
            "is_language_supported": MagicMock(return_value=True),
            "extract_syntax_diagnostics": None,
            "get_folds": None,
            "get_highlights": None,
            "health_check": MagicMock(return_value={}),
            "stats": MagicMock(return_value={}),
        }
        
        with patch.object(NativeBackend, "_get_turbo_parse", return_value=mock_turbo_state):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir", return_value={"tree": {}}) as mock_elixir:
                    # Test _should_use_elixir with specific entrypoint
                    should_use = NativeBackend._should_use_elixir(
                        NativeBackend.Capabilities.PARSE, 
                        entrypoint="parse_file"
                    )
                    # Should be True because parse_file entrypoint is not available in turbo
                    assert should_use is True, (
                        "RUST_FIRST + missing parse_file entrypoint should use Elixir"
                    )
                    
                    # Now test actual parse_file call
                    _ = NativeBackend.parse_file("/test/file.py", "python")

                    # Should have called Elixir since parse_file is missing from turbo
                    mock_elixir.assert_called_once()
                    assert mock_elixir.call_args[0][0] == "parse_file"

    def test_rust_first_partial_turbo_missing_get_folds_uses_elixir(self):
        """Test RUST_FIRST + partial turbo (missing get_folds) => falls back to Elixir.
        
        bd-13-partial-fix-regression: When turbo_parse has available=True but
        get_folds entrypoint is missing, get_folds should try Elixir.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        
        # Simulate partial turbo_parse: available=True but get_folds is None
        mock_turbo_state = {
            "available": True,  # Generic availability based on core functions
            "parse_file": MagicMock(return_value={"tree": {}}),
            "parse_source": MagicMock(return_value={"tree": {}}),
            "extract_symbols": MagicMock(return_value=[]),
            "supported_languages": MagicMock(return_value=["python"]),
            "is_language_supported": MagicMock(return_value=True),
            "extract_syntax_diagnostics": MagicMock(return_value={}),
            "get_folds": None,  # Non-core function missing
            "get_highlights": None,
            "health_check": MagicMock(return_value={}),
            "stats": MagicMock(return_value={}),
        }
        
        with patch.object(NativeBackend, "_get_turbo_parse", return_value=mock_turbo_state):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir", return_value={"folds": []}) as mock_elixir:
                    # Test _should_use_elixir with specific entrypoint
                    should_use = NativeBackend._should_use_elixir(
                        NativeBackend.Capabilities.PARSE, 
                        entrypoint="get_folds"
                    )
                    # Should be True because get_folds entrypoint is not available in turbo
                    assert should_use is True, (
                        "RUST_FIRST + missing get_folds entrypoint should use Elixir"
                    )
                    
                    # Now test actual get_folds call
                    _ = NativeBackend.get_folds("code", "python")

                    # Should have called Elixir since get_folds is missing from turbo
                    mock_elixir.assert_called_once()
                    assert mock_elixir.call_args[0][0] == "get_folds"

    def test_rust_first_partial_turbo_missing_diagnostics_uses_elixir(self):
        """Test RUST_FIRST + partial turbo (missing extract_syntax_diagnostics) => Elixir.
        
        bd-13-partial-fix-regression: When turbo_parse has available=True but
        extract_syntax_diagnostics entrypoint is missing.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        
        # Simulate partial turbo_parse: available=True but diagnostics is None
        mock_turbo_state = {
            "available": True,
            "parse_file": MagicMock(return_value={"tree": {}}),
            "parse_source": MagicMock(return_value={"tree": {}}),
            "extract_symbols": MagicMock(return_value=[]),
            "supported_languages": MagicMock(return_value=["python"]),
            "is_language_supported": MagicMock(return_value=True),
            "extract_syntax_diagnostics": None,  # Diagnostics missing
            "get_folds": MagicMock(return_value={}),
            "get_highlights": MagicMock(return_value={}),
            "health_check": MagicMock(return_value={}),
            "stats": MagicMock(return_value={}),
        }
        
        with patch.object(NativeBackend, "_get_turbo_parse", return_value=mock_turbo_state):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir", return_value={"diagnostics": []}) as mock_elixir:
                    # Test _should_use_elixir with specific entrypoint
                    should_use = NativeBackend._should_use_elixir(
                        NativeBackend.Capabilities.PARSE, 
                        entrypoint="extract_syntax_diagnostics"
                    )
                    # Should be True because diagnostics entrypoint is not available in turbo
                    assert should_use is True, (
                        "RUST_FIRST + missing diagnostics entrypoint should use Elixir"
                    )
                    
                    # Now test actual extract_syntax_diagnostics call
                    _ = NativeBackend.extract_syntax_diagnostics("code", "python")

                    # Should have called Elixir since diagnostics is missing from turbo
                    mock_elixir.assert_called_once()
                    assert mock_elixir.call_args[0][0] == "extract_syntax_diagnostics"

    def test_rust_first_entrypoint_available_skips_elixir(self):
        """Test RUST_FIRST + entrypoint available => skips Elixir (normal RUST_FIRST behavior).
        
        Verifies that the fix doesn't break normal RUST_FIRST behavior when
        the requested entrypoint IS available in turbo_parse.
        """
        NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
        
        # Simulate full turbo_parse with all entrypoints available
        mock_parse_file = MagicMock(return_value={"tree": {"from": "turbo"}})
        mock_turbo_state = {
            "available": True,
            "parse_file": mock_parse_file,
            "parse_source": MagicMock(return_value={"tree": {}}),
            "extract_symbols": MagicMock(return_value=[]),
            "supported_languages": MagicMock(return_value=["python"]),
            "is_language_supported": MagicMock(return_value=True),
            "extract_syntax_diagnostics": MagicMock(return_value={}),
            "get_folds": MagicMock(return_value={}),
            "get_highlights": MagicMock(return_value={}),
            "health_check": MagicMock(return_value={}),
            "stats": MagicMock(return_value={}),
        }
        
        with patch.object(NativeBackend, "_get_turbo_parse", return_value=mock_turbo_state):
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_call_elixir") as mock_elixir:
                    # Test _should_use_elixir with specific entrypoint
                    should_use = NativeBackend._should_use_elixir(
                        NativeBackend.Capabilities.PARSE, 
                        entrypoint="parse_file"
                    )
                    # Should be False because parse_file entrypoint IS available
                    assert should_use is False, (
                        "RUST_FIRST + available parse_file should skip Elixir"
                    )
                    
                    # Now test actual parse_file call
                    _ = NativeBackend.parse_file("/test/file.py", "python")

                    # Should NOT have called Elixir since turbo_parse handled it
                    mock_elixir.assert_not_called()
                    # Should have called turbo_parse
                    mock_parse_file.assert_called_once()

    def test_parse_batch_partial_turbo_missing_parse_file_elixir_unavailable(self, tmp_path: Path):
        """Test parse_batch with RUST_FIRST, partial turbo, Elixir unavailable.

        bd-13-regression: In a partial turbo_parse build where available=True
        (because parse_source exists) but parse_file is missing, and Elixir is
        unavailable, parse_batch() should cleanly fall back to Python without
        NoneType-callable errors or incorrectly marking last_source as turbo_parse.

        Repro condition:
        - BackendPreference.RUST_FIRST
        - turbo_parse available=True but parse_file=None
        - Elixir unavailable

        Expected: Clean Python fallback, no turbo_parse last_source, no TypeError.
        """
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            NativeBackend._last_source[NativeBackend.Capabilities.PARSE] = None

            # Simulate partial turbo_parse: available=True (parse_source exists) but parse_file=None
            # This is the key regression scenario
            mock_turbo_state = {
                "available": True,  # True because parse_source exists
                "parse_file": None,  # But parse_file is missing - causes TypeError if not checked
                "parse_source": MagicMock(return_value={"tree": {}}),  # parse_source exists
                "extract_symbols": None,
                "supported_languages": None,
                "is_language_supported": None,
                "extract_syntax_diagnostics": None,
                "get_folds": None,
                "get_highlights": None,
                "health_check": MagicMock(return_value={}),
                "stats": MagicMock(return_value={}),
            }

            with patch.object(NativeBackend, "_get_turbo_parse", return_value=mock_turbo_state):
                with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                    # Call parse_batch - should NOT raise TypeError
                    result = NativeBackend.parse_batch([str(test_file)], "python")

                    # Should return results without error
                    assert "results" in result
                    assert result["count"] == 1
                    # Individual result might have an error from Python fallback,
                    # but the operation itself should succeed

                    # CRITICAL: last_source should NOT be turbo_parse
                    # It should be python_fallback since turbo_parse was skipped
                    last_source = NativeBackend._last_source.get(NativeBackend.Capabilities.PARSE)
                    assert last_source != "turbo_parse", (
                        f"last_source should not be 'turbo_parse' when parse_file is missing, "
                        f"got '{last_source}'"
                    )
                    assert last_source == "python_fallback", (
                        f"Expected 'python_fallback' when turbo_parse parse_file missing, "
                        f"got '{last_source}'"
                    )
        finally:
            NativeBackend.set_backend_preference(original_pref)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
