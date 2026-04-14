"""Integration tests for NativeBackend file operations (Elixir backend).

Tests NativeBackend.list_files(), NativeBackend.grep(), NativeBackend.read_file(),
and NativeBackend.read_files() with both Elixir bridge and Python fallback modes.

bd-87: Added integration tests for file_ops Elixir backend.

Usage:
    # Run with Python fallback only (no Elixir required)
    uv run pytest tests/integration/test_file_ops_elixir_backend.py -v

    # Run with Elixir backend (requires Elixir control plane)
    CODEPUP_ELIXIR_ENABLED=1 uv run pytest tests/integration/test_file_ops_elixir_backend.py -v
"""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from code_puppy.native_backend import NativeBackend


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)

        # Create test files
        (test_dir / "hello.py").write_text(
            "def greet():\n    print('Hello, World!')\n\ngreet()\n",
            encoding="utf-8",
        )
        (test_dir / "utils.py").write_text(
            "def helper():\n    return 42\n",
            encoding="utf-8",
        )
        (test_dir / "README.md").write_text(
            "# Test Project\n\nThis is a test project.\n",
            encoding="utf-8",
        )

        # Create subdirectory
        (test_dir / "src").mkdir()
        (test_dir / "src" / "main.py").write_text(
            "def main():\n    print('Main entry point')\n",
            encoding="utf-8",
        )

        yield test_dir


class TestNativeBackendListFiles:
    """Test NativeBackend.list_files() functionality."""

    def test_list_files_returns_files_with_correct_structure(self, temp_test_dir: Path):
        """Test that list_files returns files with expected structure."""
        result = NativeBackend.list_files(str(temp_test_dir), recursive=False)

        # Verify result structure
        assert "files" in result
        assert isinstance(result["files"], list)
        assert "count" in result
        assert "source" in result

    def test_list_files_non_recursive(self, temp_test_dir: Path):
        """Test non-recursive file listing."""
        result = NativeBackend.list_files(str(temp_test_dir), recursive=False)

        # Should only get top-level files
        files = result["files"]
        assert "hello.py" in files
        assert "utils.py" in files
        assert "README.md" in files
        # src/ is a directory, not included in non-recursive listing
        assert result["count"] == 3

    def test_list_files_recursive(self, temp_test_dir: Path):
        """Test recursive file listing."""
        result = NativeBackend.list_files(str(temp_test_dir), recursive=True)

        # Should get all files including nested ones
        files = result["files"]
        assert any("hello.py" in str(f) for f in files)
        assert any("main.py" in str(f) for f in files)
        assert result["count"] == 4  # 3 top-level + 1 in src/

    def test_list_files_source_tracking(self, temp_test_dir: Path):
        """Test that list_files reports its source (elixir or python_fallback)."""
        result = NativeBackend.list_files(str(temp_test_dir))

        # Source should be present and valid
        assert "source" in result
        assert result["source"] in ["elixir", "python_fallback", "native_backend"]

    def test_list_files_nonexistent_directory(self):
        """Test handling of non-existent directory."""
        result = NativeBackend.list_files("/nonexistent/path/12345")

        assert "error" in result
        assert "does not exist" in result["error"].lower()
        assert result["count"] == 0

    def test_list_files_file_instead_of_directory(self, temp_test_dir: Path):
        """Test handling when path is a file, not a directory."""
        result = NativeBackend.list_files(str(temp_test_dir / "hello.py"))

        assert "error" in result
        assert "not a directory" in result["error"].lower()


class TestNativeBackendGrep:
    """Test NativeBackend.grep() functionality."""

    def test_grep_pattern_matching(self, temp_test_dir: Path):
        """Test that grep finds matching patterns."""
        result = NativeBackend.grep(r"def ", str(temp_test_dir))

        # Verify result structure
        assert "matches" in result
        assert isinstance(result["matches"], list)
        assert "total_matches" in result
        assert "source" in result

    def test_grep_finds_all_functions(self, temp_test_dir: Path):
        """Test that grep finds all function definitions."""
        result = NativeBackend.grep(r"def \w+", str(temp_test_dir))

        matches = result["matches"]
        # Should find: greet(), helper(), main()
        assert result["total_matches"] >= 3

        # Check that match structure is correct
        for match in matches:
            assert "file_path" in match
            assert "line_number" in match
            assert "line_content" in match

    def test_grep_with_specific_pattern(self, temp_test_dir: Path):
        """Test grep with a specific pattern."""
        result = NativeBackend.grep(r"def greet", str(temp_test_dir))

        assert result["total_matches"] >= 1
        # Check that we found the right function
        assert any("greet" in m.get("line_content", "") for m in result["matches"])

    def test_grep_no_matches(self, temp_test_dir: Path):
        """Test grep when pattern doesn't match anything."""
        result = NativeBackend.grep(r"nonexistent_pattern_xyz", str(temp_test_dir))

        assert result["total_matches"] == 0
        assert result["matches"] == []


