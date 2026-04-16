"""Test Pydantic model validation for adversarial planning."""

import pytest
from pydantic import ValidationError

from code_puppy.plugins.adversarial_planning.models import (
    Evidence,
    EvidenceSource,
    EvidenceClass,
    CriticalUnknown,
    PlanStep,
    Phase0AOutput,
    Phase0BOutput,
    Phase1Output,
    Phase6Output,
    AdversarialPlanConfig,
    WorkspaceContext,
    Penalty,
    OperationalReadiness,
    Blocker,
    Attack,
    ChangeSet,
    StepEvaluation,
    StepReview,
)


class TestEvidenceModels:
    """Test evidence-related models."""

    def test_evidence_source_valid(self):
        """Test valid evidence source creation."""
        source = EvidenceSource(
            kind="file",
            locator="src/main.py:10-20",
            freshness="2024-01-15",
            version_or_commit="abc123",
        )
        assert source.kind == "file"
        assert source.locator == "src/main.py:10-20"

    def test_evidence_source_invalid_kind(self):
        """Test invalid evidence source kind."""
        with pytest.raises(ValidationError):
            EvidenceSource(kind="invalid", locator="test")

    def test_evidence_source_all_valid_kinds(self):
        """Test all valid evidence source kinds."""
        valid_kinds = ["file", "test", "config", "ci", "log", "metric", "url", "prompt"]
        for kind in valid_kinds:
            source = EvidenceSource(kind=kind, locator="test")
            assert source.kind == kind

    def test_evidence_valid(self):
        """Test valid evidence creation."""
        evidence = Evidence(
            id="EV1",
            evidence_class=EvidenceClass.VERIFIED,
            claim="File exists",
            source=EvidenceSource(kind="file", locator="test.py"),
            confidence=90,
        )
        assert evidence.id == "EV1"
        assert evidence.evidence_class == EvidenceClass.VERIFIED

    def test_evidence_confidence_bounds_valid(self):
        """Test evidence confidence at bounds."""
        # At lower bound
        ev1 = Evidence(
            id="EV1",
            evidence_class=EvidenceClass.VERIFIED,
            claim="Test",
            source=EvidenceSource(kind="file", locator="test"),
            confidence=0,
        )
        assert ev1.confidence == 0

        # At upper bound
        ev2 = Evidence(
            id="EV2",
            evidence_class=EvidenceClass.VERIFIED,
            claim="Test",
            source=EvidenceSource(kind="file", locator="test"),
            confidence=100,
        )
        assert ev2.confidence == 100

    def test_evidence_confidence_out_of_bounds(self):
        """Test evidence confidence out of bounds fails validation."""
        with pytest.raises(ValidationError):
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Test",
                source=EvidenceSource(kind="file", locator="test"),
                confidence=150,  # Invalid
            )

    def test_evidence_invalid_id_format(self):
        """Test evidence ID must match EV\d+ pattern."""
        with pytest.raises(ValidationError):
            Evidence(
                id="invalid-id",  # Must be EV\d+
                evidence_class=EvidenceClass.VERIFIED,
                claim="Test",
                source=EvidenceSource(kind="file", locator="test"),
                confidence=90,
            )

    def test_evidence_class_values(self):
        """Test all evidence class enum values."""
        assert EvidenceClass.VERIFIED.value == "verified"
        assert EvidenceClass.INFERENCE.value == "inference"
        assert EvidenceClass.ASSUMPTION.value == "assumption"
        assert EvidenceClass.UNKNOWN.value == "unknown"

    def test_evidence_class_from_string(self):
        """Test evidence class accepts string values via validator."""
        evidence = Evidence(
            id="EV1",
            evidence_class="verified",  # String, not enum
            claim="Test",
            source=EvidenceSource(kind="file", locator="test.py"),
            confidence=90,
        )
        assert evidence.evidence_class == EvidenceClass.VERIFIED


class TestCriticalUnknown:
    """Test critical unknown model."""

    def test_critical_unknown_required_fields(self):
        """Test critical unknown requires key fields."""
        unknown = CriticalUnknown(
            id="UNK1",
            question="What is X?",
            why_it_matters="Affects architecture",
            fastest_probe="Check config",
        )
        assert unknown.can_proceed_without is False  # Default
        assert unknown.id == "UNK1"

    def test_critical_unknown_reversibility(self):
        """Test reversibility enum values."""
        for reversibility in ["reversible", "hard_to_reverse", "must_know_first"]:
            unknown = CriticalUnknown(
                id="UNK1",
                question="Test",
                why_it_matters="Test",
                fastest_probe="Test",
                reversibility=reversibility,
            )
            assert unknown.reversibility == reversibility

    def test_critical_unknown_invalid_reversibility(self):
        """Test invalid reversibility fails."""
        with pytest.raises(ValidationError):
            CriticalUnknown(
                id="UNK1",
                question="Test",
                why_it_matters="Test",
                fastest_probe="Test",
                reversibility="invalid_value",
            )

    def test_critical_unknown_id_pattern(self):
        """Test critical unknown ID must match UNK\d+ pattern."""
        with pytest.raises(ValidationError):
            CriticalUnknown(
                id="invalid",
                question="Test",
                why_it_matters="Test",
                fastest_probe="Test",
            )


