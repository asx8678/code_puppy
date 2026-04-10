"""Tests for the tool_allowlist plugin."""

from __future__ import annotations

import pytest

from code_puppy import callbacks as callbacks_module
from code_puppy.permission_decision import Deny
from code_puppy.plugins.tool_allowlist.register_callbacks import (
    _get_allowlist,
    _get_denylist,
    _is_tool_allowed,
    _on_pre_tool_call,
    _parse_tool_list,
)


@pytest.fixture(autouse=True)
def _isolate_callback_registry():
    """Isolate the callback registry for each test."""
    snapshot = {
        phase: list(callbacks_module.get_callbacks(phase))
        for phase in callbacks_module._callbacks
    }
    try:
        yield
    finally:
        callbacks_module.clear_callbacks()
        for phase, funcs in snapshot.items():
            for func in funcs:
                callbacks_module.register_callback(phase, func)


class TestParseToolList:
    """Tests for _parse_tool_list function."""

    def test_empty_string_returns_empty_set(self):
        assert _parse_tool_list("") == set()

    def test_none_returns_empty_set(self):
        assert _parse_tool_list(None) == set()

    def test_single_tool(self):
        assert _parse_tool_list("read_file") == {"read_file"}

    def test_multiple_tools(self):
        result = _parse_tool_list("read_file,write_file,grep")
        assert result == {"read_file", "write_file", "grep"}

    def test_whitespace_is_stripped(self):
        result = _parse_tool_list("  read_file  ,  write_file  ")
        assert result == {"read_file", "write_file"}

    def test_case_is_normalized_to_lowercase(self):
        result = _parse_tool_list("READ_FILE,Write_File,GREP")
        assert result == {"read_file", "write_file", "grep"}

    def test_empty_items_are_ignored(self):
        result = _parse_tool_list("read_file,,write_file,,")
        assert result == {"read_file", "write_file"}


class TestIsToolAllowed:
    """Tests for _is_tool_allowed function."""

    def test_no_restrictions_allows_all(self):
        """Empty allowlist and denylist -> all tools allowed."""
        assert _is_tool_allowed("any_tool", set(), set()) is True

    def test_tool_in_allowlist_allowed(self):
        """Tool in allowlist -> allowed."""
        assert _is_tool_allowed("read_file", {"read_file", "write_file"}, set()) is True

    def test_tool_not_in_allowlist_denied(self):
        """Tool not in allowlist -> denied."""
        assert _is_tool_allowed("grep", {"read_file", "write_file"}, set()) is False

    def test_tool_in_denylist_denied(self):
        """Tool in denylist -> denied regardless of allowlist."""
        assert _is_tool_allowed("agent_run_shell_command", set(), {"agent_run_shell_command"}) is False

    def test_denylist_takes_priority_over_allowlist(self):
        """Tool in both allowlist and denylist -> denied."""
        assert _is_tool_allowed("dangerous_tool", {"dangerous_tool"}, {"dangerous_tool"}) is False

    def test_case_insensitive_matching(self):
        """Tool names are compared case-insensitively."""
        assert _is_tool_allowed("READ_FILE", {"read_file"}, set()) is True
        assert _is_tool_allowed("Read_File", set(), {"read_file"}) is False


class TestOnPreToolCall:
    """Tests for _on_pre_tool_call callback function."""

    def test_no_config_returns_none(self, monkeypatch):
        """Empty config -> no restrictions -> returns None (allow)."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: set(),
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: set(),
        )

        result = _on_pre_tool_call("any_tool", {})
        assert result is None

    def test_tool_in_allowlist_returns_none(self, monkeypatch):
        """Tool in allowlist -> returns None (allow)."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: {"read_file", "write_file"},
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: set(),
        )

        result = _on_pre_tool_call("read_file", {})
        assert result is None

    def test_tool_not_in_allowlist_returns_blocked(self, monkeypatch):
        """Tool not in allowlist -> returns Deny."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: {"read_file"},
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: set(),
        )

        result = _on_pre_tool_call("grep", {})
        assert result is not None
        assert isinstance(result, Deny)
        assert "not in the allowlist" in result.reason
        assert "grep" in result.user_feedback

    def test_tool_in_denylist_returns_blocked(self, monkeypatch):
        """Tool in denylist -> returns Deny."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: set(),
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: {"agent_run_shell_command"},
        )

        result = _on_pre_tool_call("agent_run_shell_command", {})
        assert result is not None
        assert isinstance(result, Deny)
        assert "in the denylist" in result.reason

    def test_tool_not_in_denylist_returns_none(self, monkeypatch):
        """Tool not in denylist -> returns None (allow)."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: set(),
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: {"agent_run_shell_command"},
        )

        result = _on_pre_tool_call("read_file", {})
        assert result is None

    def test_denylist_priority_over_allowlist(self, monkeypatch):
        """Tool in both lists -> denylist wins."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_allowlist",
            lambda: {"dangerous_tool"},
        )
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks._get_denylist",
            lambda: {"dangerous_tool"},
        )

        result = _on_pre_tool_call("dangerous_tool", {})
        assert result is not None
        assert isinstance(result, Deny)
        assert "in the denylist" in result.reason


class TestConfigIntegration:
    """Integration tests with actual config reading."""

    def test_get_allowlist_from_config(self, monkeypatch):
        """Test reading allowlist from puppy.cfg."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks.get_value",
            lambda key: "read_file, write_file, grep" if key == "tool_allowlist" else None,
        )

        result = _get_allowlist()
        assert result == {"read_file", "write_file", "grep"}

    def test_get_denylist_from_config(self, monkeypatch):
        """Test reading denylist from puppy.cfg."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks.get_value",
            lambda key: "agent_run_shell_command, delete_file" if key == "tool_denylist" else None,
        )

        result = _get_denylist()
        assert result == {"agent_run_shell_command", "delete_file"}

    def test_empty_config_returns_empty_sets(self, monkeypatch):
        """Test that missing config returns empty sets."""
        monkeypatch.setattr(
            "code_puppy.plugins.tool_allowlist.register_callbacks.get_value",
            lambda key: None,
        )

        assert _get_allowlist() == set()
        assert _get_denylist() == set()


class TestPluginRegistration:
    """Tests for plugin registration and callback integration."""

    def test_callback_is_registered(self):
        """Verify the pre_tool_call callback is registered."""
        # Import re-registers the callback
        from code_puppy.plugins.tool_allowlist import register_callbacks  # noqa: F401

        callbacks = callbacks_module.get_callbacks("pre_tool_call")
        callback_funcs = [c for c in callbacks]

        # Check our callback is in the list
        assert any(
            getattr(c, "__name__", None) == "_on_pre_tool_call" for c in callback_funcs
        )
