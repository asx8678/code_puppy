"""Prompt building utilities for adversarial planning.

Builds structured prompts for each phase of the adversarial planning workflow.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import (
        AdversarialPlanConfig,
        Evidence,
        Phase0AOutput,
        Phase0BOutput,
        Phase1Output,
        Phase2Output,
    )


def format_evidence_list(evidence: list) -> str:
    """Format evidence list for prompts."""
    lines = []
    for e in evidence:
        lines.append(f"- [{e.id}] ({e.evidence_class.value}): {e.claim}")
        lines.append(f"  Source: {e.source.kind}:{e.source.locator}")
    return "\n".join(lines)


def format_unknowns_list(unknowns: list) -> str:
    """Format unknowns list for prompts."""
    lines = []
    for u in unknowns:
        lines.append(f"- [{u.id}] {u.question}")
        lines.append(f"  Why it matters: {u.why_it_matters}")
        lines.append(f"  Fastest probe: {u.fastest_probe}")
    return "\n".join(lines)


def build_researcher_prompt(config: "AdversarialPlanConfig") -> str:
    """Build Phase 0A researcher prompt.
    
    Args:
        config: The planning configuration
        
    Returns:
        Prompt string for the researcher agent
    """
    return f"""## Task: Environment & Evidence Discovery

Investigate this task before any planning:
{config.task}

Workspace: {config.context.workspace}
Branch/Commit: {config.context.branch_or_commit or 'HEAD'}
Access Limitations: {', '.join(config.context.access_limitations) or 'None specified'}

Your job:
1. Inspect targeted local artifacts (files nearest the likely blast radius)
2. Find existing internal patterns to reuse
3. Identify contradictions between docs/code/config
4. Surface critical unknowns that could change architecture/risk/effort
5. Do NOT propose solutions - only discover evidence

Output your findings as structured JSON matching the Phase 0A schema.
"""


def build_scope_lock_prompt(
    config: "AdversarialPlanConfig",
    phase_0a_output: "Phase0AOutput | None"
) -> str:
    """Build Phase 0B scope lock prompt.
    
    Args:
        config: The planning configuration
        phase_0a_output: Output from Phase 0A (if available)
        
    Returns:
        Prompt string for the scope lock task
    """
    evidence_summary = ""
    if phase_0a_output:
        evidence_summary = f"""
## Evidence from Discovery:
- Readiness: {phase_0a_output.readiness}
- Files examined: {len(phase_0a_output.files_examined)}
- Patterns to reuse: {phase_0a_output.existing_patterns_to_reuse}
- Critical unknowns: {len(phase_0a_output.critical_unknowns)}
"""
    
    return f"""## Task: Scope Lock

Based on the discovery evidence, lock the scope for planning:
{config.task}

{evidence_summary}

Your job:
1. Strip symptoms and restate the ACTUAL problem (one sentence)
2. Identify the problem type (feature/bugfix/migration/incident/replatform/performance/security)
3. Preserve hard constraints
4. Surface architecture-shaping unknowns
5. Do NOT recommend a solution shape - that biases planners

Output structured JSON matching the Phase 0B schema.
"""


def build_evidence_pack(phase_0a_output: "Phase0AOutput | None") -> str:
    """Build evidence pack for planners (shared, read-only).
    
    Args:
        phase_0a_output: Output from Phase 0A
        
    Returns:
        Evidence pack string for planner prompts
    """
    if not phase_0a_output:
        return "## Evidence Pack (Read-Only)\n\nNo evidence available."
    
    output = phase_0a_output
    return f"""## Evidence Pack (Read-Only)

### Workspace Summary
{output.workspace_summary}

### Problem Signature
{output.problem_signature}

### Evidence (Top 15)
{format_evidence_list(output.evidence[:15])}

### Existing Patterns to Reuse
{chr(10).join(f'- {p}' for p in output.existing_patterns_to_reuse)}

### Blast Radius
{chr(10).join(f'- {b}' for b in output.blast_radius)}

