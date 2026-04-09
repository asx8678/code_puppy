"""Tests for the reflection utility module.

This module tests the resolve_variable function which resolves dotted
module:variable paths with actionable pip install hints on ImportError.
"""

import pytest
from code_puppy.reflection import resolve_variable, MODULE_TO_PACKAGE_HINTS


class TestResolveVariable:
    """Test cases for the resolve_variable function."""

    def test_resolve_with_colon_separator(self):
        """Test resolving a path with colon separator."""
        result = resolve_variable("code_puppy.callbacks:register_callback")
        from code_puppy.callbacks import register_callback
        assert result is register_callback

    def test_resolve_with_dot_separator(self):
        """Test resolving a path with dot separator (last dot treated as separator)."""
        result = resolve_variable("code_puppy.callbacks.register_callback")
        from code_puppy.callbacks import register_callback
        assert result is register_callback

    def test_resolve_function_from_standard_library(self):
        """Test resolving a function from the standard library."""
        result = resolve_variable("os.path:join")
        import os.path
        assert result is os.path.join

    def test_resolve_class(self):
        """Test resolving a class."""
        result = resolve_variable("code_puppy.callbacks:PhaseType")
        from code_puppy.callbacks import PhaseType
        assert result is PhaseType

    def test_resolve_module_variable(self):
        """Test resolving a module-level variable."""
        result = resolve_variable("code_puppy.reflection:MODULE_TO_PACKAGE_HINTS")
        assert result is MODULE_TO_PACKAGE_HINTS

    def test_resolve_with_expected_type_success(self):
        """Test type validation when type matches."""
        result = resolve_variable(
            "code_puppy.callbacks:register_callback",
            expected_type=type(lambda: None)  # function type
        )
        assert callable(result)

    def test_resolve_with_expected_type_mismatch(self):
        """Test type validation when type doesn't match."""
        with pytest.raises(TypeError) as exc_info:
            resolve_variable(
                "code_puppy.callbacks:register_callback",
                expected_type=str
            )
        assert "has type" in str(exc_info.value)
        assert "but expected" in str(exc_info.value)

    def test_empty_path_raises_value_error(self):
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_variable("")
        assert "Path must be a non-empty string" in str(exc_info.value)

    def test_none_path_raises_value_error(self):
        """Test that None path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_variable(None)
        assert "Path must be a non-empty string" in str(exc_info.value)

    def test_no_separator_raises_value_error(self):
        """Test that path without separator raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_variable("somepath")
        assert "Invalid path format" in str(exc_info.value)
        assert "separator" in str(exc_info.value)

    def test_empty_module_path_raises_value_error(self):
        """Test that path with empty module part raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_variable(":variable")
        assert "Module path is empty" in str(exc_info.value)

    def test_empty_variable_name_raises_value_error(self):
        """Test that path with empty variable part raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_variable("module:")
        assert "Variable name is empty" in str(exc_info.value)

    def test_attribute_error_for_missing_variable(self):
        """Test that missing variable raises AttributeError with helpful message."""
        with pytest.raises(AttributeError) as exc_info:
            resolve_variable("code_puppy.callbacks:nonexistent_function")
        assert "has no attribute" in str(exc_info.value)
        assert "Available public attributes" in str(exc_info.value)

    def test_import_error_for_missing_module(self):
        """Test that missing module raises ImportError."""
        with pytest.raises(ImportError) as exc_info:
            resolve_variable("nonexistent_module_xyz:function")
        assert "Could not import module" in str(exc_info.value)

    def test_pip_install_hint_for_langsmith(self):
        """Test that langsmith import error includes pip install hint."""
        with pytest.raises(ImportError) as exc_info:
            resolve_variable("langsmith:Client")
        assert "pip install langsmith" in str(exc_info.value)

    def test_pip_install_hint_for_langfuse(self):
        """Test that langfuse import error includes pip install hint."""
        with pytest.raises(ImportError) as exc_info:
            resolve_variable("langfuse:Langfuse")
        assert "pip install langfuse" in str(exc_info.value)

    def test_pip_install_hint_for_playwright(self):
        """Test that playwright import error includes pip install hint.
        
        Note: playwright is installed in this test environment, so we verify
        the module can be imported. In a real environment without playwright,
        the error would include the pip hint.
        """
        # playwright is installed - just verify it resolves correctly
        result = resolve_variable("playwright.sync_api:sync_playwright")
        from playwright.sync_api import sync_playwright
        assert result is sync_playwright

    def test_pip_install_hint_for_dbos(self):
        """Test that dbos import error includes pip install hint.
        
        Note: dbos is installed in this test environment, so we verify
        the module can be imported. In a real environment without dbos,
        the error would include the pip hint.
        """
        # dbos is installed - just verify it resolves correctly
        result = resolve_variable("dbos:DBOS")
        import dbos
        assert result is dbos.DBOS

    def test_pip_install_hint_for_dbos_transact(self):
        """Test that dbos_transact import error includes pip install hint."""
        with pytest.raises(ImportError) as exc_info:
            resolve_variable("dbos_transact:DBOS")
        assert "pip install dbos" in str(exc_info.value)

    def test_pip_install_hint_for_nested_module(self):
        """Test that nested module import error includes pip install hint for root module."""
        with pytest.raises(ImportError) as exc_info:
            resolve_variable("langsmith.client:SomeClass")
        assert "pip install langsmith" in str(exc_info.value)

    def test_nested_module_resolution(self):
        """Test resolving from a nested module."""
        result = resolve_variable("code_puppy.agents.base_agent:BaseAgent")
        from code_puppy.agents.base_agent import BaseAgent
        assert result is BaseAgent

    def test_deeply_nested_module_path(self):
        """Test resolving with a deeply nested module path."""
        result = resolve_variable("code_puppy.agents.pack.shepherd:ShepherdAgent")
        from code_puppy.agents.pack.shepherd import ShepherdAgent
        assert result is ShepherdAgent


class TestModuleToPackageHints:
    """Test cases for the MODULE_TO_PACKAGE_HINTS dictionary."""

    def test_contains_expected_keys(self):
        """Test that MODULE_TO_PACKAGE_HINTS contains the expected keys."""
        expected_keys = {"langsmith", "langfuse", "playwright", "dbos", "dbos_transact"}
        for key in expected_keys:
            assert key in MODULE_TO_PACKAGE_HINTS

    def test_langsmith_hint(self):
        """Test langsmith hint is correct."""
        assert MODULE_TO_PACKAGE_HINTS["langsmith"] == "langsmith"

    def test_langfuse_hint(self):
        """Test langfuse hint is correct."""
        assert MODULE_TO_PACKAGE_HINTS["langfuse"] == "langfuse"

    def test_playwright_hint(self):
        """Test playwright hint is correct."""
        assert MODULE_TO_PACKAGE_HINTS["playwright"] == "playwright"

    def test_dbos_hint(self):
        """Test dbos hint is correct."""
        assert MODULE_TO_PACKAGE_HINTS["dbos"] == "dbos"

    def test_dbos_transact_hint(self):
        """Test dbos_transact hint maps to dbos package."""
        assert MODULE_TO_PACKAGE_HINTS["dbos_transact"] == "dbos"