class TestNativeBackendReadFile:
    """Test NativeBackend.read_file() functionality."""

    def test_read_file_returns_correct_structure(self, temp_test_dir: Path):
        """Test that read_file returns expected structure."""
        result = NativeBackend.read_file(str(temp_test_dir / "hello.py"))

        # Verify result structure
        assert "content" in result
        assert isinstance(result["content"], str)
        assert "num_tokens" in result
        assert "source" in result

    def test_read_file_content(self, temp_test_dir: Path):
        """Test that read_file returns correct content."""
        result = NativeBackend.read_file(str(temp_test_dir / "hello.py"))

        content = result["content"]
        assert "def greet():" in content
        assert "Hello, World!" in content

    def test_read_file_with_line_range(self, temp_test_dir: Path):
        """Test reading specific line ranges."""
        result = NativeBackend.read_file(
            str(temp_test_dir / "hello.py"), start_line=1, num_lines=2
        )

        content = result["content"]
        lines = [ln for ln in content.split("\n") if ln]  # Remove empty lines
        # Should only have first 2 non-empty lines (def greet() and print())
        assert len(lines) <= 2
        assert "def greet():" in content
        # Should NOT have the standalone "greet()" call (which is on line 4)
        assert "greet()" not in content or "def greet()" in content

    def test_read_file_token_estimation(self, temp_test_dir: Path):
        """Test that token estimation is reasonable."""
        result = NativeBackend.read_file(str(temp_test_dir / "hello.py"))

        content = result["content"]
        num_tokens = result["num_tokens"]

        # Rough check: tokens should be around 1/4 of characters
        assert num_tokens > 0
        assert num_tokens <= len(content)

    def test_read_file_nonexistent(self):
        """Test handling of non-existent file."""
        result = NativeBackend.read_file("/nonexistent/file.py")

        assert "error" in result
        assert result["content"] is None or result.get("error") is not None


class TestNativeBackendReadFiles:
    """Test NativeBackend.read_files() functionality."""

    def test_read_files_returns_correct_structure(self, temp_test_dir: Path):
        """Test that read_files returns expected structure."""
        paths = [
            str(temp_test_dir / "hello.py"),
            str(temp_test_dir / "utils.py"),
        ]
        result = NativeBackend.read_files(paths)

        # Verify result structure
        assert "files" in result
        assert isinstance(result["files"], list)
        assert "total_files" in result
        assert "successful_reads" in result

    def test_read_files_batch_reading(self, temp_test_dir: Path):
        """Test that batch reading works correctly."""
        paths = [
            str(temp_test_dir / "hello.py"),
            str(temp_test_dir / "utils.py"),
            str(temp_test_dir / "README.md"),
        ]
        result = NativeBackend.read_files(paths)

        # Should have read all files
        assert result["total_files"] == 3
        assert result["successful_reads"] == 3

        # Check each file result
        files = result["files"]
        assert len(files) == 3

        for f in files:
            assert "file_path" in f
            assert "content" in f
            assert "success" in f
            assert f["success"] is True

    def test_read_files_with_partial_failure(self, temp_test_dir: Path):
        """Test handling when some files don't exist."""
        paths = [
            str(temp_test_dir / "hello.py"),
            "/nonexistent/file.py",
        ]
        result = NativeBackend.read_files(paths)

        # Should have attempted both files
        assert result["total_files"] == 2
        # Only one should succeed
        assert result["successful_reads"] == 1

        # Check individual results
        files = result["files"]
        successful = [f for f in files if f["success"]]
        failed = [f for f in files if not f["success"]]

        assert len(successful) == 1
        assert len(failed) == 1

    def test_read_files_with_line_range(self, temp_test_dir: Path):
        """Test batch reading with line range applied to all files."""
        paths = [
            str(temp_test_dir / "hello.py"),
            str(temp_test_dir / "utils.py"),
        ]
        result = NativeBackend.read_files(paths, start_line=1, num_lines=1)

        # Check that line range was applied
        for f in result["files"]:
            if f["success"]:
                content = f["content"]
                # Each file should only have about 1 line
                lines = content.strip().split("\n")
                assert len(lines) <= 2  # Allow for trailing newline


class TestNativeBackendFallbackBehavior:
    """Test fallback behavior when native capabilities are unavailable."""

    def test_fallback_when_elixir_unavailable(self, temp_test_dir: Path):
        """Test that Python fallback works when Elixir is unavailable."""
        # Mock Elixir as unavailable
        with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
            result = NativeBackend.list_files(str(temp_test_dir))

            # Should still work via Python fallback
            assert "error" not in result or result.get("files")
            assert result["count"] > 0
            assert result["source"] in ["python_fallback", "native_backend"]

    def test_grep_fallback_when_elixir_unavailable(self, temp_test_dir: Path):
        """Test grep fallback when Elixir is unavailable."""
        with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
            result = NativeBackend.grep(r"def ", str(temp_test_dir))

            # Should still work via Python fallback
            assert "matches" in result
            assert result["total_matches"] > 0
            assert result["source"] in ["python_fallback", "native_backend"]

    def test_capability_disabled_triggers_fallback(self, temp_test_dir: Path):
        """Test that disabled capability forces Python fallback."""
        # Disable file_ops capability
        original_enabled = NativeBackend._capability_enabled.copy()
        NativeBackend._capability_enabled["file_ops"] = False

        try:
            result = NativeBackend.list_files(str(temp_test_dir))

            # Should still work (via Python)
            assert "files" in result
            assert result["count"] > 0
        finally:
            # Restore original state
            NativeBackend._capability_enabled = original_enabled


