"""Comprehensive tests for code_puppy/plugins/__init__.py lazy loading.

Tests cover lazy plugin loading functions including:
- Plugin discovery without importing
- Lazy loading when phases trigger
- Error handling paths
- Idempotent loading behavior
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import code_puppy.plugins as plugins_module
from code_puppy.plugins import (
    USER_PLUGINS_DIR,
    _discover_builtin_plugins,
    _discover_user_plugins,
    _extract_phases_from_callbacks_file,
    _register_lazy_plugin,
    _create_loader_builtin,
    _create_loader_user,
    _load_plugins_for_phase,
    ensure_plugins_loaded_for_phase,
    ensure_user_plugins_dir,
    get_user_plugins_dir,
    load_plugin_callbacks,
    _LAZY_PLUGIN_REGISTRY,
    _LOADED_PLUGINS,
)


class TestGetUserPluginsDir:
    """Test get_user_plugins_dir function."""

    def test_returns_user_plugins_path(self):
        """Test that function returns the USER_PLUGINS_DIR constant."""
        result = get_user_plugins_dir()
        assert result == USER_PLUGINS_DIR
        assert result == Path.home() / ".code_puppy" / "plugins"


class TestEnsureUserPluginsDir:
    """Test ensure_user_plugins_dir function."""

    def test_creates_directory_if_not_exists(self, tmp_path):
        """Test that directory is created if it doesn't exist."""
        test_dir = tmp_path / ".code_puppy" / "plugins"
        assert not test_dir.exists()

        with patch.object(plugins_module, "USER_PLUGINS_DIR", test_dir):
            result = ensure_user_plugins_dir()
            assert result == test_dir
            assert test_dir.exists()
            assert test_dir.is_dir()

    def test_returns_existing_directory(self, tmp_path):
        """Test that existing directory is returned without error."""
        test_dir = tmp_path / ".code_puppy" / "plugins"
        test_dir.mkdir(parents=True)
        assert test_dir.exists()

        with patch.object(plugins_module, "USER_PLUGINS_DIR", test_dir):
            result = ensure_user_plugins_dir()
            assert result == test_dir
            assert test_dir.exists()


class TestExtractPhasesFromCallbacksFile:
    """Test _extract_phases_from_callbacks_file function."""

    def test_extracts_single_phase(self, tmp_path):
        """Test extracting a single register_callback phase."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text('register_callback("startup", my_func)')

        result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
        assert result == ["startup"]

    def test_extracts_multiple_phases(self, tmp_path):
        """Test extracting multiple register_callback phases."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text("""
register_callback("startup", my_func)
register_callback("shutdown", my_shutdown)
register_callback("stream_event", my_stream)
""")

        result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
        assert sorted(result) == sorted(["startup", "shutdown", "stream_event"])

    def test_ignores_invalid_phases(self, tmp_path):
        """Test that invalid/unsupported phases are ignored."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text("""
