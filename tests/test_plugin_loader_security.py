"""Security tests for the plugin loader.

These tests verify that the plugin loader correctly handles malicious or
malformed plugins by rejecting them or failing gracefully without crashing
the application.

Tests cover:
- Plugins that raise exceptions during registration
- Path traversal attempts via plugin names
- Global state modification attempts
- Symlink attacks pointing outside the plugins directory
- Timeout handling during plugin registration
- Valid plugin loading (happy path)
"""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Helper Fixtures
# ============================================================================


@pytest.fixture
def mock_user_plugins_dir(tmp_path: Path) -> Path:
    """Create a temporary user plugins directory."""
    plugins_dir = tmp_path / "user_plugins"
    plugins_dir.mkdir(parents=True)
    return plugins_dir


@pytest.fixture
def enable_user_plugins():
    """Mock the config to enable user plugins."""
    with patch("code_puppy.config.get_value") as mock_get_value:

        def mock_get_value_impl(key: str):
            if key == "enable_user_plugins":
                return "true"
            if key == "allowed_user_plugins":
                return None  # No allowlist restriction
            return None

        mock_get_value.side_effect = mock_get_value_impl
        yield mock_get_value


@pytest.fixture
def reset_plugin_state():
    """Reset global plugin loader state before and after tests."""
    # Store original state
    from code_puppy import plugins as plugins_module

    original_discovered = plugins_module._PLUGINS_DISCOVERED
    original_registry = plugins_module._LAZY_PLUGIN_REGISTRY.copy()
    original_loaded = plugins_module._LOADED_PLUGINS.copy()

    # Reset state for clean test
    plugins_module._PLUGINS_DISCOVERED = False
    plugins_module._LAZY_PLUGIN_REGISTRY.clear()
    plugins_module._LOADED_PLUGINS.clear()

    yield

    # Restore original state
    plugins_module._PLUGINS_DISCOVERED = original_discovered
    plugins_module._LAZY_PLUGIN_REGISTRY.clear()
    plugins_module._LAZY_PLUGIN_REGISTRY.update(original_registry)
    plugins_module._LOADED_PLUGINS.clear()
    plugins_module._LOADED_PLUGINS.update(original_loaded)


# ============================================================================
# Test: Plugin with exception during register_callbacks
# ============================================================================


