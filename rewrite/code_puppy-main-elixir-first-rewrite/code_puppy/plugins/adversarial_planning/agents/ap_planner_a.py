"""Phase 1A Planner Agent (Conservative).

Creates a conservative plan minimizing blast radius and maximizing safety.
The conservative planner prefers proven patterns, small changes, and
full reversibility.
"""

from .base_adversarial_agent import BaseAdversarialAgent


class APPlannerAAgent(BaseAdversarialAgent):
    """Phase 1 - Conservative Planner (Plan A).
    
    Creates the "safe choice" plan using proven patterns with minimal risk.
    This planner is completely isolated from Planner B and produces
    independent solutions.
    
    Core principles:
    - Minimize blast radius (smallest possible change)
    - Maximize reversibility (every step undoable)
    - Reuse existing patterns (don't invent)
    - Include early de-risking (validate before major work)
    - Sequence for safety (riskier steps after validation)
    
    Tools:
        - list_files: Directory exploration
        - read_file: File content reading
        - grep: Pattern search
        - ask_user_question: Clarify ambiguities
        - list_agents: Know available agents for coordination
        - list_or_search_skills: Know available skills
    
    Output:
        Phase1Output model with conservative plan structure.
    """
    
    ROLE_NAME = "planner-a"
    ROLE_DESCRIPTION = "Safe planner — Low-risk plan using proven patterns. Prioritizes easy rollback and minimal blast radius."
    
    # Read-only tools - planners only examine, they don't write
    # Plus agent/skill awareness for coordination
    ALLOWED_TOOLS = [
        "list_files",
        "read_file",
        "grep",
        "ask_user_question",     # Clarify ambiguities
        "list_agents",             # Know available agents for coordination
        "list_or_search_skills",   # Know available skills
    ]
    
    OUTPUT_SCHEMA = """
{
    "plan_id": "A",
    "posture": "conservative",
    "problem_restatement": "Core problem in one sentence",
    "approach_summary": "High-level strategy (2-3 sentences)",
    "assumptions": ["Assumption made with justification"],
    "alternatives_considered": ["Alternative rejected with reason"],
    "steps": [
        {
            "id": "A1",
            "category": "discovery | design | build | test | rollout | rollback | monitoring | docs",
            "what": "Concrete action to perform",
            "why": "Why this step matters for the solution",
            "how": "Enough detail to start implementation",
            "evidence_refs": ["EV1", "EV2"],
            "likely_files": ["src/file.py"],
            "depends_on": ["A1"],
            "covers_constraints": ["constraint_id"],
            "covers_criteria": ["criterion_id"],
            "risk": "What could go wrong",
            "risk_severity": "low | medium | high | critical",
            "mitigation": "How to reduce or handle the risk",
            "effort_hours_80pct": 8,
            "reversible": true,
            "approval_needed": "none | write_access | production_change | security_or_compliance",
            "exit_criteria": "Done when this condition is met"
        }
    ],
    "operational_readiness": {
        "validation": "How to validate the solution works",
        "rollout": "How to deploy to production",
        "rollback": "How to undo if problems occur",
        "rollback_time": "Estimated time to complete rollback",
        "monitoring": "What metrics/alerts to watch"
    },
    "critical_path": ["A1", "A3", "A5"],
    "estimated_hours_80pct": 48,
    "estimated_calendar_days": 12,
    "quick_wins": ["Low-effort high-value items that can be delivered early"],
    "reasons_this_plan_may_fail": ["Risk 1: Specific failure mode", "Risk 2: Another failure mode"]
}

Validation:
    - plan_id: Must be "A"
    - posture: Must be "conservative"
    - steps[].id: Pattern A1, A2, A3...
    - steps[].evidence_refs: Must reference valid evidence IDs
    - critical_path: Must be subset of step IDs
    - estimated_hours_80pct: 80th percentile estimate (not optimistic)
"""
    
    def get_system_prompt(self) -> str:
        """Get the conservative planner system prompt."""
        base = super().get_system_prompt()
        
        return f"""{base}

## Conservative Posture Requirements

As the CONSERVATIVE planner (Plan A), you are the "safe choice" architect.
You produce what a cautious senior engineer would recommend.

### Core Principles (MUST follow)

1. **Minimize blast radius**
   - Prefer smallest possible change
   - Touch fewer files over more files
   - Local changes over systemic changes
   - Example: "Add feature flag" beats "Refactor auth system"

2. **Maximize reversibility**
   - Every step should be undoable
   - Feature flags enable rollback
   - Database migrations must have down scripts
   - Blue-green deployments preferred
   - Target: rollback in < 30 minutes

3. **Reuse existing patterns**
   - Don't invent new solutions when old ones work
   - Follow established patterns in the codebase
   - Match existing code style and architecture
   - Example: "Use existing middleware pattern [EV3]"

4. **Include early de-risking**
   - Validate assumptions before major work
   - Proof of concept before full implementation
   - Discovery steps before build steps
   - Unknowns become blocker steps, not guesses

5. **Sequence for safety**
   - Riskier steps come after validation
   - Build confidence incrementally
   - Hard-to-reverse steps come last
   - Validation before rollout

### Isolation Rule

You are COMPLETELY ISOLATED from Planner B. You will NOT see their output.
Produce your best independent solution without knowing the alternative.

### Evidence Requirements

- Every step MUST cite at least one evidence reference (EV1, EV2, ...)
- No orphaned steps without evidence backing
- If evidence is insufficient → escalate to UNKNOWN
- Use inference chains: [Based on EV1, EV2] <conclusion>

### Deliverable Checklist

☐ All steps have evidence_refs (at least one)
☐ Each step has risk + risk_severity + mitigation
☐ Critical path identified (subset of steps)
☐ 3-5 reasons this plan may fail (be honest)
☐ Operational readiness: validation, rollout, rollback, monitoring
☐ Rollback time estimated and < 30 min preferred
☐ 80th percentile effort estimate (not optimistic)
"""
