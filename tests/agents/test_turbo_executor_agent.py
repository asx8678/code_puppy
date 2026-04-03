"""Tests for the Turbo Executor agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent
from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationType,
    Plan,
    PlanResult,
    PlanStatus,
)


class TestTurboExecutorAgent:
    """Test suite for TurboExecutorAgent."""

    def test_agent_properties(self):
        """Test basic agent properties."""
        agent = TurboExecutorAgent()

        assert agent.name == "turbo-executor"
        assert agent.display_name == "Turbo Executor 🚀"
        assert "batch file operations" in agent.description.lower()
        assert "1m context" in agent.description.lower()

    def test_uses_config_based_model_pinning(self):
        """Test that the agent uses config-based model pinning (not hardcoded)."""
        # Agent should NOT override get_model_name - uses BaseAgent config-based pinning
        assert not hasattr(TurboExecutorAgent, 'PINNED_MODEL')

    def test_available_tools(self):
        """Test that the agent has the expected tools."""
        agent = TurboExecutorAgent()
        tools = agent.get_available_tools()

        expected_tools = [
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "agent_run_shell_command",
            "agent_share_your_reasoning",
        ]

        for tool in expected_tools:
            assert tool in tools

    def test_system_prompt(self):
        """Test that the system prompt is defined and contains key phrases."""
        agent = TurboExecutorAgent()
        prompt = agent.get_system_prompt()

        assert "Turbo Executor" in prompt
        assert "batch file operations" in prompt.lower()
        assert "1M context" in prompt
        assert "list_files" in prompt
        assert "grep" in prompt
        assert "read_files" in prompt or "read files" in prompt.lower()

    def test_create_plan(self):
        """Test creating a plan from operation specifications."""
        agent = TurboExecutorAgent()

        operations = [
            {
                "type": "list_files",
                "args": {"directory": ".", "recursive": True},
                "priority": 10,
                "id": "op1",
            },
            {
                "type": "grep",
                "args": {"search_string": "def ", "directory": "."},
                "priority": 20,
                "id": "op2",
            },
        ]

        plan = agent.create_plan("test-plan", operations, max_parallel=2)

        assert plan.id == "test-plan"
        assert len(plan.operations) == 2
        assert plan.max_parallel == 2

        # Check first operation
        assert plan.operations[0].type == OperationType.LIST_FILES
        assert plan.operations[0].args["directory"] == "."
        assert plan.operations[0].priority == 10
        assert plan.operations[0].id == "op1"

        # Check second operation
        assert plan.operations[1].type == OperationType.GREP
        assert plan.operations[1].args["search_string"] == "def "
        assert plan.operations[1].priority == 20
        assert plan.operations[1].id == "op2"

    def test_create_plan_with_defaults(self):
        """Test creating a plan with default values."""
        agent = TurboExecutorAgent()

        operations = [{"type": "list_files", "args": {}}]
        plan = agent.create_plan("simple-plan", operations)

        assert plan.id == "simple-plan"
        assert len(plan.operations) == 1
        assert plan.operations[0].priority == 100  # Default priority
        assert plan.operations[0].id is None  # No ID by default
        assert plan.max_parallel == 1  # Default max_parallel

    @pytest.mark.asyncio
    async def test_execute_plan(self):
        """Test executing a plan delegates to orchestrator."""
        agent = TurboExecutorAgent()

        # Create a mock plan
        plan = Plan(
            id="test-plan",
            operations=[
                Operation(type=OperationType.LIST_FILES, args={"directory": "."})
            ],
        )

        # Mock the orchestrator
        mock_result = PlanResult(
            plan_id="test-plan",
            status=PlanStatus.COMPLETED,
            operation_results=[],
            total_duration_ms=100.0,
        )

        with patch(
            "code_puppy.agents.agent_turbo_executor.TurboOrchestrator"
        ) as mock_orchestrator_class:
            mock_orchestrator = MagicMock()
            mock_orchestrator.execute = AsyncMock(return_value=mock_result)
            mock_orchestrator_class.return_value = mock_orchestrator

            result = await agent.execute_plan(plan)

            assert result == mock_result
            mock_orchestrator.execute.assert_called_once_with(plan)

    def test_summarize_result(self):
        """Test summarizing plan results."""
        agent = TurboExecutorAgent()

        plan_result = PlanResult(
            plan_id="test-plan",
            status=PlanStatus.COMPLETED,
            operation_results=[],
            total_duration_ms=150.0,
            metadata={"total_operations": 3, "successful_operations": 3},
        )

        with patch(
            "code_puppy.agents.agent_turbo_executor.summarize_plan_result"
        ) as mock_summarize:
            mock_summarize.return_value = "## Summary\n\nPlan completed successfully!"

            summary = agent.summarize_result(plan_result, include_details=True)

            mock_summarize.assert_called_once_with(
                plan_result, include_operation_details=True
            )
            assert summary == "## Summary\n\nPlan completed successfully!"

    def test_quick_status(self):
        """Test quick status generation."""
        agent = TurboExecutorAgent()

        plan_result = PlanResult(
            plan_id="test-plan",
            status=PlanStatus.COMPLETED,
            operation_results=[],
            total_duration_ms=200.0,
        )

        with patch(
            "code_puppy.agents.agent_turbo_executor.quick_summary"
        ) as mock_quick:
            mock_quick.return_value = "✅ Plan 'test-plan': 5/5 ops, 200ms"

            status = agent.quick_status(plan_result)

            mock_quick.assert_called_once_with(plan_result)
            assert status == "✅ Plan 'test-plan': 5/5 ops, 200ms"

    def test_agent_inheritance(self):
        """Test that TurboExecutorAgent properly inherits from BaseAgent."""
        from code_puppy.agents.base_agent import BaseAgent

        agent = TurboExecutorAgent()
        assert isinstance(agent, BaseAgent)

    def test_all_operation_types_supported(self):
        """Test that all operation types can be used in plans."""
        agent = TurboExecutorAgent()

        operations = [
            {"type": "list_files", "args": {"directory": "."}},
            {"type": "grep", "args": {"search_string": "test", "directory": "."}},
            {"type": "read_files", "args": {"file_paths": ["test.py"]}},
        ]

        plan = agent.create_plan("full-test", operations)

        assert plan.operations[0].type == OperationType.LIST_FILES
        assert plan.operations[1].type == OperationType.GREP
        assert plan.operations[2].type == OperationType.READ_FILES


class TestTurboExecutorAgentIntegration:
    """Integration-style tests for TurboExecutorAgent."""

    def test_end_to_end_plan_creation(self):
        """Test creating a complex plan end-to-end."""
        agent = TurboExecutorAgent()

        # Simulate a real-world batch exploration task
        operations = [
            {
                "type": "list_files",
                "args": {"directory": "src", "recursive": True},
                "priority": 1,
                "id": "discover",
            },
            {
                "type": "grep",
                "args": {"search_string": "class.*Agent", "directory": "src"},
                "priority": 10,
                "id": "find_agents",
            },
            {
                "type": "read_files",
                "args": {"file_paths": ["src/agent.py", "src/base.py"]},
                "priority": 20,
                "id": "read_sources",
            },
        ]

        plan = agent.create_plan("explore-agents", operations, max_parallel=3)

        assert plan.id == "explore-agents"
        assert len(plan.operations) == 3
        assert plan.max_parallel == 3

        # Verify operations are sorted by priority
        priorities = [op.priority for op in plan.operations]
        assert priorities == sorted(priorities)
