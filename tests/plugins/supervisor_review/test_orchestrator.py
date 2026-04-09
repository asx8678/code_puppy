"""Tests for supervisor_review.orchestrator (bd code_puppy-79p)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
from code_puppy.plugins.supervisor_review.orchestrator import (
    build_iteration_prompt,
    build_supervisor_prompt,
    format_feedback_history,
    run_supervisor_review_loop,
)


class TestFormatFeedbackHistory:
    def test_empty(self):
        assert format_feedback_history([]) == ""

    def test_single_entry(self):
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry

        result = format_feedback_history(
            [FeedbackEntry(iteration=1, supervisor_output="fix X")]
        )
        assert "Iteration 1 feedback" in result
        assert "fix X" in result

    def test_multiple_entries(self):
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry

        entries = [
            FeedbackEntry(iteration=1, supervisor_output="fix X"),
            FeedbackEntry(iteration=2, supervisor_output="fix Y"),
        ]
        result = format_feedback_history(entries)
        assert "Iteration 1" in result
        assert "Iteration 2" in result
        assert "fix X" in result
        assert "fix Y" in result


class TestBuildIterationPrompt:
    def test_first_iteration_unchanged(self):
        result = build_iteration_prompt("do thing", [], iteration=1)
        assert result == "do thing"

    def test_later_iteration_adds_feedback(self):
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry

        feedback = [FeedbackEntry(iteration=1, supervisor_output="add tests")]
        result = build_iteration_prompt("do thing", feedback, iteration=2)
        assert "do thing" in result
        assert "Previous supervisor feedback" in result
        assert "add tests" in result

    def test_no_feedback_returns_task_as_is(self):
        result = build_iteration_prompt("do thing", [], iteration=5)
        assert result == "do thing"


class TestBuildSupervisorPrompt:
    def test_structured_mode_includes_json_instruction(self):
        result = build_supervisor_prompt(
            "do thing",
            {"agent_a": "output A"},
            iteration=1,
            satisfaction_mode="structured",
        )
        assert "do thing" in result
        assert "agent_a" in result
        assert "output A" in result
        assert '"verdict"' in result
        assert "JSON" in result

    def test_keyword_mode_includes_phrases(self):
        result = build_supervisor_prompt(
            "task",
            {"a": "x"},
            iteration=1,
            satisfaction_mode="keyword",
        )
        assert "fully met" in result
        assert "needs work" in result

    def test_llm_judge_mode(self):
        result = build_supervisor_prompt(
            "task", {"a": "x"}, iteration=1, satisfaction_mode="llm_judge"
        )
        assert "task" in result


class FakeAgentScript:
    """Helper: a scripted fake invoke_agent that returns predetermined outputs.

    Each call pops the next response for the given agent name from its queue.
    """

    def __init__(self, scripts: dict[str, list[str]]):
        # Copy lists so tests can inspect state after
        self.scripts = {name: list(outputs) for name, outputs in scripts.items()}
        self.calls: list[dict] = []

    async def __call__(
        self, agent_name: str, prompt: str, session_id: str | None = None
    ) -> str:
        self.calls.append(
            {"agent_name": agent_name, "prompt": prompt, "session_id": session_id}
        )
        queue = self.scripts.get(agent_name, [])
        if not queue:
            raise RuntimeError(f"No more scripted responses for agent {agent_name!r}")
        return queue.pop(0)


class TestRunSupervisorReviewLoop:
    @pytest.mark.asyncio
    async def test_satisfies_on_first_iteration(self):
        fake = FakeAgentScript(
            {
                "worker": ["worker result"],
                "sup": [json.dumps({"verdict": "approved", "confidence": 0.95})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="do thing",
            max_iterations=3,
            satisfaction_mode="structured",
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert result.success is True
        assert result.iterations_run == 1
        assert result.final_supervisor_output
        assert "worker" in result.final_worker_outputs
        assert len(fake.calls) == 2  # worker + supervisor

    @pytest.mark.asyncio
    async def test_satisfies_on_second_iteration(self):
        fake = FakeAgentScript(
            {
                "worker": ["first try", "second try"],
                "sup": [
                    json.dumps({"verdict": "rejected", "reason": "missing X"}),
                    json.dumps({"verdict": "approved", "reason": "X added"}),
                ],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="do thing",
            max_iterations=3,
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert result.success is True
        assert result.iterations_run == 2
        assert len(result.feedback_history) == 1  # only iter 1 contributed feedback

    @pytest.mark.asyncio
    async def test_exhausts_iterations_without_satisfaction(self):
        fake = FakeAgentScript(
            {
                "worker": ["attempt 1", "attempt 2", "attempt 3"],
                "sup": [json.dumps({"verdict": "rejected"})] * 3,
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="do thing",
            max_iterations=3,
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert result.success is False
        assert result.iterations_run == 3
        assert len(result.feedback_history) == 3

    @pytest.mark.asyncio
    async def test_feedback_injected_into_later_iterations(self):
        fake = FakeAgentScript(
            {
                "worker": ["first", "second"],
                "sup": [
                    json.dumps({"verdict": "rejected", "reason": "add more detail"}),
                    json.dumps({"verdict": "approved"}),
                ],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="write a summary",
        )
        await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)

        # The second worker call should contain feedback from iteration 1
        worker_calls = [c for c in fake.calls if c["agent_name"] == "worker"]
        assert len(worker_calls) == 2
        assert "Previous supervisor feedback" in worker_calls[1]["prompt"]
        assert "add more detail" in worker_calls[1]["prompt"]

    @pytest.mark.asyncio
    async def test_multiple_worker_agents_called_in_order(self):
        fake = FakeAgentScript(
            {
                "agent_a": ["a output"],
                "agent_b": ["b output"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["agent_a", "agent_b"],
            supervisor_agent="sup",
            task_prompt="task",
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert result.success is True
        assert "agent_a" in result.final_worker_outputs
        assert "agent_b" in result.final_worker_outputs
        call_names = [c["agent_name"] for c in fake.calls]
        assert call_names == ["agent_a", "agent_b", "sup"]

    @pytest.mark.asyncio
    async def test_worker_failure_returns_partial_result(self):
        async def failing_agent(agent_name, prompt, session_id=None):
            if agent_name == "worker":
                raise RuntimeError("worker crashed")
            return "unused"

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=failing_agent)
        assert result.success is False
        assert result.error is not None
        assert "worker crashed" in result.error
        assert result.iterations_run == 1

    @pytest.mark.asyncio
    async def test_supervisor_failure_returns_partial_result(self):
        async def sometimes_failing(agent_name, prompt, session_id=None):
            if agent_name == "sup":
                raise RuntimeError("supervisor crashed")
            return "worker output"

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
        )
        result = await run_supervisor_review_loop(
            cfg, invoke_agent_fn=sometimes_failing
        )
        assert result.success is False
        assert result.error is not None
        assert "supervisor crashed" in result.error

    @pytest.mark.asyncio
    async def test_session_ids_include_prefix(self):
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="my-session",
        )
        await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert all(
            c["session_id"] and "my-session" in c["session_id"] for c in fake.calls
        )

    @pytest.mark.asyncio
    async def test_no_session_prefix_yields_none(self):
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
        )
        await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert all(c["session_id"] is None for c in fake.calls)

    @pytest.mark.asyncio
    async def test_keyword_mode_end_to_end(self):
        fake = FakeAgentScript(
            {
                "worker": ["w1"],
                "sup": ["Good output. Fully met."],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="t",
            satisfaction_mode="keyword",
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_artifacts_written_when_root_provided(self, tmp_path: Path):
        fake = FakeAgentScript(
            {
                "worker": ["the output"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="t",
            session_prefix="test-run",
        )
        result = await run_supervisor_review_loop(
            cfg, invoke_agent_fn=fake, artifacts_root=tmp_path
        )
        assert result.artifacts_dir is not None
        artifacts = Path(result.artifacts_dir)
        assert artifacts.exists()
        assert (artifacts / "summary.json").exists()
        assert (artifacts / "iter1_worker.log").read_text() == "the output"

    @pytest.mark.asyncio
    async def test_to_dict_serializable(self):
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="t",
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)
        d = result.to_dict()
        # Must be JSON-serializable
        json.dumps(d)
