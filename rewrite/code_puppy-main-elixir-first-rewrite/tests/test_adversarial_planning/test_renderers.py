"""Test renderer functionality for adversarial planning."""

import json

from code_puppy.plugins.adversarial_planning.renderers import (
    AdversarialPlanningRenderer,
    render_session,
)


class TestRendererInit:
    """Test renderer initialization."""

    def test_renderer_init(self, sample_planning_session):
        """Test renderer initializes with session."""
        renderer = AdversarialPlanningRenderer(sample_planning_session)
        assert renderer.session == sample_planning_session


class TestRenderSummary:
    """Test summary rendering."""

    def test_render_summary_with_go_verdict(self, sample_planning_session, sample_phase_6_output):
        """Test summary with go verdict."""
        sample_planning_session.decision = sample_phase_6_output
        sample_planning_session.mode_selected = "standard"

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "GO" in summary or "go" in summary.lower()
        assert "75" in summary  # Score from sample data
        assert "Mode" in summary

    def test_render_summary_with_no_go(self, sample_planning_session, sample_phase_6_output):
        """Test summary with no_go verdict."""
        sample_phase_6_output.plan_verdict = "no_go"
        sample_phase_6_output.adjusted_plan_score = 40
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "NO GO" in summary or "no_go" in summary.lower()

    def test_render_summary_with_conditional_go(self, sample_planning_session, sample_phase_6_output):
        """Test summary with conditional_go verdict."""
        sample_phase_6_output.plan_verdict = "conditional_go"
        sample_phase_6_output.adjusted_plan_score = 65
        sample_phase_6_output.plan_condition = "Complete credential verification first"
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "CONDITIONAL" in summary or "conditional" in summary.lower()
        assert "condition" in summary.lower() or "credential" in summary.lower()

    def test_render_summary_with_global_stop(self, sample_planning_session):
        """Test summary with global stop reason."""
        sample_planning_session.global_stop_reason = "Environment discovery blocked"

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "STOPPED" in summary or "stopped" in summary.lower()
        assert "blocked" in summary.lower()

    def test_render_summary_in_progress(self, sample_planning_session):
        """Test summary when planning is in progress."""
        sample_planning_session.current_phase = "1_planning"

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "in progress" in summary.lower() or "progress" in summary.lower()

    def test_render_summary_includes_quick_wins(self, sample_planning_session, sample_phase_6_output):
        """Test summary includes quick wins."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "Quick Wins" in summary or "quick" in summary.lower()
        assert "Google login" in summary or "button" in summary.lower()

    def test_render_summary_includes_monday_morning_actions(self, sample_planning_session, sample_phase_6_output):
        """Test summary includes monday morning actions."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        assert "Monday Morning Actions" in summary or "next actions" in summary.lower()
        assert "Verify" in summary or "Run" in summary

    def test_render_summary_counts_blockers(self, sample_planning_session, sample_review_a, sample_review_b):
        """Test summary counts and displays blockers."""
        sample_planning_session.review_a = sample_review_a
        sample_planning_session.review_b = sample_review_b

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        summary = renderer.render_summary()

        # review_b has 1 blocker
        assert "Blockers" in summary or "blockers" in summary.lower()


class TestRenderEvidenceSummary:
    """Test evidence summary rendering."""

    def test_render_evidence_counts(self, sample_planning_session, sample_phase_0a_output):
        """Test evidence counts by class are shown."""
        sample_planning_session.phase_0a_output = sample_phase_0a_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_evidence_summary()

        assert "Verified" in result
        assert "Inference" in result
        assert "Assumption" in result

    def test_render_evidence_readiness(self, sample_planning_session, sample_phase_0a_output):
        """Test readiness is displayed."""
        sample_planning_session.phase_0a_output = sample_phase_0a_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_evidence_summary()

        assert sample_phase_0a_output.readiness.upper() in result
        assert str(sample_phase_0a_output.confidence) in result

    def test_render_evidence_contradictions(self, sample_planning_session, sample_phase_0a_output):
        """Test contradictions are displayed when present."""
        sample_phase_0a_output.contradictions = ["Config says X but code does Y"]
        sample_planning_session.phase_0a_output = sample_phase_0a_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_evidence_summary()

        assert "Contradiction" in result or "contradiction" in result.lower()


