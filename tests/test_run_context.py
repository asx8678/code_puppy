"""Tests for run_context module."""

import asyncio
from dataclasses import fields

import pytest

from code_puppy.run_context import (
    RunContext,
    RunContextManager,
    create_root_run_context,
    get_current_run_context,
    reset_run_context,
    set_current_run_context,
)


class TestRunContext:
    """Test RunContext dataclass functionality."""

    def test_create_basic_context(self):
        """Test creating a basic RunContext."""
        ctx = RunContext(
            run_id="test-123",
            component_type="agent",
            component_name="test_agent",
        )
        
        assert ctx.run_id == "test-123"
        assert ctx.component_type == "agent"
        assert ctx.component_name == "test_agent"
        assert ctx.parent_run_id is None
        assert ctx.success is None
        assert ctx.end_time is None

    def test_create_child_context(self):
        """Test creating child context from parent."""
        parent = RunContext(
            run_id="parent-123",
            component_type="agent",
            component_name="parent_agent",
            session_id="session-abc",
            tags=["important"],
        )
        
        child = RunContext.create_child(
            parent,
            component_type="tool",
            component_name="read_file",
        )
        
        assert child.parent_run_id == "parent-123"
        assert child.session_id == "session-abc"
        assert "important" in child.tags  # Inherits tags
        assert child.component_type == "tool"
        assert child.component_name == "read_file"
        assert child.run_id != parent.run_id  # Different IDs

    def test_end_context_success(self):
        """Test ending context with success."""
        ctx = RunContext(
            run_id="test-123",
            component_type="tool",
            component_name="test_tool",
        )
        
        ctx.end(success=True)
        
        assert ctx.success is True
        assert ctx.end_time is not None
        assert ctx.error_type is None
        assert ctx.duration_ms is not None
        assert ctx.duration_ms >= 0

    def test_end_context_failure(self):
        """Test ending context with failure."""
        ctx = RunContext(
            run_id="test-123",
            component_type="tool",
            component_name="test_tool",
        )
        
        error = ValueError("Something went wrong")
        ctx.end(success=False, error=error)
        
        assert ctx.success is False
        assert ctx.error_type == "ValueError"
        assert ctx.end_time is not None

    def test_to_dict(self):
        """Test converting context to dictionary."""
        ctx = RunContext(
            run_id="test-123",
            component_type="agent",
            component_name="test_agent",
            metadata={"key": "value"},
        )
        ctx.end(success=True)
        
        data = ctx.to_dict()
        
        assert data["run_id"] == "test-123"
        assert data["component_type"] == "agent"
        assert data["metadata"] == {"key": "value"}
        assert data["success"] is True
        assert "duration_ms" in data


class TestContextVars:
    """Test context variable operations."""

    def test_get_set_reset(self):
        """Test getting, setting, and resetting context."""
        # Initially None
        assert get_current_run_context() is None
        
        # Create and set context
        ctx = create_root_run_context("agent", "test")
        token = set_current_run_context(ctx)
        
        # Should be retrievable
        assert get_current_run_context() is ctx
        
        # Reset
        reset_run_context(token)
        
        # Back to None
        assert get_current_run_context() is None

    def test_create_root_run_context(self):
        """Test helper function creates valid context."""
        ctx = create_root_run_context(
            component_type="model",
            component_name="gpt-4",
            session_id="session-123",
            tags=["chat"],
            metadata={"temperature": 0.7},
        )
        
        assert ctx.component_type == "model"
        assert ctx.component_name == "gpt-4"
        assert ctx.session_id == "session-123"
        assert "chat" in ctx.tags
        assert ctx.metadata == {"temperature": 0.7}
        assert ctx.parent_run_id is None  # Root has no parent


