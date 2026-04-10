"""Shared test fixtures for adversarial planning tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from code_puppy.plugins.adversarial_planning.models import (
    AdversarialPlanConfig,
    WorkspaceContext,
    PlanningSession,
    Phase0AOutput,
    Phase0BOutput,
    Phase1Output,
    Phase2Output,
    Phase4Output,
    Phase5Output,
    Phase6Output,
    Phase7Output,
    Evidence,
    EvidenceSource,
    EvidenceClass,
    CriticalUnknown,
    PlanStep,
    OperationalReadiness,
    Blocker,
    Penalty,
    StepEvaluation,
    Attack,
    ChangeSet,
    StepReview,
)


@pytest.fixture
def sample_config():
    """Create a sample adversarial planning config."""
    return AdversarialPlanConfig(
        mode="auto",
        context=WorkspaceContext(
            workspace="/test/workspace",
            branch_or_commit="main",
            access_limitations=[],
        ),
        task="Implement user authentication with OAuth2",
        success_criteria=["Users can log in with Google", "Session persists"],
        hard_constraints=["Must use existing user table", "No breaking changes"],
    )


@pytest.fixture
def sample_evidence():
    """Create sample evidence objects."""
    return [
        Evidence(
            id="EV1",
            evidence_class=EvidenceClass.VERIFIED,
            claim="User model exists in models/user.py",
            source=EvidenceSource(
                kind="file",
                locator="models/user.py:1-50",
                freshness="2024-01-15",
            ),
            confidence=95,
        ),
        Evidence(
            id="EV2",
            evidence_class=EvidenceClass.INFERENCE,
            claim="OAuth library is compatible based on version",
            source=EvidenceSource(
                kind="config",
                locator="pyproject.toml:15",
            ),
            confidence=75,
        ),
        Evidence(
            id="EV3",
            evidence_class=EvidenceClass.ASSUMPTION,
            claim="Google OAuth credentials are available",
            source=EvidenceSource(kind="prompt", locator="user-input"),
            confidence=50,
        ),
    ]


@pytest.fixture
def sample_phase_0a_output(sample_evidence):
    """Create sample Phase 0A output."""
    return Phase0AOutput(
        readiness="ready",
        confidence=82,
        workspace_summary="Python web application with Flask",
        problem_signature="Add OAuth2 authentication flow",
        evidence=sample_evidence,
        files_examined=["models/user.py", "auth/login.py", "config.py"],
        existing_patterns_to_reuse=["Flask-Login pattern in auth/"],
        contradictions=[],
        blast_radius=["auth/", "templates/login.html", "config.py"],
        critical_unknowns=[
            CriticalUnknown(
                id="UNK1",
                question="Are OAuth credentials configured?",
                why_it_matters="Cannot proceed without valid credentials",
                fastest_probe="Check .env for GOOGLE_CLIENT_ID",
                can_proceed_without=False,
            )
        ],
    )


@pytest.fixture
def sample_phase_0b_output():
    """Create sample Phase 0B output."""
    return Phase0BOutput(
        normalized_problem="Add Google OAuth2 login alongside existing auth",
        problem_type="feature",
        verified_facts=["User model exists", "Flask-Login is configured"],
        inferences=["OAuth library appears compatible"],
        hard_constraints=["No breaking changes to existing login"],
        in_scope=["Google OAuth flow", "Session management", "User linking"],
        out_of_scope=["Apple Sign-In", "SAML", "Password reset changes"],
        critical_unknowns=[],
        planning_guardrails=["Must maintain existing login flow"],
        pre_mortem={
            "scenario": "OAuth integration failed",
            "causes": ["Credential misconfiguration", "Callback URL mismatch"],
        },
    )


@pytest.fixture
def sample_plan_step():
    """Create a sample plan step."""
    return PlanStep(
        id="A1",
        category="build",
        what="Add OAuth2 callback route",
        why="Handle Google's auth response",
        how="Create /auth/google/callback endpoint",
        evidence_refs=["EV1"],
        likely_files=["auth/oauth.py"],
        depends_on=[],
        covers_constraints=["No breaking changes"],
        covers_criteria=["Users can log in with Google"],
        risk="Callback URL mismatch",
        risk_severity="medium",
        mitigation="Test in staging first",
        effort_hours_80pct=4,
        reversible=True,
        approval_needed="none",
        exit_criteria="Callback route returns 200",
    )


@pytest.fixture
def sample_plan_a(sample_plan_step):
    """Create sample Plan A output."""
    return Phase1Output(
        plan_id="A",
        posture="conservative",
        problem_restatement="Add OAuth2 without breaking existing auth",
        approach_summary="Extend Flask-Login with OAuth provider",
        assumptions=["Credentials are available"],
        alternatives_considered=["Auth0 hosted", "Firebase Auth"],
        steps=[sample_plan_step],
        operational_readiness=OperationalReadiness(
            validation="Run OAuth flow in staging",
            rollout="Feature flag for gradual rollout",
            rollback="Disable feature flag",
            rollback_time="< 1 minute",
            monitoring="Track OAuth success rate",
        ),
        critical_path=["A1"],
        estimated_hours_80pct=24,
        estimated_calendar_days=5,
        quick_wins=["Add Google button to login page"],
        reasons_this_plan_may_fail=["Credential issues", "Callback URL config"],
    )


@pytest.fixture
def sample_plan_b(sample_plan_step):
    """Create sample Plan B (contrarian) output."""
    step_b = sample_plan_step.model_copy()
    step_b.id = "B1"
    step_b.what = "Replace Flask-Login with Authlib"
    step_b.how = "Full OAuth2 implementation with Authlib"
    step_b.effort_hours_80pct = 16

    return Phase1Output(
        plan_id="B",
        posture="contrarian",
        problem_restatement="Modernize auth with full OAuth2 support",
        approach_summary="Replace Flask-Login with Authlib for multi-provider",
        assumptions=["Team accepts larger change"],
        alternatives_considered=["Keep Flask-Login"],
        steps=[step_b],
        operational_readiness=OperationalReadiness(
            validation="Full test suite + manual testing",
            rollout="Shadow mode then cutover",
            rollback="Revert to Flask-Login branch",
            rollback_time="< 5 minutes",
            monitoring="Auth error rate, latency",
        ),
        critical_path=["B1"],
        estimated_hours_80pct=48,
        estimated_calendar_days=10,
        quick_wins=[],
        reasons_this_plan_may_fail=["Larger scope", "Migration complexity"],
    )


@pytest.fixture
def sample_review_a():
    """Create sample review for Plan A."""
    return Phase2Output(
        reviewed_plan="A",
        overall={
            "base_case": "Low-risk incremental approach",
            "fatal_flaw": None,
            "wrong_problem": None,
            "score": 75,
            "ship_readiness": "ready_with_caveats",
            "codebase_fit": "high",
        },
        step_reviews=[],
        missing_steps=["Add CSRF protection"],
        assumption_audit=[],
        constraint_violations=[],
        operational_gaps=OperationalReadiness(
            validation="OK",
            rollout="OK",
            rollback="OK",
            monitoring="Needs more metrics",
        ),
        effort_reassessment={
            "planner_total": 24,
            "reviewer_estimate": 32,
            "reason": "Integration testing underestimated",
        },
        blockers=[],
        strongest_surviving_element="Reversible feature flag approach",
    )


@pytest.fixture
def sample_review_b():
    """Create sample review for Plan B."""
    return Phase2Output(
        reviewed_plan="B",
        overall={
            "base_case": "Future-proof architecture",
            "fatal_flaw": "Scope too large for timeline",
            "wrong_problem": None,
            "score": 55,
            "ship_readiness": "needs_work",
            "codebase_fit": "medium",
        },
        step_reviews=[],
        missing_steps=[],
        assumption_audit=[],
        constraint_violations=["May cause breaking changes"],
        operational_gaps=OperationalReadiness(
            validation="Needs more coverage",
            rollout="Risky cutover",
            rollback="Slow",
            monitoring="OK",
        ),
        effort_reassessment={
            "planner_total": 48,
            "reviewer_estimate": 72,
            "reason": "Migration underestimated",
        },
        blockers=[
            Blocker(
                id="BLK1",
                description="Timeline too aggressive",
                severity="blocker",
                repair_path="Extend timeline or reduce scope",
            )
        ],
        strongest_surviving_element="Multi-provider architecture",
    )


@pytest.fixture
def sample_phase_4_output(sample_plan_step):
    """Create sample Phase 4 synthesis output."""
    merged_step = sample_plan_step.model_copy()
    merged_step.id = "S1"

    return Phase4Output(
        merged_problem="Add Google OAuth2 with minimal disruption",
        merged_approach="Hybrid: Flask-Login extension with Authlib for OAuth",
        merged_steps=[merged_step],
        operational_readiness=OperationalReadiness(
            validation="Staging OAuth test + unit tests",
            rollout="Feature flag gradual rollout",
            rollback="Feature flag disable",
            rollback_time="< 1 minute",
            monitoring="OAuth metrics dashboard",
        ),
        traceability={
            "constraints": [{"constraint": "No breaking changes", "covered_by": ["S1"]}],
            "criteria": [{"criterion": "Google login works", "validated_by": ["S1"]}],
        },
        critical_path=["S1"],
        resolved_conflicts=["Keep Flask-Login vs Authlib debate"],
        discarded_steps=["Full Flask-Login replacement"],
        blockers=[],
        dissent_log=[
            {"alternative": "Full Authlib migration", "why_rejected": "Too risky for timeline"}
        ],
        estimated_hours_80pct=30,
        merged_confidence=78,
    )


@pytest.fixture
def sample_phase_5_output():
    """Create sample Phase 5 red team output."""
    return Phase5Output(
        overall={
            "attack_surface": "low",
            "most_vulnerable_area": "OAuth callback handling",
            "fatal_flaw_found": False,
            "fatal_flaw": None,
        },
        attacks=[
            Attack(
                id="ATK1",
                category="input_validation",
                description="Malformed OAuth callback could bypass validation",
                likelihood="low",
                impact="high",
                affected_steps=["S1"],
                recommendation="Add strict state parameter validation",
            )
        ],
        cascading_failures=["OAuth failure could lock out users"],
        timeline_stress={
            "at_150_percent": "Still viable with reduced scope",
            "at_200_percent": "Critical path failure risk",
        },
        recommendations=["Add rate limiting on OAuth endpoints"],
        clean_bill_of_health=True,
        summary="Plan is resilient with minor hardening needed",
    )


@pytest.fixture
def sample_phase_6_output():
    """Create sample Phase 6 decision output."""
    return Phase6Output(
        evaluations=[
            StepEvaluation(
                step_id="S1",
                impact_score=85,
                feasibility_score=90,
                risk_adjusted_score=82,
                urgency_score=80,
                weighted_score=84,
                verdict="do",
            )
        ],
        execution_order=["S1"],
        quick_wins=["Add Google login button to existing page"],
        minimum_viable_plan={
            "steps": ["S1"],
            "hours": 8,
            "covers_criteria": ["Users can log in with Google"],
            "gaps": ["Session persistence testing"],
        },
        full_plan={
            "steps": ["S1", "S2", "S3"],
            "hours": 30,
            "all_criteria_covered": True,
        },
        must_verify_first=["OAuth credentials exist"],
        first_probes=["Check .env for GOOGLE_CLIENT_ID"],
        raw_plan_score=80,
        penalties=[Penalty(reason="scope uncertainty", points=5)],
        adjusted_plan_score=75,
        plan_verdict="go",
        plan_condition=None,
        constraint_compliance={"status": "compliant", "violations": []},
        criteria_coverage={"covered": 2, "total": 2, "gaps": []},
        monday_morning_actions=[
            "Verify OAuth credentials in staging",
            "Run existing auth tests to establish baseline",
        ],
        summary="Proceed with OAuth integration using feature flags",
        dissenting_note=None,
    )


@pytest.fixture
def sample_phase_7_output():
    """Create sample Phase 7 changeset output."""
    return Phase7Output(
        change_sets=[
            ChangeSet(
                id="CS1",
                goal="Add OAuth callback route",
                files=["auth/oauth.py", "config.py"],
                reversible=True,
                verification=["Test OAuth callback returns 200"],
            ),
            ChangeSet(
                id="CS2",
                goal="Add Google login button",
                files=["templates/login.html", "static/css/auth.css"],
                reversible=True,
                verification=["Button renders correctly"],
            ),
        ],
        safe_first_change={
            "goal": "Add OAuth callback route behind feature flag",
            "why_first": "Isolated change with easy rollback",
            "files": ["auth/oauth.py"],
        },
        verification_sequence=[
            "Run unit tests",
            "Test OAuth flow in staging",
            "Verify feature flag works",
        ],
        release_notes=[
            "Added Google OAuth2 login option",
            "Maintains backward compatibility with existing auth",
        ],
    )


@pytest.fixture
def mock_invoke_agent():
    """Create a mock invoke_agent function."""
    async def _mock_invoke(agent_name: str, prompt: str, session_id: str) -> str:
        # Return appropriate JSON based on agent
        if "researcher" in agent_name:
            if "scope" in session_id:
                return '{"normalized_problem": "Test problem", "problem_type": "feature", "verified_facts": [], "inferences": [], "hard_constraints": [], "in_scope": [], "out_of_scope": [], "critical_unknowns": [], "planning_guardrails": [], "pre_mortem": {}}'
            return '{"readiness": "ready", "confidence": 80, "workspace_summary": "Test", "problem_signature": "Test problem", "evidence": [], "files_examined": [], "existing_patterns_to_reuse": [], "contradictions": [], "blast_radius": [], "critical_unknowns": []}'
        elif "planner-a" in agent_name:
            return '{"plan_id": "A", "posture": "conservative", "problem_restatement": "Test", "approach_summary": "Test approach", "assumptions": [], "alternatives_considered": [], "steps": [], "operational_readiness": {"validation": "", "rollout": "", "rollback": "", "monitoring": ""}, "critical_path": [], "estimated_hours_80pct": 20, "estimated_calendar_days": 5, "quick_wins": [], "reasons_this_plan_may_fail": []}'
        elif "planner-b" in agent_name:
            return '{"plan_id": "B", "posture": "contrarian", "problem_restatement": "Test alt", "approach_summary": "Different approach", "assumptions": [], "alternatives_considered": [], "steps": [], "operational_readiness": {"validation": "", "rollout": "", "rollback": "", "monitoring": ""}, "critical_path": [], "estimated_hours_80pct": 40, "estimated_calendar_days": 10, "quick_wins": [], "reasons_this_plan_may_fail": []}'
        elif "reviewer" in agent_name:
            return '{"reviewed_plan": "A", "overall": {"score": 70, "ship_readiness": "ready", "fatal_flaw": null, "codebase_fit": "high"}, "step_reviews": [], "missing_steps": [], "assumption_audit": [], "constraint_violations": [], "operational_gaps": {"validation": "", "rollout": "", "rollback": "", "monitoring": ""}, "effort_reassessment": {}, "blockers": [], "strongest_surviving_element": "Good"}'
        elif "arbiter" in agent_name:
            if "decision" in session_id:
                return '{"evaluations": [], "execution_order": [], "quick_wins": [], "minimum_viable_plan": {}, "full_plan": {}, "must_verify_first": [], "first_probes": [], "raw_plan_score": 75, "penalties": [], "adjusted_plan_score": 75, "plan_verdict": "go", "constraint_compliance": {}, "criteria_coverage": {}, "monday_morning_actions": [], "summary": "Test"}'
            elif "changeset" in session_id:
                return '{"change_sets": [], "safe_first_change": {}, "verification_sequence": [], "release_notes": []}'
            return '{"merged_problem": "Test", "merged_approach": "Best", "merged_steps": [], "operational_readiness": {"validation": "", "rollout": "", "rollback": "", "monitoring": ""}, "traceability": {}, "critical_path": [], "resolved_conflicts": [], "discarded_steps": [], "blockers": [], "dissent_log": [], "estimated_hours_80pct": 30, "merged_confidence": 75}'
        elif "red-team" in agent_name:
            return '{"overall": {"attack_surface": "low", "fatal_flaw_found": false}, "attacks": [], "cascading_failures": [], "timeline_stress": {}, "recommendations": [], "clean_bill_of_health": true, "summary": "Resilient"}'
        return '{}'

    return _mock_invoke


@pytest.fixture
def mock_emit_progress():
    """Create a mock progress emitter."""
    return MagicMock()


@pytest.fixture
def sample_planning_session(sample_config):
    """Create a sample planning session with full state."""
    return PlanningSession(
        session_id="ap-test-session",
        config=sample_config,
        current_phase="complete",
        mode_selected="standard",
    )