class TestPlanStep:
    """Test plan step model."""

    def test_plan_step_valid(self, sample_plan_step):
        """Test valid plan step."""
        assert sample_plan_step.id == "A1"
        assert sample_plan_step.reversible is True
        assert sample_plan_step.risk_severity in ["low", "medium", "high", "critical"]

    def test_plan_step_id_pattern(self):
        """Test plan step ID must match A\d+ or B\d+ pattern."""
        # Valid patterns
        for step_id in ["A1", "A12", "B1", "B99"]:
            step = PlanStep(
                id=step_id,
                category="build",
                what="Test",
                why="Test",
                how="Test",
                risk="None",
                risk_severity="low",
                mitigation="None",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed="none",
                exit_criteria="Done",
            )
            assert step.id == step_id

        # Invalid pattern
        with pytest.raises(ValidationError):
            PlanStep(
                id="C1",  # Must start with A or B
                category="build",
                what="Test",
                why="Test",
                how="Test",
                risk="None",
                risk_severity="low",
                mitigation="None",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed="none",
                exit_criteria="Done",
            )

    def test_plan_step_category_values(self):
        """Test valid category values."""
        valid_categories = [
            "discovery", "design", "build", "test",
            "rollout", "rollback", "monitoring", "docs"
        ]
        for cat in valid_categories:
            step = PlanStep(
                id="A1",
                category=cat,
                what="Test",
                why="Test",
                how="Test",
                risk="None",
                risk_severity="low",
                mitigation="None",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed="none",
                exit_criteria="Done",
            )
            assert step.category == cat

    def test_plan_step_invalid_category(self):
        """Test invalid category fails validation."""
        with pytest.raises(ValidationError):
            PlanStep(
                id="A1",
                category="invalid_category",
                what="Test",
                why="Test",
                how="Test",
                risk="None",
                risk_severity="low",
                mitigation="None",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed="none",
                exit_criteria="Done",
            )

    def test_plan_step_risk_severity_values(self):
        """Test valid risk severity values."""
        for severity in ["low", "medium", "high", "critical"]:
            step = PlanStep(
                id="A1",
                category="build",
                what="Test",
                why="Test",
                how="Test",
                risk="Test risk",
                risk_severity=severity,
                mitigation="Test mitigation",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed="none",
                exit_criteria="Done",
            )
            assert step.risk_severity == severity

    def test_plan_step_approval_values(self):
        """Test valid approval needed values."""
        for approval in ["none", "write_access", "production_change", "security_or_compliance"]:
            step = PlanStep(
                id="A1",
                category="build",
                what="Test",
                why="Test",
                how="Test",
                risk="None",
                risk_severity="low",
                mitigation="None",
                effort_hours_80pct=1,
                reversible=True,
                approval_needed=approval,
                exit_criteria="Done",
            )
            assert step.approval_needed == approval


class TestMergedStepValidation:
    """Tests for M-prefixed merged step ID validation."""

    def test_plan_step_accepts_a_prefix(self, sample_plan_step_data):
        """A-prefix IDs should validate for Plan A steps."""
        data = sample_plan_step_data.copy()
        data["id"] = "A1"
        step = PlanStep(**data)
        assert step.id == "A1"

    def test_plan_step_accepts_b_prefix(self, sample_plan_step_data):
        """B-prefix IDs should validate for Plan B steps."""
        data = sample_plan_step_data.copy()
        data["id"] = "B5"
        step = PlanStep(**data)
        assert step.id == "B5"

    def test_plan_step_accepts_m_prefix(self, sample_plan_step_data):
        """M-prefix IDs should validate for merged steps."""
        data = sample_plan_step_data.copy()
        data["id"] = "M1"
        step = PlanStep(**data)
        assert step.id == "M1"

    def test_plan_step_rejects_invalid_prefix(self, sample_plan_step_data):
        """Invalid prefixes should raise ValidationError."""
        data = sample_plan_step_data.copy()
        data["id"] = "X1"  # Invalid prefix
        with pytest.raises(ValidationError):
            PlanStep(**data)

    def test_provenance_fields_optional(self, sample_plan_step_data):
        """source_plan and survival_reason should be optional."""
        data = sample_plan_step_data.copy()
        data["id"] = "M1"
        # Don't set provenance fields
        step = PlanStep(**data)
        assert step.source_plan is None
        assert step.survival_reason is None

    def test_provenance_fields_accepted(self, sample_plan_step_data):
        """Provenance fields should be accepted when provided."""
        data = sample_plan_step_data.copy()
        data["id"] = "M1"
        data["source_plan"] = "merged"
        data["survival_reason"] = "Best of both worlds"
        step = PlanStep(**data)
        assert step.source_plan == "merged"
        assert step.survival_reason == "Best of both worlds"


