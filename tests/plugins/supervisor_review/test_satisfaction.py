"""Tests for supervisor_review.satisfaction (bd code_puppy-79p)."""

from __future__ import annotations

import json

import pytest

from code_puppy.plugins.supervisor_review.satisfaction import (
    KeywordSatisfactionChecker,
    LLMJudgeSatisfactionChecker,
    StructuredSatisfactionChecker,
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


class TestLLMJudgeSatisfactionChecker:
    def test_stub_delegates_with_lower_confidence(self):
        checker = LLMJudgeSatisfactionChecker()
        r = checker.is_satisfied(json.dumps({"verdict": "approved", "confidence": 0.9}))
        assert r.satisfied is True
        assert r.confidence < 0.9  # degraded
        assert "llm_judge stub" in r.reason

    def test_stub_logs_warning_on_first_use(self, caplog):
        """Stub logs a warning on first use to make behavior explicit (code_puppy-bnp)."""
        import logging

        # Reset the warning flag to ensure we test the first-use behavior
        LLMJudgeSatisfactionChecker._warning_logged = False

        with caplog.at_level(logging.WARNING):
            checker = LLMJudgeSatisfactionChecker()
            r = checker.is_satisfied(json.dumps({"verdict": "approved"}))

        # Warning should be logged on first use
        assert "LLMJudgeSatisfactionChecker is a stub" in caplog.text
        assert "delegates to StructuredSatisfactionChecker" in caplog.text
        assert "Configure a custom judge_agent_fn" in caplog.text

    def test_stub_warning_logged_only_once(self, caplog):
        """Warning is only logged once, not on every call (code_puppy-bnp)."""
        import logging

        # Reset the warning flag
        LLMJudgeSatisfactionChecker._warning_logged = False

        with caplog.at_level(logging.WARNING):
            checker1 = LLMJudgeSatisfactionChecker()
            checker1.is_satisfied(json.dumps({"verdict": "approved"}))

            # Clear the log records
            caplog.clear()

            # Create a new instance - warning should NOT be logged again
            checker2 = LLMJudgeSatisfactionChecker()
            checker2.is_satisfied(json.dumps({"verdict": "approved"}))

        # No new warning should be logged
        assert "LLMJudgeSatisfactionChecker is a stub" not in caplog.text


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
