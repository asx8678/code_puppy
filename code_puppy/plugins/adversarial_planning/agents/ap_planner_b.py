"""Phase 1B Planner Agent (Contrarian).

Creates a contrarian plan challenging defaults and seeking better outcomes.
The contrarian planner questions assumptions, explores alternatives,
and accepts more risk for significantly better results.
"""

from .base_adversarial_agent import BaseAdversarialAgent


class APPlannerBAgent(BaseAdversarialAgent):
    """Phase 1 - Contrarian Planner (Plan B).
    
    Creates an alternative solution that challenges the obvious approach.
    This planner is completely isolated from Planner A and produces
    materially different solutions.
    
    Core principles:
    - Challenge the obvious approach (question "how it's always done")
    - Seek better outcome/risk ratio (accept more risk for much better outcomes)
    - Consider alternatives others dismiss (newer technologies, different patterns)
    - Question constraints (are they hard requirements or assumptions?)
    - Optimize for long-term (short-term pain for sustainable solutions)
    
    Requirements:
    - Must differ MATERIALLY from conservative approach in at least TWO areas
    - A paraphrase of Plan A is a FAILURE
    - Must genuinely explore alternatives
    
    Tools:
        - list_files: Directory exploration
        - read_file: File content reading
        - grep: Pattern search
        - ask_user_question: Clarify ambiguities
        - list_agents: Know available agents for coordination
        - list_or_search_skills: Know available skills
    
    Output:
        Phase1Output model with contrarian plan structure.
    """
    
    ROLE_NAME = "planner-b"
    ROLE_DESCRIPTION = "Alternative planner — Challenges the obvious approach. Produces a meaningfully different plan than the safe planner."
    
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
    "plan_id": "B",
    "posture": "contrarian",
    "problem_restatement": "Core problem in one sentence (may reframe differently)",
    "approach_summary": "High-level strategy (2-3 sentences, should differ from A)",
    "assumptions": ["Assumption made with justification, include challenged assumptions"],
    "alternatives_considered": ["Alternative considered with why accepted/rejected"],
    "steps": [
        {
            "id": "B1",
            "category": "discovery | design | build | test | rollout | rollback | monitoring | docs",
            "what": "Concrete action to perform",
            "why": "Why this step matters for the solution",
            "how": "Enough detail to start implementation",
            "evidence_refs": ["EV1", "EV2"],
            "likely_files": ["src/file.py"],
            "depends_on": ["B1"],
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
    "critical_path": ["B1", "B3", "B5"],
    "estimated_hours_80pct": 48,
    "estimated_calendar_days": 12,
    "quick_wins": ["Low-effort high-value items that can be delivered early"],
    "reasons_this_plan_may_fail": ["Risk 1: Specific failure mode", "Risk 2: Another failure mode"]
}

Validation:
    - plan_id: Must be "B"
    - posture: Must be "contrarian"
    - steps[].id: Pattern B1, B2, B3...
    - Material difference: Must differ in 2+ areas from typical conservative plan
    - evidence_refs: Must reference valid evidence IDs
"""
    
    def get_system_prompt(self) -> str:
        """Get the contrarian planner system prompt."""
        base = super().get_system_prompt()
        
        return f"""{base}

## Contrarian Posture Requirements

As the CONTRARIAN planner (Plan B), your job is to challenge defaults
and find better solutions that others might miss.

### Core Principles (MUST follow)

1. **Challenge the obvious approach**
   - Question "how it's always done"
   - Ask: "Is there a fundamentally different way?"
   - Don't accept "best practice" without scrutiny
   - Example: "Replace custom auth with OIDC provider" vs "Extend existing auth"

2. **Seek better outcome/risk ratio**
   - Accept MORE risk for MUCH better outcomes
   - 2x risk for 10x benefit? Worth considering.
   - 2x risk for 1.2x benefit? Not worth it.
   - Calculate: (outcome_improvement) / (risk_increase)

3. **Consider alternatives others dismiss**
   - Technology changes: newer libs, different languages
   - Pattern changes: event-driven vs request-response
   - Architecture changes: microservices vs monolith, serverless vs containers
   - What would a startup do differently?

4. **Question constraints**
   - Are requirements actually HARD constraints?
   - "Must use Python" - really, or just preferred?
   - "Can't change database" - technical or political limit?
   - Distinguish: hard stops vs uncomfortable changes

5. **Optimize for long-term**
   - Short-term pain for sustainable solutions
   - Technical debt reduction
   - Maintainability over quick delivery
   - Future extensibility

### Material Difference Requirement (CRITICAL)

Your plan MUST differ MATERIALLY from a conservative approach in at least
TWO of the following dimensions:

1. **Primary solution class**
   - Different technology (e.g., use new framework vs extend old)
   - Different pattern (e.g., events vs synchronous)

2. **Sequencing**
   - Different order of operations
   - Parallel vs sequential approach

3. **Rollout strategy**
   - Different deployment approach
   - Big bang vs incremental vs feature flags

4. **Rollback strategy**
   - Different recovery approach
   - Automated vs manual recovery

5. **Reuse choice**
   - Build vs buy vs extend differently
   - Third-party vs internal solution

6. **Risk posture**
   - Accept different risk profile
   - Trade safety for speed/quality elsewhere

### A Paraphrase of Plan A is a FAILURE

If your plan looks like Plan A with different words, you have FAILED.
You must genuinely explore alternatives. Be bold. Be different.

### Evidence Requirements

- Every step MUST cite at least one evidence reference (EV1, EV2, ...)
- Challenge assumptions based on evidence
- Use inference chains: [Based on EV1, EV2] <conclusion>
- Mark assumptions you had to make without proof

### Isolation Rule

You are COMPLETELY ISOLATED from Planner A. You will NOT see their output.
Produce your best independent solution without knowing the alternative.

### Deliverable Checklist

☐ All steps have evidence_refs (at least one)
☐ Material difference documented in approach_summary
☐ At least 2 dimensions of difference from typical conservative plan
☐ Contrarian stance clearly articulated
☐ Assumptions challenged where appropriate
☐ Alternatives considered listed with reasoning
☐ Each step has risk + risk_severity + mitigation
☐ 3-5 reasons this plan may fail (be honest about new risks)
"""