class TestOperationalReadiness:
    """Test operational readiness model."""

    def test_operational_readiness_valid(self):
        """Test valid operational readiness."""
        or_model = OperationalReadiness(
            validation="Run tests",
            rollout="Gradual rollout",
            rollback="Revert commit",
            monitoring="Track metrics",
        )
        assert or_model.validation == "Run tests"
        assert or_model.rollback_time is None  # Optional field

    def test_operational_readiness_required_fields(self):
        """Test required fields cannot be empty."""
        with pytest.raises(ValidationError):
            OperationalReadiness(
                validation="",  # Empty not allowed (min_length=1)
                rollout="Test",
                rollback="Test",
                monitoring="Test",
            )


class TestPhaseOutputs:
    """Test phase output models."""

    def test_phase_0a_output(self, sample_phase_0a_output):
        """Test Phase 0A output validation."""
        assert sample_phase_0a_output.readiness == "ready"
        assert len(sample_phase_0a_output.evidence) == 3
        assert 0 <= sample_phase_0a_output.confidence <= 100

    def test_phase_0a_readiness_values(self):
        """Test valid readiness values."""
        for readiness in ["ready", "limited", "blocked"]:
            output = Phase0AOutput(
                readiness=readiness,
                confidence=50,
                workspace_summary="Test",
                problem_signature="Test",
            )
            assert output.readiness == readiness

    def test_phase_0a_invalid_readiness(self):
        """Test invalid readiness fails."""
        with pytest.raises(ValidationError):
            Phase0AOutput(
                readiness="invalid",
                confidence=50,
                workspace_summary="Test",
                problem_signature="Test",
            )

    def test_phase_0b_output(self, sample_phase_0b_output):
        """Test Phase 0B output validation."""
        assert sample_phase_0b_output.problem_type == "feature"
        assert len(sample_phase_0b_output.hard_constraints) > 0

    def test_phase_0b_problem_types(self):
        """Test valid problem types."""
        valid_types = [
            "feature", "bugfix", "migration", "incident",
            "replatform", "performance", "security"
        ]
        for ptype in valid_types:
            output = Phase0BOutput(
                normalized_problem="Test",
                problem_type=ptype,
            )
            assert output.problem_type == ptype

    def test_phase_1_output(self, sample_plan_a):
        """Test Phase 1 output validation."""
        assert sample_plan_a.plan_id == "A"
        assert sample_plan_a.posture == "conservative"
        assert sample_plan_a.estimated_hours_80pct >= 0

    def test_phase_1_posture_values(self):
        """Test valid posture values."""
        for posture in ["conservative", "contrarian"]:
            output = Phase1Output(
                plan_id="A",
                posture=posture,
                problem_restatement="Test",
                approach_summary="Test",
                operational_readiness=OperationalReadiness(
                    validation="Test", rollout="Test", rollback="Test", monitoring="Test"
                ),
                estimated_hours_80pct=20,
                estimated_calendar_days=5,
            )
            assert output.posture == posture

    def test_phase_1_plan_id_values(self):
        """Test valid plan_id values."""
        for plan_id in ["A", "B"]:
            output = Phase1Output(
                plan_id=plan_id,
                posture="conservative",
                problem_restatement="Test",
                approach_summary="Test",
                operational_readiness=OperationalReadiness(
                    validation="Test", rollout="Test", rollback="Test", monitoring="Test"
                ),
                estimated_hours_80pct=20,
                estimated_calendar_days=5,
            )
            assert output.plan_id == plan_id

    def test_phase_2_output(self, sample_review_a):
        """Test Phase 2 output validation."""
        assert sample_review_a.reviewed_plan == "A"
        assert sample_review_a.strongest_surviving_element is not None

    def test_phase_4_output(self, sample_phase_4_output):
        """Test Phase 4 output validation."""
        assert sample_phase_4_output.merged_confidence >= 0
        assert sample_phase_4_output.merged_confidence <= 100

    def test_phase_5_output(self, sample_phase_5_output):
        """Test Phase 5 output validation."""
        assert isinstance(sample_phase_5_output.clean_bill_of_health, bool)

    def test_phase_6_output_verdict_values(self):
        """Test valid plan verdict values."""
        for verdict in ["go", "conditional_go", "no_go"]:
            output = Phase6Output(
                raw_plan_score=75,
                adjusted_plan_score=70,
                plan_verdict=verdict,
                summary="Test",
            )
            assert output.plan_verdict == verdict

    def test_phase_7_output(self, sample_phase_7_output):
        """Test Phase 7 output validation."""
        assert len(sample_phase_7_output.change_sets) == 2
        assert "verification_sequence" in sample_phase_7_output.model_fields


