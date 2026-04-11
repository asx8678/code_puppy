"""Tests for supervisor_review plugin registration (bd code_puppy-79p)."""

# pytest imported for potential future use; not currently needed for these tests
import pytest  # noqa: F401


class TestPluginRegistrationImports:
    def test_module_imports_cleanly(self):
        """Importing the plugin must not crash."""
        from code_puppy.plugins.supervisor_review import register_callbacks  # noqa: F401

    def test_register_tools_callback_defined(self):
        from code_puppy.plugins.supervisor_review import register_callbacks

        assert callable(register_callbacks._register_tools)

    def test_register_tools_returns_list(self):
        from code_puppy.plugins.supervisor_review import register_callbacks

        result = register_callbacks._register_tools()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_register_tools_entry_shape(self):
        from code_puppy.plugins.supervisor_review import register_callbacks

        entries = register_callbacks._register_tools()
        entry = entries[0]
        assert "name" in entry
        assert "register_func" in entry
        assert entry["name"] == "supervisor_review_loop"
        assert callable(entry["register_func"])

    def test_register_supervisor_review_tool_callable(self):
        from code_puppy.plugins.supervisor_review.register_callbacks import (
            register_supervisor_review_tool,
        )

        assert callable(register_supervisor_review_tool)


class TestRegisterFuncInteractsWithMockAgent:
    """Smoke test: the register_func must decorate something on a mock agent."""

    def test_register_adds_tool_to_mock_agent(self):
        from code_puppy.plugins.supervisor_review.register_callbacks import (
            register_supervisor_review_tool,
        )

        registered: list[str] = []

        class MockAgent:
            def tool(self, func):
                # pydantic-ai style: @agent.tool as a decorator
                registered.append(func.__name__)
                return func

        agent = MockAgent()
        register_supervisor_review_tool(agent)
        assert "supervisor_review_loop" in registered


class TestOrchestratorPublicAPI:
    """Sanity check that Round A's public API is importable from the plugin."""

    def test_orchestrator_exports(self):
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
            build_iteration_prompt,
            build_supervisor_prompt,  # noqa: F401
            format_feedback_history,  # noqa: F401
        )

        assert callable(run_supervisor_review_loop)
        assert callable(build_iteration_prompt)

    def test_models_exports(self):
        from code_puppy.plugins.supervisor_review.models import (  # noqa: F401
            FeedbackEntry,
            IterationResult,
            ReviewLoopConfig,
            SatisfactionResult,
            SupervisorReviewResult,
        )

        # Instantiate one to confirm it works
        cfg = ReviewLoopConfig(
            worker_agents=["a"], supervisor_agent="sup", task_prompt="t"
        )
        assert cfg.max_iterations == 3

    def test_satisfaction_exports(self):
        from code_puppy.plugins.supervisor_review.satisfaction import (
            get_satisfaction_checker,
            StructuredSatisfactionChecker,
            KeywordSatisfactionChecker,  # noqa: F401
            LLMJudgeSatisfactionChecker,  # noqa: F401
        )

        assert isinstance(
            get_satisfaction_checker("structured"), StructuredSatisfactionChecker
        )
