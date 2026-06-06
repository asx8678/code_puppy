"""Full coverage tests for tools/__init__.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestToolRegistry:
    def test_tool_registry_populated(self):
        from code_puppy.tools import TOOL_REGISTRY

        assert "list_files" in TOOL_REGISTRY
        assert "edit_file" in TOOL_REGISTRY
        assert "universal_constructor" in TOOL_REGISTRY

    def test_get_available_tool_names(self):
        from code_puppy.tools import get_available_tool_names

        names = get_available_tool_names()
        assert isinstance(names, list)
        assert "read_file" in names


class TestLoadPluginTools:
    def test_load_plugin_tools_with_result(self):
        from code_puppy.tools import TOOL_REGISTRY, _load_plugin_tools

        mock_fn = MagicMock()
        with patch(
            "code_puppy.tools.on_register_tools",
            return_value=[[{"name": "test_plugin_tool", "register_func": mock_fn}]],
        ):
            _load_plugin_tools()
            assert "test_plugin_tool" in TOOL_REGISTRY
            del TOOL_REGISTRY["test_plugin_tool"]

    @pytest.mark.parametrize(
        "on_register_kwargs",
        [
            {"return_value": [None]},
            {"return_value": [[{"invalid": True}]]},
            {"side_effect": Exception("boom")},
        ],
        ids=["none_result", "invalid_tool_def", "exception"],
    )
    def test_load_plugin_tools_resilient(self, on_register_kwargs):
        from code_puppy.tools import _load_plugin_tools

        with patch("code_puppy.tools.on_register_tools", **on_register_kwargs):
            _load_plugin_tools()  # Should not raise/crash


class TestHasExtendedThinkingActive:
    def test_none_model(self):
        from code_puppy.tools import has_extended_thinking_active

        with patch("code_puppy.config.get_global_model_name", return_value=None):
            assert has_extended_thinking_active() is False

    def test_non_anthropic_model(self):
        from code_puppy.tools import has_extended_thinking_active

        assert has_extended_thinking_active("gpt-4") is False

    @pytest.mark.parametrize(
        ("model", "setting", "expected"),
        [
            ("claude-3", "enabled", True),
            ("claude-3", "adaptive", True),
            ("claude-3", True, True),
            ("claude-3", False, False),
            ("anthropic-model", "enabled", True),
        ],
        ids=["enabled", "adaptive", "legacy_true", "disabled", "anthropic_prefix"],
    )
    def test_anthropic_model(self, model, setting, expected):
        from code_puppy.tools import has_extended_thinking_active

        with (
            patch(
                "code_puppy.config.get_effective_model_settings",
                return_value={"extended_thinking": setting},
            ),
            patch(
                "code_puppy.model_utils.get_default_extended_thinking",
                return_value=False,
            ),
        ):
            assert has_extended_thinking_active(model) is expected


class TestRegisterToolsForAgent:
    def test_register_known_tools(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        agent.tool_plain = lambda fn: fn
        agent.tool = lambda fn: fn
        register_tools_for_agent(agent, ["list_files"])

    def test_register_unknown_tool(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        with patch("code_puppy.tools.emit_warning"):
            register_tools_for_agent(agent, ["nonexistent_tool_xyz"])

    def test_skip_uc_when_disabled(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        with patch(
            "code_puppy.config.get_universal_constructor_enabled", return_value=False
        ):
            register_tools_for_agent(agent, ["universal_constructor"])

    def test_skip_removed_reasoning_tool(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        with (
            patch("code_puppy.tools.emit_warning") as mock_warn,
            patch(
                "code_puppy.config.get_universal_constructor_enabled", return_value=True
            ),
        ):
            register_tools_for_agent(agent, ["agent_share_your_reasoning"])
            mock_warn.assert_not_called()

    def test_uc_tool_prefix(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        with (
            patch(
                "code_puppy.config.get_universal_constructor_enabled", return_value=True
            ),
            patch("code_puppy.tools._register_uc_tool_wrapper"),
        ):
            register_tools_for_agent(agent, ["uc:my_tool"])

    def test_uc_tool_prefix_disabled(self):
        from code_puppy.tools import register_tools_for_agent

        agent = MagicMock()
        with patch(
            "code_puppy.config.get_universal_constructor_enabled", return_value=False
        ):
            register_tools_for_agent(agent, ["uc:my_tool"])


class TestRegisterAllTools:
    def test_register_all(self):
        from code_puppy.tools import register_all_tools

        agent = MagicMock()
        agent.tool_plain = lambda fn: fn
        agent.tool = lambda fn: fn
        with patch(
            "code_puppy.config.get_universal_constructor_enabled", return_value=False
        ):
            register_all_tools(agent)


class TestRegisterUcToolWrapper:
    def test_tool_not_found(self):
        from code_puppy.tools import _register_uc_tool_wrapper

        agent = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_tool.return_value = None
        with (
            patch("code_puppy.tools.emit_warning"),
            patch(
                "code_puppy.plugins.universal_constructor.registry.get_registry",
                return_value=mock_registry,
            ),
        ):
            _register_uc_tool_wrapper(agent, "nonexistent")

    def test_function_not_found(self):
        from code_puppy.tools import _register_uc_tool_wrapper

        agent = MagicMock()
        mock_registry = MagicMock()
        mock_tool = MagicMock()
        mock_tool.meta.description = "desc"
        mock_tool.docstring = "doc"
        mock_registry.get_tool.return_value = mock_tool
        mock_registry.get_tool_function.return_value = None
        with (
            patch("code_puppy.tools.emit_warning"),
            patch(
                "code_puppy.plugins.universal_constructor.registry.get_registry",
                return_value=mock_registry,
            ),
        ):
            _register_uc_tool_wrapper(agent, "my_tool")

    def test_registry_exception(self):
        from code_puppy.tools import _register_uc_tool_wrapper

        agent = MagicMock()
        with (
            patch("code_puppy.tools.emit_warning"),
            patch(
                "code_puppy.plugins.universal_constructor.registry.get_registry",
                side_effect=Exception("boom"),
            ),
        ):
            _register_uc_tool_wrapper(agent, "my_tool")

    def test_successful_registration(self):
        from code_puppy.tools import _register_uc_tool_wrapper

        agent = MagicMock()
        mock_registry = MagicMock()
        mock_tool = MagicMock()
        mock_tool.meta.description = "desc"
        mock_tool.docstring = "doc"
        mock_tool.full_name = "my_tool"
        mock_registry.get_tool.return_value = mock_tool

        def sample_func(x: int) -> str:
            return str(x)

        mock_registry.get_tool_function.return_value = sample_func

        with patch(
            "code_puppy.plugins.universal_constructor.registry.get_registry",
            return_value=mock_registry,
        ):
            _register_uc_tool_wrapper(agent, "my_tool")
            agent.tool.assert_called_once()