### Critical Unknowns
{format_unknowns_list(output.critical_unknowns)}
"""


def build_scope_lock_pack(phase_0b_output: "Phase0BOutput | None") -> str:
    """Build scope lock for planners.
    
    Args:
        phase_0b_output: Output from Phase 0B
        
    Returns:
        Scope lock string for planner prompts
    """
    if not phase_0b_output:
        return "## Scope Lock\n\nNo scope lock available."
    
    output = phase_0b_output
    return f"""## Scope Lock

### Normalized Problem
{output.normalized_problem}

### Problem Type
{output.problem_type}

### Hard Constraints
{chr(10).join(f'- {c}' for c in output.hard_constraints)}

### In Scope
{chr(10).join(f'- {s}' for s in output.in_scope)}

### Out of Scope
{chr(10).join(f'- {s}' for s in output.out_of_scope)}

### Planning Guardrails
{chr(10).join(f'- {g}' for g in output.planning_guardrails)}
"""


def build_planner_prompt(
    plan_id: str,
    posture: str,
    evidence_pack: str,
    scope_lock: str
) -> str:
    """Build prompt for a planner agent.
    
    Args:
        plan_id: Plan identifier (A or B)
        posture: Planning posture (conservative or contrarian)
        evidence_pack: Evidence pack string
        scope_lock: Scope lock string
        
    Returns:
        Prompt string for the planner
    """
    return f"""## Task: Create Plan {plan_id} ({posture.upper()} posture)

{evidence_pack}

{scope_lock}

Create your plan following the {posture} posture requirements.

Remember:
1. You CANNOT see the other planner's work
2. Your plan must include at least one early de-risking step
3. Every step must reference evidence (EV1, EV2, etc.)
4. Include operational readiness (validation, rollout, rollback, monitoring)

Output structured JSON matching the Phase 1 schema with plan_id="{plan_id}".
"""


def _format_evidence_for_review(evidence: list) -> str:
    """Format evidence items for reviewer prompt inclusion.
    
    Args:
        evidence: List of EvidenceItem objects
        
    Returns:
        Formatted string summary of evidence for reviewer context
    """
    lines = []
    for ev in evidence[:10]:  # Limit to prevent prompt bloat
        ev_class = getattr(ev, 'evidence_class', 'unknown')
        claim = getattr(ev, 'claim', 'N/A')
        confidence = getattr(ev, 'confidence', 0)
        # Handle both string and enum evidence_class
        if hasattr(ev_class, 'value'):
            ev_class = ev_class.value
        lines.append(f"- [{str(ev_class).upper()}] {claim} (confidence: {confidence}%)")
    if len(evidence) > 10:
        lines.append(f"... and {len(evidence) - 10} more evidence items")
    return "\n".join(lines)


def build_review_prompt(
    plan: "Phase1Output",
    plan_id: str,
    *,
    evidence_pack: list | None = None,
    scope_lock: "Phase0BOutput | None" = None,
    success_criteria: list[str] | None = None,
    hard_constraints: list[str] | None = None,
) -> str:
    """Build review prompt for a plan.
    
    Args:
        plan: The plan to review
        plan_id: Identifier for the plan being reviewed
        evidence_pack: Evidence items from Phase 0A discovery
        scope_lock: Scope lock output from Phase 0B
        success_criteria: List of success criteria to validate against
        hard_constraints: List of hard constraints to validate against
        
    Returns:
        Prompt string for the reviewer
    """
    evidence_section = ""
    if evidence_pack:
        evidence_section = f"""
## Available Evidence (from Phase 0A)
{_format_evidence_for_review(evidence_pack)}
"""

    scope_section = ""
    if scope_lock:
        normalized_problem = getattr(scope_lock, 'normalized_problem', 'N/A')
        problem_signature = getattr(scope_lock, 'problem_signature', 'N/A')
        scope_section = f"""
## Scope Lock (from Phase 0B)
- Problem: {normalized_problem}
- Signature: {problem_signature}
"""

    criteria_section = ""
    if success_criteria:
        criteria_section = f"""
## Success Criteria to Validate
{chr(10).join(f'- {c}' for c in success_criteria)}
"""

    constraints_section = ""
    if hard_constraints:
        constraints_section = f"""
