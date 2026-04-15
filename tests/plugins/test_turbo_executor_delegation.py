"""Tests for Turbo Executor agent delegation patterns.

Tests that agents can properly delegate batch file operations to the
turbo-executor agent via invoke_agent and the load_prompt callback.
"""

import pytest


class TestDelegationPrompt:
    """Test that a brief delegation hint is added to agent prompts."""

    def test_load_turbo_prompt_returns_hint(self):
        """Test that _load_turbo_prompt returns a brief hint."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "Turbo Executor" in prompt
        assert "turbo-executor" in prompt
        assert "invoke_agent" in prompt
        assert "turbo_execute" in prompt

    def test_prompt_is_concise(self):
        """Test that prompt is concise (not the old 60+ line block)."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should be under 300 chars (was 2000+ before compression)
        assert len(prompt) < 300
        assert "batch file ops" in prompt.lower()

    def test_prompt_references_help(self):
        """Test that prompt references /turbo help for details."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "/turbo help" in prompt

    def test_prompt_contains_both_invocation_methods(self):
        """Test that prompt mentions both invoke_agent and turbo_execute."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        assert "invoke_agent" in prompt
        assert "turbo_execute" in prompt


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
        assert len(result) > 50  # Brief hint, not massive block

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
    """Test that delegation threshold is mentioned in the prompt."""

    def test_delegation_threshold_mentioned(self):
        """Test that the >5 file threshold is mentioned."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()
        assert ">5 files" in prompt or ">5" in prompt


class TestDelegationExamples:
    """Test that the prompt reference is practical."""

    def test_prompt_mentions_invoke_agent(self):
        """Test that prompt shows invoke_agent usage."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _load_turbo_prompt,
        )

        prompt = _load_turbo_prompt()

        # Should reference invoke_agent
        assert "invoke_agent(" in prompt
        assert "turbo-executor" in prompt


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
