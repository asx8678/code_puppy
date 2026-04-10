"""Test adversarial planning orchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from code_puppy.plugins.adversarial_planning.orchestrator import (
    AdversarialPlanningOrchestrator,
    GlobalStopCondition,
)
from code_puppy.plugins.adversarial_planning.validators import needs_rebuttal
from code_puppy.plugins.adversarial_planning.models import (
    AdversarialPlanConfig,
    WorkspaceContext,
)


class TestOrchestratorInit:
    """Test orchestrator initialization."""

    def test_init_creates_session(self, sample_config):
        """Test orchestrator creates a planning session."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        assert orchestrator.session is not None
        assert orchestrator.session.current_phase == "init"
        assert orchestrator.session_id.startswith("ap-")

    def test_init_generates_unique_session_ids(self, sample_config):
        """Test each orchestrator gets unique session ID."""
        orch1 = AdversarialPlanningOrchestrator(sample_config)
        orch2 = AdversarialPlanningOrchestrator(sample_config)

        assert orch1.session_id != orch2.session_id

    def test_init_with_custom_invoke(self, sample_config, mock_invoke_agent):
        """Test orchestrator accepts custom invoke function."""
        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=mock_invoke_agent,
        )

        assert orchestrator._invoke_agent == mock_invoke_agent

    def test_init_with_custom_emit(self, sample_config, mock_emit_progress):
        """Test orchestrator accepts custom emit function."""
        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            emit_progress_fn=mock_emit_progress,
        )

        assert orchestrator._emit_progress == mock_emit_progress


class TestModeSelection:
    """Test mode selection logic."""

    def test_mode_standard_forced(self, sample_config):
        """Test standard mode when explicitly set."""
        sample_config.mode = "standard"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "standard"

    def test_mode_deep_forced(self, sample_config):
        """Test deep mode when explicitly set."""
        sample_config.mode = "deep"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_mode_auto_selects_deep_for_security_risk(self, sample_config, sample_phase_0a_output):
        """Test auto mode selects deep for security_risk evidence."""
        sample_config.mode = "auto"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        # Add security_risk evidence
        from code_puppy.plugins.adversarial_planning.models import Evidence, EvidenceSource, EvidenceClass
        sample_phase_0a_output.evidence.append(
            Evidence(
                id="EV99",
                evidence_class=EvidenceClass.VERIFIED,
                claim="security_risk: authentication bypass possible",
                source=EvidenceSource(kind="file", locator="auth.py"),
                confidence=90,
            )
        )
        orchestrator.session.phase_0a_output = sample_phase_0a_output

        orchestrator._select_mode()
        assert orchestrator.session.mode_selected == "deep"

    def test_mode_auto_selects_deep_for_production_change(self, sample_config, sample_phase_0a_output):
        """Test auto mode selects deep for production_change evidence."""
        sample_config.mode = "auto"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        from code_puppy.plugins.adversarial_planning.models import Evidence, EvidenceSource, EvidenceClass
        sample_phase_0a_output.evidence.append(
            Evidence(
                id="EV99",
                evidence_class=EvidenceClass.VERIFIED,
                claim="This involves a production_change deployment",
                source=EvidenceSource(kind="config", locator="deploy.yml"),
                confidence=95,
            )
        )
        orchestrator.session.phase_0a_output = sample_phase_0a_output

        orchestrator._select_mode()
        assert orchestrator.session.mode_selected == "deep"

    def test_mode_auto_selects_deep_for_data_migration(self, sample_config, sample_phase_0a_output):
        """Test auto mode selects deep for data_migration evidence."""
        sample_config.mode = "auto"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        from code_puppy.plugins.adversarial_planning.models import Evidence, EvidenceSource, EvidenceClass
        sample_phase_0a_output.evidence.append(
            Evidence(
                id="EV99",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Requires data_migration of user records",
                source=EvidenceSource(kind="file", locator="migrate.py"),
                confidence=90,
            )
        )
        orchestrator.session.phase_0a_output = sample_phase_0a_output

        orchestrator._select_mode()
        assert orchestrator.session.mode_selected == "deep"

    def test_mode_auto_selects_deep_for_many_unknowns(self, sample_config, sample_phase_0a_output):
        """Test auto mode selects deep when >2 critical unknowns."""
        sample_config.mode = "auto"
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        # Add more unknowns
        from code_puppy.plugins.adversarial_planning.models import CriticalUnknown
        sample_phase_0a_output.critical_unknowns.extend([
            CriticalUnknown(id="UNK2", question="Q2", why_it_matters="M2", fastest_probe="P2"),
            CriticalUnknown(id="UNK3", question="Q3", why_it_matters="M3", fastest_probe="P3"),
        ])
        orchestrator.session.phase_0a_output = sample_phase_0a_output

        orchestrator._select_mode()
        assert orchestrator.session.mode_selected == "deep"


