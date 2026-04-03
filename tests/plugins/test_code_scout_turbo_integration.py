"""Integration tests for Code Scout agent and Turbo Executor relationship.

Tests that verify the scout-turbo integration:
1. CodeScoutAgent is a proper BaseAgent subclass
2. turbo_execute and invoke_agent tools are available
3. Tool ordering prioritizes turbo-first approach
4. System prompt contains turbo integration guidance
5. No naming conflicts with turbo-executor
"""

from __future__ import annotations

import pytest

# Conditional skip based on whether CodeScoutAgent can be imported
try:
    from code_puppy.agents.agent_code_scout import CodeScoutAgent
    from code_puppy.agents.base_agent import BaseAgent
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False

requires_agent = pytest.mark.skipif(
    not HAS_AGENT,
    reason="CodeScoutAgent import failed (likely missing dependency)"
)


@requires_agent
class TestAutoDiscovery:
    """Test that CodeScoutAgent can be imported and discovered."""

    def test_code_scout_import(self):
        """Test that CodeScoutAgent can be imported from agent_code_scout."""
        assert CodeScoutAgent is not None

    def test_code_scout_instantiation(self):
        """Test that CodeScoutAgent can be instantiated."""
        agent = CodeScoutAgent()
        assert agent is not None


@requires_agent
class TestBaseAgentSubclass:
    """Test that CodeScoutAgent is a proper BaseAgent subclass."""

    def test_code_scout_is_base_agent_subclass(self):
        """Test that CodeScoutAgent inherits from BaseAgent."""
        assert issubclass(CodeScoutAgent, BaseAgent)

    def test_code_scout_instance_is_base_agent(self):
        """Test that CodeScoutAgent instance is a BaseAgent."""
        agent = CodeScoutAgent()
        assert isinstance(agent, BaseAgent)

    def test_code_scout_implements_required_properties(self):
        """Test that CodeScoutAgent implements required BaseAgent properties."""
        agent = CodeScoutAgent()

        # All BaseAgent subclasses must implement these
        assert hasattr(agent, "name")
        assert hasattr(agent, "display_name")
        assert hasattr(agent, "description")
        assert callable(getattr(agent, "get_system_prompt", None))
        assert callable(getattr(agent, "get_available_tools", None))

    def test_code_scout_properties_return_strings(self):
        """Test that CodeScoutAgent properties return proper types."""
        agent = CodeScoutAgent()

        assert isinstance(agent.name, str)
        assert isinstance(agent.display_name, str)
        assert isinstance(agent.description, str)
        assert isinstance(agent.get_system_prompt(), str)


@requires_agent
class TestTurboExecuteToolAvailability:
    """Test that turbo_execute tool is available to Code Scout."""

    def test_turbo_execute_in_available_tools(self):
        """Test that 'turbo_execute' is in the agent's available tools list."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert "turbo_execute" in tools

    def test_turbo_execute_is_first_tool(self):
        """Test that turbo_execute appears first in tools list."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert tools[0] == "turbo_execute"


@requires_agent
class TestInvokeAgentToolAvailability:
    """Test that invoke_agent tool is available to Code Scout."""

    def test_invoke_agent_in_available_tools(self):
        """Test that 'invoke_agent' is in the agent's available tools list."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert "invoke_agent" in tools

    def test_invoke_agent_is_second_tool(self):
        """Test that invoke_agent appears second in tools list (after turbo_execute)."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        assert tools[1] == "invoke_agent"


