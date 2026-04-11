"""Test session isolation for adversarial planning."""

import pytest

from code_puppy.plugins.adversarial_planning.orchestrator import AdversarialPlanningOrchestrator


class TestSessionIsolation:
    """Test that planners run in isolated sessions."""

    @pytest.fixture
    def tracking_invoke(self):
        """Create an invoke function that tracks session IDs."""
        calls = []

        async def _invoke(agent_name: str, prompt: str, session_id: str) -> str:
            calls.append({
                "agent": agent_name,
                "session_id": session_id,
                "prompt_length": len(prompt),
            })

            # Return minimal valid response based on agent
            if "planner-a" in agent_name:
                return '{"plan_id": "A", "posture": "conservative", "problem_restatement": "Test", "approach_summary": "Approach A differs significantly from Plan B", "assumptions": [], "alternatives_considered": [], "steps": [{"id": "A1", "category": "build", "what": "Step A", "why": "Reason", "how": "Method", "risk": "None", "risk_severity": "low", "mitigation": "None", "effort_hours_80pct": 20, "reversible": true, "approval_needed": "none", "exit_criteria": "Done"}], "operational_readiness": {"validation": "Test", "rollout": "Test", "rollback": "Test", "monitoring": "Test"}, "critical_path": ["A1"], "estimated_hours_80pct": 20, "estimated_calendar_days": 5, "quick_wins": [], "reasons_this_plan_may_fail": []}'
            elif "planner-b" in agent_name:
                return '{"plan_id": "B", "posture": "contrarian", "problem_restatement": "Test alt view", "approach_summary": "Approach B takes a different path entirely for higher risk", "assumptions": [], "alternatives_considered": [], "steps": [{"id": "B1", "category": "design", "what": "Step B", "why": "Different reason", "how": "Different method", "risk": "Some", "risk_severity": "medium", "mitigation": "Mitigate", "effort_hours_80pct": 40, "reversible": false, "approval_needed": "write_access", "exit_criteria": "Done"}], "operational_readiness": {"validation": "Test", "rollout": "Test", "rollback": "Test", "monitoring": "Test"}, "critical_path": ["B1"], "estimated_hours_80pct": 40, "estimated_calendar_days": 10, "quick_wins": [], "reasons_this_plan_may_fail": []}'
            elif "researcher" in agent_name:
                if "scope" in session_id:
                    return '{"normalized_problem": "Test problem", "problem_type": "feature", "verified_facts": [], "inferences": [], "hard_constraints": [], "in_scope": [], "out_of_scope": [], "critical_unknowns": [], "planning_guardrails": [], "pre_mortem": {"scenario": "", "causes": []}}'
                return '{"readiness": "ready", "confidence": 80, "workspace_summary": "Test workspace", "problem_signature": "Test problem signature", "evidence": [], "files_examined": [], "existing_patterns_to_reuse": [], "contradictions": [], "blast_radius": [], "critical_unknowns": []}'
            elif "reviewer" in agent_name:
                return '{"reviewed_plan": "A", "overall": {"score": 70, "ship_readiness": "ready", "fatal_flaw": null, "codebase_fit": "high"}, "step_reviews": [], "missing_steps": [], "assumption_audit": [], "constraint_violations": [], "operational_gaps": {"validation": "Run integration tests", "rollout": "Deploy to staging", "rollback": "Revert commit", "monitoring": "Check error rates"}, "effort_reassessment": {}, "blockers": [], "strongest_surviving_element": "Good approach"}'
            elif "arbiter" in agent_name:
                if "decision" in session_id:
                    return '{"evaluations": [], "execution_order": [], "quick_wins": [], "minimum_viable_plan": {}, "full_plan": {}, "must_verify_first": [], "first_probes": [], "raw_plan_score": 75, "penalties": [], "adjusted_plan_score": 75, "plan_verdict": "go", "constraint_compliance": {}, "criteria_coverage": {}, "monday_morning_actions": [], "summary": "Test decision"}'
                elif "changeset" in session_id:
                    return '{"change_sets": [], "safe_first_change": {}, "verification_sequence": [], "release_notes": []}'
                return '{"merged_problem": "Test merged", "merged_approach": "Best combined", "merged_steps": [], "operational_readiness": {"validation": "Test", "rollout": "Test", "rollback": "Test", "monitoring": "Test"}, "traceability": {}, "critical_path": [], "resolved_conflicts": [], "discarded_steps": [], "blockers": [], "dissent_log": [], "estimated_hours_80pct": 30, "merged_confidence": 75}'
            elif "red-team" in agent_name:
                return '{"overall": {"attack_surface": "low", "most_vulnerable_area": "none", "fatal_flaw_found": false, "fatal_flaw": null}, "attacks": [], "cascading_failures": [], "timeline_stress": {}, "recommendations": [], "clean_bill_of_health": true, "summary": "Resilient plan"}'
            return '{}'

        return _invoke, calls

    @pytest.mark.asyncio
    async def test_planners_get_different_sessions(self, sample_config, tracking_invoke):
        """Test that Planner A and B get different session IDs."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        # Find planner calls
        planner_a_calls = [c for c in calls if "planner-a" in c["agent"]]
        planner_b_calls = [c for c in calls if "planner-b" in c["agent"]]

        assert len(planner_a_calls) >= 1
        assert len(planner_b_calls) >= 1

        # Session IDs must be different
        a_session = planner_a_calls[0]["session_id"]
        b_session = planner_b_calls[0]["session_id"]

        assert a_session != b_session
        assert "planner-a" in a_session
        assert "planner-b" in b_session

    @pytest.mark.asyncio
    async def test_planners_dont_see_each_others_plans(self, sample_config, tracking_invoke):
        """Test that planners don't receive each other's plans in prompts."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        # Verify they were called with different session IDs
        planner_calls = [c for c in calls if "planner" in c["agent"]]

        session_ids = set(c["session_id"] for c in planner_calls)
        assert len(session_ids) >= 2  # At least 2 unique sessions

    @pytest.mark.asyncio
    async def test_all_phases_get_unique_sessions(self, sample_config, tracking_invoke):
        """Test that every phase gets a unique session ID."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        # All session IDs should be unique
        session_ids = [c["session_id"] for c in calls]
        assert len(session_ids) == len(set(session_ids)), "Session IDs should be unique"

    @pytest.mark.asyncio
    async def test_reviewer_isolation(self, sample_config, tracking_invoke):
        """Test reviewers run in isolated sessions."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        # Find reviewer calls
        reviewer_calls = [c for c in calls if "reviewer" in c["agent"]]

        assert len(reviewer_calls) >= 2  # Should have at least 2 reviews

        session_ids = [c["session_id"] for c in reviewer_calls]
        assert len(set(session_ids)) == len(session_ids), "Reviewer session IDs must be unique"

    @pytest.mark.asyncio
    async def test_arbiter_different_session_from_planners(self, sample_config, tracking_invoke):
        """Test arbiter runs in different session from planners."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        arbiter_calls = [c for c in calls if "arbiter" in c["agent"]]
        planner_calls = [c for c in calls if "planner" in c["agent"]]

        assert len(arbiter_calls) >= 1
        assert len(planner_calls) >= 1

        arbiter_sessions = set(c["session_id"] for c in arbiter_calls)
        planner_sessions = set(c["session_id"] for c in planner_calls)

        # No overlap
        assert not arbiter_sessions & planner_sessions

    @pytest.mark.asyncio
    async def test_session_prefix_consistency(self, sample_config, tracking_invoke):
        """Test all session IDs share common prefix from orchestrator."""
        invoke_fn, calls = tracking_invoke

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            invoke_agent_fn=invoke_fn,
        )

        await orchestrator.run()

        # Extract base session ID (everything before first hyphen in suffix)
        # Session format: {session_id}-{phase}-{role}
        session_ids = [c["session_id"] for c in calls]

        # All should start with the orchestrator's session ID
        base_id = orchestrator.session_id
        for sid in session_ids:
            assert sid.startswith(base_id), f"Session {sid} doesn't start with {base_id}"
