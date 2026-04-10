"""Tests for supervisor_review.satisfaction (bd code_puppy-79p, code_puppy-056)."""

from __future__ import annotations

import json

import pytest

from code_puppy.plugins.supervisor_review.satisfaction import (
    KeywordSatisfactionChecker,
    LLMJudgeSatisfactionChecker,
    StructuredSatisfactionChecker,
    _parse_judge_response,
    get_satisfaction_checker,
)


class TestStructuredSatisfactionChecker:
    def _check(self, text: str):
        return StructuredSatisfactionChecker().is_satisfied(text)

    def test_empty(self):
        r = self._check("")
        assert r.satisfied is False
        assert "empty" in r.reason

    def test_verdict_approved(self):
        r = self._check(json.dumps({"verdict": "approved", "confidence": 0.95}))
        assert r.satisfied is True
        assert r.confidence == 0.95

    def test_verdict_rejected(self):
        r = self._check(json.dumps({"verdict": "rejected"}))
        assert r.satisfied is False

    def test_satisfied_bool_true(self):
        r = self._check(json.dumps({"satisfied": True, "reason": "all good"}))
        assert r.satisfied is True
        assert r.reason == "all good"

    def test_satisfied_bool_false(self):
        r = self._check(json.dumps({"satisfied": False}))
        assert r.satisfied is False
        assert r.confidence < 0.9  # rejection confidence default is 0.6

    def test_orion_aligned_true(self):
        r = self._check(json.dumps({"aligned": True, "issues": []}))
        assert r.satisfied is True

    def test_orion_aligned_false(self):
        r = self._check(json.dumps({"aligned": False, "issues": ["x"]}))
        assert r.satisfied is False

    def test_verdict_in_markdown_fence(self):
        r = self._check('```json\n{"verdict": "approved"}\n```')
        assert r.satisfied is True

    def test_verdict_with_hyphen_normalized(self):
        r = self._check(json.dumps({"verdict": "needs-work"}))
        assert r.satisfied is False

    def test_unrecognized_json(self):
        r = self._check(json.dumps({"random": "field"}))
        assert r.satisfied is False
        assert "no recognized verdict" in r.reason

    def test_non_json_text(self):
        r = self._check("this is not json at all")
        assert r.satisfied is False


class TestKeywordSatisfactionChecker:
    def _check(self, text: str):
        return KeywordSatisfactionChecker().is_satisfied(text)

    def test_empty(self):
        assert self._check("").satisfied is False

    def test_fully_met(self):
        r = self._check("Everything looks good. Fully met.")
        assert r.satisfied is True

    def test_fully_satisfied(self):
        assert self._check("Fully satisfied with the work.").satisfied is True

    def test_needs_work(self):
        r = self._check("The output is good but needs work on error handling.")
        assert r.satisfied is False

    def test_not_met(self):
        assert self._check("Requirements not met.").satisfied is False

    def test_partially_met_rejected(self):
        assert self._check("Requirements partially met.").satisfied is False

    def test_rejection_takes_priority(self):
        # If both keywords are present, rejection wins (Orion-style)
        r = self._check("Needs work. But mostly fully met.")
        assert r.satisfied is False

    def test_ambiguous(self):
        r = self._check("I reviewed the code.")
        assert r.satisfied is False
        assert "no approval or rejection" in r.reason


class TestParseJudgeResponse:
    """Tests for _parse_judge_response helper (bd code_puppy-056)."""

    def test_empty_response(self):
        r = _parse_judge_response("")
        assert r.satisfied is False
        assert r.confidence == 0.0
        assert "empty" in r.reason

    def test_structured_json_satisfied_true(self):
        r = _parse_judge_response(
            json.dumps({"satisfied": True, "confidence": 0.9, "reason": "all done"})
        )
        assert r.satisfied is True
        assert r.confidence == 0.9
        assert r.reason == "all done"

    def test_structured_json_satisfied_false(self):
        r = _parse_judge_response(
            json.dumps({"satisfied": False, "confidence": 0.85, "reason": "issues found"})
        )
        assert r.satisfied is False
        assert r.confidence == 0.85

    def test_structured_json_default_confidence(self):
        r = _parse_judge_response(json.dumps({"satisfied": True}))
        assert r.satisfied is True
        assert r.confidence == 0.8  # default when not specified

    def test_keyword_approval_fallback(self):
        r = _parse_judge_response("The work is complete and approved by the supervisor.")
        assert r.satisfied is True
        assert "keyword heuristic" in r.reason

    def test_keyword_rejection_fallback(self):
        r = _parse_judge_response("The supervisor says the work needs work.")
        assert r.satisfied is False
        assert "keyword heuristic" in r.reason

    def test_unparseable_response(self):
        r = _parse_judge_response("I am not sure what to make of this.")
        assert r.satisfied is False
        assert r.confidence == 0.3
        assert "could not parse" in r.reason


