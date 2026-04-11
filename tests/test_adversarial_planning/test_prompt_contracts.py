"""Contract tests verifying prompt outputs validate against models.

These tests ensure that JSON matching prompt instructions will actually
parse through model_validate() without errors.
"""

import pytest
from pydantic import ValidationError

from code_puppy.plugins.adversarial_planning.models import (
    Phase2Output,
    Phase4Output,
    Phase6Output,
    PlanStep,
    StepEvaluation,
    OperationalReadiness,
)


class TestPhase2ReviewerContract:
    """Tests that reviewer prompt output validates against Phase2Output."""

    def test_ship_readiness_values_accepted(self):
        """All documented ship_readiness values should validate.

        Prompt documentation lists: not_ready, needs_work, ready_with_caveats, ready
        These are stored in Phase2Output.overall dict.
        """
        valid_values = ["not_ready", "needs_work", "ready_with_caveats", "ready"]
        # Phase2Output.overall is a dict, so any valid dict is accepted
        # The model doesn't restrict the values directly, but the contract
        # is that these values should be used in prompts
        for value in valid_values:
            output = Phase2Output(
                reviewed_plan="A",
                overall={"ship_readiness": value, "score": 75},
                strongest_surviving_element="Good approach",
                operational_gaps=OperationalReadiness(
                    validation="Test plan exists",
                    rollout="Staged rollout defined",
                    rollback="Rollback documented",
                    monitoring="Monitoring in place",
                ),
            )
            assert output.overall["ship_readiness"] == value

    def test_wrong_problem_accepts_string_or_null(self):
        """wrong_problem should accept string or null, not boolean.

        The field is typed as string | null in the schema (dict field).
        """
        # String should work
        output_string = Phase2Output(
            reviewed_plan="A",
            overall={"wrong_problem": "The problem was misframed as X", "score": 50},
            strongest_surviving_element="Some element",
            operational_gaps=OperationalReadiness(
                validation="Test",
                rollout="Rollout",
                rollback="Rollback",
                monitoring="Monitor",
            ),
        )
        assert output_string.overall["wrong_problem"] == "The problem was misframed as X"

        # None/null should work
        output_null = Phase2Output(
            reviewed_plan="B",
            overall={"wrong_problem": None, "score": 80},
            strongest_surviving_element="Strong element",
            operational_gaps=OperationalReadiness(
                validation="Test",
                rollout="Rollout",
                rollback="Rollback",
                monitoring="Monitor",
            ),
        )
        assert output_null.overall["wrong_problem"] is None


class TestPhase4ArbiterContract:
    """Tests that arbiter prompt output validates against Phase4Output."""

    def test_merged_step_m_prefix_validates(self):
        """M-prefixed step IDs should validate.

        PlanStep.id pattern accepts A1, B1, M1, etc.
        """
        step_data = {
            "id": "M1",
            "category": "build",
            "what": "Implement feature",
            "why": "Required by spec",
            "how": "Write code",
            "risk": "Low",
            "risk_severity": "low",
            "mitigation": "Tests",
            "effort_hours_80pct": 2.0,
            "reversible": True,
            "approval_needed": "none",
            "exit_criteria": "Tests pass",
        }
        step = PlanStep(**step_data)
        assert step.id == "M1"
        assert step.id.startswith("M")

    def test_provenance_fields_optional(self):
        """source_plan and survival_reason should be optional."""
        step_data = {
            "id": "M2",
            "category": "test",
            "what": "Test it",
            "why": "Quality",
            "how": "pytest",
            "risk": "None",
            "risk_severity": "low",
            "mitigation": "N/A",
            "effort_hours_80pct": 0.5,
            "reversible": True,
            "approval_needed": "none",
            "exit_criteria": "Green",
        }
        step = PlanStep(**step_data)
        assert step.source_plan is None
        assert step.survival_reason is None

    def test_provenance_fields_accepted_when_provided(self):
        """source_plan and survival_reason should validate when provided."""
        step_data = {
            "id": "M3",
            "category": "docs",
            "what": "Document",
            "why": "Clarity",
            "how": "Markdown",
            "risk": "Typos",
            "risk_severity": "low",
            "mitigation": "Review",
            "effort_hours_80pct": 1.0,
            "reversible": True,
            "approval_needed": "none",
            "exit_criteria": "Published",
            "source_plan": "A",
            "survival_reason": "Verified approach",
        }
        step = PlanStep(**step_data)
        assert step.source_plan == "A"
        assert step.survival_reason == "Verified approach"

    def test_a_and_b_prefixes_still_valid(self):
        """Ensure A and B prefixes still validate (not just M)."""
        for prefix in ["A", "B"]:
            step_data = {
                "id": f"{prefix}1",
                "category": "build",
                "what": "Build feature",
                "why": "Need it",
                "how": "Code",
                "risk": "Medium",
                "risk_severity": "medium",
                "mitigation": "Careful review",
                "effort_hours_80pct": 4.0,
                "reversible": True,
                "approval_needed": "none",
                "exit_criteria": "Done",
            }
            step = PlanStep(**step_data)
            assert step.id == f"{prefix}1"


