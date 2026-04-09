"""Pluggable satisfaction checkers for supervisor review loop (bd code_puppy-79p).

Three strategies are provided:

1. StructuredSatisfactionChecker — expects supervisor to emit JSON with a
   verdict field. Most reliable if the supervisor agent is prompted for it.
2. KeywordSatisfactionChecker — Orion-style keyword heuristic. Brittle but
   works as a zero-config fallback. Ported from Orion
   supervisor/orchestrator.py:179-187.
3. LLMJudgeSatisfactionChecker — uses a second LLM call to judge the
   supervisor output. Expensive. Stubbed in this round; full impl requires
   invoke_agent wiring (Round B).
"""

from __future__ import annotations

from typing import Protocol

from code_puppy.plugins.supervisor_review.models import SatisfactionResult

try:
    from code_puppy.utils.llm_parsing import extract_json_from_text
except ImportError:
    extract_json_from_text = None  # type: ignore[assignment]


__all__ = [
    "SatisfactionChecker",
    "StructuredSatisfactionChecker",
    "KeywordSatisfactionChecker",
    "LLMJudgeSatisfactionChecker",
    "get_satisfaction_checker",
]


class SatisfactionChecker(Protocol):
    """Protocol for pluggable satisfaction checkers."""

    def is_satisfied(self, supervisor_output: str) -> SatisfactionResult:
        """Return whether the supervisor output indicates the work is complete."""
        ...


# ---------------------------------------------------------------------------
# Structured (JSON) checker
# ---------------------------------------------------------------------------


_APPROVED_VERDICTS = frozenset(
    {
        "approved",
        "accept",
        "accepted",
        "complete",
        "completed",
        "done",
        "satisfied",
        "pass",
        "passed",
        "ok",
        "success",
        "successful",
    }
)

_REJECTED_VERDICTS = frozenset(
    {
        "rejected",
        "reject",
        "failed",
        "fail",
        "incomplete",
        "needs_work",
        "needs-work",
        "revise",
        "retry",
    }
)


class StructuredSatisfactionChecker:
    """Expects supervisor to emit JSON containing a verdict field.

    Accepted shapes:
        {"verdict": "approved"}
        {"verdict": "approved", "confidence": 0.9, "reason": "all tests pass"}
        {"satisfied": true, "reason": "..."}
        {"aligned": true, "issues": []}  (Orion-compatible)

    If no structured verdict is found, returns unsatisfied with low confidence.
    """

    def is_satisfied(self, supervisor_output: str) -> SatisfactionResult:
        if not supervisor_output:
            return SatisfactionResult(
                satisfied=False, confidence=0.0, reason="empty supervisor output"
            )

        if extract_json_from_text is None:
            return SatisfactionResult(
                satisfied=False,
                confidence=0.0,
                reason="llm_parsing.extract_json_from_text unavailable",
            )

        parsed = extract_json_from_text(supervisor_output)
        if parsed is None or not isinstance(parsed, dict):
            return SatisfactionResult(
                satisfied=False,
                confidence=0.1,
                reason="no structured JSON verdict found",
            )

        # Try multiple schemas: "verdict" string, "satisfied" bool, "aligned" bool
        # (orion-compatible)
        if "satisfied" in parsed and isinstance(parsed["satisfied"], bool):
            sat = parsed["satisfied"]
            confidence = float(parsed.get("confidence", 0.9 if sat else 0.9))
            reason = str(parsed.get("reason", "structured 'satisfied' field"))
            return SatisfactionResult(
                satisfied=sat, confidence=confidence, reason=reason
            )

        if "aligned" in parsed and isinstance(parsed["aligned"], bool):
            sat = parsed["aligned"]
            confidence = float(parsed.get("confidence", 0.9))
            reason = str(
                parsed.get("reason", parsed.get("notes", "orion-style aligned verdict"))
            )
            return SatisfactionResult(
                satisfied=sat, confidence=confidence, reason=reason
            )

        verdict_raw = parsed.get("verdict")
        if isinstance(verdict_raw, str):
            verdict = verdict_raw.strip().lower().replace(" ", "_").replace("-", "_")
            if verdict in _APPROVED_VERDICTS:
                confidence = float(parsed.get("confidence", 0.9))
                return SatisfactionResult(
                    satisfied=True,
                    confidence=confidence,
                    reason=str(parsed.get("reason", f"verdict={verdict_raw}")),
                )
            if verdict in _REJECTED_VERDICTS:
                confidence = float(parsed.get("confidence", 0.9))
                return SatisfactionResult(
                    satisfied=False,
                    confidence=confidence,
                    reason=str(parsed.get("reason", f"verdict={verdict_raw}")),
                )

        return SatisfactionResult(
            satisfied=False,
            confidence=0.2,
            reason=f"JSON present but no recognized verdict: {list(parsed.keys())}",
        )