class TestRunContextManager:
    """Test RunContextManager context manager."""

    def test_context_manager_success(self):
        """Test successful execution within context manager."""
        with RunContextManager("tool", "read_file", session_id="abc") as ctx:
            assert get_current_run_context() is ctx
            assert ctx.component_type == "tool"
            assert ctx.component_name == "read_file"
            assert ctx.session_id == "abc"
            assert ctx.success is None  # Not ended yet
        
        # After exit, context should be ended and reset
        assert ctx.success is True  # Success because no exception
        assert ctx.end_time is not None
        assert get_current_run_context() is None

    def test_context_manager_failure(self):
        """Test failed execution within context manager."""
        with pytest.raises(ValueError, match="Test error"):
            with RunContextManager("tool", "risky_tool") as ctx:
                assert get_current_run_context() is ctx
                raise ValueError("Test error")
        
        # After exit with exception, context should reflect failure
        assert ctx.success is False
        assert ctx.error_type == "ValueError"
        assert ctx.end_time is not None
        assert get_current_run_context() is None

    def test_nested_context_managers(self):
        """Test that nested managers create proper hierarchy."""
        with RunContextManager("agent", "outer") as outer:
            assert get_current_run_context() is outer
            
            with RunContextManager("tool", "inner", parent_context=outer) as inner:
                assert get_current_run_context() is inner
                assert inner.parent_run_id == outer.run_id
            
            # Inner context ended, outer restored
            assert get_current_run_context() is outer
        
        # Both ended
        assert get_current_run_context() is None
        assert outer.success is True

    def test_child_inherits_tags(self):
        """Test that child contexts inherit parent tags."""
        with RunContextManager("agent", "parent", tags=["important", "priority"]) as parent:
            with RunContextManager("tool", "child", parent_context=parent) as child:
                assert "important" in child.tags
                assert "priority" in child.tags


class TestAsyncContext:
    """Test that context vars work correctly with asyncio."""

    @pytest.mark.asyncio
    async def test_async_context_isolation(self):
        """Test that context vars are properly isolated in async tasks."""
        ctx1 = create_root_run_context("agent", "agent1")
        ctx2 = create_root_run_context("agent", "agent2")
        
        async def task1():
            set_current_run_context(ctx1)
            await asyncio.sleep(0.01)
            return get_current_run_context()
        
        async def task2():
            set_current_run_context(ctx2)
            await asyncio.sleep(0.01)
            return get_current_run_context()
        
        # Run tasks concurrently
        result1, result2 = await asyncio.gather(task1(), task2())
        
        # Each task should see its own context
        assert result1 is ctx1
        assert result2 is ctx2

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test context manager works in async code."""
        async with RunContextManager("agent", "async_agent") as ctx:
            assert get_current_run_context() is ctx
            await asyncio.sleep(0.001)
        
        assert ctx.success is True
        assert get_current_run_context() is None


class TestIntegration:
    """Integration tests for common use cases."""

    def test_agent_run_with_tool_calls(self):
        """Simulate an agent run that makes tool calls."""
        # Start agent run
        agent_ctx = create_root_run_context(
            "agent",
            "coding_agent",
            session_id="session-xyz",
            tags=["coding_task"],
        )
        agent_token = set_current_run_context(agent_ctx)
        
        try:
            # Simulate tool call 1
            with RunContextManager("tool", "list_files", parent_context=agent_ctx) as tool1:
                # Tool execution
                pass
            
            # Verify tool1 recorded
            assert tool1.success is True
            assert tool1.parent_run_id == agent_ctx.run_id
            
            # Simulate tool call 2
            with RunContextManager("tool", "read_file", parent_context=agent_ctx) as tool2:
                pass
            
            # Complete agent run
            agent_ctx.end(success=True)
            
        finally:
            reset_run_context(agent_token)
        
        # Verify final state
        assert agent_ctx.success is True
        assert get_current_run_context() is None

    def test_all_fields_present(self):
        """Ensure all expected fields exist in RunContext."""
        expected_fields = {
            "run_id", "parent_run_id", "session_id", "component_type",
            "component_name", "tags", "metadata", "start_time", "end_time",
            "success", "error_type"
        }
        actual_fields = {f.name for f in fields(RunContext)}
        assert expected_fields == actual_fields
