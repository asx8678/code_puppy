"""Tests for path safety utilities.

Security-focused tests for the path_safety module ensuring proper defense
against path traversal and filename injection attacks.
"""

from pathlib import Path

import pytest

from code_puppy.utils.path_safety import (
    PathSafetyError,
    PathTraversalError,
    safe_join,
    safe_path_component,
    verify_contained,
    UnsafeComponentError,
)


@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
class TestSafePathComponent:
    """Tests for safe_path_component() function."""

    def test_valid_names(self):
        """Test that valid alphanumeric/underscore/hyphen names pass."""
        valid_names = [
            "file",
            "file_name",
            "file-name",
            "file123",
            "123file",
            "FILE_NAME",
            "a",
            "A",
            "_hidden",
            "file_name_123",
            "file-name-123",
        ]
        for name in valid_names:
            assert safe_path_component(name) == name

    def test_empty_name_raises(self):
        """Test that empty names are rejected."""
        with pytest.raises(UnsafeComponentError, match="must not be empty"):
            safe_path_component("")

    def test_slash_rejection(self):
        """Test that forward slashes (path separators) are rejected."""
        with pytest.raises(UnsafeComponentError, match="forbidden characters.*'/'"):
            safe_path_component("path/to/file")
        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_path_component("/absolute/path")

    def test_backslash_rejection(self):
        """Test that backslashes are rejected."""
        with pytest.raises(UnsafeComponentError, match="forbidden characters.*\\u005c\\u005c"):
            safe_path_component("path\\to\\file")

    def test_dot_rejection(self):
        """Test that dots are rejected (preventing .. traversal)."""
        with pytest.raises(UnsafeComponentError, match="forbidden characters.*'.'"):
            safe_path_component("..")
        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_path_component("file.txt")
        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_path_component(".hidden")

    def test_colon_rejection(self):
        """Test that colons are rejected (Windows drive letters, alternate data streams)."""
        with pytest.raises(UnsafeComponentError, match="forbidden characters.*':'"):
            safe_path_component("file:stream")
        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_path_component("C:file")

    def test_null_byte_rejection(self):
        """Test that null bytes are rejected."""
        with pytest.raises(UnsafeComponentError, match="forbidden characters.*\\\\x00"):
            safe_path_component("file\x00name")

    def test_max_length_enforcement(self):
        """Test that max_len is enforced."""
        # Default max_len of 64
        with pytest.raises(UnsafeComponentError, match="exceeds maximum length"):
            safe_path_component("a" * 65)

        # Should pass at exactly max_len
        assert safe_path_component("a" * 64) == "a" * 64

        # Custom max_len
        assert safe_path_component("abc", max_len=3) == "abc"
        with pytest.raises(UnsafeComponentError, match="exceeds maximum length"):
            safe_path_component("abcd", max_len=3)

        # Edge case: max_len < 1
        with pytest.raises(UnsafeComponentError, match="max_len must be >= 1"):
            safe_path_component("a", max_len=0)
        with pytest.raises(UnsafeComponentError, match="max_len must be >= 1"):
            safe_path_component("a", max_len=-1)

    def test_unicode_rejection(self):
        """Test that unicode characters outside ASCII are rejected."""
        with pytest.raises(UnsafeComponentError, match="must match pattern"):
            safe_path_component("файл")  # Cyrillic
        with pytest.raises(UnsafeComponentError, match="must match pattern"):
            safe_path_component("文件")  # Chinese
        # Null byte is caught by forbidden characters check (faster path)
        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_path_component("file\u0000name")  # Null as unicode escape

    def test_special_chars_rejection(self):
        """Test various special characters are rejected."""
        special_chars = [
            "file name",  # space
            "file\tname",  # tab
            "file\nname",  # newline
            "file$name",  # dollar
            "file%name",  # percent
            "file&name",  # ampersand
            "file(name)",  # parentheses
            "file[name]",  # brackets
            "file{name}",  # braces
            "file;name",  # semicolon
            "file|name",  # pipe
            "file<name>",  # angle brackets
            "file'name",  # single quote
            'file"name',  # double quote
            "file`name",  # backtick
            "file@name",  # at
            "file#name",  # hash
            "file!name",  # exclamation
            "file?name",  # question
            "file*name",  # asterisk (glob)
            "file+name",  # plus
            "file=name",  # equals
        ]
        for name in special_chars:
            with pytest.raises(UnsafeComponentError, match="must match pattern"):
                safe_path_component(name)

    def test_traversal_patterns(self):
        """Test common path traversal patterns are all blocked."""
        traversal_patterns = [
            "../etc/passwd",
            "../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "..",
            ".",
            "...",
            "....",
            "dir/../../../etc/passwd",
            "dir/..",
            "./file",
        ]
        for pattern in traversal_patterns:
            with pytest.raises(UnsafeComponentError):
                safe_path_component(pattern)

    def test_null_and_control_chars(self):
        """Test null bytes and control characters are blocked."""
        # Test specific control chars that should be rejected
        control_chars = [
            '\x00',  # null
            '\x01',  # start of heading
            '\n',    # newline
            '\r',    # carriage return
            '\t',    # tab
        ]
        for char in control_chars:
            if char not in _ALLOWLIST:  # Skip if it's already caught by pattern
                with pytest.raises((UnsafeComponentError, ValueError)):
                    safe_path_component(f"file{char}name")

    def test_non_string_input(self):
        """Test that non-string inputs raise appropriate errors."""
        with pytest.raises(UnsafeComponentError, match="must be a string"):
            safe_path_component(None)
        with pytest.raises(UnsafeComponentError, match="must be a string"):
            safe_path_component(123)
        with pytest.raises(UnsafeComponentError, match="must be a string"):
            safe_path_component(["file"])

    def test_return_value_unchanged(self):
        """Test that valid names are returned unchanged."""
        name = "my_safe_file_name_123"
        result = safe_path_component(name)
        assert result is name  # Same object
        assert result == name  # Equal value


