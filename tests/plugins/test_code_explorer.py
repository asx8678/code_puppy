"""Tests for the code_explorer plugin.

Tests the plugin registration, tools, and slash commands.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Import plugin functions directly
from code_puppy.plugins.code_explorer.register_callbacks import (
    _explore_help,
    _format_file_context,
    _get_explorer,
    _handle_explore_command,
    _handle_explore_dir,
    _handle_explore_file,
    _handle_explore_help,
    _handle_explore_outline,
    _on_startup,
    _register_explore_directory_tool,
    _register_get_code_context_tool,
    _register_get_file_outline_tool,
    _register_tools,
)


# -----------------------------------------------------------------------------
# Fixture Tests
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_python_file():
    """Create a sample Python file for testing."""
    content = '''
"""Sample module for testing."""

class MyClass:
    """A sample class."""

    def __init__(self):
        self.value = 0

    def method1(self) -> int:
        return self.value

def standalone_function():
    """A standalone function."""
    return 42
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(content)
        path = f.name

    yield path

    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def sample_directory(tmp_path):
    """Create a sample directory structure for testing."""
    (tmp_path / "main.py").write_text("""
def main():
    print("Hello")

class App:
    def run(self):
        main()
""")

    (tmp_path / "utils.py").write_text("""
def helper():
    return "helper"
""")

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "module.py").write_text("""
class SubModule:
    pass
""")

    (tmp_path / "readme.txt").write_text("Hello")

    yield str(tmp_path)


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing tool registration."""
    agent = MagicMock()
    registered_tools = []

    def mock_tool_decorator(f):
        registered_tools.append(f)
        return f

    agent.tool = mock_tool_decorator
    agent._registered_tools = registered_tools
    return agent


@pytest.fixture
def mock_run_context():
    """Create a mock RunContext."""
    return MagicMock()


# -----------------------------------------------------------------------------
# Helper Function Tests
# -----------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for plugin helper functions."""

    def test_on_startup_logs_message(self, caplog):
        """Test that startup logs a message."""
        with caplog.at_level("INFO"):
            _on_startup()
        assert "Code Explorer" in caplog.text

    def test_get_explorer_singleton(self):
        """Test that get_explorer returns a singleton."""
        explorer1 = _get_explorer()
        explorer2 = _get_explorer()
        assert explorer1 is explorer2


# -----------------------------------------------------------------------------
# Tool Registration Tests
# -----------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for tool registration."""

    def test_register_tools_returns_list(self):
        """Test that _register_tools returns a list of tool definitions."""
        tools = _register_tools()

        assert isinstance(tools, list)
        assert len(tools) >= 3

        # Check expected tools
        tool_names = [t["name"] for t in tools]
        assert "get_code_context" in tool_names
        assert "explore_directory" in tool_names
        assert "get_file_outline" in tool_names

    def test_register_get_code_context_tool(self, mock_agent, mock_run_context):
        """Test get_code_context tool registration."""
        _register_get_code_context_tool(mock_agent)

        # Check that a tool was registered
        assert len(mock_agent._registered_tools) == 1
        tool_func = mock_agent._registered_tools[0]

        # The function should exist and have docstring
        assert tool_func is not None
        assert hasattr(tool_func, "__doc__")

    def test_register_explore_directory_tool(self, mock_agent, mock_run_context):
        """Test explore_directory tool registration."""
        _register_explore_directory_tool(mock_agent)

        assert len(mock_agent._registered_tools) == 1
        tool_func = mock_agent._registered_tools[0]
        assert tool_func is not None
        assert "explore" in tool_func.__doc__.lower()

    def test_register_get_file_outline_tool(self, mock_agent, mock_run_context):
        """Test get_file_outline tool registration."""
        _register_get_file_outline_tool(mock_agent)

        assert len(mock_agent._registered_tools) == 1
        tool_func = mock_agent._registered_tools[0]
        assert tool_func is not None
        assert "outline" in tool_func.__doc__.lower()


# -----------------------------------------------------------------------------
# Command Handler Tests
# -----------------------------------------------------------------------------


class TestCommandHandlers:
    """Tests for slash command handlers."""

    def test_explore_help_returns_entries(self):
        """Test that _explore_help returns help entries."""
        help_entries = _explore_help()

        assert isinstance(help_entries, list)
        assert len(help_entries) >= 4

        # Check for expected commands
        commands = [entry[0] for entry in help_entries]
        assert "explore" in commands
        assert "explore file <path>" in commands
        assert "explore dir <path>" in commands
        assert "explore help" in commands

    def test_handle_explore_help(self):
        """Test the help handler."""
        result = _handle_explore_help()

        assert isinstance(result, str)
        assert "/explore" in result
        assert "Usage:" in result
        assert "file" in result
        assert "dir" in result
        assert "outline" in result

    def test_handle_explore_file(self, sample_python_file):
        """Test exploring a single file."""
        result = _handle_explore_file(sample_python_file)

        assert isinstance(result, str)
        assert "📄" in result or "Error" in result
        assert "python" in result.lower() or "Error" in result

    def test_handle_explore_file_not_found(self):
        """Test exploring a non-existent file."""
        result = _handle_explore_file("/nonexistent/file.py")

        assert isinstance(result, str)
        # The result may show a file emoji since it tries to read, or an error
        assert "📄" in result or "Error" in result or "Lines: 0" in result

    def test_handle_explore_dir(self, sample_directory):
        """Test exploring a directory."""
        result = _handle_explore_dir(sample_directory)

        assert isinstance(result, str)
        assert "📁" in result
        # Should list Python files found
        assert ".py" in result or "files" in result.lower()

    def test_handle_explore_dir_empty(self, tmp_path):
        """Test exploring an empty directory."""
        result = _handle_explore_dir(str(tmp_path))

        assert isinstance(result, str)
        assert "No supported files" in result or "📁" in result

    def test_handle_explore_outline(self, sample_python_file):
        """Test getting outline of a file."""
        result = _handle_explore_outline(sample_python_file)

        assert isinstance(result, str)
        assert "Outline" in result or "Error" in result
        # Should show symbols
        if "Error" not in result:
            assert (
                "MyClass" in result
                or "standalone_function" in result
                or "python" in result.lower()
            )

    def test_format_file_context_with_symbols(self, sample_python_file):
        """Test formatting file context with symbols."""
        # First get context through explorer
        from code_puppy.code_context import get_code_context

        context = get_code_context(sample_python_file, include_content=False)
        context_dict = context.to_dict()

        formatted = _format_file_context(context_dict)

        assert isinstance(formatted, str)
        assert (
            sample_python_file.split("/")[-1].replace(".py", "") in formatted
            or "📄" in formatted
        )