## Hard Constraints to Validate
{chr(10).join(f'- {c}' for c in hard_constraints)}
"""

    return f"""## Task: Adversarial Review of Plan {plan_id}

### Plan to Review:
{plan.model_dump_json(indent=2)}
{evidence_section}
{scope_section}
{criteria_section}
{constraints_section}

### Your Mission: FALSIFY this plan

1. Attack every unsupported claim
2. Find the fatal flaw (if any)
3. Check if the problem is even correct
4. Verify cited evidence actually exists
5. Test assumptions against the real codebase
6. Identify missing steps
7. Reassess effort realistically

For every issue:
- Explain trigger, mechanism, and impact
- Provide repair path OR recommend killing the step

Output structured JSON matching the Phase 2 schema.
"""


def build_rebuttal_prompt(plan: "Phase1Output", review: "Phase2Output") -> str:
    """Build rebuttal prompt for a planner.
    
    Args:
        plan: The original plan
        review: The review output
        
    Returns:
        Prompt string for the rebuttal
    """
    return f"""## Task: Rebuttal for Plan {plan.plan_id}

### Original Plan:
{plan.model_dump_json(indent=2)}

### Review Criticisms:
{review.model_dump_json(indent=2)}

### Your Task:
1. Accept valid criticism (update your plan)
2. Rebut only with NEW EVIDENCE (not rhetoric)
3. Revise only the affected steps - do not rewrite everything
4. If criticism is correct, acknowledge it

Output an updated plan with the same structure (Phase 1 schema).
"""


def _format_evidence_summary(evidence_pack: list) -> str:
    """Format evidence pack for synthesis prompt context.
    
    Args:
        evidence_pack: List of Evidence items
        
    Returns:
        Formatted evidence summary string
    """
    if not evidence_pack:
        return "No evidence available."
    
    lines = []
    for e in evidence_pack[:15]:  # Top 15 evidence items
        lines.append(f"- [{e.id}] ({e.evidence_class.value}): {e.claim}")
    
    # Add summary counts
    from collections import Counter
    counts = Counter(e.evidence_class.value for e in evidence_pack)
    lines.append("")
    lines.append(f"**Summary**: {len(evidence_pack)} items total")
    lines.append(f"  - Verified: {counts.get('verified', 0)}")
    lines.append(f"  - Inference: {counts.get('inference', 0)}")
    lines.append(f"  - Assumption: {counts.get('assumption', 0)}")
    lines.append(f"  - Unknown: {counts.get('unknown', 0)}")
    
    return "\n".join(lines)


def build_synthesis_prompt(
    plan_a: "Phase1Output | None",
    plan_b: "Phase1Output | None",
    review_a: "Phase2Output | None",
    review_b: "Phase2Output | None",
    *,
    evidence_pack: list["Evidence"] | None = None,
    scope_lock: "Phase0BOutput | None" = None,
    success_criteria: list[str] | None = None,
    hard_constraints: list[str] | None = None,
) -> str:
    """Build synthesis prompt for the arbiter.
    
    Args:
        plan_a: Plan A output
        plan_b: Plan B output
        review_a: Review of Plan A
        review_b: Review of Plan B
        evidence_pack: Evidence items from Phase 0A Discovery
        scope_lock: Scope lock from Phase 0B
        success_criteria: Optional success criteria to include
        hard_constraints: Optional hard constraints to include
        
    Returns:
        Prompt string for synthesis
    """
    # Build context sections
    evidence_section = ""
    if evidence_pack:
        evidence_section = f"""## Available Evidence (from Phase 0A Discovery)
{_format_evidence_summary(evidence_pack)}
"""

    scope_section = ""
    if scope_lock:
        scope_section = f"""## Problem Scope (from Phase 0B)