@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
class TestVerifyContained:
    """Tests for verify_contained() function."""

    def test_simple_containment(self, tmp_path: Path):
        """Test basic path containment check."""
        root = tmp_path / "root"
        root.mkdir()
        subdir = root / "subdir"
        subdir.mkdir()
        file_path = subdir / "file.txt"
        file_path.write_text("content")

        result = verify_contained(file_path, root)
        assert result == file_path.resolve()

    def test_containment_with_relative_paths(self, tmp_path: Path):
        """Test containment with relative paths."""
        root = tmp_path / "root"
        root.mkdir()
        subdir = root / "subdir"
        subdir.mkdir()

        # Change to tmp_path to test relative paths
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = verify_contained(Path("root/subdir"), Path("root"))
            assert result == subdir.resolve()
        finally:
            os.chdir(original_cwd)

    def test_traversal_blocked(self, tmp_path: Path):
        """Test that path traversal is blocked."""
        root = tmp_path / "root"
        root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        other_file = other / "secret.txt"
        other_file.write_text("secret")

        # Attempt to escape using ..
        with pytest.raises(PathTraversalError, match="not contained within root"):
            verify_contained(root / ".." / "other" / "secret.txt", root)

    def test_traversal_with_symlinks(self, tmp_path: Path):
        """Test that symlink-based traversal is blocked."""
        root = tmp_path / "root"
        root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        other_file = other / "secret.txt"
        other_file.write_text("secret")

        # Create symlink inside root pointing outside
        symlink = root / "link"
        symlink.symlink_to(other)

        # Resolving the symlink should show it escapes root
        with pytest.raises(PathTraversalError, match="not contained within root"):
            verify_contained(symlink / "secret.txt", root)

    def test_same_directory(self, tmp_path: Path):
        """Test that root itself is considered contained."""
        root = tmp_path / "root"
        root.mkdir()

        result = verify_contained(root, root)
        assert result == root.resolve()

    def test_nonexistent_path(self, tmp_path: Path):
        """Test behavior with non-existent paths."""
        root = tmp_path / "root"
        root.mkdir()
        nonexistent = root / "nonexistent" / "file.txt"

        # Should still verify containment even if path doesn't exist
        result = verify_contained(nonexistent, root)
        assert result == nonexistent.resolve()

    def test_nonexistent_root(self, tmp_path: Path):
        """Test behavior when root doesn't exist.

        Note: Path.resolve() on non-existent paths returns the absolute path
        without following symlinks. The path will still be checked for
        containment, and if it's outside the resolved root path, a traversal
        error will be raised.
        """
        nonexistent_root = tmp_path / "does_not_exist"
        some_path = tmp_path / "some_file.txt"

        # On macOS/Linux, resolve() works on non-existent paths
        # The containment check will determine if the path is valid
        # Since some_path is not under nonexistent_root, it should fail
        with pytest.raises(PathSafetyError):
            verify_contained(some_path, nonexistent_root)

    def test_broken_symlink(self, tmp_path: Path):
        """Test handling of broken symlinks.

        When resolve() follows a broken symlink to its target, if the target
        is outside the root, it should be detected as a traversal attempt.
        This is correct security behavior - we don't want to allow symlinks
        that point outside the root.
        """
        root = tmp_path / "root"
        root.mkdir()

        # Create a broken symlink inside root pointing outside root
        broken_link = root / "broken"
        broken_link.symlink_to("/nonexistent/path")

        # resolve() follows the symlink to /nonexistent/path which is outside root
        # This should raise a PathTraversalError (correct security behavior)
        with pytest.raises(PathTraversalError, match="not contained within root"):
            verify_contained(broken_link, root)

    def test_absolute_path_outside_root(self, tmp_path: Path):
        """Test that absolute paths outside root are blocked."""
        root = tmp_path / "root"
        root.mkdir()

        # Absolute path completely outside
        with pytest.raises(PathTraversalError, match="not contained within root"):
            verify_contained(Path("/etc/passwd"), root)

    def test_parent_traversal_blocked(self, tmp_path: Path):
        """Test various parent directory traversal attempts."""
        root = tmp_path / "root"
        root.mkdir()

        traversal_attempts = [
            "../file.txt",
            "../../file.txt",
            "dir/../../../file.txt",
            "dir/../../../../file.txt",
        ]

        for attempt in traversal_attempts:
            with pytest.raises(PathTraversalError, match="not contained within root"):
                verify_contained(root / attempt, root)

    def test_path_is_root_subpath(self, tmp_path: Path):
        """Test subpath directly under root."""
        root = tmp_path / "root"
        root.mkdir()
        direct_file = root / "file.txt"
        direct_file.write_text("content")

        result = verify_contained(direct_file, root)
        assert result == direct_file.resolve()

    def test_invalid_input_types(self):
        """Test that invalid types raise appropriate errors."""
        with pytest.raises(PathSafetyError, match="path must be a Path"):
            verify_contained("not_a_path", Path("/root"))  # type: ignore

        with pytest.raises(PathSafetyError, match="root must be a Path"):
            verify_contained(Path("/file"), "not_a_path")  # type: ignore