register_callback("startup", my_func)
register_callback("invalid_phase", my_func)
""")

        result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
        assert result == ["startup"]

    def test_defaults_to_startup_if_no_register_callback(self, tmp_path):
        """Test that startup is default if no register_callback calls found."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text("# Just some code without register_callback")

        result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
        assert result == ["startup"]

    def test_handles_single_quotes(self, tmp_path):
        """Test that single quotes work for phase names."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text("register_callback('startup', my_func)")

        result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
        assert result == ["startup"]

    def test_handles_file_read_error(self, tmp_path, caplog):
        """Test graceful handling of file read errors."""
        callbacks_file = tmp_path / "register_callbacks.py"
        callbacks_file.write_text("content")

        with patch.object(Path, "read_text", side_effect=IOError("Read error")):
            result = _extract_phases_from_callbacks_file(callbacks_file, "test_plugin")
            assert result == ["startup"]  # Defaults to startup on error


class TestDiscoverBuiltinPlugins:
    """Test _discover_builtin_plugins function."""

    def test_discovers_valid_plugin(self, tmp_path):
        """Test discovering a valid built-in plugin."""
        plugin_dir = tmp_path / "my_plugin"
        plugin_dir.mkdir()
        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.write_text('register_callback("startup", my_func)')

        with patch(
            "code_puppy.config.get_safety_permission_level", return_value="high"
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert len(result) == 1
            assert result[0][0] == "my_plugin"
            assert "startup" in result[0][1]

    def test_skips_directories_starting_with_underscore(self, tmp_path):
        """Test that directories starting with _ are skipped."""
        private_dir = tmp_path / "_private"
        private_dir.mkdir()
        (private_dir / "register_callbacks.py").write_text("# Private")

        with patch(
            "code_puppy.config.get_safety_permission_level", return_value="high"
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert result == []

    def test_skips_files_not_directories(self, tmp_path):
        """Test that regular files are skipped."""
        (tmp_path / "some_file.py").write_text("# Just a file")

        with patch(
            "code_puppy.config.get_safety_permission_level", return_value="high"
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert result == []

    def test_skips_directories_without_register_callbacks(self, tmp_path):
        """Test that directories without register_callbacks.py are skipped."""
        plugin_dir = tmp_path / "incomplete_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("# Just init")

        with patch(
            "code_puppy.config.get_safety_permission_level", return_value="high"
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert result == []

    def test_skips_shell_safety_when_safety_level_high(self, tmp_path):
        """Test shell_safety plugin is skipped when safety_permission_level is high."""
        plugin_dir = tmp_path / "shell_safety"
        plugin_dir.mkdir()
        (plugin_dir / "register_callbacks.py").write_text("# Shell safety")

        with (
            patch("code_puppy.config.get_safety_permission_level", return_value="high"),
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert "shell_safety" not in [r[0] for r in result]

    def test_loads_shell_safety_when_safety_level_low(self, tmp_path):
        """Test shell_safety plugin is discovered when safety_permission_level is low."""
        plugin_dir = tmp_path / "shell_safety"
        plugin_dir.mkdir()
        (plugin_dir / "register_callbacks.py").write_text("# Shell safety")

        with (
            patch("code_puppy.config.get_safety_permission_level", return_value="low"),
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert "shell_safety" in [r[0] for r in result]

    def test_discovers_multiple_plugins(self, tmp_path):
        """Test discovering multiple plugins."""
        for name in ["plugin_a", "plugin_b", "plugin_c"]:
            plugin_dir = tmp_path / name
            plugin_dir.mkdir()
            (plugin_dir / "register_callbacks.py").write_text(
                'register_callback("startup", func)'
            )

        with patch(
            "code_puppy.config.get_safety_permission_level", return_value="high"
        ):
            result = _discover_builtin_plugins(tmp_path)
            assert len(result) == 3
            assert set(r[0] for r in result) == {"plugin_a", "plugin_b", "plugin_c"}


class TestDiscoverUserPlugins:
    """Test _discover_user_plugins function."""

    def test_returns_empty_for_nonexistent_directory(self, tmp_path):
        """Test that non-existent directory returns empty list."""
        nonexistent = tmp_path / "does_not_exist"
        result = _discover_user_plugins(nonexistent)
        assert result == []

    def test_warns_if_path_is_file_not_directory(self, tmp_path, caplog):
        """Test that warning is logged if path is a file, not directory."""
        file_path = tmp_path / "not_a_dir"
        file_path.write_text("I'm a file")

        result = _discover_user_plugins(file_path)
        assert result == []
        assert "User plugins path is not a directory" in caplog.text

    def test_adds_user_plugins_dir_to_sys_path(self, tmp_path):
        """Test that user plugins directory is added to sys.path."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()
        user_plugins_str = str(user_plugins_dir)

        if user_plugins_str in sys.path:
            sys.path.remove(user_plugins_str)

        try:
            _discover_user_plugins(user_plugins_dir)
            assert user_plugins_str in sys.path
        finally:
            if user_plugins_str in sys.path:
                sys.path.remove(user_plugins_str)

    def test_skips_directories_starting_with_underscore(self, tmp_path):
        """Test that directories starting with _ are skipped."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()

        private_dir = user_plugins_dir / "_private"
        private_dir.mkdir()
        (private_dir / "register_callbacks.py").write_text("# Private")

        try:
            result = _discover_user_plugins(user_plugins_dir)
            assert result == []
        finally:
            if str(user_plugins_dir) in sys.path:
                sys.path.remove(str(user_plugins_dir))

    def test_skips_directories_starting_with_dot(self, tmp_path):
        """Test that directories starting with . are skipped."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()

        hidden_dir = user_plugins_dir / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "register_callbacks.py").write_text("# Hidden")

        try:
            result = _discover_user_plugins(user_plugins_dir)
            assert result == []
        finally:
            if str(user_plugins_dir) in sys.path:
                sys.path.remove(str(user_plugins_dir))

    def test_skips_files_not_directories(self, tmp_path):
        """Test that regular files are skipped."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "some_file.py").write_text("# Just a file")

        try:
            result = _discover_user_plugins(user_plugins_dir)
            assert result == []
        finally:
            if str(user_plugins_dir) in sys.path:
                sys.path.remove(str(user_plugins_dir))

    def test_discovers_plugin_with_register_callbacks(self, tmp_path):
        """Test discovering a user plugin with register_callbacks.py."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()

        plugin_dir = user_plugins_dir / "my_user_plugin"
        plugin_dir.mkdir()
        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.write_text('register_callback("startup", my_func)')

        try:
            result = _discover_user_plugins(user_plugins_dir)
            assert len(result) == 1
            assert result[0][0] == "my_user_plugin"
        finally:
            if str(user_plugins_dir) in sys.path:
                sys.path.remove(str(user_plugins_dir))

    def test_discovers_plugin_with_init_fallback(self, tmp_path):
        """Test discovering a user plugin that only has __init__.py."""
        user_plugins_dir = tmp_path / "user_plugins"
        user_plugins_dir.mkdir()

        plugin_dir = user_plugins_dir / "simple_plugin"
        plugin_dir.mkdir()
        init_file = plugin_dir / "__init__.py"
        init_file.write_text("# Simple plugin")

        try:
            result = _discover_user_plugins(user_plugins_dir)
            assert len(result) == 1
            assert result[0][0] == "simple_plugin"
            assert result[0][1] == ["startup"]
        finally:
            if str(user_plugins_dir) in sys.path:
                sys.path.remove(str(user_plugins_dir))


