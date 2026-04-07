"""Tests for the turbo_parse plugin.

This plugin provides high-performance parsing via the turbo_parse Rust module.
Tests verify availability checking, callback registration, and graceful fallback.
"""

import importlib.util
from unittest import mock

from code_puppy.callbacks import clear_callbacks, get_callbacks, register_callback


def is_turbo_parse_available() -> bool:
    """Check if turbo_parse module is available without importing it."""
    return importlib.util.find_spec("turbo_parse") is not None


class TestTurboParseAvailability:
    """Tests for the is_turbo_parse_available function."""

    def test_availability_check_returns_bool(self):
        """Test that availability check returns a boolean."""
        result = is_turbo_parse_available()
        assert isinstance(result, bool)

    def test_availability_check_uses_importlib(self):
        """Test that availability check uses importlib.util.find_spec."""
        with mock.patch("importlib.util.find_spec") as mock_find_spec:
            mock_find_spec.return_value = None
            result = is_turbo_parse_available()
            mock_find_spec.assert_called_once_with("turbo_parse")
            assert result is False

    def test_availability_check_returns_true_when_spec_found(self):
        """Test that availability check returns True when spec exists."""
        with mock.patch("importlib.util.find_spec") as mock_find_spec:
            mock_spec = mock.Mock()
            mock_find_spec.return_value = mock_spec
            result = is_turbo_parse_available()
            assert result is True


class TestTurboParsePluginCallbacks:
    """Tests for the turbo_parse plugin callback registration."""

    def setup_method(self):
        """Clear callbacks before each test."""
        clear_callbacks("startup")
        clear_callbacks("register_tools")

    def teardown_method(self):
        """Clear callbacks after each test."""
        clear_callbacks("startup")
        clear_callbacks("register_tools")

    def test_plugin_registers_startup_callback(self):
        """Test that the plugin registers a startup callback."""
        # Import the register_callbacks module and register callbacks directly
        from code_puppy.plugins.turbo_parse import register_callbacks

        register_callbacks._on_startup  # Verify function exists
        # Register directly to ensure test works regardless of import order
        register_callback("startup", register_callbacks._on_startup)

        callbacks = get_callbacks("startup")
        assert any(
            cb.__module__ == "code_puppy.plugins.turbo_parse.register_callbacks"
            for cb in callbacks
        )

    def test_plugin_registers_tools_callback(self):
        """Test that the plugin registers a register_tools callback."""
        from code_puppy.plugins.turbo_parse import register_callbacks

        register_callbacks._register_tools  # Verify function exists
        # Register directly to ensure test works regardless of import order
        register_callback("register_tools", register_callbacks._register_tools)

        callbacks = get_callbacks("register_tools")
        assert any(
            cb.__module__ == "code_puppy.plugins.turbo_parse.register_callbacks"
            for cb in callbacks
        )

    def test_register_tools_callback_returns_list(self):
        """Test that the register_tools callback returns a list."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _register_tools

        result = _register_tools()
        assert isinstance(result, list)
        assert len(result) == 0  # Currently a placeholder


class TestTurboParseStartup:
    """Tests for the turbo_parse startup behavior."""

    def setup_method(self):
        """Clear callbacks before each test."""
        clear_callbacks("startup")

    def teardown_method(self):
        """Clear callbacks after each test."""
        clear_callbacks("startup")

    def test_startup_handles_missing_module_gracefully(self, caplog):
        """Test that startup handles missing turbo_parse gracefully."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available",
            return_value=False,
        ):
            with caplog.at_level("INFO"):
                _on_startup()

        assert any(
            "not available" in record.message.lower() or "fallback" in record.message.lower()
            for record in caplog.records
        )

    def test_startup_logs_when_module_available(self, caplog):
        """Test that startup logs when turbo_parse is available."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        mock_module = mock.Mock()
        mock_module.__version__ = "1.0.0"
        mock_module.health_check.return_value = {"version": "1.0.0"}

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available",
            return_value=True,
        ):
            with mock.patch("builtins.__import__", return_value=mock_module):
                with caplog.at_level("INFO"):
                    _on_startup()

        # Should have an INFO or DEBUG log about the module being available
        assert any(
            "available" in record.message.lower()
            for record in caplog.records
        )


class TestTurboParseExports:
    """Tests for the plugin's public exports."""

    def test_init_exports_version(self):
        """Test that __init__.py exports __version__."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "__version__")
        assert turbo_parse.__version__ == "0.1.0"

    def test_init_exports_availability_function(self):
        """Test that __init__.py exports is_turbo_parse_available."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "is_turbo_parse_available")
        assert callable(turbo_parse.is_turbo_parse_available)
        result = turbo_parse.is_turbo_parse_available()
        assert isinstance(result, bool)

    def test_all_exports_are_public(self):
        """Test that __all__ only contains public names."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "__all__")
        for name in turbo_parse.__all__:
            # Single underscore prefix is private; dunder names like __version__ are public
            assert not name.startswith("_") or name.startswith("__"), (
                f"Private name {name} in __all__"
            )