class TestBlocker:
    """Test blocker model."""

    def test_blocker_valid(self):
        """Test valid blocker creation."""
        blocker = Blocker(
            id="BLK1",
            description="Critical issue",
            severity="blocker",
            repair_path="Fix it",
        )
        assert blocker.id == "BLK1"
        assert blocker.kill_recommendation is False  # Default

    def test_blocker_severity_values(self):
        """Test valid severity values."""
        for severity in ["blocker", "critical", "major"]:
            blocker = Blocker(
                id="BLK1",
                description="Test",
                severity=severity,
            )
            assert blocker.severity == severity


class TestPenalty:
    """Test penalty model."""

    def test_penalty_model(self):
        """Test penalty model."""
        penalty = Penalty(reason="same-model fallback", points=15)
        assert penalty.points == 15
        assert penalty.reason == "same-model fallback"


class TestAttack:
    """Test attack model."""

    def test_attack_valid(self):
        """Test valid attack creation."""
        attack = Attack(
            id="ATK1",
            category="input_validation",
            description="SQL injection risk",
            likelihood="low",
            impact="critical",
            recommendation="Use parameterized queries",
        )
        assert attack.id == "ATK1"
        assert attack.impact == "critical"


class TestChangeSet:
    """Test change set model."""

    def test_change_set_valid(self):
        """Test valid change set."""
        cs = ChangeSet(
            id="CS1",
            goal="Add feature",
            files=["file.py"],
            reversible=True,
            verification=["Test passes"],
        )
        assert cs.id == "CS1"
        assert cs.reversible is True


class TestStepEvaluation:
    """Test step evaluation model."""

    def test_step_evaluation_valid(self):
        """Test valid step evaluation."""
        eval_model = StepEvaluation(
            step_id="A1",
            impact_score=80,
            feasibility_score=85,
            risk_adjusted_score=75,
            urgency_score=90,
            weighted_score=82,
            verdict="do",
        )
        assert eval_model.verdict == "do"
        assert 0 <= eval_model.impact_score <= 100

    def test_step_evaluation_verdict_values(self):
        """Test valid verdict values."""
        for verdict in ["do", "conditional", "defer", "skip"]:
            eval_model = StepEvaluation(
                step_id="A1",
                impact_score=50,
                feasibility_score=50,
                risk_adjusted_score=50,
                urgency_score=50,
                weighted_score=50,
                verdict=verdict,
            )
            assert eval_model.verdict == verdict


class TestStepReview:
    """Test step review model."""

    def test_step_review_valid(self):
        """Test valid step review."""
        review = StepReview(
            step_id="A1",
            verdict="accept",
            issues=[],
            suggestions=["Add more validation"],
        )
        assert review.step_id == "A1"
        assert review.verdict == "accept"

    def test_step_review_verdict_values(self):
        """Test valid verdict values."""
        for verdict in ["accept", "modify", "reject"]:
            review = StepReview(
                step_id="A1",
                verdict=verdict,
            )
            assert review.verdict == verdict


class TestConfigModels:
    """Test configuration models."""

    def test_workspace_context(self):
        """Test workspace context."""
        ctx = WorkspaceContext(
            workspace="/home/user/project",
            branch_or_commit="feature-branch",
            access_limitations=["no-prod-access"],
        )
        assert ctx.workspace == "/home/user/project"

    def test_adversarial_plan_config(self, sample_config):
        """Test full config."""
        assert sample_config.mode == "auto"
        assert "OAuth2" in sample_config.task

    def test_config_mode_values(self):
        """Test valid mode values."""
        for mode in ["auto", "standard", "deep"]:
            config = AdversarialPlanConfig(
                mode=mode,
                context=WorkspaceContext(workspace="/test"),
                task="Test task",
            )
            assert config.mode == mode
