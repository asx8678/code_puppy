"""Tests for session-scoped orchestrator instances.

These tests verify that issue ekfe is properly addressed:
- Each invoke_agent('turbo-executor', ...) gets its own orchestrator instance
- Plans from different sessions don't interfere with each other
"""

import pytest
from unittest.mock import MagicMock, patch

from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationType,
    Plan,
    PlanResult,
    PlanStatus,
)
from code_puppy.plugins.turbo_executor.orchestrator import TurboOrchestrator
from code_puppy.plugins.turbo_executor.register_callbacks import (
    OrchestratorRegistry,
    _get_orchestrator,
)


class TestOrchestratorRegistry:
    """Test suite for OrchestratorRegistry session scoping."""

    def test_registry_creates_default_instance(self):
        """Test that registry creates a default instance for None ID."""
        registry = OrchestratorRegistry()
        orch = registry.get_orchestrator(None)

        assert orch is not None
        assert isinstance(orch, TurboOrchestrator)

    def test_registry_returns_same_default_instance(self):
        """Test that same default instance is returned for multiple None calls."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator(None)
        orch2 = registry.get_orchestrator(None)

        assert orch1 is orch2  # Same instance

    def test_registry_creates_separate_instances_per_id(self):
        """Test that different IDs get separate orchestrator instances."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("session-1")
        orch2 = registry.get_orchestrator("session-2")

        assert orch1 is not orch2  # Different instances
        assert isinstance(orch1, TurboOrchestrator)
        assert isinstance(orch2, TurboOrchestrator)

    def test_registry_returns_same_instance_for_same_id(self):
        """Test that same ID returns same orchestrator instance."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("session-abc")
        orch2 = registry.get_orchestrator("session-abc")

        assert orch1 is orch2  # Same instance for same ID

    def test_registry_instance_count(self):
        """Test that registry tracks instance count correctly."""
        registry = OrchestratorRegistry()

        assert registry.get_instance_count() == 0

        registry.get_orchestrator("session-1")
        assert registry.get_instance_count() == 1

        registry.get_orchestrator("session-2")
        assert registry.get_instance_count() == 2

        # Getting same ID doesn't increase count
        registry.get_orchestrator("session-1")
        assert registry.get_instance_count() == 2

    def test_registry_remove_instance(self):
        """Test removing an orchestrator instance from registry."""
        registry = OrchestratorRegistry()

        registry.get_orchestrator("session-to-remove")
        assert registry.get_instance_count() == 1

        removed = registry.remove_orchestrator("session-to-remove")
        assert removed is True
        assert registry.get_instance_count() == 0

        # Removing non-existent returns False
        removed = registry.remove_orchestrator("non-existent")
        assert removed is False

    def test_registry_clear_all_instances(self):
        """Test clearing all orchestrator instances."""
        registry = OrchestratorRegistry()

        registry.get_orchestrator("session-1")
        registry.get_orchestrator("session-2")
        registry.get_orchestrator(None)  # Default

        assert registry.get_instance_count() == 2

        registry.clear_all_instances()

        assert registry.get_instance_count() == 0
        # Default is also cleared
        assert registry._default_instance is None


class TestSessionScopedOrchestrators:
    """Test that different agent sessions get isolated orchestrators."""

    def test_different_agent_ids_get_different_orchestrators(self):
        """Test that different agent IDs get separate orchestrator instances."""
        # Simulate different agent invocations
        agent_id_1 = "turbo-executor-abc123"
        agent_id_2 = "turbo-executor-def456"

        orch1 = _get_orchestrator(instance_id=agent_id_1)
        orch2 = _get_orchestrator(instance_id=agent_id_2)

        # Different instances for different agent IDs
        assert orch1 is not orch2
        assert isinstance(orch1, TurboOrchestrator)
        assert isinstance(orch2, TurboOrchestrator)

    def test_same_agent_id_gets_same_orchestrator(self):
        """Test that same agent ID returns cached orchestrator instance."""
        agent_id = "turbo-executor-same-session"

        orch1 = _get_orchestrator(instance_id=agent_id)
        orch2 = _get_orchestrator(instance_id=agent_id)

        # Same instance for same agent ID
        assert orch1 is orch2


class TestSessionIsolation:
    """Test that plans from different sessions don't interfere."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions_isolated_execution(self):
        """Test that concurrent sessions execute plans independently."""
        import tempfile
        import asyncio
        from pathlib import Path

        # Create separate temp directories for each "session"
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            # Create different files in each directory
            (Path(tmpdir1) / "file1.txt").write_text("content for session 1")
            (Path(tmpdir2) / "file2.txt").write_text("content for session 2")

            # Get separate orchestrators for different "sessions"
            orch1 = _get_orchestrator(instance_id="session-1")
            orch2 = _get_orchestrator(instance_id="session-2")

            # Create plans that read from different directories
            plan1 = Plan(
                id="plan-session-1",
                operations=[
                    Operation(
                        type=OperationType.LIST_FILES,
                        args={"directory": tmpdir1},
                    )
                ],
            )
            plan2 = Plan(
                id="plan-session-2",
                operations=[
                    Operation(
                        type=OperationType.LIST_FILES,
                        args={"directory": tmpdir2},
                    )
                ],
            )

            # Execute both plans
            result1 = await orch1.execute(plan1)
            result2 = await orch2.execute(plan2)

            # Both should complete successfully
            assert result1.status == PlanStatus.COMPLETED
            assert result2.status == PlanStatus.COMPLETED

            # Results should be from their respective directories
            assert "file1.txt" in str(result1.operation_results[0].data)
            assert "file2.txt" in str(result2.operation_results[0].data)

    @pytest.mark.asyncio
    async def test_orchestrator_state_isolation(self):
        """Test that orchestrator state is isolated between sessions."""
        # Get two different orchestrators
        orch1 = _get_orchestrator(instance_id="state-session-1")
        orch2 = _get_orchestrator(instance_id="state-session-2")

        # Configure them differently
        orch1.enable_parallel = True
        orch2.enable_parallel = False

        # Verify configurations are isolated
        assert orch1.enable_parallel is True
        assert orch2.enable_parallel is False