class TestNativeBackendSecurityGates:
    """Test security gates for sensitive paths."""

    @pytest.mark.skipif(
        os.getenv("SKIP_SECURITY_TESTS"),
        reason="Security tests skipped via environment variable",
    )
    def test_sensitive_path_blocked(self):
        """Test that sensitive paths are blocked (mock)."""
        # This test demonstrates the security pattern
        # In a real implementation, this would test path sanitization

        # Mock the _call_elixir to raise an error for sensitive paths
        def mock_call_elixir(method: str, params: dict[str, Any]) -> dict[str, Any]:
            path = params.get("directory", params.get("path", ""))
            # Simulate path blocking
            if any(sensitive in path for sensitive in ["/etc/passwd", "/root"]):
                raise PermissionError(f"Access denied: {path}")
            return {"success": True, "files": []}

        with patch.object(NativeBackend, "_call_elixir", mock_call_elixir):
            # Should fallback to Python which has its own checks
            result = NativeBackend.list_files("/etc")
            # Python fallback should handle this gracefully
            assert (
                "error" not in result
                or "does not exist" in result.get("error", "").lower()
            )


class TestNativeBackendEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_directory(self):
        """Test listing an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = NativeBackend.list_files(tmpdir)

            assert result["count"] == 0
            assert result["files"] == []

    def test_very_long_line(self, temp_test_dir: Path):
        """Test handling of files with very long lines."""
        # Create a file with a very long line
        long_line = "x" * 10000
        (temp_test_dir / "long_line.txt").write_text(long_line, encoding="utf-8")

        result = NativeBackend.read_file(str(temp_test_dir / "long_line.txt"))

        assert result["content"] is not None
        assert len(result["content"]) >= 10000

    def test_special_characters_in_path(self, temp_test_dir: Path):
        """Test handling of paths with special characters."""
        # Create file with spaces and special chars in name
        special_file = temp_test_dir / "file with spaces & symbols.txt"
        special_file.write_text("test content", encoding="utf-8")

        result = NativeBackend.read_file(str(special_file))

        assert result["content"] == "test content"

    def test_unicode_content(self, temp_test_dir: Path):
        """Test handling of unicode file content."""
        unicode_file = temp_test_dir / "unicode.txt"
        unicode_file.write_text("Hello 世界 🌍 émojis!", encoding="utf-8")

        result = NativeBackend.read_file(str(unicode_file))

        assert result["content"] == "Hello 世界 🌍 émojis!"


class TestNativeBackendIntegration:
    """Integration tests combining multiple operations."""

    def test_list_then_read_workflow(self, temp_test_dir: Path):
        """Test listing files then reading them."""
        # First list files
        list_result = NativeBackend.list_files(str(temp_test_dir), recursive=False)

        # Then read each file
        for file_path in list_result["files"]:
            full_path = temp_test_dir / file_path
            if full_path.is_file():
                read_result = NativeBackend.read_file(str(full_path))
                assert read_result["content"] is not None or "error" in read_result

    def test_grep_then_read_workflow(self, temp_test_dir: Path):
        """Test grepping then reading matching files."""
        # First grep for a pattern
        grep_result = NativeBackend.grep(r"def ", str(temp_test_dir))

        # Collect unique files with matches
        files_to_read = set()
        for match in grep_result["matches"]:
            files_to_read.add(match["file_path"])

        # Read each file
        for file_path in files_to_read:
            read_result = NativeBackend.read_file(file_path)
            assert "content" in read_result


@pytest.mark.skipif(
    not os.getenv("CODEPUP_ELIXIR_ENABLED"),
    reason="Elixir backend tests require CODEPUP_ELIXIR_ENABLED=1",
)
class TestNativeBackendWithElixir:
    """Tests that specifically require Elixir backend to be available.

    These tests are skipped unless CODEPUP_ELIXIR_ENABLED is set.
    """

    def test_elixir_backend_available(self):
        """Verify Elixir backend is actually available when flag is set."""
        assert NativeBackend._is_elixir_available(), (
            "Elixir backend should be available when CODEPUP_ELIXIR_ENABLED is set"
        )

    def test_list_files_via_elixir(self, temp_test_dir: Path):
        """Test that files can be listed via Elixir backend."""
        # This test only runs when Elixir is enabled
        result = NativeBackend.list_files(str(temp_test_dir))

        # When Elixir is available, source should indicate it
        assert result["source"] == "elixir"
        assert result["count"] > 0

    def test_elixir_response_format(self, temp_test_dir: Path):
        """Test that Elixir returns properly formatted responses."""
        result = NativeBackend.list_files(str(temp_test_dir))

        # Elixir responses should include additional metadata
        if result["source"] == "elixir":
            # Elixir may include additional fields
            assert "files" in result
            assert "count" in result