class TestRenderScopeLock:
    """Test scope lock rendering."""

    def test_render_scope_basic(self, sample_planning_session, sample_phase_0b_output):
        """Test basic scope lock info is rendered."""
        sample_planning_session.phase_0b_output = sample_phase_0b_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_scope_lock()

        assert sample_phase_0b_output.normalized_problem in result
        assert sample_phase_0b_output.problem_type in result

    def test_render_scope_constraints(self, sample_planning_session, sample_phase_0b_output):
        """Test constraints are listed."""
        sample_planning_session.phase_0b_output = sample_phase_0b_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_scope_lock()

        assert "Constraint" in result or "constraint" in result.lower()
        assert sample_phase_0b_output.hard_constraints[0] in result

    def test_render_scope_in_out_scope(self, sample_planning_session, sample_phase_0b_output):
        """Test in-scope and out-of-scope are rendered."""
        sample_planning_session.phase_0b_output = sample_phase_0b_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_scope_lock()

        assert "In Scope" in result or "in scope" in result.lower()
        assert "Out of Scope" in result or "out of scope" in result.lower()


class TestRenderPlanComparison:
    """Test plan comparison rendering."""

    def test_render_comparison_both_plans(self, sample_planning_session, sample_plan_a, sample_plan_b):
        """Test comparison with both plans."""
        sample_planning_session.plan_a = sample_plan_a
        sample_planning_session.plan_b = sample_plan_b

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_plan_comparison()

        assert "Plan A" in result
        assert "Plan B" in result
        # Posture is shown in the header with capitalized first letter
        assert sample_plan_a.posture.capitalize() in result or sample_plan_a.posture in result
        assert sample_plan_b.posture.capitalize() in result or sample_plan_b.posture in result

    def test_render_comparison_step_counts(self, sample_planning_session, sample_plan_a, sample_plan_b):
        """Test step counts are compared."""
        sample_planning_session.plan_a = sample_plan_a
        sample_planning_session.plan_b = sample_plan_b

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_plan_comparison()

        assert str(len(sample_plan_a.steps)) in result
        assert str(len(sample_plan_b.steps)) in result


class TestRenderReviewSummary:
    """Test review summary rendering."""

    def test_render_review_scores(self, sample_planning_session, sample_review_a, sample_review_b):
        """Test review scores are displayed."""
        sample_planning_session.review_a = sample_review_a
        sample_planning_session.review_b = sample_review_b

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_review_summary()

        assert str(sample_review_a.overall["score"]) in result
        assert str(sample_review_b.overall["score"]) in result

    def test_render_review_fatal_flaws(self, sample_planning_session, sample_review_a, sample_review_b):
        """Test fatal flaws are highlighted."""
        sample_planning_session.review_a = sample_review_a
        sample_planning_session.review_b = sample_review_b

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_review_summary()

        assert "Fatal Flaw" in result or "fatal" in result.lower()
        assert sample_review_b.overall["fatal_flaw"] in result


class TestRenderSynthesis:
    """Test synthesis rendering."""

    def test_render_synthesis_basic(self, sample_planning_session, sample_phase_4_output):
        """Test synthesis info is rendered."""
        sample_planning_session.synthesis = sample_phase_4_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_synthesis()

        assert sample_phase_4_output.merged_problem in result
        assert sample_phase_4_output.merged_approach in result
        assert str(sample_phase_4_output.merged_confidence) in result

    def test_render_synthesis_steps(self, sample_planning_session, sample_phase_4_output):
        """Test merged steps are listed."""
        sample_planning_session.synthesis = sample_phase_4_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_synthesis()

        assert "Merged Steps" in result
        for step in sample_phase_4_output.merged_steps[:3]:
            assert step.id in result

    def test_render_synthesis_dissent(self, sample_planning_session, sample_phase_4_output):
        """Test dissent log is rendered."""
        sample_planning_session.synthesis = sample_phase_4_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_synthesis()

        assert "Dissent Log" in result or "dissent" in result.lower()
        assert sample_phase_4_output.dissent_log[0]["alternative"] in result


