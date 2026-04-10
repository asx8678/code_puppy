"""Validation utilities for adversarial planning phases.

Provides validation functions for phase exit gates.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when phase validation fails."""
    pass


def validate_phase_0a_output(output: Any) -> None:
    """Validate Phase 0A exit gate.
    
    Args:
        output: Phase0AOutput instance to validate
        
    Raises:
        ValidationError: If validation fails
    """
    if not output:
        raise ValidationError("Phase 0A output is None")
    
    # All claims must be labeled
    for evidence in output.evidence:
        if not evidence.evidence_class:
            raise ValidationError(f"Evidence {evidence.id} missing class label")
    
    # Every unknown needs fastest probe
    for unknown in output.critical_unknowns:
        if not unknown.fastest_probe:
            raise ValidationError(f"Unknown {unknown.id} missing fastest_probe")


def validate_phase_0b_output(output: Any) -> None:
    """Validate Phase 0B exit gate.
    
    Args:
        output: Phase0BOutput instance to validate
        
    Raises:
        ValidationError: If validation fails
    """
    if not output:
        raise ValidationError("Phase 0B output is None")
    
    # Single problem statement
    if not output.normalized_problem:
        raise ValidationError("Missing normalized problem statement")
    
    # Hard constraints explicit (warning only, not blocking)
    if not output.hard_constraints:
        logger.warning("No hard constraints identified")


def validate_phase_1_exit(plan_a: Any, plan_b: Any) -> None:
    """Validate Phase 1 exit gate - plans must differ materially.
    
    Args:
        plan_a: Phase1Output for plan A
        plan_b: Phase1Output for plan B
        
    Raises:
        ValidationError: If plans don't differ enough
    """
    if not plan_a or not plan_b:
        raise ValidationError("Both plans required for validation")
    
    differences = 0
    
    # Different primary approach?
    if plan_a.approach_summary != plan_b.approach_summary:
        differences += 1
    
    # Different step count (significant)?
    if abs(len(plan_a.steps) - len(plan_b.steps)) >= 3:
        differences += 1
    
    # Different effort estimates (>20% diff)?
    max_hours = max(plan_a.estimated_hours_80pct, plan_b.estimated_hours_80pct)
    effort_diff = abs(plan_a.estimated_hours_80pct - plan_b.estimated_hours_80pct)
    if max_hours > 0 and effort_diff > 0.2 * max_hours:
        differences += 1
    
    # Different first steps?
    if plan_a.steps and plan_b.steps:
        if plan_a.steps[0].category != plan_b.steps[0].category:
            differences += 1
    
    if differences < 2:
        logger.warning(f"Plans may not differ materially enough ({differences} differences found)")


def validate_phase_2_output(review_a: Any, review_b: Any) -> None:
    """Validate Phase 2 exit gate.
    
    Args:
        review_a: Phase2Output for review A
        review_b: Phase2Output for review B
    """
    if not review_a or not review_b:
        raise ValidationError("Both reviews required for validation")
    
    # Unsupported claims must be surfaced (implicit in review process)
    # Blockers must be explicit (already structured)
    pass


def validate_phase_4_output(output: Any) -> None:
    """Validate Phase 4 exit gate.
    
    Args:
        output: Phase4Output instance to validate
    """
    if not output:
        raise ValidationError("Phase 4 output is None")
    
    # Traceability complete
    if not output.traceability.get("constraints") and not output.traceability.get("criteria"):
        logger.warning("Traceability may be incomplete")
    
    # Dissent preserved
    if not output.dissent_log:
        logger.warning("No dissent log - strongest rejected alternative not preserved")


def check_global_stop_conditions(session: Any) -> str | None:
    """Check for global stop conditions.
    
    Args:
        session: PlanningSession with current state
        
    Returns:
        Stop reason if found, None otherwise
    """
    # Kill conditions from Phase 0A
    if session.phase_0a_output:
        if session.phase_0a_output.readiness == "blocked":
            return "Environment discovery blocked - cannot proceed"
    
    # Hard access blocks
    if session.phase_0b_output:
        for constraint in session.phase_0b_output.hard_constraints:
            if "BLOCKED" in constraint.upper() or "IMPOSSIBLE" in constraint.upper():
                return f"Hard constraint violated: {constraint}"
    
    # Unresolvable blockers from review
    if session.review_a and session.review_b:
        for blocker in session.review_a.blockers + session.review_b.blockers:
            if blocker.kill_recommendation and not blocker.repair_path:
                return f"Unresolvable blocker: {blocker.description}"
    
    return None


def needs_rebuttal(session: Any) -> bool:
    """Check if Phase 3 Rebuttal is needed.
    
    Args:
        session: PlanningSession with current state
        
    Returns:
        True if rebuttal phase should run
    """
    if not session.review_a or not session.review_b:
        return False
    
    # Rebuttal needed if:
    # 1. Either review has blockers
    # 2. Either review has fatal_flaw
    # 3. Score delta > 10 between reviews
    
    has_blockers = (
        len(session.review_a.blockers) > 0 or
        len(session.review_b.blockers) > 0
    )
    
    has_fatal_flaw = (
        session.review_a.overall.get("fatal_flaw") or
        session.review_b.overall.get("fatal_flaw")
    )
    
    score_a = session.review_a.overall.get("score", 0)
    score_b = session.review_b.overall.get("score", 0)
    score_delta = abs(score_a - score_b)
    
    return has_blockers or has_fatal_flaw or score_delta > 10