# ---------------------------------------------------------------------------
# Keyword (Orion-style) checker
# ---------------------------------------------------------------------------


_KEYWORD_APPROVED = (
    "fully met",
    "fully satisfied",
    "fully aligned",
    "all requirements met",
    "approved",
    "lgtm",
    "looks good to me",
)

_KEYWORD_REJECTED = (
    "partially met",
    "not met",
    "needs work",
    "needs revision",
    "rejected",
    "not approved",
    "incomplete",
)


class KeywordSatisfactionChecker:
    """Port of Orion's keyword-based satisfaction check.

    Reference: orion-multistep-analysis supervisor/orchestrator.py:179-187.

    Brittle across models. Default-false on ambiguous output.
    """

    def is_satisfied(self, supervisor_output: str) -> SatisfactionResult:
        if not supervisor_output:
            return SatisfactionResult(
                satisfied=False, confidence=0.0, reason="empty supervisor output"
            )
        text = supervisor_output.lower()

        # Reject keywords take priority (Orion order)
        for keyword in _KEYWORD_REJECTED:
            if keyword in text:
                return SatisfactionResult(
                    satisfied=False,
                    confidence=0.7,
                    reason=f"found rejection keyword: {keyword!r}",
                )
        for keyword in _KEYWORD_APPROVED:
            if keyword in text:
                return SatisfactionResult(
                    satisfied=True,
                    confidence=0.7,
                    reason=f"found approval keyword: {keyword!r}",
                )

        return SatisfactionResult(
            satisfied=False,
            confidence=0.3,
            reason="no approval or rejection keywords found",
        )


# ---------------------------------------------------------------------------
# LLM judge checker (stub for Round A; full impl in Round B)
# ---------------------------------------------------------------------------


class LLMJudgeSatisfactionChecker:
    """Uses a second LLM call to judge supervisor satisfaction.

    This is a STUB in Round A — the full implementation requires wiring to
    invoke_agent, which is Round B's responsibility. For now, this checker
    delegates to StructuredSatisfactionChecker with a degraded confidence
    score so it's usable but honest about being a placeholder.
    """

    def __init__(self, judge_agent: str = "shepherd") -> None:
        self.judge_agent = judge_agent
        self._fallback = StructuredSatisfactionChecker()

    def is_satisfied(self, supervisor_output: str) -> SatisfactionResult:
        result = self._fallback.is_satisfied(supervisor_output)
        # Flag that this was the stubbed path
        return SatisfactionResult(
            satisfied=result.satisfied,
            confidence=max(0.0, result.confidence - 0.2),
            reason=f"[llm_judge stub: delegated to structured] {result.reason}",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_satisfaction_checker(mode: str) -> SatisfactionChecker:
    """Return the satisfaction checker for the given mode."""
    if mode == "structured":
        return StructuredSatisfactionChecker()
    if mode == "keyword":
        return KeywordSatisfactionChecker()
    if mode == "llm_judge":
        return LLMJudgeSatisfactionChecker()
    raise ValueError(
        f"Unknown satisfaction mode: {mode!r}. "
        f"Expected one of 'structured', 'keyword', 'llm_judge'."
    )
