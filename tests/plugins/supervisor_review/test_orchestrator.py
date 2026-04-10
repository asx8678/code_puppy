"""Tests for supervisor_review.orchestrator (bd code_puppy-79p)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_puppy.plugins.supervisor_review.models import ReviewLoopConfig
from code_puppy.plugins.supervisor_review.orchestrator import (
    _sanitize_agent_name,
    _write_artifacts,
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

    def test_worker_outputs_wrapped_in_trust_boundary_delimiters(self):
        """Worker outputs are wrapped in <worker-output> XML-style tags (code_puppy-koy)."""
        result = build_supervisor_prompt(
            "do thing",
            {"agent_a": "output A", "agent_b": "output B"},
            iteration=1,
            satisfaction_mode="structured",
        )
        # Check for trust-boundary delimiters
        assert "<worker-output agent='agent_a'>" in result
        assert "<worker-output agent='agent_b'>" in result
        assert "</worker-output>" in result
        assert "output A" in result
        assert "output B" in result

    def test_untrusted_content_warning_in_prompt(self):
        """Prompt includes explicit warning about untrusted worker content (code_puppy-koy)."""
        result = build_supervisor_prompt(
            "do thing",
            {"agent_x": "some output"},
            iteration=1,
            satisfaction_mode="structured",
        )
        # Check for untrusted content warning
        assert "UNTRUSTED CONTENT" in result
        assert "NOT from a trusted source" in result
        assert "may contain errors" in result
        assert "hallucinations" in result

    def test_empty_worker_output_handled(self):
        """Empty worker outputs are wrapped in delimiters with (no output) placeholder."""
        result = build_supervisor_prompt(
            "task",
            {"agent_empty": ""},
            iteration=1,
            satisfaction_mode="structured",
        )
        # Check empty output is wrapped in delimiters
        assert "<worker-output agent='agent_empty'>" in result
        assert "(no output)" in result
        assert "</worker-output>" in result


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

    @pytest.mark.asyncio
    async def test_session_prefix_path_traversal_rejected(self):
        """SECURITY: session_prefix with path traversal characters must be rejected."""
        traversal_prefixes = [
            "../etc/passwd",
            "..\\windows\\system32",
            "..",
            "a/../b",
            "a/b/c/../../../d",
            "prefix/../../../etc",
        ]
        for bad_prefix in traversal_prefixes:
            with pytest.raises(ValueError, match="session_prefix"):
                ReviewLoopConfig(
                    worker_agents=["worker"],
                    supervisor_agent="sup",
                    task_prompt="task",
                    session_prefix=bad_prefix,
                )

    @pytest.mark.asyncio
    async def test_agent_name_backslash_rejected(self):
        """SECURITY: agent names with backslashes must be rejected."""
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        # Backslash in agent name should be rejected
        cfg = ReviewLoopConfig(
            worker_agents=["evil\\..\\..\\agent"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )
        # PathSafetyError inherits from ValueError - uses shared path_safety utility
        with pytest.raises(ValueError, match="forbidden"):
            await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)

    @pytest.mark.asyncio
    async def test_agent_name_dotdot_rejected(self):
        """SECURITY: agent names containing '..' must be rejected."""
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["agent..with..dots"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )
        # PathSafetyError inherits from ValueError - uses shared path_safety utility
        with pytest.raises(ValueError, match="forbidden"):
            await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)

    @pytest.mark.asyncio
    async def test_agent_name_path_separator_rejected(self):
        """SECURITY: agent names with forward slashes must be rejected."""
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["evil/path"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )
        # PathSafetyError inherits from ValueError - uses shared path_safety utility
        with pytest.raises(ValueError, match="forbidden"):
            await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)

    @pytest.mark.asyncio
    async def test_agent_name_nul_rejected(self):
        """SECURITY: agent names with NUL bytes must be rejected."""
        fake = FakeAgentScript(
            {
                "worker": ["out"],
                "sup": [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["agent\x00name"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )
        # PathSafetyError inherits from ValueError - uses shared path_safety utility
        with pytest.raises(ValueError, match="forbidden"):
            await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)


class TestSanitizeAgentName:
    """Direct tests for _sanitize_agent_name function."""

    def test_valid_names_pass(self):
        """Alphanumeric, underscore, and hyphen are allowed."""
        assert _sanitize_agent_name("agent1") == "agent1"
        assert _sanitize_agent_name("my_agent") == "my_agent"
        assert _sanitize_agent_name("my-agent") == "my-agent"
        assert _sanitize_agent_name("Agent123") == "Agent123"

    def test_empty_name_raises(self):
        """Empty string should raise ValueError."""
        # PathSafetyError inherits from ValueError - uses shared path_safety utility
        with pytest.raises(ValueError, match="must not be empty"):
            _sanitize_agent_name("")

    def test_dot_raises(self):
        """Dot character should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("agent.name")

    def test_backslash_raises(self):
        """Backslash should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("agent\\name")

    def test_forward_slash_raises(self):
        """Forward slash should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("agent/name")

    def test_colon_raises(self):
        """Colon should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("agent:name")

    def test_nul_byte_raises(self):
        """NUL byte should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("agent\x00name")

    def test_dotdot_raises(self):
        """Dotdot sequence should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden"):
            _sanitize_agent_name("..")


class TestWriteArtifactsPathTraversal:
    """Tests for path traversal defense in _write_artifacts."""

    def test_session_prefix_dot_blocked(self, tmp_path: Path):
        """SECURITY: session_prefix with dots should be rejected by defense-in-depth check."""
        from code_puppy.plugins.supervisor_review.models import IterationResult

        # Create a config with a clean session_prefix (validated in ReviewLoopConfig)
        # but simulate a bypass attempt in _write_artifacts by mutating the config
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )

        # Manually corrupt the session_prefix to bypass model validation
        # This simulates what would happen if validation was bypassed
        object.__setattr__(cfg, "session_prefix", "../outside")

        iteration = IterationResult(
            iteration=1,
            worker_outputs={"worker": "output"},
            supervisor_output="supervisor response",
        )

        # The defense-in-depth check in _write_artifacts should catch this
        with pytest.raises(ValueError, match="unsafe characters|path traversal"):
            _write_artifacts(tmp_path, cfg, [iteration], [])

    def test_session_prefix_absolute_path_blocked(self, tmp_path: Path):
        """SECURITY: Absolute path in session_prefix should be blocked."""
        from code_puppy.plugins.supervisor_review.models import IterationResult

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )

        # Try an absolute path escape (this actually escapes containment)
        object.__setattr__(cfg, "session_prefix", "/etc")

        iteration = IterationResult(
            iteration=1,
            worker_outputs={"worker": "output"},
            supervisor_output="supervisor response",
        )

        # The absolute path check should catch this
        with pytest.raises(ValueError, match="unsafe characters|path traversal|outside root"):
            _write_artifacts(tmp_path, cfg, [iteration], [])

    def test_agent_name_traversal_in_output_blocked(self, tmp_path: Path):
        """SECURITY: Agent name with path traversal should be rejected."""
        from code_puppy.plugins.supervisor_review.models import IterationResult

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe",
        )

        iteration = IterationResult(
            iteration=1,
            worker_outputs={"evil../..agent": "output"},  # Bad agent name
            supervisor_output="supervisor response",
        )

        # _sanitize_agent_name should reject the bad agent name
        with pytest.raises(ValueError, match="agent_name|forbidden"):
            _write_artifacts(tmp_path, cfg, [iteration], [])

    def test_valid_session_prefix_allowed(self, tmp_path: Path):
        """Valid session_prefix should work normally."""
        from code_puppy.plugins.supervisor_review.models import IterationResult

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            session_prefix="safe-prefix",
        )

        iteration = IterationResult(
            iteration=1,
            worker_outputs={"worker": "output"},
            supervisor_output="supervisor response",
        )

        artifacts_dir = _write_artifacts(tmp_path, cfg, [iteration], [])

        assert artifacts_dir.exists()
        assert (artifacts_dir / "iter1_worker.log").exists()
        assert (artifacts_dir / "iter1_supervisor.log").exists()
        assert (artifacts_dir / "summary.json").exists()


class TestTimeoutHandling:
    """Regression tests for per_invocation_timeout_seconds (code_puppy-pyi)."""

    @pytest.mark.asyncio
    async def test_worker_timeout_graceful_failure(self):
        """Hung worker agent times out gracefully with proper error recording."""
        import asyncio

        async def slow_worker(agent_name, prompt, session_id=None):
            if agent_name == "worker":
                # Simulate a hung agent that never returns
                await asyncio.sleep(1000)
            return "supervisor output"

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            per_invocation_timeout_seconds=0.1,  # Very short timeout
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=slow_worker)
        assert result.success is False
        assert result.error is not None
        assert "timed out after 0.1s" in result.error
        assert result.iterations_run == 1
        # Check that the timeout was recorded in the iteration result
        assert result.iterations[0].error is not None
        assert "timed out" in result.iterations[0].error

    @pytest.mark.asyncio
    async def test_supervisor_timeout_graceful_failure(self):
        """Hung supervisor agent times out gracefully with proper error recording."""
        import asyncio

        async def slow_supervisor(agent_name, prompt, session_id=None):
            if agent_name == "sup":
                # Simulate a hung supervisor
                await asyncio.sleep(1000)
            return "worker output"

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            per_invocation_timeout_seconds=0.1,
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=slow_supervisor)
        assert result.success is False
        assert result.error is not None
        assert "supervisor agent" in result.error
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_no_timeout_allows_slow_agents(self):
        """When timeout is None (default), slow agents should complete."""
        import asyncio

        async def slightly_slow_agent(agent_name, prompt, session_id=None):
            await asyncio.sleep(0.01)  # Small delay, but within reason
            if agent_name == "sup":
                return '{"verdict": "approved"}'
            return "worker output"

        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            per_invocation_timeout_seconds=None,  # No timeout
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=slightly_slow_agent)
        assert result.success is True
        assert result.iterations_run == 1


class TestBoundedFeedbackHistory:
    """Regression tests for feedback history budget (code_puppy-evn)."""

    def test_format_feedback_history_empty(self):
        """Empty feedback returns empty string."""
        from code_puppy.plugins.supervisor_review.orchestrator import format_feedback_history

        result = format_feedback_history([])
        assert result == ""

    def test_format_feedback_history_respects_budget(self):
        """Feedback history is trimmed to respect character budget."""
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry
        from code_puppy.plugins.supervisor_review.orchestrator import format_feedback_history

        # Create many long feedback entries
        entries = [
            FeedbackEntry(iteration=i, supervisor_output=f"Feedback for iteration {i}: " + "x" * 500)
            for i in range(1, 21)  # 20 iterations of ~550 chars each
        ]

        # With a tight budget, only recent entries should be included
        result = format_feedback_history(entries, budget_chars=2000)
        # Should include a note about omitted entries
        assert "omitted" in result or len(result) <= 2000 + 100  # budget + margin
        # Most recent iteration should be present
        assert "Iteration 20 feedback" in result
        # Very old iterations should be omitted or the text should be bounded
        assert len(result) < 5000  # Definitely much smaller than full history

    def test_format_feedback_history_keeps_most_recent(self):
        """Most recent feedback is always included even with tight budget."""
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry
        from code_puppy.plugins.supervisor_review.orchestrator import format_feedback_history

        entries = [
            FeedbackEntry(iteration=i, supervisor_output=f"Feedback {i}: " + "y" * 1000)
            for i in range(1, 11)
        ]

        # Very tight budget - but should still include most recent
        result = format_feedback_history(entries, budget_chars=500)
        # Should mention the most recent iteration
        assert "Iteration 10" in result
        # Should have some content from the most recent feedback
        assert "Feedback 10" in result

    def test_format_feedback_history_omission_note(self):
        """When entries are omitted, a note explains why."""
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry
        from code_puppy.plugins.supervisor_review.orchestrator import format_feedback_history

        entries = [
            FeedbackEntry(iteration=i, supervisor_output=f"Feedback for iteration {i}")
            for i in range(1, 6)
        ]

        # Tight budget should cause some omissions
        result = format_feedback_history(entries, budget_chars=200)
        # Should have a note about omitted entries
        if "omitted" in result:
            # Note format check
            assert "earlier iteration(s) omitted" in result
            assert "budget" in result.lower()

    def test_feedback_budget_in_prompt(self):
        """Feedback budget parameter affects prompt size."""
        from code_puppy.plugins.supervisor_review.models import FeedbackEntry
        from code_puppy.plugins.supervisor_review.orchestrator import build_iteration_prompt

        entries = [
            FeedbackEntry(iteration=i, supervisor_output=f"Iteration {i} feedback: " + "z" * 500)
            for i in range(1, 11)
        ]

        # Large budget should include more content
        large_budget_prompt = build_iteration_prompt("task", entries, iteration=2, feedback_budget_chars=10000)
        # Small budget should be more compact
        small_budget_prompt = build_iteration_prompt("task", entries, iteration=2, feedback_budget_chars=500)

        assert len(large_budget_prompt) > len(small_budget_prompt)
        # Both should include the most recent feedback
        assert "Iteration 10" in large_budget_prompt
        assert "Iteration 10" in small_budget_prompt

    @pytest.mark.asyncio
    async def test_feedback_history_bounded_in_loop(self):
        """End-to-end: feedback history growth is bounded during review loop."""
        import json

        fake = FakeAgentScript(
            {
                "worker": ["attempt"] * 10,
                "sup": [json.dumps({"verdict": "rejected", "reason": "x" * 1000})] * 9 + [json.dumps({"verdict": "approved"})],
            }
        )
        cfg = ReviewLoopConfig(
            worker_agents=["worker"],
            supervisor_agent="sup",
            task_prompt="task",
            max_iterations=10,
            feedback_history_budget_chars=2000,  # Tight budget
        )
        result = await run_supervisor_review_loop(cfg, invoke_agent_fn=fake)

        # Should have run all iterations
        assert result.iterations_run == 10
        # Should have limited feedback history
        # The feedback entries themselves are not truncated, but prompts should respect budget
        assert len(result.feedback_history) == 9  # 9 rejected before approval

        # Verify prompts in worker calls respect budget
        worker_calls = [c for c in fake.calls if c["agent_name"] == "worker"]
        # Later worker calls should have bounded prompt size
        for call in worker_calls[3:]:  # Check middle/later calls
            assert len(call["prompt"]) < 10000  # Should be bounded, not unbounded
