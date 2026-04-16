"""Contract tests for plugins.

Tests validate that plugins follow code_puppy's contracts for:
- Import safety
- Callback deduplication
- Registration patterns
"""

import pytest

from code_puppy import callbacks
from tests.contracts import (
    ContractViolation,
    PluginContract,
    validate_plugin_contracts,
)


class TestBuiltinPlugins:
    """Test that builtin plugins pass contract validation."""

    def test_import_plugin_loader(self):
        """Test that plugins module is importable."""

        def import_plugins():
            from code_puppy import plugins

            return plugins

        errors = validate_plugin_contracts("code_puppy.plugins", import_plugins)
        assert not errors, f"Import errors: {errors}"

    def test_import_builtin_plugins(self):
        """Test that each builtin plugin is importable."""
        builtin_plugins = [
            "code_puppy.plugins.agent_skills",
            "code_puppy.plugins.error_classifier",
            "code_puppy.plugins.file_permission_handler",
            "code_puppy.plugins.scheduler",
            "code_puppy.plugins.shell_safety",
        ]

        for plugin_name in builtin_plugins:

            def make_import(name):
                return lambda: __import__(name, fromlist=["register_callbacks"])

            errors = validate_plugin_contracts(plugin_name, make_import(plugin_name))
            assert not errors, f"Plugin {plugin_name} failed: {errors}"


class TestCallbackDeduplication:
    """Test callback registration deduplication."""

    def test_same_callback_deduplicated(self):
        """Test that registering the same callback twice is deduplicated."""
        call_count = 0

        def test_callback():
            nonlocal call_count
            call_count += 1

        # Register twice
        callbacks.register_callback("startup", test_callback)
        callbacks.register_callback("startup", test_callback)

        # Get callbacks
        cb_list = callbacks.get_callbacks("startup")

        # Should only appear once
        matches = [cb for cb in cb_list if cb is test_callback]
        assert len(matches) == 1, f"Callback duplicated: {len(matches)} times"

    def test_different_callbacks_not_deduplicated(self):
        """Test that different callbacks are not deduplicated."""

        def callback1():
            pass

        def callback2():
            pass

        # Clear first
        callbacks.clear_callbacks("shutdown")

        # Register two different callbacks
        callbacks.register_callback("shutdown", callback1)
        callbacks.register_callback("shutdown", callback2)

        cb_list = callbacks.get_callbacks("shutdown")

        assert callback1 in cb_list
        assert callback2 in cb_list


class TestContractHelpers:
    """Test the contract helper functions."""

    def test_validate_import_safety_success(self):
        """Test import validation passes for valid module."""

        def good_import():
            import code_puppy.callbacks

            return code_puppy.callbacks

        # Should not raise
        PluginContract.validate_import_safety("test", good_import)

    def test_validate_import_safety_failure(self):
        """Test import validation fails for bad module."""

        def bad_import():
            raise ImportError("Module not found")

        with pytest.raises(ContractViolation) as exc_info:
            PluginContract.validate_import_safety("bad_module", bad_import)

        assert "Import failed" in str(exc_info.value)

    def test_validate_plugin_contracts_returns_errors(self):
        """Test that validate_plugin_contracts returns error list."""

        def bad_import():
            raise RuntimeError("Failed")

        errors = validate_plugin_contracts("test", bad_import)

        assert len(errors) == 1
        assert "Contract violation" in errors[0]