class TestPluginExceptionHandling:
    """Test that plugins raising exceptions during registration are handled gracefully."""

    def test_plugin_with_exception_skipped_gracefully(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """A plugin that raises an exception during register_callbacks should not crash the loader.

        The loader should catch the exception, log it, and continue with other plugins.
        """
        from code_puppy.plugins import _discover_user_plugins

        # Create a malicious plugin that raises an exception
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        bad_plugin_dir = plugins_dir / "bad_plugin"
        bad_plugin_dir.mkdir()

        # Create register_callbacks.py that raises an exception
        callbacks_file = bad_plugin_dir / "register_callbacks.py"
        callbacks_file.write_text(
            """
raise RuntimeError("Malicious plugin crashed during registration!")
"""
        )

        # Should not raise - discovery phase only parses the file, doesn't execute
        discovered = _discover_user_plugins(plugins_dir)

        # The plugin should be discovered (parsing succeeds even if content is bad)
        # It will fail when actually loaded, not during discovery
        assert any(name == "bad_plugin" for name, _ in discovered)

    def test_plugin_load_exception_caught(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """Test that exceptions during actual plugin loading are caught."""
        from code_puppy.plugins import _create_loader_user

        # Create plugin directory
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        bad_plugin_dir = plugins_dir / "bad_plugin"
        bad_plugin_dir.mkdir()

        # Create register_callbacks.py that raises an exception
        callbacks_file = bad_plugin_dir / "register_callbacks.py"
        callbacks_file.write_text(
            """
raise RuntimeError("Plugin crashed during exec_module!")
"""
        )

        # Create the loader function
        loader = _create_loader_user("bad_plugin", callbacks_file)

        # The loader should catch the exception and return None
        result = loader()
        assert result is None


# ============================================================================
# Test: Plugin name with '..' in it — path traversal check
# ============================================================================


class TestPluginPathTraversal:
    """Test that plugin names with path traversal sequences are rejected."""

    def test_dotdot_plugin_name_rejected(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
        caplog,
    ):
        """Plugin names containing '..' should be rejected as potential path traversal attacks.

        Uses behavioral testing with mocked iterdir to avoid source inspection.
        """
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Mock a directory entry with '..' in the name
        mock_item = MagicMock(spec=Path)
        mock_item.name = "evil..plugin"
        mock_item.is_dir.return_value = True

        with patch.object(Path, "iterdir", return_value=[mock_item]):
            with caplog.at_level(logging.WARNING):
                discovered = list(_discover_user_plugins(plugins_dir))

        # Plugin with '..' in name should not be discovered
        assert not any("evil..plugin" in str(p) for _, p in discovered)
        # Security warning should be logged
        assert any(
            "SECURITY" in msg and "evil..plugin" in msg for msg in caplog.messages
        )

    def test_forward_slash_plugin_name_rejected(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
        caplog,
    ):
        """Plugin names containing '/' should be rejected as potential path traversal attacks."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Mock a directory entry with '/' in the name
        mock_item = MagicMock(spec=Path)
        mock_item.name = "evil/plugin"
        mock_item.is_dir.return_value = True

        with patch.object(Path, "iterdir", return_value=[mock_item]):
            with caplog.at_level(logging.WARNING):
                discovered = list(_discover_user_plugins(plugins_dir))

        # Plugin with '/' in name should not be discovered
        assert not any("evil/plugin" in str(p) for _, p in discovered)
        # Security warning should be logged
        assert any(
            "SECURITY" in msg and "evil/plugin" in msg for msg in caplog.messages
        )

    def test_backslash_plugin_name_rejected(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
        caplog,
    ):
        """Plugin names containing '\\' should be rejected as potential path traversal attacks."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Mock a directory entry with '\\' in the name
        mock_item = MagicMock(spec=Path)
        mock_item.name = "evil\\plugin"
        mock_item.is_dir.return_value = True

        with patch.object(Path, "iterdir", return_value=[mock_item]):
            with caplog.at_level(logging.WARNING):
                discovered = list(_discover_user_plugins(plugins_dir))

        # Plugin with '\\' in name should not be discovered
        assert not any("evil\\plugin" in str(p) for _, p in discovered)
        # Security warning should be logged
        assert any(
            "SECURITY" in msg and "evil\\plugin" in msg for msg in caplog.messages
        )

    def test_null_byte_plugin_name_rejected(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
        caplog,
    ):
        """Plugin names containing '\\x00' should be rejected as potential attacks."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Mock a directory entry with null byte in the name
        mock_item = MagicMock(spec=Path)
        mock_item.name = "evil\x00plugin"
        mock_item.is_dir.return_value = True

        with patch.object(Path, "iterdir", return_value=[mock_item]):
            with caplog.at_level(logging.WARNING):
                discovered = list(_discover_user_plugins(plugins_dir))

        # Plugin with null byte in name should not be discovered
        assert len(discovered) == 0
        # Security warning should be logged
        assert any("SECURITY" in msg for msg in caplog.messages)

    def test_plugin_directory_path_traversal_protection(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """Verify that normal plugins are discovered correctly."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create a plugin directory
        plugin_dir = plugins_dir / "test_plugin"
        plugin_dir.mkdir()

        # Create the callbacks file
        (plugin_dir / "register_callbacks.py").write_text("pass")

        # Test normal case - should work
        discovered = _discover_user_plugins(plugins_dir)
        assert any(name == "test_plugin" for name, _ in discovered)


# ============================================================================
# Test: Plugin attempting to modify global state
# ============================================================================


class TestPluginGlobalStateIsolation:
    """Test how plugins can or cannot modify global state.

    NOTE: Python plugins have full system access by design. There's no true
    isolation without running in a sandbox/VM/subprocess. These tests document
    the current behavior rather than enforcing strict isolation.
    """

    def test_plugin_can_modify_sys_modules(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """Document that plugins CAN modify sys.modules - no isolation exists.

        This is a security concern but is inherent to how Python plugin loading works.
        The warning in the code acknowledges this: 'executes arbitrary Python code
        with full system privileges'.
        """
        from code_puppy.plugins import _create_loader_user

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "state_changer"
        plugin_dir.mkdir()

        # Create a plugin that modifies sys.modules
        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.write_text(
            """
import sys
# This plugin can modify global state - no isolation
sys.modules["__injected_by_malicious_plugin__"] = "compromised"
"""
        )

        # Load the plugin
        loader = _create_loader_user("state_changer", callbacks_file)

        # Before loading, module should not exist
        assert "__injected_by_malicious_plugin__" not in sys.modules

        # Load the plugin (will execute the code)
        result = loader()

        # After loading, the module WILL exist (no isolation)
        # This documents the current behavior - plugins have full access
        assert "__injected_by_malicious_plugin__" in sys.modules

        # Cleanup
        del sys.modules["__injected_by_malicious_plugin__"]

    def test_security_warning_logged_for_suspicious_plugin(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
        caplog,
    ):
        """Verify that a security warning is logged when a bad plugin is detected.

        Uses behavioral testing with mocked iterdir and caplog instead of source inspection.
        """
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Mock a directory entry with '..' in the name to trigger security warning
        mock_item = MagicMock(spec=Path)
        mock_item.name = "suspicious..plugin"
        mock_item.is_dir.return_value = True

        with patch.object(Path, "iterdir", return_value=[mock_item]):
            with caplog.at_level(logging.WARNING):
                list(_discover_user_plugins(plugins_dir))

        # Check that a security warning was logged
        security_warnings = [
            msg for msg in caplog.messages if "SECURITY" in msg and "suspicious" in msg
        ]
        assert len(security_warnings) > 0, "Expected security warning in logs"


# ============================================================================
# Test: Plugin that takes too long
# ============================================================================


class TestPluginTimeout:
    """Test timeout handling for slow plugins.

    NOTE: Currently there is no timeout mechanism in the plugin loader.
    A malicious plugin can hang indefinitely during registration.
    This test documents this limitation.
    """

    def test_no_timeout_mechanism_exists(
        self,
        tmp_path: Path,
    ):
        """Document that there is currently no timeout mechanism for plugin loading.

        This is a security gap - a malicious plugin can hang the entire application
        by entering an infinite loop during registration.

        TODO: Consider adding a signal-based timeout mechanism using signal.SIGALRM
        (Unix) or threading with a timeout (cross-platform) for user plugin loading.
        """
        import inspect
        from code_puppy import plugins as plugins_module

        # Check that there's no timeout handling in the user plugin loader
        source = inspect.getsource(plugins_module._create_loader_user)

        # No timeout mechanisms should exist (signal, threading.Timer, etc)
        assert "timeout" not in source.lower()
        assert "signal" not in source.lower()
        assert "alarm" not in source.lower()
        assert "Timer" not in source

        # Document the limitation in the test
        # Future implementations should add timeout protection here

    def test_slow_plugin_will_block(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """Document that slow/blocking plugins will block the loader.

        This test demonstrates that a plugin with blocking code will
        block plugin loading. This is current behavior, not desired behavior.
        """
        # We won't actually test infinite blocking as that would hang the test
        # Instead, we document the current limitation
        pytest.skip(
            "Skipping: Testing actual blocking would hang the test suite. "
            "This documents a known limitation: no timeout mechanism exists for plugin loading."
        )


# ============================================================================
# Test: Valid plugin loads correctly (happy path)
# ============================================================================


class TestValidPluginLoading:
    """Test that valid plugins load correctly (ensure security checks don't break normal operation)."""

    def test_valid_plugin_loads_successfully(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """A valid plugin with proper register_callbacks should load without issues."""
        from code_puppy.plugins import _discover_user_plugins, _create_loader_user

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create a valid plugin
        valid_plugin_dir = plugins_dir / "valid_plugin"
        valid_plugin_dir.mkdir()

        # Create a proper register_callbacks.py
        callbacks_file = valid_plugin_dir / "register_callbacks.py"
        callbacks_file.write_text(
            '''
"""A valid test plugin."""
from code_puppy.callbacks import register_callback

def _on_startup():
    print("Valid plugin loaded!")

register_callback("startup", _on_startup)
'''
        )

        # Discover the plugin
        discovered = _discover_user_plugins(plugins_dir)
        plugin_names = [name for name, _ in discovered]
        assert "valid_plugin" in plugin_names

        # Load the plugin
        loader = _create_loader_user("valid_plugin", callbacks_file)
        result = loader()

        # Should return the module, not None
        assert result is not None
        assert hasattr(result, "_on_startup")

    def test_multiple_valid_plugins_load(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """Multiple valid plugins should all load successfully."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create multiple valid plugins
        for i in range(3):
            plugin_dir = plugins_dir / f"valid_plugin_{i}"
            plugin_dir.mkdir()
            (plugin_dir / "register_callbacks.py").write_text(
                f"""
from code_puppy.callbacks import register_callback

def _on_startup():
    pass

register_callback("startup", _on_startup)
"""
            )

        # Discover all plugins
        discovered = _discover_user_plugins(plugins_dir)
        plugin_names = {name for name, _ in discovered}

        assert "valid_plugin_0" in plugin_names
        assert "valid_plugin_1" in plugin_names
        assert "valid_plugin_2" in plugin_names


# ============================================================================
# Test: Symlink plugin pointing outside dir
# ============================================================================


class TestSymlinkSecurity:
    """Test that symlinked plugins pointing outside the plugins directory are rejected."""

    def test_symlink_to_external_path_rejected(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """A symlink pointing outside the plugins directory should be rejected."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create an external directory (outside plugins_dir)
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "malicious.py"
        external_file.write_text("# Malicious external code")

        # Create a plugin directory with a symlink to the external file
        plugin_dir = plugins_dir / "symlinked_plugin"
        plugin_dir.mkdir()

        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.symlink_to(external_file)

        # Verify the symlink points outside
        assert callbacks_file.is_symlink()

        # The plugin should be rejected during discovery
        discovered = _discover_user_plugins(plugins_dir)
        plugin_names = {name for name, _ in discovered}

        # Should be rejected due to symlink pointing outside
        assert "symlinked_plugin" not in plugin_names

    def test_internal_symlink_allowed(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """A symlink pointing within the plugins directory should be allowed."""
        from code_puppy.plugins import _discover_user_plugins

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create a shared file within the plugins directory
        shared_dir = plugins_dir / "_shared"
        shared_dir.mkdir()
        shared_file = shared_dir / "common_callbacks.py"
        shared_file.write_text("# Shared plugin code")

        # Create a plugin that symlinks to the internal shared file
        plugin_dir = plugins_dir / "symlinked_plugin"
        plugin_dir.mkdir()

        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.symlink_to(shared_file)

        # Verify the symlink is internal
        assert callbacks_file.is_symlink()
        assert shared_file.resolve().is_relative_to(plugins_dir.resolve())

        # Internal symlinks (relative or pointing within plugins dir) should be discovered
        discovered = _discover_user_plugins(plugins_dir)
        plugin_names = {name for name, _ in discovered}

        # Internal symlinks pointing within the plugins directory should be allowed
        assert "symlinked_plugin" in plugin_names

    def test_symlink_security_check_exists(
        self,
    ):
        """Verify that the code contains symlink security checks."""
        import inspect
        from code_puppy import plugins as plugins_module

        source = inspect.getsource(plugins_module._discover_user_plugins)

        # Check for symlink handling
        assert "is_symlink" in source
        assert "readlink" in source


# ============================================================================
# Integration Tests
# ============================================================================


class TestPluginLoaderIntegration:
    """Integration tests combining multiple security scenarios."""

    def test_mixed_plugins_some_bad_some_good(
        self,
        tmp_path: Path,
        enable_user_plugins,
        reset_plugin_state,
    ):
        """A mix of good and bad plugins - good ones should still load."""
        from code_puppy.plugins import _discover_user_plugins, _create_loader_user

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create a good plugin
        good_plugin_dir = plugins_dir / "good_plugin"
        good_plugin_dir.mkdir()
        good_callbacks = good_plugin_dir / "register_callbacks.py"
        good_callbacks.write_text(
            """
from code_puppy.callbacks import register_callback

def _on_startup():
    pass

register_callback("startup", _on_startup)
"""
        )

        # Create a bad plugin that will raise on load
        bad_plugin_dir = plugins_dir / "bad_plugin"
        bad_plugin_dir.mkdir()
        bad_callbacks = bad_plugin_dir / "register_callbacks.py"
        bad_callbacks.write_text(
            """
raise RuntimeError("Plugin failed!")
"""
        )

        # Create a plugin that will be rejected due to symlink
        symlink_plugin_dir = plugins_dir / "symlinked_bad"
        symlink_plugin_dir.mkdir()
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "evil.py"
        external_file.write_text("# Evil code")
        symlink_callbacks = symlink_plugin_dir / "register_callbacks.py"
        symlink_callbacks.symlink_to(external_file)

        # Discover plugins
        discovered = _discover_user_plugins(plugins_dir)
        discovered_dict = {name: phases for name, phases in discovered}

        # Good plugin should be discovered
        assert "good_plugin" in discovered_dict

        # Bad plugin (raises on load, not on parse) will be discovered
        # because parsing doesn't execute the code
        assert "bad_plugin" in discovered_dict

        # Symlink plugin should be rejected during discovery
        assert "symlinked_bad" not in discovered_dict

        # Try loading the good plugin - should work
        good_loader = _create_loader_user("good_plugin", good_callbacks)
        good_result = good_loader()
        assert good_result is not None

        # Try loading the bad plugin - should return None (graceful failure)
        bad_loader = _create_loader_user("bad_plugin", bad_callbacks)
        bad_result = bad_loader()
        assert bad_result is None  # Gracefully returns None on exception