@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
class TestSafeJoin:
    """Tests for safe_join() function."""

    def test_simple_join(self, tmp_path: Path):
        """Test basic path joining with sanitization."""
        root = tmp_path / "root"
        root.mkdir()

        result = safe_join(root, "subdir", "file")
        expected = (root / "subdir" / "file").resolve()
        assert result == expected

    def test_multiple_components(self, tmp_path: Path):
        """Test joining multiple components."""
        root = tmp_path / "root"
        root.mkdir()

        result = safe_join(root, "a", "b", "c", "d")
        expected = (root / "a" / "b" / "c" / "d").resolve()
        assert result == expected

    def test_single_component(self, tmp_path: Path):
        """Test joining single component."""
        root = tmp_path / "root"
        root.mkdir()

        result = safe_join(root, "file")
        expected = (root / "file").resolve()
        assert result == expected

    def test_traversal_in_component_blocked(self, tmp_path: Path):
        """Test that traversal attempts in components are blocked."""
        root = tmp_path / "root"
        root.mkdir()

        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_join(root, "..", "file")

        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_join(root, "subdir", "..", "file")

    def test_dot_in_component_blocked(self, tmp_path: Path):
        """Test that dots in components are blocked."""
        root = tmp_path / "root"
        root.mkdir()

        with pytest.raises(UnsafeComponentError, match="forbidden"):
            safe_join(root, "file.txt")

    def test_special_chars_in_component_blocked(self, tmp_path: Path):
        """Test that special characters in components are blocked."""
        root = tmp_path / "root"
        root.mkdir()

        with pytest.raises(UnsafeComponentError):
            safe_join(root, "file name")

        with pytest.raises(UnsafeComponentError):
            safe_join(root, "file\tname")

        with pytest.raises(UnsafeComponentError):
            safe_join(root, "file;name")

    def test_empty_component_list(self, tmp_path: Path):
        """Test joining with no components (returns root)."""
        root = tmp_path / "root"
        root.mkdir()

        # Empty components should return verified root
        result = safe_join(root)
        assert result == root.resolve()

    def test_returns_resolved_path(self, tmp_path: Path):
        """Test that returned path is fully resolved."""
        root = tmp_path / "root"
        root.mkdir()

        # Use relative root
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = safe_join(Path("root"), "subdir", "file")
            assert result.is_absolute()
            assert "root" in str(result)
            assert "subdir" in str(result)
            assert str(result).endswith("file")
        finally:
            os.chdir(original_cwd)