- Problem: {scope_lock.normalized_problem}
- Type: {scope_lock.problem_type}
- Hard Constraints: {', '.join(scope_lock.hard_constraints) or 'None'}
"""

    criteria_section = ""
    if success_criteria:
        criteria_section = "## Success Criteria\n" + "\n".join(f"- {c}" for c in success_criteria) + "\n"

    constraints_section = ""
    if hard_constraints:
        constraints_section = "## Hard Constraints\n" + "\n".join(f"- {c}" for c in hard_constraints) + "\n"

    return f"""## Task: Synthesize Best Plan

{evidence_section}{scope_section}{criteria_section}{constraints_section}### Plan A (Conservative):
{plan_a.model_dump_json(indent=2) if plan_a else 'N/A'}

### Review of Plan A:
{review_a.model_dump_json(indent=2) if review_a else 'N/A'}

### Plan B (Contrarian):
{plan_b.model_dump_json(indent=2) if plan_b else 'N/A'}

### Review of Plan B:
{review_b.model_dump_json(indent=2) if review_b else 'N/A'}

### Decision Rules (apply in order):
1. Verified facts outrank inference
2. False claims are removed or repaired
3. Reviewer-added missing steps must be considered
4. Simpler beats complex when impact similar
5. More reversible beats less reversible when outcome similar
6. Existing patterns beat bespoke when fit adequate
7. Unresolved unknowns remain blockers
8. Preserve dissent log

Output the merged plan as Phase 4 schema JSON.
"""


def build_red_team_prompt(synthesis: "Any") -> str:
    """Build red team prompt.
    
    Args:
        synthesis: Synthesis output from Phase 4
        
    Returns:
        Prompt string for the red team
    """
    return f"""## Task: Red Team Stress Test

### Merged Plan to Attack:
{synthesis.model_dump_json(indent=2) if synthesis else 'N/A'}

### Attack Vectors (check ALL):
1. Single point of failure
2. Invalid assumption
3. Timeline slip (150%, 200%)
4. Key person loss
5. Dependency failure
6. Edge case
7. Security/privacy issue
8. Migration/compatibility issue
9. Observability blind spot
10. Rare but real scenario

Find weaknesses. If fatal flaw exists and is fixable, suggest patch.
If resilient, issue clean_bill_of_health.

Output Phase 5 schema JSON.
"""


def build_decision_prompt(
    synthesis: "Any",
    red_team: "Any | None"
) -> str:
    """Build decision prompt.
    
    Args:
        synthesis: Synthesis output from Phase 4
        red_team: Red team output from Phase 5 (if deep mode)
        
    Returns:
        Prompt string for the decision phase
    """
    red_team_summary = ""
    if red_team:
        red_team_summary = f"""
### Red Team Results:
- Attack Surface: {red_team.overall.get('attack_surface', 'unknown')}
- Fatal Flaw: {red_team.overall.get('fatal_flaw', 'None')}
- Clean Bill: {red_team.clean_bill_of_health}
"""
    
    return f"""## Task: Execution Decision

### Merged Plan:
{synthesis.model_dump_json(indent=2) if synthesis else 'N/A'}

{red_team_summary}

### Scoring Axes:
- Impact: 0.30
- Feasibility: 0.25
- Risk-adjusted: 0.25
- Urgency: 0.20

### Plan-Level Verdict Bands (plan_verdict field):
- ≥75: go
- 55-74: conditional_go
- <55: no_go

Note: `defer` and `skip` are valid only for step-level verdicts (StepEvaluation.verdict), not plan-level.

Evaluate each step. Determine execution order. Identify quick wins.
Define minimum viable plan and full plan.
List what must be verified first (first_probes).
Calculate raw score, then I'll apply penalties.

Output Phase 6 schema JSON.
"""


def build_changeset_prompt(decision: "Any") -> str:
    """Build changeset prompt.
    
    Args:
        decision: Decision output from Phase 6
        
    Returns:
        Prompt string for changeset synthesis
    """
    return f"""## Task: Change-Set Synthesis

### Decision:
{decision.model_dump_json(indent=2) if decision else 'N/A'}

### Execution Order:
{decision.execution_order if decision else []}

Translate approved steps into reversible logical change sets.
Identify the lowest-risk first change.
Include verification sequence.

Output Phase 7 schema JSON.
"""