class TestPhaseExecution:
    """Test phase execution."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires full agent stack")
    async def test_full_workflow_standard_mode(self, sample_config, mock_invoke_agent, mock_emit_progress):
        """Test full standard mode workflow completes."""
        sample_config.mode = "standard"

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=mock_invoke_agent,
            emit_progress_fn=mock_emit_progress,
        )

        session = await orchestrator.run()

        # Should complete without error
        assert session.global_stop_reason is None
        assert session.current_phase in ("6_decision", "7_changeset", "complete")

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires full agent stack")
    async def test_global_stop_on_blocked_discovery(self, sample_config, mock_emit_progress):
        """Test workflow stops when discovery is blocked."""
        async def blocked_invoke(agent_name, prompt, session_id):
            return '{"readiness": "blocked", "confidence": 10, "workspace_summary": "", "problem_signature": "", "evidence": [], "files_examined": [], "existing_patterns_to_reuse": [], "contradictions": [], "blast_radius": [], "critical_unknowns": []}'

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=blocked_invoke,
            emit_progress_fn=mock_emit_progress,
        )

        session = await orchestrator.run()

        assert session.global_stop_reason is not None
        assert "blocked" in session.global_stop_reason.lower()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires full agent stack")
    async def test_progress_emitted_during_run(self, sample_config, mock_invoke_agent, mock_emit_progress):
        """Test progress events are emitted during run."""
        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=mock_invoke_agent,
            emit_progress_fn=mock_emit_progress,
        )

        await orchestrator.run()

        # Should have called emit_progress multiple times
        assert mock_emit_progress.call_count > 0


class TestNeedsRebuttal:
    """Test rebuttal phase decision logic using the validators module."""

    def test_needs_rebuttal_with_blockers(self, sample_config, sample_review_a, sample_review_b):
        """Test rebuttal needed when blockers exist."""
        from code_puppy.plugins.adversarial_planning.models import PlanningSession
        session = PlanningSession(
            session_id="test-session",
            config=sample_config,
            review_a=sample_review_a,
            review_b=sample_review_b,
        )

        # review_b has a blocker
        assert needs_rebuttal(session) is True

    def test_needs_rebuttal_with_fatal_flaw(self, sample_config, sample_review_a, sample_review_b):
        """Test rebuttal needed when fatal flaw exists."""
        from code_puppy.plugins.adversarial_planning.models import PlanningSession
        # Remove blockers but keep fatal flaw
        sample_review_b.blockers = []

        session = PlanningSession(
            session_id="test-session",
            config=sample_config,
            review_a=sample_review_a,
            review_b=sample_review_b,
        )

        # needs_rebuttal returns truthy value (the fatal flaw string) when there's a fatal flaw
        result = needs_rebuttal(session)
        assert result  # Should be truthy (the fatal flaw string)

    def test_no_rebuttal_when_clean(self, sample_config, sample_review_a):
        """Test no rebuttal when reviews are clean."""
        from code_puppy.plugins.adversarial_planning.models import PlanningSession
        # Both reviews clean (use same review twice)
        clean_review = sample_review_a.model_copy()
        clean_review.overall["fatal_flaw"] = None
        clean_review.blockers = []

        clean_review_b = clean_review.model_copy()
        clean_review_b.reviewed_plan = "B"

        session = PlanningSession(
            session_id="test-session",
            config=sample_config,
            review_a=clean_review,
            review_b=clean_review_b,
        )

        # Scores are same, no blockers, no fatal flaw
        assert needs_rebuttal(session) is False

    def test_needs_rebuttal_score_delta(self, sample_config, sample_review_a, sample_review_b):
        """Test rebuttal needed when score delta > 10."""
        from code_puppy.plugins.adversarial_planning.models import PlanningSession
        # Make clean reviews but with score delta
        review_a = sample_review_a.model_copy()
        review_a.blockers = []
        review_a.overall["fatal_flaw"] = None
        review_a.overall["score"] = 80

        review_b = sample_review_b.model_copy()
        review_b.blockers = []
        review_b.overall["fatal_flaw"] = None
        review_b.overall["score"] = 65  # Delta = 15

        session = PlanningSession(
            session_id="test-session",
            config=sample_config,
            review_a=review_a,
            review_b=review_b,
        )

        assert needs_rebuttal(session) is True


class TestParsePhaseOutput:
    """Test output parsing."""

    def test_parse_json_block(self, sample_config):
        """Test parsing JSON from code block."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        from code_puppy.plugins.adversarial_planning.models import Phase0AOutput
        result = """
Some text here
```json
{"readiness": "ready", "confidence": 80, "workspace_summary": "Test", "problem_signature": "Test"}
```
More text here
"""
        output = orchestrator._parse_phase_output(result, Phase0AOutput)
        assert output.readiness == "ready"
        assert output.confidence == 80

    def test_parse_json_object(self, sample_config):
        """Test parsing JSON from raw object."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        from code_puppy.plugins.adversarial_planning.models import Phase0AOutput
        result = '{"readiness": "limited", "confidence": 60, "workspace_summary": "Test", "problem_signature": "Test"}'
        output = orchestrator._parse_phase_output(result, Phase0AOutput)
        assert output.readiness == "limited"
        assert output.confidence == 60


class TestApplyPenalties:
    """Test penalty application."""

    def test_same_model_fallback_penalty(self, sample_config, sample_phase_4_output):
        """Test same-model fallback applies 15 point penalty."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator.session.same_model_fallback = True
        orchestrator.session.synthesis = sample_phase_4_output

        from code_puppy.plugins.adversarial_planning.models import Phase6Output
        decision = Phase6Output(
            raw_plan_score=90,
            adjusted_plan_score=90,
            plan_verdict="go",
            summary="Test",
        )

        result = orchestrator._apply_penalties(decision)

        # Should have same-model penalty
        assert any("same-model" in p.reason for p in result.penalties)
        assert result.adjusted_plan_score == 75  # 90 - 15

    def test_verdict_recalculation(self, sample_config, sample_phase_4_output):
        """Test verdict is recalculated after penalties."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator.session.same_model_fallback = True
        orchestrator.session.synthesis = sample_phase_4_output

        from code_puppy.plugins.adversarial_planning.models import Phase6Output

        # Start with high score that becomes no-go after penalty
        decision = Phase6Output(
            raw_plan_score=60,
            adjusted_plan_score=60,
            plan_verdict="conditional_go",
            summary="Test",
        )

        result = orchestrator._apply_penalties(decision)

        # Score: 60 - 15 = 45 (< 55), so should be no_go
        assert result.adjusted_plan_score == 45
        assert result.plan_verdict == "no_go"

    def test_verdict_go_threshold(self, sample_config, sample_phase_4_output):
        """Test verdict becomes go when score >= 75."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator.session.synthesis = sample_phase_4_output

        from code_puppy.plugins.adversarial_planning.models import Phase6Output
        decision = Phase6Output(
            raw_plan_score=80,
            adjusted_plan_score=80,
            plan_verdict="no_go",
            summary="Test",
        )

        result = orchestrator._apply_penalties(decision)
        assert result.plan_verdict == "go"

    def test_verdict_conditional_threshold(self, sample_config, sample_phase_4_output):
        """Test verdict becomes conditional_go when score 55-74."""
        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator.session.synthesis = sample_phase_4_output

        from code_puppy.plugins.adversarial_planning.models import Phase6Output
        decision = Phase6Output(
            raw_plan_score=65,
            adjusted_plan_score=65,
            plan_verdict="no_go",
            summary="Test",
        )

        result = orchestrator._apply_penalties(decision)
        assert result.plan_verdict == "conditional_go"
