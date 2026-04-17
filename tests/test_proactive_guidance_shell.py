"""Tests for shell and agent guidance in proactive_guidance plugin.

Tests for _get_shell_guidance() and _get_agent_guidance() functions.
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
# Tests: Guidance Generation for Shell Commands
# ---------------------------------------------------------------------------


class TestShellGuidance:
    """Tests for _get_shell_guidance() function."""

    def test_pytest_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after successful pytest run."""
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance
        assert "commit" in guidance.lower() or "Tests passed" in guidance

    def test_pytest_success_coverage_suggestion(self, plugin_module, fresh_state):
        """Test that successful pytest suggests coverage in normal mode."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "--cov" in guidance or "coverage" in guidance.lower()

    def test_pytest_success_no_coverage_in_minimal(self, plugin_module, fresh_state):
        """Test that minimal verbosity doesn't include coverage suggestion."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_shell_guidance("pytest tests/", 0)
        assert guidance is not None
        assert "--cov" not in guidance

    def test_git_commit_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after git commit."""
        guidance = plugin_module._get_shell_guidance("git commit -m 'msg'", 0)
        assert guidance is not None
        # Note: "git commit -m 'test'" would match pytest pattern, so we use 'msg'
        assert "push" in guidance.lower()

    def test_git_add_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after git add."""
        guidance = plugin_module._get_shell_guidance("git add file.py", 0)
        assert guidance is not None
        assert "push" in guidance.lower()

    def test_git_push_pr_suggestion_in_verbose(self, plugin_module, fresh_state):
        """Test verbose mode suggests creating PR."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_shell_guidance("git commit -m 'msg'", 0)
        assert guidance is not None
        assert "pr create" in guidance.lower() or "PR" in guidance

    def test_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after successful build."""
        guidance = plugin_module._get_shell_guidance("cargo build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "🎯" in guidance

    def test_make_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after make command."""
        guidance = plugin_module._get_shell_guidance("make all", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "🎯" in guidance or "✅" in guidance

    def test_npm_install_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm install."""
        guidance = plugin_module._get_shell_guidance("npm install", 0)
        assert guidance is not None
        assert "dependencies" in guidance.lower() or "📦" in guidance

    def test_pip_install_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after pip install."""
        guidance = plugin_module._get_shell_guidance("pip install requests", 0)
        assert guidance is not None
        assert "freeze" in guidance or "📦" in guidance

    def test_grep_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after grep command."""
        guidance = plugin_module._get_shell_guidance("grep -r 'pattern' src/", 0)
        assert guidance is not None
        assert "Found matches" in guidance or "🔍" in guidance or "✅" in guidance

    def test_find_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after find command."""
        guidance = plugin_module._get_shell_guidance("find . -name '*.py'", 0)
        assert guidance is not None
        assert "Found matches" in guidance or "🔍" in guidance or "✅" in guidance

    def test_ls_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after ls command."""
        guidance = plugin_module._get_shell_guidance("ls -la", 0)
        assert guidance is not None
        assert "Explore" in guidance or "📂" in guidance or "✅" in guidance

    def test_tree_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after tree command."""
        guidance = plugin_module._get_shell_guidance("tree", 0)
        assert guidance is not None
        assert "Explore" in guidance or "📂" in guidance or "✅" in guidance

    def test_npm_test_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm test."""
        guidance = plugin_module._get_shell_guidance("npm test", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance

    def test_cargo_test_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after cargo test."""
        guidance = plugin_module._get_shell_guidance("cargo test", 0)
        assert guidance is not None
        assert "Tests passed" in guidance or "✅" in guidance

    def test_cargo_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after cargo build."""
        guidance = plugin_module._get_shell_guidance("cargo build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "✅" in guidance

    def test_npm_run_build_success_guidance(self, plugin_module, fresh_state):
        """Test guidance after npm run build."""
        guidance = plugin_module._get_shell_guidance("npm run build", 0)
        assert guidance is not None
        assert "Build succeeded" in guidance or "✅" in guidance

    def test_generic_command_success(self, plugin_module, fresh_state):
        """Test guidance for generic commands that match no specific patterns."""
        guidance = plugin_module._get_shell_guidance("echo hello", 0)
        assert guidance is not None
        assert "✅" in guidance or "Command completed" in guidance

    def test_command_failure_guidance(self, plugin_module, fresh_state):
        """Test guidance when command fails (non-zero exit code)."""
        guidance = plugin_module._get_shell_guidance("false", 1)
        assert guidance is not None
        assert "⚠️" in guidance or "failed" in guidance.lower()
        assert "exit code 1" in guidance
        assert "Debug" in guidance or "verbose" in guidance.lower()

    def test_command_failure_exit_code_2(self, plugin_module, fresh_state):
        """Test guidance when command fails with exit code 2."""
        guidance = plugin_module._get_shell_guidance("grep pattern file.txt", 2)
        assert guidance is not None
        assert "⚠️" in guidance or "failed" in guidance.lower()
        assert "exit code 2" in guidance

    def test_shell_reuse_suggestion_in_normal_mode(self, plugin_module, fresh_state):
        """Test that normal mode suggests running similar command."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_shell_guidance("echo test", 0)
        assert guidance is not None
        assert "/shell" in guidance or "Use ↑" in guidance

    def test_shell_reuse_not_in_minimal_mode(self, plugin_module, fresh_state):
        """Test that minimal mode doesn't suggest command reuse."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_shell_guidance("echo test", 0)
        assert guidance is not None
        assert "/shell" not in guidance


# ---------------------------------------------------------------------------
# Tests: Guidance Generation for Agent Invocations
# ---------------------------------------------------------------------------


class TestAgentGuidance:
    """Tests for _get_agent_guidance() function."""

    def test_agent_completion_guidance(self, plugin_module, fresh_state):
        """Test basic agent completion guidance."""
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "test_agent" in guidance
        assert "🤖" in guidance or "completed" in guidance.lower()

    def test_normal_verbosity_includes_review(self, plugin_module, fresh_state):
        """Test normal verbosity includes review suggestion."""
        fresh_state["verbosity"] = "normal"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "Review" in guidance or "output" in guidance.lower()
        assert "Iterate" in guidance or "re-invoke" in guidance.lower()

    def test_verbose_verbosity_extra_guidance(self, plugin_module, fresh_state):
        """Test verbose verbosity includes extra suggestions."""
        fresh_state["verbosity"] = "verbose"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "context" in guidance.lower() or "Document" in guidance

    def test_minimal_verbosity_basic_only(self, plugin_module, fresh_state):
        """Test minimal verbosity only includes basic completion message."""
        fresh_state["verbosity"] = "minimal"
        guidance = plugin_module._get_agent_guidance("test_agent")
        assert guidance is not None
        assert "test_agent" in guidance
        # Verify minimal mode excludes verbose content
        assert "Review" not in guidance
        assert "Iterate" not in guidance
