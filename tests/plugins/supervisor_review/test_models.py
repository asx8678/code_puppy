"""Tests for supervisor_review.models (bd code_puppy-79p)."""

from __future__ import annotations

import pytest

from code_puppy.plugins.supervisor_review.models import (
    FeedbackEntry,
    IterationResult,
    ReviewLoopConfig,
    SatisfactionResult,
    SupervisorReviewResult,
)


class TestSatisfactionResult:
    def test_basic(self):
        r = SatisfactionResult(satisfied=True, confidence=0.9, reason="ok")
        assert r.satisfied is True
        assert r.confidence == 0.9
        assert r.reason == "ok"

    def test_confidence_clamped_low(self):
        r = SatisfactionResult(satisfied=False, confidence=-0.5)
        assert r.confidence == 0.0

    def test_confidence_clamped_high(self):
        r = SatisfactionResult(satisfied=True, confidence=1.5)
        assert r.confidence == 1.0


class TestFeedbackEntry:
    def test_basic(self):
        fe = FeedbackEntry(iteration=1, supervisor_output="needs work")
        assert fe.iteration == 1
        assert fe.supervisor_output == "needs work"
        assert fe.timestamp > 0


class TestIterationResult:
    def test_defaults(self):
        ir = IterationResult(iteration=1)
        assert ir.iteration == 1
        assert ir.worker_outputs == {}
        assert ir.supervisor_output == ""
        assert ir.satisfaction is None
        assert ir.satisfied is False
        assert ir.error is None

    def test_satisfied_property(self):
        ir = IterationResult(
            iteration=1,
            satisfaction=SatisfactionResult(satisfied=True, confidence=1.0),
        )
        assert ir.satisfied is True

    def test_not_satisfied_property(self):
        ir = IterationResult(
            iteration=1,
            satisfaction=SatisfactionResult(satisfied=False, confidence=0.5),
        )
        assert ir.satisfied is False


class TestReviewLoopConfig:
    def test_basic(self):
        cfg = ReviewLoopConfig(
            worker_agents=["a", "b"],
            supervisor_agent="sup",
            task_prompt="do thing",
        )
        assert cfg.max_iterations == 3
        assert cfg.satisfaction_mode == "structured"

    def test_empty_workers_raises(self):
        with pytest.raises(ValueError, match="worker_agents must not be empty"):
            ReviewLoopConfig(worker_agents=[], supervisor_agent="sup", task_prompt="x")

    def test_empty_supervisor_raises(self):
        with pytest.raises(ValueError, match="supervisor_agent must not be empty"):
            ReviewLoopConfig(worker_agents=["a"], supervisor_agent="", task_prompt="x")

    def test_zero_iterations_raises(self):
        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                max_iterations=0,
            )

    def test_invalid_satisfaction_mode_raises(self):
        with pytest.raises(ValueError, match="satisfaction_mode must be one of"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                satisfaction_mode="magic",
            )

    def test_valid_satisfaction_modes(self):
        for mode in ("structured", "keyword", "llm_judge"):
            cfg = ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                satisfaction_mode=mode,
            )
            assert cfg.satisfaction_mode == mode

    # SECURITY: session_prefix validation tests
    def test_session_prefix_valid_alphanumeric(self):
        """Alphanumeric, underscore, and hyphen are allowed."""
        cfg = ReviewLoopConfig(
            worker_agents=["a"],
            supervisor_agent="sup",
            task_prompt="x",
            session_prefix="my_session-123",
        )
        assert cfg.session_prefix == "my_session-123"

    def test_session_prefix_path_traversal_rejected(self):
        """SECURITY: session_prefix with path traversal must be rejected."""
        traversal_attempts = [
            "../etc/passwd",
            "..\\windows\\system32",
            "..",
            "a/../b",
            "../../../etc",
            "prefix/../../../d",
        ]
        for bad_prefix in traversal_attempts:
            with pytest.raises(ValueError, match="session_prefix"):
                ReviewLoopConfig(
                    worker_agents=["a"],
                    supervisor_agent="sup",
                    task_prompt="x",
                    session_prefix=bad_prefix,
                )

    def test_session_prefix_forward_slash_rejected(self):
        """SECURITY: Forward slash in session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="path/to/file",
            )

    def test_session_prefix_backslash_rejected(self):
        """SECURITY: Backslash in session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="path\\to\\file",
            )

    def test_session_prefix_dot_rejected(self):
        """SECURITY: Dot in session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="my.prefix",
            )

    def test_session_prefix_colon_rejected(self):
        """SECURITY: Colon in session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="c:windows",
            )

    def test_session_prefix_nul_rejected(self):
        """SECURITY: NUL byte in session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="prefix\x00name",
            )

    def test_session_prefix_too_long_rejected(self):
        """SECURITY: session_prefix over 64 chars must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="a" * 65,
            )

    def test_session_prefix_64_chars_allowed(self):
        """SECURITY: session_prefix of exactly 64 chars is allowed."""
        cfg = ReviewLoopConfig(
            worker_agents=["a"],
            supervisor_agent="sup",
            task_prompt="x",
            session_prefix="a" * 64,
        )
        assert cfg.session_prefix == "a" * 64

    def test_session_prefix_empty_rejected(self):
        """SECURITY: Empty session_prefix must be rejected."""
        with pytest.raises(ValueError, match="session_prefix"):
            ReviewLoopConfig(
                worker_agents=["a"],
                supervisor_agent="sup",
                task_prompt="x",
                session_prefix="",
            )

    def test_session_prefix_none_allowed(self):
        """None (no prefix) is allowed."""
        cfg = ReviewLoopConfig(
            worker_agents=["a"],
            supervisor_agent="sup",
            task_prompt="x",
            session_prefix=None,
        )
        assert cfg.session_prefix is None


class TestSupervisorReviewResult:
    def test_to_dict_empty(self):
        r = SupervisorReviewResult(success=False, iterations_run=0, max_iterations=3)
        d = r.to_dict()
        assert d["success"] is False
        assert d["iterations_run"] == 0
        assert d["max_iterations"] == 3
        assert d["iterations"] == []
        assert d["feedback_history"] == []

    def test_to_dict_with_iteration(self):
        iter_result = IterationResult(
            iteration=1,
            worker_outputs={"a": "out"},
            supervisor_output="needs work",
            satisfaction=SatisfactionResult(satisfied=False, confidence=0.7),
        )
        r = SupervisorReviewResult(
            success=False,
            iterations_run=1,
            max_iterations=3,
            iterations=[iter_result],
            feedback_history=[
                FeedbackEntry(iteration=1, supervisor_output="needs work")
            ],
        )
        d = r.to_dict()
        assert len(d["iterations"]) == 1
        assert d["iterations"][0]["worker_outputs"] == {"a": "out"}
        assert d["iterations"][0]["satisfied"] is False
        assert len(d["feedback_history"]) == 1
