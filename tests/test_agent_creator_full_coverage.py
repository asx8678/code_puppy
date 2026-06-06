"""Full coverage tests for agents/agent_creator_agent.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from code_puppy.agents.agent_creator_agent import AgentCreatorAgent

VALID_CONFIG = {
    "name": "test-agent",
    "description": "Test",
    "system_prompt": "ok",
    "tools": [],
}


class TestAgentCreatorAgent:
    @pytest.mark.parametrize(
        "attr, expected",
        [
            ("name", "agent-creator"),
            ("display_name", "Agent Creator"),
            ("description", "JSON"),
        ],
    )
    def test_simple_properties(self, attr, expected):
        assert expected in getattr(AgentCreatorAgent(), attr)

    def test_get_user_prompt(self):
        assert "Agent Creator" in AgentCreatorAgent().get_user_prompt()

    def test_get_system_prompt(self):
        agent = AgentCreatorAgent()
        with (
            patch(
                "code_puppy.agents.agent_creator_agent.get_available_tool_names",
                return_value=["read_file"],
            ),
            patch(
                "code_puppy.agents.agent_creator_agent.get_user_agents_directory",
                return_value="/tmp/agents",
            ),
            patch("code_puppy.agents.agent_creator_agent.ModelFactory") as mock_factory,
        ):
            mock_factory.load_config.return_value = {
                "gpt-4": {"type": "openai", "context_length": 128000}
            }
            prompt = agent.get_system_prompt()
            assert "read_file" in prompt
            assert "gpt-4" in prompt

    def test_get_system_prompt_with_uc_tools(self):
        agent = AgentCreatorAgent()
        mock_tool = MagicMock()
        mock_tool.full_name = "api.weather"
        mock_tool.meta.enabled = True
        mock_tool.meta.description = "Weather tool"

        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = [mock_tool]

        with (
            patch(
                "code_puppy.agents.agent_creator_agent.get_available_tool_names",
                return_value=[],
            ),
            patch(
                "code_puppy.agents.agent_creator_agent.get_user_agents_directory",
                return_value="/tmp",
            ),
            patch("code_puppy.agents.agent_creator_agent.ModelFactory") as mock_factory,
            patch(
                "code_puppy.plugins.universal_constructor.registry.get_registry",
                return_value=mock_registry,
            ),
        ):
            mock_factory.load_config.return_value = {}
            prompt = agent.get_system_prompt()
            assert "api.weather" in prompt

    @pytest.mark.parametrize("uc_enabled", [True, False])
    def test_get_available_tools(self, uc_enabled):
        agent = AgentCreatorAgent()
        with patch(
            "code_puppy.config.get_universal_constructor_enabled",
            return_value=uc_enabled,
        ):
            tools = agent.get_available_tools()
            assert ("universal_constructor" in tools) is uc_enabled

    def test_validate_agent_json_valid(self):
        assert AgentCreatorAgent().validate_agent_json(VALID_CONFIG) == []

    def test_validate_agent_json_missing_fields(self):
        assert len(AgentCreatorAgent().validate_agent_json({})) == 4

    @pytest.mark.parametrize(
        "overrides, expected_substr",
        [
            ({"name": "bad name"}, "spaces"),
            ({"name": ""}, "non-empty"),
            ({"tools": "not-a-list"}, "list"),
            ({"tools": ["nonexistent_tool_xyz"]}, "Invalid"),
            ({"system_prompt": 123}, "string or list"),
            ({"system_prompt": ["ok", 123]}, "strings"),
        ],
    )
    def test_validate_agent_json_errors(self, overrides, expected_substr):
        config = {**VALID_CONFIG, **overrides}
        errors = AgentCreatorAgent().validate_agent_json(config)
        assert any(expected_substr in e for e in errors)

    def test_get_agent_file_path(self):
        agent = AgentCreatorAgent()
        with patch(
            "code_puppy.agents.agent_creator_agent.get_user_agents_directory",
            return_value="/tmp/agents",
        ):
            assert agent.get_agent_file_path("my-agent").endswith("my-agent.json")

    def test_create_agent_json_success(self, tmp_path):
        agent = AgentCreatorAgent()
        with patch.object(
            agent, "get_agent_file_path", return_value=str(tmp_path / "test-agent.json")
        ):
            success, msg = agent.create_agent_json(VALID_CONFIG)
            assert success is True
            assert "Successfully" in msg

    def test_create_agent_json_already_exists(self, tmp_path):
        agent = AgentCreatorAgent()
        existing = tmp_path / "test-agent.json"
        existing.write_text("{}")
        with patch.object(agent, "get_agent_file_path", return_value=str(existing)):
            success, msg = agent.create_agent_json(VALID_CONFIG)
            assert success is False
            assert "already exists" in msg

    def test_create_agent_json_validation_error(self):
        success, msg = AgentCreatorAgent().create_agent_json({})
        assert success is False
        assert "Validation" in msg

    def test_create_agent_json_write_error(self):
        agent = AgentCreatorAgent()
        with patch.object(
            agent, "get_agent_file_path", return_value="/nonexistent/dir/test.json"
        ):
            success, msg = agent.create_agent_json(VALID_CONFIG)
            assert success is False
            assert "Failed" in msg
