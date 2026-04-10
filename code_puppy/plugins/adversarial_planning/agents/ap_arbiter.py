"""Phase 4 Arbiter Agent.

Merges surviving elements from competing plans into executable plan.
The Arbiter synthesizes the best elements from Plans A and B after
adversarial review, resolves conflicts, and produces a unified plan.

This is NOT compromise - it's selecting what SURVIVED scrutiny.
"""

from .base_adversarial_agent import BaseAdversarialAgent


class APArbiterAgent(BaseAdversarialAgent):
    """Phase 4/6 - Synthesis & Decision Agent.
    
    The Arbiter's role is to:
    - Merge the best elements from both plans
    - Resolve conflicts between plans
    - Remove or repair falsified claims
    - Explicitly consider reviewer-added missing steps
    - Preserve a dissent log of rejected alternatives
    - Produce a unified executable plan
    
    Philosophy: "You are NOT creating a compromise. You are selecting what SURVIVED."
    
    Tools:
        - list_files: Verify file references
        - read_file: Read evidence and plans
        - grep: Search for patterns to validate
        - list_agents: Coordinate with specialists
        - invoke_agent: Delegate verification tasks
        - list_or_search_skills: Find relevant skills
        - ask_user_question: Clarify ambiguities
    
    Output:
        Phase4Output model with merged plan.
    """
    
    ROLE_NAME = "arbiter"
    ROLE_DESCRIPTION = "Merges surviving elements into executable plan"
    
    # Arbiter needs FULL coordination capabilities
    ALLOWED_TOOLS = [
        "list_files",
        "read_file",
        "grep",
        "list_agents",       # Coordinate with specialists
        "invoke_agent",      # Delegate verification tasks
        "list_or_search_skills",
        "ask_user_question", # Clarify ambiguities
    ]
    
    OUTPUT_SCHEMA = """
{
    "merged_problem": "Single unified problem statement",
    "merged_approach": "Best combined strategy from surviving elements",
    "merged_steps": [
        {
            "id": "A3 | B2 | etc",
            "category": "discovery | design | build | test | rollout | rollback | monitoring | docs",
            "what": "Concrete action",
            "why": "Why it matters",
            "how": "Implementation detail",
            "evidence_refs": ["EV1", "EV2"],
            "likely_files": ["src/file.py"],
            "depends_on": ["A1"],
            "covers_constraints": ["constraint_id"],
            "covers_criteria": ["criterion_id"],
            "risk": "What could go wrong",
            "risk_severity": "low | medium | high | critical",
            "mitigation": "How to reduce risk",
            "effort_hours_80pct": 8,
            "reversible": true,
            "approval_needed": "none | write_access | production_change | security_or_compliance",
            "exit_criteria": "Done when...",
            "source_plan": "A | B | reviewer | merged",
            "survival_reason": "Why this step survived review"
        }
    ],
    "operational_readiness": {
        "validation": "How to validate",
        "rollout": "How to roll out",
        "rollback": "How to roll back",
        "rollback_time": "Estimated rollback time",
        "monitoring": "What to monitor"
    },
    "traceability": {
        "constraints": [
            {"constraint": "Constraint description", "covered_by": ["A3", "B2"]}
        ],
        "criteria": [
            {"criterion": "Success criterion", "validated_by": ["A5"]}
        ]
    },
    "critical_path": ["A1", "B3", "A5"],
    "resolved_conflicts": [
        "Chose A's approach for X because [reason based on evidence/review]"
    ],
    "discarded_steps": [
        {
            "step_id": "B4",
            "reason": "Review found fatal flaw: [specific reason]"
        }
    ],
    "blockers": [
        {
            "id": "BLK1",
            "description": "Unresolved blocker",
            "severity": "blocker | critical | major",
            "repair_path": "How to resolve"
        }
    ],
    "dissent_log": [
        {
            "alternative": "Strongest rejected alternative",
            "why_rejected": "Evidence/review that eliminated it"
        }
    ],
    "estimated_hours_80pct": 56,
    "merged_confidence": 81
}

Validation:
    - merged_steps[].source_plan: Track origin of each step
    - resolved_conflicts: Document every decision between A and B
    - dissent_log: Preserve strongest rejected alternative
    - estimated_hours_80pct: Sum of surviving steps
    - merged_confidence: 0-100 based on evidence quality and review
"""
    
    def get_system_prompt(self) -> str:
        """Get the arbiter synthesis system prompt."""
        base = super().get_system_prompt()
        
        return f"""{base}

## Synthesis Decision Rules

Apply these rules IN ORDER. Lower-numbered rules override higher ones.

### Rule 1: Verified Facts Outrank Inference
- VERIFIED evidence beats INFERENCE
- INFERENCE beats ASSUMPTION
- False claims are removed or repaired (NOT hidden)

### Rule 2: Reviewer-Added Missing Steps Must Be Considered
- If a reviewer identified a missing step, you MUST address it
- Either: include the step, explain why not needed, or document as blocker

### Rule 3: Simpler Beats Complex (When Impact Similar)
- If two approaches achieve similar outcomes
- Choose the simpler one (fewer steps, less complexity)
- Example: A achieves goal in 3 steps, B in 7 → choose A's approach

### Rule 4: More Reversible Beats Less (When Outcome Similar)
- Reversible: feature flags, new endpoints, blue-green
- Irreversible: DB migrations, API removals, auth changes
- Choose more reversible when outcomes are equivalent

### Rule 5: Existing Patterns Beat Bespoke (When Fit Adequate)
- Match existing codebase patterns
- Don't introduce novelty without strong justification
- "Different" needs evidence of "better"

### Rule 6: Unresolved Critical Unknowns Remain Blockers
- If there's an unknown without resolution
- Make it a blocker in the merged plan
- Don't proceed blindly

### Rule 7: Preserve a Dissent Log
- Record the strongest rejected alternative
- Explain why it was rejected (evidence, review findings)
- Future teams can learn from rejected paths

## What You Are NOT Doing

❌ **Creating a compromise** - "split the difference" plans fail
❌ **Averaging plans** - (3 risky + 3 safe) / 2 is not a solution
❌ **Cherry-picking** - selecting only easy parts
❌ **Ignoring reviews** - "I like this step" over "reviewer said it's wrong"

## What You ARE Doing

✅ **Selecting what survived** - evidence + review = keep
✅ **Merging complementary strengths** - A's rollback + B's rollout
✅ **Resolving genuine conflicts** - explicit decision with reasoning
✅ **Removing falsified claims** - false stays out, period
✅ **Adding missing steps** - reviewer additions improve the plan

## Conflict Resolution Template

When A and B differ, document:
```
"Chose [A|B]'s approach for [aspect] because [decision rule applied].
Rejected alternative: [summary]. Evidence: [refs]."
```

## Deliverable Checklist

☐ Every merged step has source_plan tracking (A/B/reviewer/merged)
☐ Every conflict has explicit resolution with reasoning
☐ Every discarded step has reason (review finding, falsified claim)
☐ Dissent log preserves strongest rejected alternative
☐ Traceability maps constraints and criteria to steps
☐ Blockers clearly identified with severity
☐ Confidence honestly assessed (0-100)
"""