class TestCreateLoaders:
    """Test lazy loader creation functions."""

    def test_create_loader_builtin_success(self):
        """Test successful built-in plugin lazy loader."""
        loader = _create_loader_builtin(
            "my_plugin", "code_puppy.plugins.my_plugin.register_callbacks"
        )

        with patch("code_puppy.plugins.importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock()
            result = loader()
            assert result is not None
            mock_import.assert_called_once_with(
                "code_puppy.plugins.my_plugin.register_callbacks"
            )

    def test_create_loader_builtin_import_error(self, caplog):
        """Test built-in loader handles ImportError."""
        loader = _create_loader_builtin(
            "broken_plugin", "code_puppy.plugins.broken.register_callbacks"
        )

        with patch(
            "code_puppy.plugins.importlib.import_module",
            side_effect=ImportError("No module"),
        ):
            result = loader()
            assert result is None
            assert "Failed to lazy-load built-in plugin" in caplog.text

    def test_create_loader_user_success(self, tmp_path, monkeypatch):
        """Test successful user plugin lazy loader."""
        # Set up a fake home directory so the path validation passes
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create the expected plugins directory structure
        plugins_dir = fake_home / ".code_puppy" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_dir = plugins_dir / "my_user_plugin"
        plugin_dir.mkdir()
        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.write_text("# User plugin")

        loader = _create_loader_user("my_user_plugin", callbacks_file)

        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()
        mock_module = MagicMock()

        with (
            patch(
                "code_puppy.config.get_value",
                side_effect=lambda key: True if key == "enable_user_plugins" else None,
            ),
            patch(
                "code_puppy.plugins.importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ),
            patch(
                "code_puppy.plugins.importlib.util.module_from_spec",
                return_value=mock_module,
            ),
        ):
            result = loader()
            assert result is mock_module

    def test_create_loader_user_spec_is_none(self, tmp_path, caplog, monkeypatch):
        """Test user loader handles spec being None."""
        # Set up a fake home directory so the path validation passes
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create the expected plugins directory structure
        plugins_dir = fake_home / ".code_puppy" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_dir = plugins_dir / "bad_plugin"
        plugin_dir.mkdir()
        callbacks_file = plugin_dir / "register_callbacks.py"
        callbacks_file.write_text("# User plugin")

        loader = _create_loader_user("bad_plugin", callbacks_file)

        with (
            patch(
                "code_puppy.config.get_value",
                side_effect=lambda key: True if key == "enable_user_plugins" else None,
            ),
            patch(
                "code_puppy.plugins.importlib.util.spec_from_file_location",
                return_value=None,
            ),
        ):
            result = loader()
            assert result is None
            assert "Could not create module spec for user plugin" in caplog.text


class TestLoadPluginsForPhase:
    """Test _load_plugins_for_phase and ensure_plugins_loaded_for_phase."""

    def test_loads_registered_plugins(self):
        """Test that plugins registered for a phase are loaded."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock(return_value=MagicMock())
        _LAZY_PLUGIN_REGISTRY["test_phase"] = [("builtin", "test_plugin", mock_loader)]

        original_loaded = set(_LOADED_PLUGINS)
        _LOADED_PLUGINS.clear()

        try:
            result = _load_plugins_for_phase("test_phase")
            assert "test_plugin" in result
            assert mock_loader.called
            assert "builtin:test_plugin" in _LOADED_PLUGINS
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)
            _LOADED_PLUGINS.clear()
            _LOADED_PLUGINS.update(original_loaded)

    def test_skips_already_loaded_plugins(self):
        """Test that already loaded plugins are skipped."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock(return_value=MagicMock())
        _LAZY_PLUGIN_REGISTRY["test_phase"] = [("builtin", "test_plugin", mock_loader)]

        original_loaded = set(_LOADED_PLUGINS)
        _LOADED_PLUGINS.clear()
        _LOADED_PLUGINS.add("builtin:test_plugin")

        try:
            result = _load_plugins_for_phase("test_phase")
            assert result == []
            assert not mock_loader.called
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)
            _LOADED_PLUGINS.clear()
            _LOADED_PLUGINS.update(original_loaded)

    def test_handles_load_failure(self, caplog):
        """Test graceful handling when a plugin fails to load."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock(return_value=None)  # Failed load
        _LAZY_PLUGIN_REGISTRY["test_phase"] = [
            ("builtin", "failing_plugin", mock_loader)
        ]

        original_loaded = set(_LOADED_PLUGINS)
        _LOADED_PLUGINS.clear()

        try:
            result = _load_plugins_for_phase("test_phase")
            assert result == []  # Plugin not added to loaded list
            assert mock_loader.called
            assert "builtin:failing_plugin" not in _LOADED_PLUGINS
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)
            _LOADED_PLUGINS.clear()
            _LOADED_PLUGINS.update(original_loaded)

    def test_returns_empty_for_unregistered_phase(self):
        """Test that unregistered phases return empty list."""
        result = _load_plugins_for_phase("nonexistent_phase")
        assert result == []

    def test_public_api_ensure_plugins_loaded(self):
        """Test the public API function."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock(return_value=MagicMock())
        _LAZY_PLUGIN_REGISTRY["my_phase"] = [("user", "my_plugin", mock_loader)]

        original_loaded = set(_LOADED_PLUGINS)
        _LOADED_PLUGINS.clear()

        try:
            result = ensure_plugins_loaded_for_phase("my_phase")
            assert "my_plugin" in result
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)
            _LOADED_PLUGINS.clear()
            _LOADED_PLUGINS.update(original_loaded)