class TestRenderRedTeam:
    """Test red team rendering."""

    def test_render_red_team_basic(self, sample_planning_session, sample_phase_5_output):
        """Test red team info is rendered."""
        sample_planning_session.red_team = sample_phase_5_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_red_team()

        assert "Red Team" in result or "Stress Test" in result
        assert sample_phase_5_output.overall["attack_surface"].upper() in result.upper()

    def test_render_red_team_clean_bill(self, sample_planning_session, sample_phase_5_output):
        """Test clean bill of health is displayed."""
        sample_planning_session.red_team = sample_phase_5_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_red_team()

        assert "Clean Bill" in result or "clean" in result.lower()
        assert str(sample_phase_5_output.clean_bill_of_health) in result

    def test_render_red_team_attacks(self, sample_planning_session, sample_phase_5_output):
        """Test attacks are listed."""
        sample_planning_session.red_team = sample_phase_5_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_red_team()

        assert "Attack" in result
        if sample_phase_5_output.attacks:
            assert sample_phase_5_output.attacks[0].category in result


class TestRenderDecision:
    """Test decision rendering."""

    def test_render_decision_verdict(self, sample_planning_session, sample_phase_6_output):
        """Test verdict is prominently displayed."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_decision()

        assert sample_phase_6_output.plan_verdict.upper() in result.upper()
        assert "VERDICT" in result or "Verdict" in result

    def test_render_decision_scores(self, sample_planning_session, sample_phase_6_output):
        """Test raw and adjusted scores are displayed."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_decision()

        assert str(sample_phase_6_output.raw_plan_score) in result
        assert str(sample_phase_6_output.adjusted_plan_score) in result

    def test_render_decision_penalties(self, sample_planning_session, sample_phase_6_output):
        """Test penalties are listed."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_decision()

        assert "Penalt" in result  # Penalty or Penalties
        for penalty in sample_phase_6_output.penalties:
            assert str(penalty.points) in result or penalty.reason in result

    def test_render_decision_execution_order(self, sample_planning_session, sample_phase_6_output):
        """Test execution order is listed."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_decision()

        assert "Execution Order" in result
        for step_id in sample_phase_6_output.execution_order[:3]:
            assert step_id in result

    def test_render_decision_dissenting_note(self, sample_planning_session, sample_phase_6_output):
        """Test dissenting note is rendered if present."""
        sample_phase_6_output.dissenting_note = "Concerned about timeline"
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_decision()

        assert "Dissent" in result or "dissenting" in result.lower()
        assert sample_phase_6_output.dissenting_note in result


class TestRenderChangeSets:
    """Test change sets rendering."""

    def test_render_changesets_basic(self, sample_planning_session, sample_phase_7_output):
        """Test change sets are rendered."""
        sample_planning_session.change_sets = sample_phase_7_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_change_sets()

        assert "Change Set" in result
        assert str(len(sample_phase_7_output.change_sets)) in result

    def test_render_changesets_safe_first(self, sample_planning_session, sample_phase_7_output):
        """Test safe first change is highlighted."""
        sample_planning_session.change_sets = sample_phase_7_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_change_sets()

        assert "Safe First" in result or "safe_first" in result.lower()
        assert sample_phase_7_output.safe_first_change["goal"] in result

    def test_render_changesets_verification(self, sample_planning_session, sample_phase_7_output):
        """Test verification sequence is shown."""
        sample_planning_session.change_sets = sample_phase_7_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer._render_change_sets()

        assert "Verification" in result
        for step in sample_phase_7_output.verification_sequence[:2]:
            assert step in result


