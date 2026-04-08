"""Tests for workflow state tracking."""

import pytest

from code_puppy.workflow_state import (
    WorkflowFlag,
    WorkflowState,
    get_workflow_state,
    set_flag,
    clear_flag,
    has_flag,
    reset_workflow_state,
    set_metadata,
    get_metadata,
    increment_counter,
)


class TestWorkflowFlag:
    """Test WorkflowFlag enumeration."""

    def test_all_flags_exist(self):
        """Test all expected flags are defined."""
        expected_flags = [
            "DID_GENERATE_CODE",
            "DID_EXECUTE_SHELL",
            "DID_LOAD_CONTEXT",
            "DID_CREATE_PLAN",
            "DID_ENCOUNTER_ERROR",
            "NEEDS_USER_CONFIRMATION",
            "DID_SAVE_SESSION",
            "DID_USE_FALLBACK_MODEL",
            "DID_TRIGGER_COMPACTION",
            "DID_MAKE_API_CALL",
            "DID_EDIT_FILE",
            "DID_CREATE_FILE",
            "DID_DELETE_FILE",
            "DID_RUN_TESTS",
            "DID_CHECK_LINT",
        ]
        for flag_name in expected_flags:
            assert hasattr(WorkflowFlag, flag_name)
            assert WorkflowFlag[flag_name] is not None


class TestWorkflowState:
    """Test WorkflowState dataclass."""

    def test_empty_state(self):
        """Test fresh state has no flags."""
        state = WorkflowState()
        assert not state.did_generate_code
        assert not state.did_execute_shell
        assert not state.did_load_context
        assert state.summary() == "No actions recorded"

    def test_setting_flags(self):
        """Test setting flags via properties."""
        state = WorkflowState()

        # Set some flags
        state.flags.add(WorkflowFlag.DID_GENERATE_CODE)
        state.flags.add(WorkflowFlag.DID_EXECUTE_SHELL)

        assert state.did_generate_code
        assert state.did_execute_shell
        assert not state.did_load_context

    def test_to_dict(self):
        """Test serialization to dict."""
        state = WorkflowState()
        state.flags.add(WorkflowFlag.DID_GENERATE_CODE)
        state.metadata["test"] = "value"

        data = state.to_dict()
        assert "flags" in data
        assert "metadata" in data
        assert "DID_GENERATE_CODE" in data["flags"]
        assert data["metadata"]["test"] == "value"

    def test_summary(self):
        """Test summary generation."""
        state = WorkflowState()
        assert state.summary() == "No actions recorded"

        state.flags.add(WorkflowFlag.DID_GENERATE_CODE)
        assert "Did Generate Code" in state.summary()


class TestWorkflowStateFunctions:
    """Test workflow state module-level functions."""

    def test_get_and_set_flag(self):
        """Test getting and setting workflow state."""
        # Reset first
        reset_workflow_state()

        state = get_workflow_state()
        assert not state.did_generate_code

        set_flag("did_generate_code")
        assert state.did_generate_code

    def test_set_flag_with_enum(self):
        """Test setting flag using enum."""
        reset_workflow_state()

        set_flag(WorkflowFlag.DID_EXECUTE_SHELL)
        assert has_flag(WorkflowFlag.DID_EXECUTE_SHELL)
        assert has_flag("did_execute_shell")

    def test_clear_flag(self):
        """Test clearing flags."""
        reset_workflow_state()

        set_flag("did_generate_code", True)
        assert has_flag("did_generate_code")

        clear_flag("did_generate_code")
        assert not has_flag("did_generate_code")

    def test_reset_workflow_state(self):
        """Test resetting state."""
        set_flag("did_generate_code")

        new_state = reset_workflow_state()
        assert not new_state.did_generate_code
        assert not has_flag("did_generate_code")

    def test_metadata(self):
        """Test metadata operations."""
        reset_workflow_state()

        set_metadata("agent_name", "test_agent")
        assert get_metadata("agent_name") == "test_agent"
        assert get_metadata("missing", "default") == "default"

    def test_increment_counter(self):
        """Test counter increment."""
        reset_workflow_state()

        assert increment_counter("files_created") == 1
        assert increment_counter("files_created") == 2
        assert increment_counter("files_created", 3) == 5

    def test_unknown_flag_warning(self):
        """Test that unknown flags are handled gracefully."""
        # Should not raise, just log warning
        set_flag("unknown_flag_xyz")
        # Should return False for has_flag
        assert not has_flag("unknown_flag_xyz")


class TestPreToolCallTracking:
    """Tests for _on_pre_tool_call flag tracking (code_puppy-8e0)."""

    def test_create_file_sets_flags(self):
        """pre_tool_call with create_file sets DID_CREATE_FILE and DID_GENERATE_CODE."""
        from code_puppy.workflow_state import (
            _on_pre_tool_call,
            reset_workflow_state,
            WorkflowFlag,
            has_flag,
        )

        reset_workflow_state()
        _on_pre_tool_call("create_file", {})
        assert has_flag(WorkflowFlag.DID_CREATE_FILE)
        assert has_flag(WorkflowFlag.DID_GENERATE_CODE)

    def test_replace_in_file_sets_flags(self):
        """pre_tool_call with replace_in_file sets DID_EDIT_FILE and DID_GENERATE_CODE."""
        from code_puppy.workflow_state import (
            _on_pre_tool_call,
            reset_workflow_state,
            WorkflowFlag,
            has_flag,
        )

        reset_workflow_state()
        _on_pre_tool_call("replace_in_file", {})
        assert has_flag(WorkflowFlag.DID_EDIT_FILE)
        assert has_flag(WorkflowFlag.DID_GENERATE_CODE)

    def test_unrelated_tool_no_file_flags(self):
        """pre_tool_call with an unrelated tool doesn't set file flags."""
        from code_puppy.workflow_state import (
            _on_pre_tool_call,
            reset_workflow_state,
            WorkflowFlag,
            has_flag,
        )

        reset_workflow_state()
        _on_pre_tool_call("list_files", {})
        assert not has_flag(WorkflowFlag.DID_CREATE_FILE)
        assert not has_flag(WorkflowFlag.DID_EDIT_FILE)


@pytest.mark.asyncio
async def test_workflow_state_async_isolation():
    """Regression test for code_puppy-5l1: workflow state must be isolated
    across concurrent async tasks (ContextVar, not threading.local)."""
    import asyncio
    from code_puppy.workflow_state import _current_state, get_workflow_state

    # Clear the ContextVar so each task starts with None and creates its own
    # WorkflowState. Otherwise both tasks inherit the same object from the
    # parent context (shallow copy).
    _current_state.set(None)

    results = {}

    async def task(name, flag_value):
        state = get_workflow_state()
        state.metadata["test_flag"] = flag_value
        await asyncio.sleep(0.01)  # Yield to other tasks
        results[name] = state.metadata.get("test_flag")

    await asyncio.gather(
        task("task_a", True),
        task("task_b", False),
    )

    # Each task should see its own flag value, not the other's
    assert results["task_a"] is True, "Task A saw Task B's state!"
    assert results["task_b"] is False, "Task B saw Task A's state!"