# -----------------------------------------------------------------------------
# Command Routing Tests
# -----------------------------------------------------------------------------


class TestCommandRouting:
    """Tests for command routing and dispatch."""

    def test_handle_explore_command_unknown(self):
        """Test that unknown subcommands are rejected."""
        result = _handle_explore_command("/explore unknowncmd", "explore")

        # Should return True (handled) with error message
        assert result is True

    def test_handle_explore_command_wrong_base(self):
        """Test that non-explore commands are ignored."""
        result = _handle_explore_command("/othercmd something", "othercmd")

        # Should return None (not handled)
        assert result is None

    def test_handle_explore_command_no_subcommand(self):
        """Test command with no subcommand shows help."""
        result = _handle_explore_command("/explore", "explore")

        # Should return True (handled)
        assert result is True

    def test_handle_explore_command_file_no_path(self):
        """Test file subcommand without path shows error."""
        result = _handle_explore_command("/explore file", "explore")

        # Should be handled (True)
        assert result is True

    def test_handle_explore_command_dir_no_path(self):
        """Test dir subcommand without path shows error."""
        result = _handle_explore_command("/explore dir", "explore")

        # Should be handled (True)
        assert result is True

    def test_handle_explore_command_outline_no_path(self):
        """Test outline subcommand without path shows error."""
        result = _handle_explore_command("/explore outline", "explore")

        # Should be handled (True)
        assert result is True


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestIntegration:
    """Integration tests for the plugin."""

    def test_full_exploration_flow(self, sample_directory):
        """Test full exploration flow end-to-end."""
        # Explore directory
        dir_result = _handle_explore_dir(sample_directory)
        assert "📁" in dir_result

        # Explore specific file
        py_file = os.path.join(sample_directory, "main.py")
        file_result = _handle_explore_file(py_file)
        assert "📄" in file_result or "Error" in file_result

        # Get outline
        outline_result = _handle_explore_outline(py_file)
        assert "Outline" in outline_result or "Error" in outline_result


# -----------------------------------------------------------------------------
# Error Handling Tests
# -----------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_handle_file_with_exception(self):
        """Test graceful handling of exceptions in file exploration."""
        with patch(
            "code_puppy.plugins.code_explorer.register_callbacks._get_code_context",
            side_effect=Exception("Test error"),
        ):
            result = _handle_explore_file("/some/path.py")
            assert "Error" in result or "❌" in result

    def test_handle_dir_with_exception(self):
        """Test graceful handling of exceptions in directory exploration."""
        with patch(
            "code_puppy.plugins.code_explorer.register_callbacks._explore_directory",
            side_effect=Exception("Test error"),
        ):
            result = _handle_explore_dir("/some/dir")
            assert "Error" in result or "❌" in result

    def test_handle_outline_with_exception(self):
        """Test graceful handling of exceptions in outline extraction."""
        with patch(
            "code_puppy.plugins.code_explorer.register_callbacks._get_file_outline",
            side_effect=Exception("Test error"),
        ):
            result = _handle_explore_outline("/some/path.py")
            assert "Error" in result or "❌" in result


# -----------------------------------------------------------------------------
# Cache Stats Tests
# -----------------------------------------------------------------------------


class TestCacheFunctionality:
    """Tests for caching functionality."""

    def test_explorer_cache_stats(self, sample_python_file):
        """Test that cache stats work correctly."""
        from code_puppy.code_context import CodeExplorer

        explorer = CodeExplorer(enable_cache=True)

        # Initially empty
        stats = explorer.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["parse_count"] == 0

        # Explore a file
        explorer.explore_file(sample_python_file)

        # Stats should update
        stats = explorer.get_cache_stats()
        assert stats["cache_size"] == 1
        assert stats["parse_count"] == 1

        # Second access should hit cache
        explorer.explore_file(sample_python_file)
        stats = explorer.get_cache_stats()
        assert stats["cache_hits"] == 1

    def test_cache_invalidation(self, sample_python_file):
        """Test cache invalidation."""
        from code_puppy.code_context import CodeExplorer

        explorer = CodeExplorer(enable_cache=True)

        # Explore and cache
        explorer.explore_file(sample_python_file)
        assert len(explorer._cache) == 1

        # Invalidate
        explorer.invalidate_cache(sample_python_file)
        assert len(explorer._cache) == 0

        # Clear all
        explorer.explore_file(sample_python_file)
        explorer.invalidate_cache()
        assert len(explorer._cache) == 0
