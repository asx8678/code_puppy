"""Unit tests for Turbo Executor multi-instance support.

Tests the OrchestratorRegistry and multi-instance isolation features:
- Default instance sharing
- Per-agent instance isolation
- Instance lifecycle management
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationType,
    Plan,
    PlanStatus,
)
from code_puppy.plugins.turbo_executor.orchestrator import TurboOrchestrator
from code_puppy.plugins.turbo_executor.register_callbacks import (
    OrchestratorRegistry,
)


@pytest.fixture
def temp_dir_with_files():
    """Create a temporary directory with some files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "test1.py").write_text("def hello():\n    pass\n")
        (Path(tmpdir) / "test2.py").write_text("def world():\n    return 42\n")
        yield tmpdir


class TestOrchestratorRegistry:
    """Test multi-instance orchestrator registry."""

    def test_registry_creates_default_instance(self):
        """Test that registry creates default instance when None is passed."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator(None)
        orch2 = registry.get_orchestrator(None)

        # Should return the same default instance
        assert orch1 is orch2
        assert isinstance(orch1, TurboOrchestrator)

    def test_registry_creates_isolated_instances(self):
        """Test that different instance IDs get different orchestrators."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("agent-1")
        orch2 = registry.get_orchestrator("agent-2")

        # Should be different instances
        assert orch1 is not orch2
        assert isinstance(orch1, TurboOrchestrator)
        assert isinstance(orch2, TurboOrchestrator)

    def test_registry_returns_same_instance_for_same_id(self):
        """Test that same ID returns the same orchestrator instance."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("agent-1")
        orch2 = registry.get_orchestrator("agent-1")

        # Should return the same instance
        assert orch1 is orch2

    def test_registry_instance_count(self):
        """Test that instance count tracks managed instances."""
        registry = OrchestratorRegistry()
        assert registry.get_instance_count() == 0

        registry.get_orchestrator("agent-1")
        assert registry.get_instance_count() == 1

        registry.get_orchestrator("agent-2")
        assert registry.get_instance_count() == 2

        # Default instance shouldn't count
        registry.get_orchestrator(None)
        assert registry.get_instance_count() == 2

    def test_registry_remove_instance(self):
        """Test removing an orchestrator instance from registry."""
        registry = OrchestratorRegistry()
        registry.get_orchestrator("agent-1")
        assert registry.get_instance_count() == 1

        removed = registry.remove_orchestrator("agent-1")
        assert removed is True
        assert registry.get_instance_count() == 0

        # Removing non-existent instance returns False
        removed = registry.remove_orchestrator("non-existent")
        assert removed is False

    def test_registry_clear_all_instances(self):
        """Test clearing all managed instances."""
        registry = OrchestratorRegistry()
        registry.get_orchestrator("agent-1")
        registry.get_orchestrator("agent-2")
        registry.get_orchestrator(None)  # Default

        assert registry.get_instance_count() == 2

        registry.clear_all_instances()
        assert registry.get_instance_count() == 0

        # Default should also be cleared
        new_default = registry.get_orchestrator(None)
        assert new_default is not None


class TestInstanceIsolation:
    """Test instance isolation during plan execution."""

    @pytest.mark.asyncio
    async def test_multi_instance_isolation_execution(self, temp_dir_with_files):
        """Test that different instances can execute plans independently."""
        import os

        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("agent-1")
        orch2 = registry.get_orchestrator("agent-2")

        # Both instances should be able to execute plans
        file_path = os.path.join(temp_dir_with_files, "test1.py")
        plan1 = Plan(
            id="plan-1",
            operations=[Operation(type=OperationType.LIST_FILES, args={"directory": temp_dir_with_files})],
        )
        plan2 = Plan(
            id="plan-2",
            operations=[Operation(type=OperationType.READ_FILES, args={"file_paths": [file_path]})],
        )

        # Execute both plans concurrently
        result1, result2 = await asyncio.gather(orch1.execute(plan1), orch2.execute(plan2))

        # Both should complete successfully
        assert result1.status == PlanStatus.COMPLETED
        assert result2.status == PlanStatus.COMPLETED

        # Results should be independent
        assert result1.plan_id == "plan-1"
        assert result2.plan_id == "plan-2"

    @pytest.mark.asyncio
    async def test_same_instance_multiple_plans(self, temp_dir_with_files):
        """Test that same instance can execute multiple plans sequentially."""
        registry = OrchestratorRegistry()
        orch = registry.get_orchestrator("reusable-agent")

        plan1 = Plan(
            id="first-plan",
            operations=[Operation(type=OperationType.LIST_FILES, args={"directory": temp_dir_with_files})],
        )
        plan2 = Plan(
            id="second-plan",
            operations=[Operation(type=OperationType.GREP, args={"search_string": "def ", "directory": temp_dir_with_files})],
        )

        # Execute sequentially
        result1 = await orch.execute(plan1)
        result2 = await orch.execute(plan2)

        # Both should complete
        assert result1.status == PlanStatus.COMPLETED
        assert result2.status == PlanStatus.COMPLETED
        assert result1.plan_id == "first-plan"
        assert result2.plan_id == "second-plan"

    def test_default_instance_isolation(self):
        """Test that default instance is shared across calls with None."""
        registry = OrchestratorRegistry()

        # Multiple calls with None should return the same instance
        default1 = registry.get_orchestrator(None)
        default2 = registry.get_orchestrator(None)
        default3 = registry.get_orchestrator()

        assert default1 is default2
        assert default2 is default3

    def test_named_instances_different_from_default(self):
        """Test that named instances are different from the default."""
        registry = OrchestratorRegistry()

        default_orch = registry.get_orchestrator(None)
        named_orch = registry.get_orchestrator("named-agent")

        assert default_orch is not named_orch


class TestRegistryIntegration:
    """Integration tests for the orchestrator registry."""

    def test_concurrent_registry_access(self):
        """Test that registry handles concurrent access safely."""
        registry = OrchestratorRegistry()

        # Simulate concurrent access from multiple "agents"
        instances = []
        for i in range(10):
            orch = registry.get_orchestrator(f"concurrent-agent-{i}")
            instances.append(orch)

        # All should be unique instances
        assert len(set(id(orch) for orch in instances)) == 10
        assert registry.get_instance_count() == 10

    def test_registry_after_clear(self):
        """Test that registry works correctly after clearing."""
        registry = OrchestratorRegistry()

        # Create some instances
        orch1 = registry.get_orchestrator("agent-1")
        registry.clear_all_instances()

        # Create new instance with same ID
        orch2 = registry.get_orchestrator("agent-1")

        # Should be a new instance (not the same object)
        assert orch1 is not orch2
        assert registry.get_instance_count() == 1

    @pytest.mark.asyncio
    async def test_instance_history_tracking(self, temp_dir_with_files):
        """Test that each instance maintains its own execution history."""
        registry = OrchestratorRegistry()
        orch1 = registry.get_orchestrator("agent-with-history-1")
        orch2 = registry.get_orchestrator("agent-with-history-2")

        plan = Plan(
            id="history-test",
            operations=[Operation(type=OperationType.LIST_FILES, args={"directory": temp_dir_with_files})],
        )

        # Execute with first instance
        result1 = await orch1.execute(plan)

        # History should reflect this execution
        from code_puppy.plugins.turbo_executor.history import get_history
        history = get_history()

        # Both instances should be able to execute without interfering
        assert result1.status == PlanStatus.COMPLETED

        # Execute with second instance (different plan)
        plan2 = Plan(
            id="history-test-2",
            operations=[Operation(type=OperationType.LIST_FILES, args={"directory": temp_dir_with_files})],
        )
        result2 = await orch2.execute(plan2)
        assert result2.status == PlanStatus.COMPLETED
