"""Integration tests for supervisor_review invoke_agent wiring (bd code_puppy-bnp).

Verifies that the runtime wiring between supervisor_review's orchestrator
and code_puppy.tools.agent_tools.invoke_agent_headless works correctly.
"""

from __future__ import annotations

import pytest


class TestInvokeAgentHeadlessImport:
    """Verify invoke_agent_headless is importable at module level."""

    def test_import_succeeds(self):
        """invoke_agent_headless should be importable from agent_tools."""
        from code_puppy.tools.agent_tools import invoke_agent_headless

        assert callable(invoke_agent_headless)

    def test_is_async(self):
        """invoke_agent_headless should be an async function."""
        import asyncio

        from code_puppy.tools.agent_tools import invoke_agent_headless

        assert asyncio.iscoroutinefunction(invoke_agent_headless)

    def test_signature_matches_expected(self):
        """invoke_agent_headless should accept (agent_name, prompt, session_id)."""
        import inspect

        from code_puppy.tools.agent_tools import invoke_agent_headless

        sig = inspect.signature(invoke_agent_headless)
        params = list(sig.parameters.keys())
        assert "agent_name" in params
        assert "prompt" in params
        assert "session_id" in params

    def test_session_id_is_optional(self):
        """session_id parameter should be optional (default None)."""
        import inspect

        from code_puppy.tools.agent_tools import invoke_agent_headless

        sig = inspect.signature(invoke_agent_headless)
        session_param = sig.parameters["session_id"]
        assert session_param.default is None


class TestDefaultInvokeAgent:
    """Verify _default_invoke_agent uses invoke_agent_headless."""

    def test_default_invoke_agent_does_not_crash_on_import(self):
        """_default_invoke_agent should import invoke_agent_headless without error.

        This is the core regression test: previously, _default_invoke_agent tried
        to import the closure `invoke_agent` which always failed with ImportError.
        """
        from code_puppy.plugins.supervisor_review.orchestrator import (
            _default_invoke_agent,
        )

        assert callable(_default_invoke_agent)

    def test_default_invoke_agent_is_async(self):
        """_default_invoke_agent should be an async function."""
        import asyncio

        from code_puppy.plugins.supervisor_review.orchestrator import (
            _default_invoke_agent,
        )

        assert asyncio.iscoroutinefunction(_default_invoke_agent)


class TestOrchestratorUsesHeadlessDefault:
    """Verify run_supervisor_review_loop defaults to invoke_agent_headless."""

    @pytest.mark.asyncio
    async def test_default_fn_calls_headless(self, monkeypatch):
        """When no invoke_agent_fn is provided, the orchestrator should use
        invoke_agent_headless via _default_invoke_agent.

        We monkeypatch invoke_agent_headless to verify it gets called.
        """
        calls = []

        async def mock_headless(agent_name, prompt, session_id=None):
            calls.append({"agent_name": agent_name, "prompt": prompt})
            # Return "approved" JSON so the loop terminates on first iteration
            if agent_name == "test-supervisor":
                return '{"verdict": "approved", "confidence": 0.95, "reason": "test"}'
            return "mock worker output"

        monkeypatch.setattr(
            "code_puppy.tools.agent_tools.invoke_agent_headless",
            mock_headless,
        )
        # Also patch the import inside _default_invoke_agent
        monkeypatch.setattr(
            "code_puppy.plugins.supervisor_review.orchestrator.invoke_agent_headless",
            mock_headless,
            raising=False,
        )

        from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
        )

        config = ReviewLoopConfig(
            worker_agents=["test-worker"],
            supervisor_agent="test-supervisor",
            task_prompt="Test task",
            max_iterations=1,
            satisfaction_mode="structured",
        )

        # Don't pass invoke_agent_fn — should use default which calls headless
        result = await run_supervisor_review_loop(config)

        # Verify invoke_agent_headless was called for both worker and supervisor
        assert len(calls) >= 2
        agent_names = [c["agent_name"] for c in calls]
        assert "test-worker" in agent_names
        assert "test-supervisor" in agent_names