class TestRegisterLazyPlugin:
    """Test _register_lazy_plugin function."""

    def test_registers_plugin_for_phase(self):
        """Test that plugin is registered for the correct phase."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock()

        try:
            _register_lazy_plugin("startup", "builtin", "test_plugin", mock_loader)
            assert "startup" in _LAZY_PLUGIN_REGISTRY
            assert len(_LAZY_PLUGIN_REGISTRY["startup"]) == 1
            assert _LAZY_PLUGIN_REGISTRY["startup"][0] == (
                "builtin",
                "test_plugin",
                mock_loader,
            )
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)

    def test_handles_multiple_phases(self):
        """Test registering same plugin for multiple phases."""
        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        mock_loader = MagicMock()

        try:
            _register_lazy_plugin("startup", "builtin", "multi_plugin", mock_loader)
            _register_lazy_plugin("shutdown", "builtin", "multi_plugin", mock_loader)

            assert "startup" in _LAZY_PLUGIN_REGISTRY
            assert "shutdown" in _LAZY_PLUGIN_REGISTRY
            assert len(_LAZY_PLUGIN_REGISTRY["startup"]) == 1
            assert len(_LAZY_PLUGIN_REGISTRY["shutdown"]) == 1
        finally:
            _LAZY_PLUGIN_REGISTRY.clear()
            _LAZY_PLUGIN_REGISTRY.update(original_registry)


class TestLoadPluginCallbacks:
    """Test load_plugin_callbacks function (lazy loading discovery)."""

    def test_idempotent_discovery(self):
        """Test that plugins are only discovered once (idempotent)."""
        original_discovered = plugins_module._PLUGINS_DISCOVERED
        plugins_module._PLUGINS_DISCOVERED = True

        try:
            result = load_plugin_callbacks()
            assert result == {"builtin": [], "user": []}
        finally:
            plugins_module._PLUGINS_DISCOVERED = original_discovered

    def test_discovers_and_registers_plugins(self, tmp_path):
        """Test that load_plugin_callbacks discovers and registers plugins."""
        original_discovered = plugins_module._PLUGINS_DISCOVERED
        plugins_module._PLUGINS_DISCOVERED = False

        original_registry = dict(_LAZY_PLUGIN_REGISTRY)
        _LAZY_PLUGIN_REGISTRY.clear()

        with (
            patch(
                "code_puppy.plugins._discover_builtin_plugins",
                return_value=[
                    ("plugin_a", ["startup"]),
                    ("plugin_b", ["startup", "shutdown"]),
                ],
            ) as mock_discover_builtin,
            patch(
                "code_puppy.plugins._discover_user_plugins",
                return_value=[("user_plugin", ["startup"])],
            ) as mock_discover_user,
        ):
            try:
                result = load_plugin_callbacks()
                # Should discover the plugins but not import them yet
                assert len(result["builtin"]) == 2
                assert set(result["builtin"]) == {"plugin_a", "plugin_b"}
                assert len(result["user"]) == 1
                assert result["user"][0] == "user_plugin"
                # Plugins should be registered in lazy registry
                assert "startup" in _LAZY_PLUGIN_REGISTRY
                assert "shutdown" in _LAZY_PLUGIN_REGISTRY
                mock_discover_builtin.assert_called_once()
                mock_discover_user.assert_called_once()
            finally:
                plugins_module._PLUGINS_DISCOVERED = original_discovered
                _LAZY_PLUGIN_REGISTRY.clear()
                _LAZY_PLUGIN_REGISTRY.update(original_registry)

    def test_sets_discovered_flag(self):
        """Test that _PLUGINS_DISCOVERED flag is set after discovery."""
        original_discovered = plugins_module._PLUGINS_DISCOVERED
        plugins_module._PLUGINS_DISCOVERED = False

        with (
            patch("code_puppy.plugins._discover_builtin_plugins", return_value=[]),
            patch("code_puppy.plugins._discover_user_plugins", return_value=[]),
        ):
            try:
                load_plugin_callbacks()
                assert plugins_module._PLUGINS_DISCOVERED is True
            finally:
                plugins_module._PLUGINS_DISCOVERED = original_discovered

    def test_logs_discovered_plugins(self, caplog):
        """Test that discovered plugins are logged."""
        import logging

        original_discovered = plugins_module._PLUGINS_DISCOVERED
        plugins_module._PLUGINS_DISCOVERED = False

        with (
            patch(
                "code_puppy.plugins._discover_builtin_plugins",
                return_value=[("test_builtin", ["startup"])],
            ),
            patch(
                "code_puppy.plugins._discover_user_plugins",
                return_value=[("test_user", ["startup"])],
            ),
            caplog.at_level(logging.DEBUG),
        ):
            try:
                load_plugin_callbacks()
                assert "Discovered plugins" in caplog.text
            finally:
                plugins_module._PLUGINS_DISCOVERED = original_discovered

    def test_skips_discovery_when_already_done_logs_debug(self, caplog):
        """Test that skipping duplicate discovery is logged."""
        import logging

        original_discovered = plugins_module._PLUGINS_DISCOVERED
        plugins_module._PLUGINS_DISCOVERED = True

        with caplog.at_level(logging.DEBUG):
            try:
                load_plugin_callbacks()
                assert "Plugins already discovered" in caplog.text
            finally:
                plugins_module._PLUGINS_DISCOVERED = original_discovered
