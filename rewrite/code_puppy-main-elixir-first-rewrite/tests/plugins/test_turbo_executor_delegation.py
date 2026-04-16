"""Tests for Turbo Executor agent delegation patterns.

Tests that agents can properly delegate batch file operations to the
turbo-executor agent via invoke_agent and the load_prompt callback.
"""

import pytest


class TestDelegationPrompt:
    """Test that delegation guidance is added to agent prompts."""

    def test_load_turbo_prompt_returns_guidance(self):
        """Test that _load_turbo_prompt returns delegation guidance."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should contain delegation guidance
        assert "Turbo Executor Delegation" in prompt
        assert "turbo-executor" in prompt
        assert "invoke_agent" in prompt

    def test_prompt_contains_when_to_delegate(self):
        """Test that prompt explains when to delegate."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "When to Delegate" in prompt
        assert "Exploring large codebases" in prompt
        assert "Reading many files" in prompt

    def test_prompt_contains_how_to_delegate(self):
        """Test that prompt explains how to delegate."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "How to Delegate" in prompt
        assert "invoke_agent" in prompt
        assert "turbo-executor" in prompt

    def test_prompt_contains_options(self):
        """Test that prompt explains two delegation options."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "Two Options for Batch Operations" in prompt
        assert "Option 1" in prompt
        assert "Option 2" in prompt
        assert "turbo_execute" in prompt

    def test_prompt_contains_scenarios(self):
        """Test that prompt contains example scenarios."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "Example Delegation Scenarios" in prompt
        assert "Scenario 1" in prompt
        assert "Scenario 2" in prompt

    def test_prompt_contains_remember_section(self):
        """Test that prompt has a remember section with thresholds."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "Remember" in prompt
        assert "Small tasks" in prompt
        assert "Medium tasks" in prompt
        assert "Large tasks" in prompt


class TestAgentRegistration:
    """Test that turbo-executor agent is registered."""

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_register_turbo_agents_returns_agent(self):
        """Test that _register_turbo_agents returns the agent definition."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _register_turbo_agents,
        )

        agents = _register_turbo_agents()

        assert len(agents) == 1
        assert agents[0]["name"] == "turbo-executor"
        assert "class" in agents[0]

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_registered_agent_is_turbo_executor_class(self):
        """Test that registered agent class is TurboExecutorAgent."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _register_turbo_agents,
        )

        agents = _register_turbo_agents()

        assert agents[0]["class"] is TurboExecutorAgent


class TestTurboExecutorAgent:
    """Test TurboExecutorAgent is invokable via delegate patterns."""

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_name(self):
        """Test that turbo-executor agent has correct name."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        assert agent.name == "turbo-executor"

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_display_name(self):
        """Test that turbo-executor agent has display name."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        assert "Turbo" in agent.display_name
        assert "🚀" in agent.display_name

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_description(self):
        """Test that turbo-executor agent has description."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        assert "batch" in agent.description.lower() or "1M" in agent.description

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_system_prompt(self):
        """Test that turbo-executor agent has a system prompt."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        prompt = agent.get_system_prompt()
        assert len(prompt) > 0
        assert "Turbo" in prompt or "batch" in prompt.lower()

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_file_tools(self):
        """Test that turbo-executor agent has file operation tools."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        tools = agent.get_available_tools()

        assert "list_files" in tools
        assert "read_file" in tools
        assert "grep" in tools

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_turbo_executor_agent_has_planning_tools(self):
        """Test that turbo-executor agent has planning tools."""
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        agent = TurboExecutorAgent()
        tools = agent.get_available_tools()

        assert "agent_share_your_reasoning" in tools


class TestDelegationIntegration:
    """Test integration between callbacks and agent system."""

    def test_callback_imports(self):
        """Test that all callback functions can be imported."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _custom_help,
            _get_orchestrator,
            _handle_turbo_command,
            _load_turbo_prompt,
            _on_startup,
            _register_turbo_agents,
            _register_turbo_execute_tool,
            _register_turbo_tools,
        )

        assert callable(_on_startup)
        assert callable(_get_orchestrator)
        assert callable(_custom_help)
        assert callable(_handle_turbo_command)
        assert callable(_register_turbo_tools)
        assert callable(_register_turbo_execute_tool)
        assert callable(_load_turbo_prompt)
        assert callable(_register_turbo_agents)

    def test_prompt_callback_returns_string(self):
        """Test that load_prompt callback returns a string."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        result = _load_turbo_prompt()
        assert isinstance(result, str)
        assert len(result) > 100  # Should be substantial content

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_agent_registration_callback_returns_list(self):
        """Test that register_agents callback returns a list."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _register_turbo_agents,
        )

        result = _register_turbo_agents()
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.skip(reason="Requires mcp package to be installed")
    def test_agent_registration_has_required_fields(self):
        """Test that agent registration has required fields."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _register_turbo_agents,
        )

        agents = _register_turbo_agents()
        agent_def = agents[0]

        assert "name" in agent_def
        assert "class" in agent_def
        assert agent_def["name"] == "turbo-executor"


class TestDelegationThresholds:
    """Test that delegation thresholds are clear in the prompt."""

    def test_small_task_threshold(self):
        """Test that small task threshold is documented."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention < 5 file operations for small tasks
        assert "< 5" in prompt or "small" in prompt.lower()

    def test_medium_task_threshold(self):
        """Test that medium task threshold is documented."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention 5-10 operations for medium tasks
        assert "5-10" in prompt or "medium" in prompt.lower()

    def test_large_task_threshold(self):
        """Test that large task threshold is documented."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention > 10 operations for large tasks
        assert "> 10" in prompt or "large" in prompt.lower()

    def test_1m_context_window_mentioned(self):
        """Test that 1M context window is mentioned."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention the 1M context window
        assert "1M" in prompt or "1 Million" in prompt


class TestDelegationExamples:
    """Test that delegation examples are practical."""

    def test_example_contains_invoke_agent(self):
        """Test that examples show invoke_agent usage."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should have code examples with invoke_agent
        assert "invoke_agent(" in prompt
        assert "turbo-executor" in prompt

    def test_example_shows_session_id(self):
        """Test that examples show session_id usage."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should show session_id parameter
        assert "session_id=" in prompt or "session_id" in prompt

    def test_scenario_1_mentions_codebase_exploration(self):
        """Test that scenario 1 is about codebase exploration."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention exploring codebases
        assert "codebase" in prompt.lower() or "exploring" in prompt.lower()

    def test_scenario_2_mentions_refactoring(self):
        """Test that scenario 2 is about refactoring."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should mention refactoring
        assert "refactoring" in prompt.lower() or "deprecated" in prompt.lower()


class TestCallbackRegistration:
    """Test that callbacks are properly registered."""

    def test_all_callbacks_registered(self):
        """Test that all necessary callbacks are registered."""
        # Note: Callbacks are registered at module import time
        # We verify the functions exist and are callable
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _custom_help,
            _handle_turbo_command,
            _load_turbo_prompt,
            _on_startup,
            _register_turbo_agents,
            _register_turbo_tools,
        )

        assert callable(_on_startup)
        assert callable(_custom_help)
        assert callable(_handle_turbo_command)
        assert callable(_register_turbo_tools)
        assert callable(_load_turbo_prompt)
        assert callable(_register_turbo_agents)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