@requires_agent
class TestTurboFirstToolOrdering:
    """Test that turbo-first ordering is maintained in tools list."""

    def test_turbo_execute_before_list_files(self):
        """Test that turbo_execute appears before list_files."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        turbo_idx = tools.index("turbo_execute")
        list_files_idx = tools.index("list_files")

        assert turbo_idx < list_files_idx

    def test_turbo_execute_before_read_file(self):
        """Test that turbo_execute appears before read_file."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        turbo_idx = tools.index("turbo_execute")
        read_file_idx = tools.index("read_file")

        assert turbo_idx < read_file_idx

    def test_turbo_execute_before_grep(self):
        """Test that turbo_execute appears before grep."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        turbo_idx = tools.index("turbo_execute")
        grep_idx = tools.index("grep")

        assert turbo_idx < grep_idx

    def test_invoke_agent_before_individual_tools(self):
        """Test that invoke_agent appears before individual file tools."""
        agent = CodeScoutAgent()
        tools = agent.get_available_tools()

        invoke_idx = tools.index("invoke_agent")
        list_files_idx = tools.index("list_files")
        read_file_idx = tools.index("read_file")
        grep_idx = tools.index("grep")

        assert invoke_idx < list_files_idx
        assert invoke_idx < read_file_idx
        assert invoke_idx < grep_idx

    def test_tools_list_contains_all_expected_tools(self):
        """Test that tools list contains the complete set of expected tools."""
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


@requires_agent
class TestSystemPromptTurboIntegration:
    """Test that system prompt contains proper turbo integration guidance."""

    def test_prompt_mentions_turbo_execute_as_primary(self):
        """Test that prompt mentions turbo_execute as PRIMARY tool."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        # Should emphasize turbo_execute as primary
        assert "turbo_execute" in prompt
        assert "PRIMARY" in prompt.upper() or "primary" in prompt.lower()

    def test_prompt_contains_json_plan_example(self):
        """Test that prompt contains JSON plan example format."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        # Should show JSON plan structure
        assert '"operations"' in prompt or '"id"' in prompt
        assert "json" in prompt.lower() or "JSON" in prompt

    def test_prompt_contains_list_files_operation_type(self):
        """Test that JSON example contains list_files operation type."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert '"type": "list_files"' in prompt or "list_files" in prompt

    def test_prompt_contains_grep_operation_type(self):
        """Test that JSON example contains grep operation type."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert '"type": "grep"' in prompt or "grep" in prompt

    def test_prompt_contains_read_files_operation_type(self):
        """Test that JSON example contains read_files operation type."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert '"type": "read_files"' in prompt or "read_files" in prompt

    def test_prompt_contains_phase_1_survey(self):
        """Test that prompt contains Phase 1: SURVEY reconnaissance phase."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Phase 1" in prompt or "Phase 1: SURVEY" in prompt or "SURVEY" in prompt

    def test_prompt_contains_phase_2_deep_read(self):
        """Test that prompt contains Phase 2: DEEP READ reconnaissance phase."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Phase 2" in prompt or "Phase 2: DEEP READ" in prompt or "DEEP READ" in prompt

    def test_prompt_contains_phase_3_targeted_search(self):
        """Test that prompt contains Phase 3: TARGETED SEARCH reconnaissance phase."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Phase 3" in prompt or "Phase 3: TARGETED SEARCH" in prompt or "TARGETED SEARCH" in prompt

    def test_prompt_contains_phase_4_synthesize(self):
        """Test that prompt contains Phase 4: SYNTHESIZE reconnaissance phase."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Phase 4" in prompt or "Phase 4: SYNTHESIZE" in prompt or "SYNTHESIZE" in prompt

    def test_prompt_contains_sub_agent_delegation_section(self):
        """Test that prompt contains sub-agent delegation guidance."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Sub-Agent Delegation" in prompt or "sub-agent" in prompt.lower()
        assert "invoke_agent" in prompt
        assert "turbo-executor" in prompt


@requires_agent
class TestNoPluginConflicts:
    """Test that agent name doesn't conflict with turbo-executor."""

    def test_agent_name_is_code_scout(self):
        """Test that agent name is 'code-scout'."""
        agent = CodeScoutAgent()

        assert agent.name == "code-scout"

    def test_agent_name_not_turbo_executor(self):
        """Test that agent name is not 'turbo-executor'."""
        agent = CodeScoutAgent()

        assert agent.name != "turbo-executor"

    def test_agent_name_different_from_turbo_executor(self):
        """Test that agent name is distinct from turbo-executor name."""
        agent = CodeScoutAgent()

        # Names should be completely different
        assert "turbo" not in agent.name.lower()
        assert "executor" not in agent.name.lower()

    def test_display_name_contains_scout(self):
        """Test that display name indicates scouting functionality."""
        agent = CodeScoutAgent()

        assert "Scout" in agent.display_name or "scout" in agent.display_name.lower()

    def test_description_mentions_turbo_integration(self):
        """Test that description mentions turbo-executor integration."""
        agent = CodeScoutAgent()

        assert "turbo" in agent.description.lower() or "turbo-executor" in agent.description


@requires_agent
class TestAgentIdentity:
    """Test Code Scout agent identity and metadata."""

    def test_display_name_is_code_scout_emoji(self):
        """Test that display name is 'Code Scout 🔭'."""
        agent = CodeScoutAgent()

        assert agent.display_name == "Code Scout 🔭"

    def test_description_mentions_reconnaissance(self):
        """Test that description mentions reconnaissance."""
        agent = CodeScoutAgent()

        assert "reconnaissance" in agent.description.lower()

    def test_description_mentions_minimal_llm_turns(self):
        """Test that description mentions minimal LLM turns efficiency."""
        agent = CodeScoutAgent()

        assert "minimal LLM turns" in agent.description or "efficient" in agent.description.lower()

    def test_has_user_prompt(self):
        """Test that agent provides a user prompt/greeting."""
        agent = CodeScoutAgent()
        user_prompt = agent.get_user_prompt()

        assert user_prompt is not None
        assert isinstance(user_prompt, str)
        assert len(user_prompt) > 0

    def test_user_prompt_contains_scout_emoji(self):
        """Test that user prompt contains scout emoji."""
        agent = CodeScoutAgent()
        user_prompt = agent.get_user_prompt()

        assert "🔭" in user_prompt


@requires_agent
class TestTurboFirstPrinciple:
    """Test that turbo-first principle is emphasized in system prompt."""

    def test_prompt_contains_turbo_first_header(self):
        """Test that prompt has 'TURBO-FIRST PRINCIPLE' section header."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "TURBO-FIRST" in prompt or "turbo-first" in prompt.lower()

    def test_prompt_contains_always_use_turbo_execute(self):
        """Test that prompt says when to ALWAYS use turbo_execute."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "ALWAYS use turbo_execute" in prompt or "always use turbo_execute" in prompt.lower()

    def test_prompt_contains_only_use_individual_tools(self):
        """Test that prompt explains when to only use individual tools."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Only use individual tools" in prompt or "only use individual" in prompt.lower()


@requires_agent
class TestReconnaissanceProtocol:
    """Test that reconnaissance protocol is properly documented."""

    def test_prompt_contains_reconnaissance_protocol_header(self):
        """Test that prompt has 'Reconnaissance Protocol' section."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "Reconnaissance Protocol" in prompt

    def test_prompt_contains_turbo_execute_usage_section(self):
        """Test that prompt explains turbo_execute usage."""
        agent = CodeScoutAgent()
        prompt = agent.get_system_prompt()

        assert "turbo_execute Usage" in prompt or "Usage" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