class TestPhase6DecisionContract:
    """Tests that decision prompt output validates against Phase6Output."""

    def test_plan_verdict_accepts_valid_values(self):
        """Plan verdict should accept go, conditional_go, no_go only."""
        valid_verdicts = ["go", "conditional_go", "no_go"]
        for verdict in valid_verdicts:
            output = Phase6Output(
                evaluations=[],
                execution_order=[],
                raw_plan_score=75,
                penalties=[],
                adjusted_plan_score=70,
                plan_verdict=verdict,  # type: ignore[arg-type]
                summary="Test verdict",
            )
            assert output.plan_verdict == verdict

    def test_plan_verdict_rejects_defer_skip(self):
        """defer and skip should NOT be valid for plan_verdict."""
        invalid_verdicts = ["defer", "skip"]
        # These are only valid for StepEvaluation.verdict
        for verdict in invalid_verdicts:
            with pytest.raises(ValidationError) as exc_info:
                Phase6Output(
                    evaluations=[],
                    execution_order=[],
                    raw_plan_score=75,
                    penalties=[],
                    adjusted_plan_score=70,
                    plan_verdict=verdict,  # type: ignore[arg-type]
                    summary="Invalid verdict test",
                )
            assert "plan_verdict" in str(exc_info.value)

    def test_step_evaluation_accepts_defer_skip(self):
        """StepEvaluation.verdict CAN use defer and skip."""
        valid_step_verdicts = ["do", "conditional", "defer", "skip"]
        for verdict in valid_step_verdicts:
            eval_data = {
                "step_id": "M1",
                "impact_score": 50.0,
                "feasibility_score": 60.0,
                "risk_adjusted_score": 55.0,
                "urgency_score": 70.0,
                "weighted_score": 58.0,
                "verdict": verdict,
            }
            step_eval = StepEvaluation(**eval_data)
            assert step_eval.verdict == verdict

    def test_step_evaluation_verdict_rejects_invalid(self):
        """StepEvaluation.verdict should reject go, no_go, conditional_go."""
        invalid_step_verdicts = ["go", "no_go", "conditional_go"]
        for verdict in invalid_step_verdicts:
            with pytest.raises(ValidationError) as exc_info:
                StepEvaluation(
                    step_id="M1",
                    impact_score=50.0,
                    feasibility_score=60.0,
                    risk_adjusted_score=55.0,
                    urgency_score=70.0,
                    weighted_score=58.0,
                    verdict=verdict,  # type: ignore[arg-type]
                )
            assert "verdict" in str(exc_info.value)

    def test_complete_phase6_with_step_evaluations(self):
        """Test a complete Phase6Output with valid step evaluations."""
        step_evals = [
            StepEvaluation(
                step_id="M1",
                impact_score=80.0,
                feasibility_score=90.0,
                risk_adjusted_score=85.0,
                urgency_score=70.0,
                weighted_score=81.0,
                verdict="do",
            ),
            StepEvaluation(
                step_id="M2",
                impact_score=30.0,
                feasibility_score=40.0,
                risk_adjusted_score=35.0,
                urgency_score=20.0,
                weighted_score=31.0,
                verdict="defer",
            ),
            StepEvaluation(
                step_id="M3",
                impact_score=10.0,
                feasibility_score=20.0,
                risk_adjusted_score=15.0,
                urgency_score=5.0,
                weighted_score=12.0,
                verdict="skip",
            ),
        ]

        output = Phase6Output(
            evaluations=step_evals,
            execution_order=["M1"],
            raw_plan_score=70,
            penalties=[],
            adjusted_plan_score=70,
            plan_verdict="conditional_go",
            summary="Conditional go based on evaluation",
            plan_condition="Resolve blockers first",
        )

        assert len(output.evaluations) == 3
        assert output.plan_verdict == "conditional_go"
        assert output.plan_condition is not None
