"""Tests for write guidance in proactive_guidance plugin.

Tests for _get_write_guidance() function and related functionality.
"""

from __future__ import annotations

import importlib

import pytest


def _import_plugin():
    """Import and return the plugin module with all its functions."""
    module = importlib.import_module(
        "code_puppy.plugins.proactive_guidance.register_callbacks"
    )
    return module


@pytest.fixture
def plugin_module():
    """Fixture providing the plugin module."""
    return _import_plugin()


@pytest.fixture
def fresh_state(plugin_module):
    """Fixture that resets plugin state to known defaults."""
    original_state = dict(plugin_module._state)
    plugin_module._state["enabled"] = True
    plugin_module._state["verbosity"] = "normal"
    plugin_module._state["last_tool"] = None
    plugin_module._state["guidance_count"] = 0
    yield plugin_module._state
    # Restore original state after test
    plugin_module._state.clear()
    plugin_module._state.update(original_state)


# ---------------------------------------------------------------------------
# Tests: Guidance Generation for Write Operations
# ---------------------------------------------------------------------------


class TestWriteGuidance:
    """Tests for _get_write_guidance() function."""

    def test_python_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Python files includes pytest and syntax check."""
        guidance = plugin_module._get_write_guidance("test.py", "def hello(): pass")
        assert guidance is not None
        assert "pytest" in guidance
        assert "py_compile" in guidance
        assert "✨ Next steps for your new file:" in guidance

    def test_javascript_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for JavaScript files."""
        guidance = plugin_module._get_write_guidance("app.js", "console.log('hi')")
        assert guidance is not None
        assert "pytest" in guidance  # Uses generic guidance for code files
        assert "py_compile" in guidance

    def test_typescript_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for TypeScript files."""
        guidance = plugin_module._get_write_guidance("app.ts", "const x: number = 1")
        assert guidance is not None
        assert "pytest" in guidance

    def test_markdown_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for markdown files."""
        guidance = plugin_module._get_write_guidance("README.md", "# Title")
        assert guidance is not None
        assert "cat" in guidance
        assert "head -20" in guidance

    def test_json_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for JSON files includes validation."""
        guidance = plugin_module._get_write_guidance("config.json", '{"key": "val"}')
        assert guidance is not None
        assert "Validate" in guidance
        assert "json.load" in guidance

    def test_yaml_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for YAML files."""
        guidance = plugin_module._get_write_guidance("config.yaml", "key: val")
        assert guidance is not None
        assert "Validate" in guidance

    def test_shell_script_guidance(self, plugin_module, fresh_state):
        """Test guidance for shell scripts includes shellcheck and chmod."""
        guidance = plugin_module._get_write_guidance("script.sh", "#!/bin/bash")
        assert guidance is not None
        assert "shellcheck" in guidance
        assert "chmod +x" in guidance

    def test_bash_script_guidance(self, plugin_module, fresh_state):
        """Test guidance for bash scripts."""
        guidance = plugin_module._get_write_guidance("script.bash", "#!/bin/bash")
        assert guidance is not None
        assert "shellcheck" in guidance

    def test_rust_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Rust files."""
        guidance = plugin_module._get_write_guidance("main.rs", "fn main() {}")
        assert guidance is not None
        assert "pytest" in guidance

    def test_go_file_guidance(self, plugin_module, fresh_state):
        """Test guidance for Go files."""
        guidance = plugin_module._get_write_guidance("main.go", "package main")
        assert guidance is not None
        assert "pytest" in guidance

    def test_minimal_verbosity_no_view_option(self, plugin_module, fresh_state):
        """Test that minimal verbosity excludes view file option."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_write_guidance("test.py", "pass")
        assert guidance is not None
        assert "/file" not in guidance  # View file option not shown in minimal mode
        assert "/grep" not in guidance  # Search option not shown in minimal mode

    def test_verbose_verbosity_extra_suggestions(self, plugin_module, fresh_state):
        """Test that verbose verbosity includes extra suggestions."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_write_guidance("test.py", "pass")
        assert guidance is not None
        # Verbose mode should include more lines than minimal suggestion count
        # Check for additional suggestions (verbose adds test file and git diff suggestions)
        assert guidance.count("\n") >= 4  # Should have header + 4 suggestions in verbose mode

    def test_empty_suggestions_returns_none(self, plugin_module, fresh_state):
        """Test that files with no specific guidance return None in minimal mode."""
        # Use an unknown extension that doesn't match any patterns
        fresh_state["verbosity"] = "minimal"
        result = plugin_module._get_write_guidance("file.unknownxyz", "content")
        # With minimal verbosity and no matching patterns, should return None
        assert result is None