class TestRenderTraceabilityMatrix:
    """Test traceability matrix rendering."""

    def test_render_traceability_with_synthesis(self, sample_planning_session, sample_phase_4_output):
        """Test traceability matrix renders with synthesis."""
        sample_planning_session.synthesis = sample_phase_4_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer.render_traceability_matrix()

        assert "Traceability" in result
        assert "Constraint" in result
        assert "Criteria" in result or "Coverage" in result

    def test_render_traceability_no_synthesis(self, sample_planning_session):
        """Test graceful handling when no synthesis."""
        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer.render_traceability_matrix()

        assert "No synthesis available" in result


class TestFullRender:
    """Test full render methods."""

    def test_render_full_comprehensive(self, sample_planning_session, sample_phase_0a_output, sample_phase_0b_output, sample_plan_a, sample_plan_b, sample_review_a, sample_review_b, sample_phase_4_output, sample_phase_6_output):
        """Test full render with complete session."""
        sample_planning_session.phase_0a_output = sample_phase_0a_output
        sample_planning_session.phase_0b_output = sample_phase_0b_output
        sample_planning_session.plan_a = sample_plan_a
        sample_planning_session.plan_b = sample_plan_b
        sample_planning_session.review_a = sample_review_a
        sample_planning_session.review_b = sample_review_b
        sample_planning_session.synthesis = sample_phase_4_output
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        result = renderer.render_full()

        assert "Adversarial Planning Results" in result
        assert sample_planning_session.session_id in result

    def test_to_json(self, sample_planning_session):
        """Test JSON export."""
        renderer = AdversarialPlanningRenderer(sample_planning_session)
        json_str = renderer.to_json()

        # Should be valid JSON
        data = json.loads(json_str)
        assert data["session_id"] == sample_planning_session.session_id

    def test_to_markdown(self, sample_planning_session, sample_phase_0a_output, sample_phase_6_output):
        """Test markdown export equals full render."""
        sample_planning_session.phase_0a_output = sample_phase_0a_output
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        markdown = renderer.to_markdown()
        full = renderer.render_full()

        assert markdown == full

    def test_to_minimal(self, sample_planning_session, sample_phase_6_output):
        """Test minimal export equals summary."""
        sample_planning_session.decision = sample_phase_6_output

        renderer = AdversarialPlanningRenderer(sample_planning_session)
        minimal = renderer.to_minimal()
        summary = renderer.render_summary()

        assert minimal == summary


class TestConvenienceFunction:
    """Test the render_session convenience function."""

    def test_render_session_summary_default(self, sample_planning_session):
        """Test default format is summary."""
        result = render_session(sample_planning_session)
        # Should get summary by default
        assert "Mode" in result or "mode" in result.lower()

    def test_render_session_full_format(self, sample_planning_session, sample_phase_0a_output):
        """Test full format selection."""
        sample_planning_session.phase_0a_output = sample_phase_0a_output
        result = render_session(sample_planning_session, format="full")
        assert "Adversarial Planning Results" in result or "Phase" in result

    def test_render_session_traceability_format(self, sample_planning_session, sample_phase_4_output):
        """Test traceability format selection."""
        sample_planning_session.synthesis = sample_phase_4_output
        result = render_session(sample_planning_session, format="traceability")
        assert "Traceability" in result

    def test_render_session_json_format(self, sample_planning_session):
        """Test JSON format selection."""
        result = render_session(sample_planning_session, format="json")
        # Should be valid JSON
        data = json.loads(result)
        assert "session_id" in data

    def test_render_session_unknown_format_fallback(self, sample_planning_session):
        """Test unknown format falls back to summary."""
        result = render_session(sample_planning_session, format="unknown_format")
        # Should still return a valid summary
        assert "Mode" in result or "VERDICT" in result or "STOPPED" in result or "in progress" in result.lower()
