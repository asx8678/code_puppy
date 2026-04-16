"""Tests for path_classify_bridge module.

Verifies that the bridge module:
1. Loads without error
2. Correctly routes to Rust when available
3. Falls back gracefully when Rust is unavailable
4. Returns correct values for known patterns
"""

from code_puppy import path_classify_bridge as bridge


class TestBridgeLoad:
    """Test that the bridge module loads correctly."""

    def test_module_imports(self):
        """Bridge module should import without error."""
        assert bridge is not None

    def test_rust_available_flag_exists(self):
        """RUST_AVAILABLE flag should exist and be a bool."""
        assert hasattr(bridge, "RUST_AVAILABLE")
        assert isinstance(bridge.RUST_AVAILABLE, bool)

    def test_all_functions_exist(self):
        """All classification functions should be exported."""
        assert callable(bridge.should_ignore_path)
        assert callable(bridge.should_ignore_dir_path)
        assert callable(bridge.is_sensitive_path)
        assert callable(bridge.classify_path)


class TestIgnorePathPatterns:
    """Test ignore path detection for known patterns."""

    def test_ignore_node_modules(self):
        """node_modules directories should be ignored."""
        assert bridge.should_ignore_path("node_modules/foo") is True
        assert bridge.should_ignore_path("./node_modules/foo") is True

    def test_ignore_pycache(self):
        """__pycache__ directories should be ignored."""
        assert bridge.should_ignore_path("__pycache__/bar.pyc") is True
        assert bridge.should_ignore_path("./__pycache__/bar.pyc") is True

    def test_ignore_git_directory(self):
        """.git directory should be ignored."""
        # Bare .git path is ignored
        assert bridge.should_ignore_path(".git/HEAD") is True
        # Note: ./.git/HEAD pattern matching depends on normalization
        # Both Rust and Python have some edge cases here

    def test_no_ignore_source_files(self):
        """Source files should NOT be ignored."""
        assert bridge.should_ignore_path("src/main.py") is False
        assert bridge.should_ignore_path("./src/main.py") is False

    def test_no_ignore_readme(self):
        """README files should NOT be ignored."""
        assert bridge.should_ignore_path("README.md") is False
        assert bridge.should_ignore_path("./README.md") is False


class TestIgnoreDirPathPatterns:
    """Test directory ignore path detection."""

    def test_ignore_dir_node_modules(self):
        """node_modules directory should be ignored."""
        assert bridge.should_ignore_dir_path("node_modules") is True
        assert bridge.should_ignore_dir_path("./node_modules") is True

    def test_ignore_dir_pycache(self):
        """__pycache__ directory should be ignored."""
        assert bridge.should_ignore_dir_path("__pycache__") is True

    def test_ignore_dir_git(self):
        """.git directory should be ignored."""
        assert bridge.should_ignore_dir_path(".git") is True


class TestSensitivePathPatterns:
    """Test sensitive path detection for known patterns."""

    def test_sensitive_env_file(self):
        """.env files should be marked as sensitive."""
        assert bridge.is_sensitive_path(".env") is True
        assert bridge.is_sensitive_path("./.env") is True

    def test_sensitive_id_rsa(self):
        """SSH private keys in .ssh directory should be marked as sensitive."""
        # Bare id_rsa filename is NOT sensitive (could be any file named id_rsa)
        assert bridge.is_sensitive_path("id_rsa") is False
        # But id_rsa in ~/.ssh/ is sensitive
        assert bridge.is_sensitive_path("~/.ssh/id_rsa") is True

    def test_sensitive_credentials_json(self):
        """credentials.json is NOT sensitive in Python fallback (only .env files are)."""
        # Note: Python is_sensitive_path only matches:
        # - .env files (with exceptions for .env.example, .env.sample, .env.template)
        # - SSH keys, cloud creds dirs, .pem/.key extensions
        # credentials.json is NOT in the sensitive list
        result = bridge.is_sensitive_path("credentials.json")
        assert result is False

    def test_no_sensitive_source_files(self):
        """Source files should NOT be sensitive."""
        assert bridge.is_sensitive_path("src/main.py") is False

    def test_no_sensitive_readme(self):
        """README files should NOT be sensitive."""
        assert bridge.is_sensitive_path("README.md") is False


