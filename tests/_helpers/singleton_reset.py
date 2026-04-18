"""Reset all singleton state for test isolation.

Import and call reset_all_singletons() in conftest fixtures
to ensure clean state between tests.

This module consolidates all singleton reset helpers into a single
function, eliminating duplication in conftest.py fixtures.

Order matters: consumers before producers to avoid race conditions.
"""

import logging

logger = logging.getLogger(__name__)


def reset_all_singletons() -> None:
    """Reset all singletons in dependency order (consumers first).

    Each reset is wrapped in its own try/except so one failing module
    doesn't prevent other resets from running.
    """
    # =========================================================================
    # 1. Messaging layer (consumers first)
    # =========================================================================

    # 1a. Message queue
    try:
        from code_puppy.messaging.message_queue import reset_global_queue_for_tests

        reset_global_queue_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 1b. Message bus
    try:
        from code_puppy.messaging.bus import reset_global_bus_for_tests

        reset_global_bus_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 1c. History buffer
    try:
        from code_puppy.messaging.history_buffer import reset_global_buffer_for_tests

        reset_global_buffer_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 1d. Sub-agent console manager
    try:
        from code_puppy.messaging.subagent_console import SubAgentConsoleManager

        SubAgentConsoleManager.reset_instance()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 2. Plugin layer
    # =========================================================================

    # 2a. Run limiter (pack parallelism)
    try:
        from code_puppy.plugins.pack_parallelism.run_limiter import (
            reset_run_limiter_for_tests,
        )

        reset_run_limiter_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 3. Core infrastructure
    # =========================================================================

    # 3a. Callbacks registry
    try:
        from code_puppy.callbacks import _reset_for_tests

        _reset_for_tests()
    except Exception:
        pass  # Function may not exist yet

    # 3b. Policy engine
    try:
        from code_puppy.policy_engine import reset_policy_engine

        reset_policy_engine()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 3c. Security boundary
    try:
        from code_puppy.security import reset_security_boundary

        reset_security_boundary()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 4. Configuration layer
    # =========================================================================

    # 4a. Config package loader
    try:
        from code_puppy.config_package.loader import reset_puppy_config_for_tests

        reset_puppy_config_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 5. Agent layer
    # =========================================================================

    # 5a. Agent manager
    try:
        from code_puppy.agents.agent_manager import reset_state_for_tests

        reset_state_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 6. MCP layer
    # =========================================================================

    # 6a. MCP manager
    try:
        from code_puppy.mcp_.manager import reset_manager_for_tests

        reset_manager_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 6b. MCP retry manager
    try:
        from code_puppy.mcp_.retry_manager import reset_retry_manager_for_tests

        reset_retry_manager_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 6c. MCP error isolation
    try:
        from code_puppy.mcp_.error_isolation import reset_isolator_for_tests

        reset_isolator_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 7. Concurrency and rate limiting
    # =========================================================================

    # 7a. Concurrency limits (semaphores)
    try:
        from code_puppy.concurrency_limits import reset_semaphores_for_tests

        reset_semaphores_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # 7b. Adaptive rate limiter
    try:
        from code_puppy.adaptive_rate_limiter import reset_state_for_tests

        reset_state_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 8. Code context
    # =========================================================================

    # 8a. Code explorer
    try:
        from code_puppy.code_context import reset_explorer_for_tests

        reset_explorer_for_tests()
    except Exception:
        pass  # Module may not be loaded in all test contexts

    # =========================================================================
    # 9. Request caching
    # =========================================================================

    # 9a. Global request cache
    try:
        from code_puppy.request_cache import reset_global_request_cache

        reset_global_request_cache()
    except Exception:
        pass  # Module may not be loaded in all test contexts
