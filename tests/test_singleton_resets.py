"""Tests for singleton reset helpers used in test isolation.

These tests verify that each reset_*_for_tests() function properly
clears the singleton state, allowing subsequent getter calls to
create fresh instances.
"""

import pytest


class TestMessageBusReset:
    """Tests for reset_global_bus_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new bus instance with different id()."""
        from code_puppy.messaging.bus import (
            get_message_bus,
            reset_global_bus_for_tests,
        )

        # Get initial instance and record its id
        bus1 = get_message_bus()
        id1 = id(bus1)

        # Emit some messages to dirty the state
        from code_puppy.messaging.messages import TextMessage, MessageLevel

        bus1.emit_text(MessageLevel.INFO, "test message")

        # Reset and get new instance
        reset_global_bus_for_tests()
        bus2 = get_message_bus()
        id2 = id(bus2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"

        # Verify the new instance is clean
        assert bus2.outgoing_qsize == 0, "New bus should have empty outgoing queue"
        assert bus2.incoming_qsize == 0, "New bus should have empty incoming queue"
        assert bus2.pending_requests_count == 0, "New bus should have no pending requests"


class TestHistoryBufferReset:
    """Tests for reset_global_buffer_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new buffer instance with different id()."""
        from code_puppy.messaging.history_buffer import (
            get_history_buffer,
            reset_global_buffer_for_tests,
        )

        # Get initial instance and record its id
        buf1 = get_history_buffer()
        id1 = id(buf1)

        # Add some data to dirty the state
        buf1.record("test-session", {"type": "test", "data": "value"})

        # Reset and get new instance
        reset_global_buffer_for_tests()
        buf2 = get_history_buffer()
        id2 = id(buf2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"

        # Verify the new instance is clean
        assert buf2.session_count() == 0, "New buffer should have no sessions"


class TestCodeExplorerReset:
    """Tests for reset_explorer_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new explorer instance with different id()."""
        from code_puppy.code_context import (
            get_explorer_instance,
            reset_explorer_for_tests,
        )

        # Get initial instance and record its id
        explorer1 = get_explorer_instance()
        id1 = id(explorer1)

        # Reset and get new instance
        reset_explorer_for_tests()
        explorer2 = get_explorer_instance()
        id2 = id(explorer2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"


class TestAgentManagerReset:
    """Tests for reset_state_for_tests()."""

    def test_reset_clears_state(self):
        """Verify reset clears all agent manager state."""
        import code_puppy.agents.agent_manager as am
        from code_puppy.agents.agent_manager import (
            reset_state_for_tests,
            set_current_agent,
        )

        # Set up some state
        try:
            set_current_agent("code-puppy")
        except Exception:
            pass  # Agent might not exist in test env

        # Reset
        reset_state_for_tests()

        # Verify state is cleared by accessing through module
        # (since reset replaces the _state object, we need fresh module access)
        assert am._state.current_agent is None, "Current agent should be None after reset"
        assert (
            am._state.registry_populated is False
        ), "Registry populated flag should be False after reset"
        assert len(am._state.agent_registry) == 0, "Registry should be empty after reset"
        assert len(am._state.agent_histories) == 0, "Histories should be empty after reset"


class TestMCPManagerReset:
    """Tests for reset_manager_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new manager instance with different id()."""
        from code_puppy.mcp_.manager import (
            get_mcp_manager,
            reset_manager_for_tests,
        )

        # Get initial instance and record its id
        mgr1 = get_mcp_manager()
        id1 = id(mgr1)

        # Add some pending tasks to dirty the state
        mgr1._pending_start_tasks["test"] = None

        # Reset and get new instance
        reset_manager_for_tests()
        mgr2 = get_mcp_manager()
        id2 = id(mgr2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"

        # Verify the new instance is clean
        assert len(mgr2._pending_start_tasks) == 0, "Pending start tasks should be empty"
        assert len(mgr2._pending_stop_tasks) == 0, "Pending stop tasks should be empty"


class TestRetryManagerReset:
    """Tests for reset_retry_manager_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new retry manager instance with different id()."""
        from code_puppy.mcp_.retry_manager import (
            get_retry_manager,
            reset_retry_manager_for_tests,
        )

        # Get initial instance and record its id
        mgr1 = get_retry_manager()
        id1 = id(mgr1)

        # Reset and get new instance
        reset_retry_manager_for_tests()
        mgr2 = get_retry_manager()
        id2 = id(mgr2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"


class TestErrorIsolatorReset:
    """Tests for reset_isolator_for_tests()."""

    def test_reset_creates_fresh_instance(self):
        """Verify reset returns a new isolator instance with different id()."""
        from code_puppy.mcp_.error_isolation import (
            get_error_isolator,
            reset_isolator_for_tests,
        )

        # Get initial instance and record its id
        iso1 = get_error_isolator()
        id1 = id(iso1)

        # Add some stats to dirty the state
        iso1.server_stats["test-server"] = None

        # Reset and get new instance
        reset_isolator_for_tests()
        iso2 = get_error_isolator()
        id2 = id(iso2)

        # Verify it's a different instance
        assert id1 != id2, "Reset should create a new instance"

        # Verify the new instance is clean
        assert len(iso2.server_stats) == 0, "Server stats should be empty after reset"


class TestAdaptiveRateLimiterReset:
    """Tests for reset_state_for_tests()."""

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        """Verify reset clears all rate limiter state."""
        from code_puppy.adaptive_rate_limiter import (
            _state,
            record_rate_limit,
            reset_state_for_tests,
        )

        # Add some state by recording a rate limit
        await record_rate_limit("test-model")

        # Verify state exists
        assert len(_state.model_states) > 0, "Model states should not be empty"

        # Reset
        reset_state_for_tests()

        # Verify state is cleared
        assert len(_state.model_states) == 0, "Model states should be empty after reset"
        assert _state.recovery_task is None, "Recovery task should be None after reset"
        assert (
            _state.recovery_started is False
        ), "Recovery started flag should be False after reset"


class TestConcurrencyLimitsReset:
    """Tests for reset_semaphores_for_tests()."""

    def test_reset_clears_semaphores(self):
        """Verify reset clears all semaphore instances."""
        from code_puppy.concurrency_limits import (
            get_concurrency_status,
            reset_semaphores_for_tests,
        )

        # Initialize semaphores by calling get_concurrency_status
        status = get_concurrency_status()
        assert status is not None

        # Reset
        reset_semaphores_for_tests()

        # Verify semaphores are cleared by checking module globals
        # Note: We need to import the module to check the actual globals
        import code_puppy.concurrency_limits as cl

        assert cl._file_ops_semaphore is None, "File ops semaphore should be None"
        assert cl._api_calls_semaphore is None, "API calls semaphore should be None"
        assert cl._tool_calls_semaphore is None, "Tool calls semaphore should be None"
        assert cl._cached_config is None, "Cached config should be None"