class TestLLMJudgeSatisfactionChecker:
    """Tests for the full LLMJudgeSatisfactionChecker (bd code_puppy-056)."""

    def test_sync_fallback_delegates_to_structured(self):
        """Sync is_satisfied delegates to structured with degraded confidence."""
        checker = LLMJudgeSatisfactionChecker()
        r = checker.is_satisfied(json.dumps({"verdict": "approved", "confidence": 0.9}))
        assert r.satisfied is True
        assert r.confidence < 0.9  # degraded by 0.1
        assert "sync fallback" in r.reason

    def test_sync_fallback_empty_output(self):
        checker = LLMJudgeSatisfactionChecker()
        r = checker.is_satisfied("")
        assert r.satisfied is False

    def test_constructor_default_judge_agent(self):
        checker = LLMJudgeSatisfactionChecker()
        assert checker.judge_agent == "shepherd"

    def test_constructor_custom_judge_agent(self):
        checker = LLMJudgeSatisfactionChecker(judge_agent="custom-reviewer")
        assert checker.judge_agent == "custom-reviewer"

    def test_constructor_with_invoke_fn(self):
        async def mock_invoke(agent_name, prompt, session_id=None):
            return '{"satisfied": true}'

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        assert checker._invoke_agent_fn is mock_invoke

    def test_has_async_method(self):
        """LLMJudgeSatisfactionChecker must have is_satisfied_async for orchestrator."""
        import asyncio

        checker = LLMJudgeSatisfactionChecker()
        assert hasattr(checker, "is_satisfied_async")
        assert asyncio.iscoroutinefunction(checker.is_satisfied_async)

    @pytest.mark.asyncio
    async def test_async_satisfied_via_injected_fn(self):
        """Async path invokes judge and parses structured response."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            assert agent_name == "shepherd"
            assert "Supervisor's review output" in prompt
            return json.dumps({"satisfied": True, "confidence": 0.92, "reason": "looks good"})

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async("All tests pass. Work is complete.")
        assert r.satisfied is True
        assert r.confidence == 0.92
        assert r.reason == "looks good"

    @pytest.mark.asyncio
    async def test_async_rejected_via_injected_fn(self):
        """Async path correctly detects rejection."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            return json.dumps({"satisfied": False, "confidence": 0.8, "reason": "tests failing"})

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async("Some issues remain. Needs revision.")
        assert r.satisfied is False
        assert r.reason == "tests failing"

    @pytest.mark.asyncio
    async def test_async_custom_judge_agent(self):
        """Async path uses the configured judge_agent name."""
        called_with_agent = []

        async def mock_invoke(agent_name, prompt, session_id=None):
            called_with_agent.append(agent_name)
            return json.dumps({"satisfied": True})

        checker = LLMJudgeSatisfactionChecker(
            judge_agent="my-custom-judge", invoke_agent_fn=mock_invoke
        )
        await checker.is_satisfied_async("supervisor output")
        assert called_with_agent == ["my-custom-judge"]

    @pytest.mark.asyncio
    async def test_async_fallback_on_invoke_failure(self):
        """Async path falls back to structured checker if judge agent fails."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            raise RuntimeError("agent unavailable")

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async(
            json.dumps({"verdict": "approved", "confidence": 0.9})
        )
        # Should fall back to sync path (structured with degraded confidence)
        assert r.satisfied is True
        assert "sync fallback" in r.reason

    @pytest.mark.asyncio
    async def test_async_empty_supervisor_output(self):
        """Async path handles empty supervisor output."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            raise AssertionError("should not be called for empty output")

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async("")
        assert r.satisfied is False
        assert r.confidence == 0.0

    @pytest.mark.asyncio
    async def test_async_judge_returns_garbage(self):
        """Async path handles unparseable judge response gracefully."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            return "I don't understand the question."

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async("supervisor says stuff")
        assert r.satisfied is False
        assert "could not parse" in r.reason

    @pytest.mark.asyncio
    async def test_async_judge_returns_none(self):
        """Async path handles None response from judge agent."""
        async def mock_invoke(agent_name, prompt, session_id=None):
            return None

        checker = LLMJudgeSatisfactionChecker(invoke_agent_fn=mock_invoke)
        r = await checker.is_satisfied_async("supervisor output text")
        assert r.satisfied is False
        assert "empty" in r.reason


class TestGetSatisfactionChecker:
    def test_structured(self):
        c = get_satisfaction_checker("structured")
        assert isinstance(c, StructuredSatisfactionChecker)

    def test_keyword(self):
        c = get_satisfaction_checker("keyword")
        assert isinstance(c, KeywordSatisfactionChecker)

    def test_llm_judge(self):
        c = get_satisfaction_checker("llm_judge")
        assert isinstance(c, LLMJudgeSatisfactionChecker)

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown satisfaction mode"):
            get_satisfaction_checker("magic")