@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_path_safety_error_base_class(self):
        """Test PathSafetyError is base for all path safety exceptions."""
        assert issubclass(PathTraversalError, PathSafetyError)
        assert issubclass(UnsafeComponentError, PathSafetyError)

    def test_catch_all_with_base_class(self):
        """Test that PathSafetyError catches all derived exceptions."""
        with pytest.raises(PathSafetyError):
            raise PathTraversalError("test")

        with pytest.raises(PathSafetyError):
            raise UnsafeComponentError("test")

    def test_value_error_inheritance(self):
        """Test that all exceptions inherit from ValueError via PathSafetyError."""
        assert issubclass(PathSafetyError, ValueError)


@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
class TestIntegrationScenarios:
    """Integration tests simulating real-world usage scenarios."""

    def test_session_file_creation(self, tmp_path: Path):
        """Simulate session logger creating files from session_id."""
        root = tmp_path / "sessions"
        root.mkdir()

        # Simulate creating session directory from user input
        session_id = "session_abc123"
        timestamp = "20240115_120000"
        safe_ts = safe_path_component(timestamp)
        safe_id = safe_path_component(session_id[:8])

        session_dir = safe_join(root, f"{safe_ts}_{safe_id}")

        # Create the actual directory and write files
        session_dir.mkdir(parents=True, exist_ok=True)
        manifest = session_dir / "manifest.json"
        manifest.write_text('{"session": "test"}')

        assert manifest.exists()
        assert verify_contained(manifest, root)

    def test_artifact_writing(self, tmp_path: Path):
        """Simulate supervisor_review writing artifacts."""
        root = tmp_path / "artifacts"
        root.mkdir()

        # Simulate safe artifact path creation
        session_prefix = "review_123"
        iteration = 1
        agent_name = "worker_agent"

        safe_prefix = safe_path_component(session_prefix)
        safe_agent = safe_path_component(agent_name)

        artifacts_dir = safe_join(root, "supervisor_review", safe_prefix)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        file_path = artifacts_dir / f"iter{iteration}_{safe_agent}.log"
        file_path.write_text("iteration output")

        # Verify containment
        assert verify_contained(file_path, root)

    def test_history_offload_path(self, tmp_path: Path):
        """Simulate history_offload creating archive files."""
        root = tmp_path / "history"
        root.mkdir()

        # Simulate safe archive path creation
        session_id = "session_abc123"
        safe_id = safe_path_component(session_id)

        # Note: safe_join only sanitizes individual components, it doesn't add extensions
        # In real usage, the extension is handled separately
        archive_dir = safe_join(root, safe_id)
        archive_dir.mkdir(parents=True, exist_ok=True)

        # For the actual file, use verify_contained after construction
        archive_path = archive_dir / "archive.history.md"
        archive_path.write_text("## Compacted at 2024-01-15\n")

        assert archive_path.exists()
        assert verify_contained(archive_path, root)


# Allowlist for control char tests (characters that are allowed and won't trigger error)
_ALLOWLIST = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