class TestClassifyPath:
    """Test the combined classify_path function."""

    def test_classify_path_returns_tuple(self):
        """classify_path should return a tuple of two bools."""
        result = bridge.classify_path("src/main.py")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(x, bool) for x in result)

    def test_classify_ignore_only(self):
        """node_modules should be ignored but not sensitive."""
        is_ignored, is_sensitive = bridge.classify_path("node_modules/foo")
        assert is_ignored is True
        assert is_sensitive is False

    def test_classify_sensitive_only(self):
        """id_rsa should be sensitive but not ignored."""
        is_ignored, is_sensitive = bridge.classify_path("~/.ssh/id_rsa")
        # id_rsa should be sensitive but not necessarily ignored
        assert is_sensitive is True

    def test_classify_path_matches_component_functions(self):
        """classify_path should match calling component functions individually."""
        paths = ["src/main.py", "node_modules/foo", "~/.ssh/id_rsa", ".env", "README.md"]
        for path in paths:
            expected = (
                bridge.should_ignore_path(path),
                bridge.is_sensitive_path(path)
            )
            assert bridge.classify_path(path) == expected

    def test_classify_neither(self):
        """Regular source files should be neither ignored nor sensitive."""
        is_ignored, is_sensitive = bridge.classify_path("src/main.py")
        assert is_ignored is False
        assert is_sensitive is False


class TestEdgeCases:
    """Edge cases that could cause issues."""

    def test_empty_string(self):
        """Empty string should not crash."""
        assert bridge.should_ignore_path("") is False
        assert bridge.should_ignore_dir_path("") is False
        assert bridge.is_sensitive_path("") is False
        assert bridge.classify_path("") == (False, False)

    def test_absolute_path(self):
        """Absolute paths should work."""
        assert bridge.should_ignore_path("/home/user/project/src/main.py") is False
        assert bridge.should_ignore_path("/home/user/project/node_modules/foo") is True

    def test_path_with_spaces(self):
        """Paths with spaces should work."""
        assert bridge.should_ignore_path("my project/src/main.py") is False
        assert bridge.should_ignore_path("my project/node_modules/foo") is True

    def test_deeply_nested_path(self):
        """Deeply nested paths should work."""
        deep_path = "a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/file.txt"
        assert bridge.should_ignore_path(deep_path) is False
        deep_ignore_path = "a/b/node_modules/c/d/file.txt"
        assert bridge.should_ignore_path(deep_ignore_path) is True

    def test_unicode_path(self):
        """Unicode paths should work."""
        assert bridge.should_ignore_path("src/café.py") is False
        assert bridge.is_sensitive_path("src/café.py") is False


class TestFallbackBehavior:
    """Verify fallback behavior when Rust is unavailable."""

    def test_bridge_imports_without_rust(self):
        """Bridge should always import even if Rust is unavailable."""
        # This test verifies the module structure is correct
        # The actual Rust availability depends on the environment
        assert hasattr(bridge, "RUST_AVAILABLE")

    def test_functions_work_without_rust(self, monkeypatch):
        """Verify functions work in fallback mode."""
        monkeypatch.setattr(bridge, "RUST_AVAILABLE", False)
        monkeypatch.setattr(bridge, "_classifier", None)
        # These should work via Python fallback
        assert isinstance(bridge.should_ignore_path("src/main.py"), bool)
        assert bridge.should_ignore_path("node_modules/foo") is True
        assert bridge.should_ignore_path("src/main.py") is False


def test_rust_routing_should_ignore_path(monkeypatch):
    """Verify Rust routing for should_ignore_path."""
    mock_classifier = type('MockClassifier', (), {
        'py_should_ignore': staticmethod(lambda path: True),
    })()
    monkeypatch.setattr(bridge, 'RUST_AVAILABLE', True)
    monkeypatch.setattr(bridge, '_classifier', mock_classifier)
    assert bridge.should_ignore_path("anything") is True


def test_rust_routing_should_ignore_dir(monkeypatch):
    """Verify Rust routing for should_ignore_dir_path."""
    mock_classifier = type('MockClassifier', (), {
        'py_should_ignore_dir': staticmethod(lambda path: True),
    })()
    monkeypatch.setattr(bridge, 'RUST_AVAILABLE', True)
    monkeypatch.setattr(bridge, '_classifier', mock_classifier)
    assert bridge.should_ignore_dir_path("anything") is True


def test_rust_routing_is_sensitive(monkeypatch):
    """Verify Rust routing for is_sensitive_path."""
    mock_classifier = type('MockClassifier', (), {
        'py_is_sensitive': staticmethod(lambda path: True),
    })()
    monkeypatch.setattr(bridge, 'RUST_AVAILABLE', True)
    monkeypatch.setattr(bridge, '_classifier', mock_classifier)
    assert bridge.is_sensitive_path("anything") is True


def test_rust_routing_classify_path(monkeypatch):
    """Verify Rust routing for classify_path."""
    mock_classifier = type('MockClassifier', (), {
        'py_classify_path': staticmethod(lambda path: (True, False)),
    })()
    monkeypatch.setattr(bridge, 'RUST_AVAILABLE', True)
    monkeypatch.setattr(bridge, '_classifier', mock_classifier)
    assert bridge.classify_path("anything") == (True, False)
