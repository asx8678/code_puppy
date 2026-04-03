"""Tests for the Code Scout agent."""

import pytest

from code_puppy.agents.agent_code_scout import CodeScoutAgent
from code_puppy.agents.base_agent import BaseAgent


class TestCodeScoutAgent:
    """Test suite for CodeScoutAgent."""

    def test_agent_properties(self):
        """Test basic agent properties return correct values."""
        agent = CodeScoutAgent()

        assert agent.name == "code-scout"
        assert agent.display_name == "Code Scout 🔭"
        assert "deep codebase reconnaissance" in agent.description.lower()
        assert "turbo-executor" in agent.description.lower()
        assert "minimal llm turns" in agent.description.lower()

    def test_uses_config_based_model_pinning(self):
        """Test that the agent uses config-based model pinning (not hardcoded)."""
        # Agent should NOT override get_model_name - uses BaseAgent config-based pinning
        assert not hasattr(CodeScoutAgent, 'PINNED_MODEL')

    def test_available_tools_count(self):
        """Test that the agent has exactly 7 expected tools."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert len(tools) == 7

    def test_turbo_execute_is_first_tool(self):
        """Test that turbo_execute appears first (turbo-first ordering)."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert tools[0] == "turbo_execute"

    def test_invoke_agent_is_in_tools(self):
        """Test that invoke_agent is available for sub-agent delegation."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert "invoke_agent" in tools

    def test_turbo_execute_appears_before_individual_tools(self):
        """Test turbo-first ordering: turbo_execute and invoke_agent before individual tools."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        turbo_index = tools.index("turbo_execute")
        invoke_index = tools.index("invoke_agent")
        list_files_index = tools.index("list_files")
        read_file_index = tools.index("read_file")
        grep_index = tools.index("grep")

        # Both batch tools should come before individual file tools
        assert turbo_index < list_files_index
        assert turbo_index < read_file_index
        assert turbo_index < grep_index
        assert invoke_index < list_files_index
        assert invoke_index < read_file_index
        assert invoke_index < grep_index

    def test_all_expected_tools_present(self):
        """Test that all 7 expected tools are present."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        expected_tools = [
            "turbo_execute",
            "invoke_agent",
            "list_files",
            "read_file",
            "grep",
            "agent_run_shell_command",
            "agent_share_your_reasoning",
        ]

        for tool in expected_tools:
            assert tool in tools, f"Expected tool '{tool}' not found in available tools"

    def test_system_prompt_contains_turbo_first_principle(self):
        """Test that system prompt contains TURBO-FIRST PRINCIPLE heading."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "TURBO-FIRST PRINCIPLE" in prompt

    def test_system_prompt_contains_turbo_execute_usage(self):
        """Test that system prompt contains turbo_execute usage instructions."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "turbo_execute" in prompt.lower()
        assert "batch file operations" in prompt.lower()

    def test_system_prompt_contains_reconnaissance_protocol(self):
        """Test that system prompt contains Reconnaissance Protocol section."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Reconnaissance Protocol" in prompt

    def test_system_prompt_contains_all_four_phases(self):
        """Test that system prompt contains all 4 reconnaissance phases."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Phase 1: SURVEY" in prompt
        assert "Phase 2: DEEP READ" in prompt
        assert "Phase 3: TARGETED SEARCH" in prompt
        assert "Phase 4: SYNTHESIZE" in prompt

    def test_system_prompt_contains_turbo_execute_json_example(self):
        """Test that system prompt contains JSON plan example for turbo_execute."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert '"id": "scout-recon"' in prompt
        assert '"type": "list_files"' in prompt
        assert '"type": "grep"' in prompt
        assert '"type": "read_files"' in prompt
        assert '"operations":' in prompt

    def test_system_prompt_contains_invoke_agent_guidance(self):
        """Test that system prompt contains invoke_agent delegation guidance."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "invoke_agent" in prompt
        assert "Sub-Agent Delegation" in prompt
        assert "turbo-executor" in prompt

    def test_system_prompt_contains_rules_section(self):
        """Test that system prompt contains numbered rules."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "## Rules" in prompt
        assert "1. START with turbo_execute" in prompt
        assert "2. Batch aggressively" in prompt
        assert "3. Read whole files" in prompt
        assert "4. One turbo call per recon phase" in prompt
        assert "5. Synthesize at the end" in prompt

    def test_user_prompt_returns_scout_greeting(self):
        """Test that user prompt returns the scout greeting message."""
        agent = CodeScoutAgent()
        user_prompt = agent.get_user_prompt()

        assert user_prompt is not None
        assert "🔭 Code Scout ready for reconnaissance" in user_prompt
        assert "What do you want me to explore?" in user_prompt

    def test_base_agent_inheritance(self):
        """Test that CodeScoutAgent properly inherits from BaseAgent."""
        agent = CodeScoutAgent()
        assert isinstance(agent, BaseAgent)

    def test_agent_identity_consistency(self):
        """Test that agent identity properties are consistent with each other."""
        agent = CodeScoutAgent()

        # Name should be kebab-case
        assert "-" in agent.name
        assert agent.name.islower()

        # Display name should contain emoji and be more readable
        assert "🔭" in agent.display_name
        assert "Code Scout" in agent.display_name

        # Description should expand on the name
        assert "scout" in agent.description.lower() or "reconnaissance" in agent.description.lower()
