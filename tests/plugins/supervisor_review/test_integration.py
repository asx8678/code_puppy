"""Integration tests for supervisor_review plugin (bd code_puppy-z2d).

Tests end-to-end wiring: plugin discovery, callback registration,
tool attachment, and full loop with default invoke path.
"""

from __future__ import annotations

import json

import pytest


# Ensure plugins are loaded before running tests
@pytest.fixture(scope="module", autouse=True)
def load_plugins():
    """Load all plugins before running integration tests."""
    from code_puppy.plugins import load_plugin_callbacks, ensure_plugins_loaded_for_phase
    load_plugin_callbacks()
    ensure_plugins_loaded_for_phase("register_tools")


class TestPluginDiscovery:
    """Verify supervisor_review is discovered by the plugin system."""

    def test_register_tools_callback_is_registered(self):
        """The register_tools callback should be in the callback registry."""
        from code_puppy.callbacks import get_callbacks

        callbacks = get_callbacks("register_tools")
        # At least supervisor_review should be registered
        callback_names = [cb.__qualname__ for cb in callbacks]
        assert any("_register_tools" in name for name in callback_names), (
            f"No _register_tools callback found. Got: {callback_names}"
        )

    def test_on_register_tools_includes_supervisor_review(self):
        """on_register_tools() should return an entry for supervisor_review_loop."""
        from code_puppy.callbacks import on_register_tools

        entries = on_register_tools()
        # Flatten: entries is a list of results, each of which may be a list
        flat = []
        for entry in entries:
            if isinstance(entry, list):
                flat.extend(entry)
            elif isinstance(entry, dict):
                flat.append(entry)

        tool_names = [e["name"] for e in flat if isinstance(e, dict) and "name" in e]
        assert "supervisor_review_loop" in tool_names, (
            f"supervisor_review_loop not in registered tools: {tool_names}"
        )

    def test_register_func_is_callable(self):
        """The register_func for supervisor_review_loop should be callable."""
        from code_puppy.callbacks import on_register_tools

        entries = on_register_tools()
        flat = []
        for entry in entries:
            if isinstance(entry, list):
                flat.extend(entry)
            elif isinstance(entry, dict):
                flat.append(entry)

        sr_entry = next(
            (e for e in flat if isinstance(e, dict) and e.get("name") == "supervisor_review_loop"),
            None,
        )
        assert sr_entry is not None
        assert callable(sr_entry["register_func"])


class TestToolAttachment:
    """Verify the tool can be attached to a mock agent."""

    def test_tool_attaches_to_mock_agent(self):
        """register_func should decorate a tool onto the given agent."""
        from code_puppy.callbacks import on_register_tools

        entries = on_register_tools()
        flat = []
        for entry in entries:
            if isinstance(entry, list):
                flat.extend(entry)
            elif isinstance(entry, dict):
                flat.append(entry)

        sr_entry = next(
            (e for e in flat if isinstance(e, dict) and e.get("name") == "supervisor_review_loop"),
            None,
        )
        assert sr_entry is not None

        registered_tools = []

        class MockAgent:
            def tool(self, func):
                registered_tools.append(func.__name__)
                return func

        sr_entry["register_func"](MockAgent())
        assert "supervisor_review_loop" in registered_tools


class TestFullLoopWithDefaultInvoke:
    """Integration test: full loop using the default invoke path."""

    @pytest.mark.asyncio
    async def test_structured_loop_approve_first_iteration(self, monkeypatch):
        """Full loop: worker → supervisor → structured check → approved."""
        calls = []

        async def mock_headless(agent_name, prompt, session_id=None):
            calls.append(agent_name)
            if agent_name == "test-supervisor":
                return json.dumps({
                    "verdict": "approved",
                    "confidence": 0.95,
                    "reason": "all requirements met",
                })
            return "worker output: implemented the feature"

        monkeypatch.setattr(
            "code_puppy.tools.agent_tools.invoke_agent_headless",
            mock_headless,
        )

        from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
        )

        config = ReviewLoopConfig(
            worker_agents=["test-coder"],
            supervisor_agent="test-supervisor",
            task_prompt="Write a hello world function",
            max_iterations=3,
            satisfaction_mode="structured",
        )
        result = await run_supervisor_review_loop(config)

        assert result.success is True
        assert result.iterations_run == 1
        assert result.error is None
        assert "test-coder" in calls
        assert "test-supervisor" in calls

    @pytest.mark.asyncio
    async def test_keyword_loop_with_feedback(self, monkeypatch):
        """Full loop: keyword mode, rejected first, approved second."""
        call_count = {"n": 0}

        async def mock_headless(agent_name, prompt, session_id=None):
            call_count["n"] += 1
            if agent_name == "reviewer":
                if call_count["n"] <= 2:
                    # First iteration: worker + supervisor
                    return "The code needs work. Missing edge case handling."
                else:
                    return "All requirements fully met. Great job."
            return f"worker output iteration {call_count['n']}"

        monkeypatch.setattr(
            "code_puppy.tools.agent_tools.invoke_agent_headless",
            mock_headless,
        )

        from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
        )

        config = ReviewLoopConfig(
            worker_agents=["coder"],
            supervisor_agent="reviewer",
            task_prompt="Implement error handling",
            max_iterations=3,
            satisfaction_mode="keyword",
        )
        result = await run_supervisor_review_loop(config)

        assert result.success is True
        assert result.iterations_run == 2
        assert len(result.feedback_history) == 1  # feedback from iteration 1

    @pytest.mark.asyncio
    async def test_llm_judge_loop_uses_async_path(self, monkeypatch):
        """Full loop: llm_judge mode invokes the async checker path."""
        judge_calls = []

        async def mock_headless(agent_name, prompt, session_id=None):
            if agent_name == "shepherd":
                judge_calls.append(prompt)
                return json.dumps({
                    "satisfied": True,
                    "confidence": 0.88,
                    "reason": "work is complete",
                })
            if agent_name == "sup":
                return "I've reviewed the code. It looks good overall."
            return "worker: did the thing"

        monkeypatch.setattr(
            "code_puppy.tools.agent_tools.invoke_agent_headless",
            mock_headless,
        )

        from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
        )

        config = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="Do the task",
            max_iterations=2,
            satisfaction_mode="llm_judge",
        )
        result = await run_supervisor_review_loop(config)

        assert result.success is True
        assert result.iterations_run == 1
        # Judge agent ("shepherd") should have been called via is_satisfied_async
        assert len(judge_calls) == 1
        assert "Supervisor's review output" in judge_calls[0]

    @pytest.mark.asyncio
    async def test_result_to_dict_serializable(self, monkeypatch):
        """Full loop result should be JSON-serializable via to_dict()."""
        async def mock_headless(agent_name, prompt, session_id=None):
            if agent_name == "sup":
                return json.dumps({"verdict": "approved"})
            return "output"

        monkeypatch.setattr(
            "code_puppy.tools.agent_tools.invoke_agent_headless",
            mock_headless,
        )

        from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
        from code_puppy.plugins.supervisor_review.orchestrator import (
            run_supervisor_review_loop,
        )

        config = ReviewLoopConfig(
            worker_agents=["w"],
            supervisor_agent="sup",
            task_prompt="task",
        )
        result = await run_supervisor_review_loop(config)
        d = result.to_dict()

        # Must be JSON-serializable
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip["success"] is True
        assert isinstance(roundtrip["iterations"], list)