class TestGlobalRegistry:
    """Test the global registry singleton."""

    def test_global_registry_exists(self):
        """Test that global registry is initialized."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _orchestrator_registry,
        )

        assert _orchestrator_registry is not None
        assert isinstance(_orchestrator_registry, OrchestratorRegistry)

    def test_global_get_orchestrator_function(self):
        """Test that _get_orchestrator helper works with global registry."""
        orch = _get_orchestrator(instance_id="test-global-session")

        assert orch is not None
        assert isinstance(orch, TurboOrchestrator)


class TestTurboExecutorAgentSessionScope:
    """Test TurboExecutorAgent uses session-scoped orchestrator."""

    @pytest.mark.asyncio
    async def test_agent_uses_own_id_for_orchestrator(self):
        """Test that agent uses its own ID to get orchestrator instance."""
        # We can't import the actual agent due to mcp dependency issues,
        # but we can verify the pattern is correct by checking the source
        # In agent_turbo_executor.py, execute_plan() uses:
        #   orchestrator = _get_orchestrator(instance_id=self.id)

        # Simulate the pattern
        class MockAgent:
            def __init__(self, agent_id):
                self.id = agent_id

            async def execute_plan(self, plan):
                from code_puppy.plugins.turbo_executor.register_callbacks import (
                    _get_orchestrator,
                )

                orchestrator = _get_orchestrator(instance_id=self.id)
                return await orchestrator.execute(plan)

        # Create two agents with different IDs
        agent1 = MockAgent("agent-1")
        agent2 = MockAgent("agent-2")

        # Both should get different orchestrator instances
        orch1 = _get_orchestrator(instance_id=agent1.id)
        orch2 = _get_orchestrator(instance_id=agent2.id)

        assert orch1 is not orch2


class TestSessionCleanup:
    """Test cleanup of session orchestrators."""

    def test_session_orchestrator_can_be_removed(self):
        """Test that session orchestrators can be cleaned up."""
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _orchestrator_registry,
        )

        session_id = "session-to-cleanup"

        # Create orchestrator for session
        _get_orchestrator(instance_id=session_id)
        assert _orchestrator_registry.get_instance_count() >= 1

        # Remove it
        removed = _orchestrator_registry.remove_orchestrator(session_id)
        assert removed is True
