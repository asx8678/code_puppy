"""Pydantic data models for the Adversarial Planning system.

All models are designed for strict validation and clear communication
between planning phases. Evidence classes enforce the confidence
hierarchy: verified > inference > assumption > unknown.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Literal
from enum import Enum


class EvidenceClass(str, Enum):
    """Confidence hierarchy for evidence classification.
    
    VERIFIED: Directly observed or confirmed
    INFERENCE: Reasonable conclusion from verified facts
    ASSUMPTION: Accepted without verification (risks)
    UNKNOWN: Recognized gap in knowledge
    """
    VERIFIED = "verified"
    INFERENCE = "inference"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"


class EvidenceSource(BaseModel):
    """Source metadata for evidence traceability.
    
    The locator uses standardized formats:
    - File: "path/to/file.py:12-48" (lines 12-48)
    - URL: "https://github.com/.../blob/SHA/path.py#L12-L48"
    - Test: "test_file.py::test_function"
    - CI: "workflow.yml:job_name"
    - Config: "pyproject.toml:[section.key]"
    """
    kind: Literal["file", "test", "config", "ci", "log", "metric", "url", "prompt"]
    locator: str  # path/to/file.ext:12-48 or https://source
    freshness: str | None = None  # YYYY-MM-DD
    version_or_commit: str | None = None  # semver or SHA


class Evidence(BaseModel):
    """Individual evidence item with classification and confidence.
    
    IDs follow pattern EV1, EV2, etc. for cross-referencing.
    Confidence is a 0-100 scale where:
    - 90-100: Verified with high confidence
    - 70-89: Inferred with strong support
    - 50-69: Assumed or inferred with caveats
    - 0-49: Low confidence or unknown
    """
    id: str = Field(pattern=r"^EV\d+$")  # EV1, EV2, etc.
    evidence_class: EvidenceClass = Field(alias="class")
    claim: str = Field(min_length=1)
    source: EvidenceSource
    confidence: int = Field(ge=0, le=100)

    @field_validator("evidence_class", mode="before")
    @classmethod
    def normalize_class(cls, v):
        """Accept both enum and string values."""
        if isinstance(v, str):
            return EvidenceClass(v)
        return v

    class Config:
        populate_by_name = True


class CriticalUnknown(BaseModel):
    """A recognized gap in knowledge that affects planning.
    
    Every critical unknown must have a fastest_probe path for
    discovery, and must declare if we can proceed without it.
    """
    id: str = Field(pattern=r"^UNK\d+")  # UNK1, UNK2, etc.
    question: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    fastest_probe: str = Field(min_length=1)
    can_proceed_without: bool = False
    discovery_method: str | None = None
    default_assumption: str | None = None
    reversibility: Literal["reversible", "hard_to_reverse", "must_know_first"] | None = None


# =============================================================================
# Phase 0: Context Extraction & Problem Framing
# =============================================================================

class Phase0AOutput(BaseModel):
    """Researcher output: Workspace survey and evidence gathering.
    
    The researcher classifies workspace readiness and identifies
    critical unknowns before any planning begins.
    """
    readiness: Literal["ready", "limited", "blocked"]
    confidence: int = Field(ge=0, le=100)
    workspace_summary: str = Field(min_length=1)
    problem_signature: str = Field(min_length=1)
    evidence: list[Evidence] = []
    files_examined: list[str] = []
    existing_patterns_to_reuse: list[str] = []
    contradictions: list[str] = []
    blast_radius: list[str] = []
    critical_unknowns: list[CriticalUnknown] = []


class Phase0BOutput(BaseModel):
    """Framer output: Normalized problem statement with scope.
    
    Consolidates Phase 0A evidence into a normalized problem
    statement with clear boundaries.
    """
    normalized_problem: str = Field(min_length=1)
    problem_type: Literal[
        "feature", "bugfix", "migration", "incident", 
        "replatform", "performance", "security"
    ]
    verified_facts: list[str] = []
    inferences: list[str] = []
    hard_constraints: list[str] = []
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    critical_unknowns: list[CriticalUnknown] = []
    planning_guardrails: list[str] = []
    pre_mortem: dict = Field(default_factory=dict)  # scenario + causes


# =============================================================================
# Phase 1: Dual Proposal Generation
# =============================================================================

class PlanStep(BaseModel):
    """Single step within a plan with full traceability.

    Steps are identified as:
    - A1, A2, A3... for Plan A steps
    - B1, B2, B3... for Plan B steps
    - M1, M2, M3... for merged/synthesized steps (Phase 4)
    """
    id: str = Field(pattern=r"^[ABM]\d+")  # A1, A2, B1, B2, M1, M2, etc.
    category: Literal[
        "discovery", "design", "build", "test", 
        "rollout", "rollback", "monitoring", "docs"
    ]
    what: str = Field(min_length=1)
    why: str = Field(min_length=1)
    how: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    likely_files: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    covers_constraints: list[str] = Field(default_factory=list)
    covers_criteria: list[str] = Field(default_factory=list)
    risk: str = Field(min_length=1)
    risk_severity: Literal["low", "medium", "high", "critical"]
    mitigation: str = Field(min_length=1)
    effort_hours_80pct: float = Field(ge=0)
    reversible: bool
    approval_needed: Literal[
        "none", "write_access", "production_change", 
        "security_or_compliance"
    ]
    exit_criteria: str = Field(min_length=1)

    # Provenance fields (optional, used in Phase 4 merged steps)
    source_plan: Literal["A", "B", "merged"] | None = None
    survival_reason: str | None = None


class OperationalReadiness(BaseModel):
    """Operational plan for validation, rollout, and rollback."""
    validation: str = Field(min_length=1)
    rollout: str = Field(min_length=1)
    rollback: str = Field(min_length=1)
    rollback_time: str | None = None
    monitoring: str = Field(min_length=1)


class Phase1Output(BaseModel):
    """Planner output: Complete plan with traceability to evidence.
    
    Two planners produce materially different solutions:
    - Planner A: Conservative, proven patterns
    - Planner B: Contrarian, higher-risk/higher-reward
    """
    plan_id: Literal["A", "B"]
    posture: Literal["conservative", "contrarian"]
    problem_restatement: str = Field(min_length=1)
    approach_summary: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    operational_readiness: OperationalReadiness
    critical_path: list[str] = Field(default_factory=list)
    estimated_hours_80pct: float = Field(ge=0)
    estimated_calendar_days: float = Field(ge=0)
    quick_wins: list[str] = Field(default_factory=list)
    reasons_this_plan_may_fail: list[str] = Field(default_factory=list)


# =============================================================================
# Phase 2: Adversarial Review
# =============================================================================

class StepReview(BaseModel):
    """Reviewer assessment of a single plan step."""
    step_id: str
    verdict: Literal["accept", "modify", "reject"]
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class Blocker(BaseModel):
    """Blocking issue requiring resolution.
    
    Blockers can have repair paths or be fatal (kill_recommendation).
    """
    id: str
    description: str = Field(min_length=1)
    severity: Literal["blocker", "critical", "major"]
    repair_path: str | None = None
    kill_recommendation: bool = False


class Phase2Output(BaseModel):
    """Reviewer output: Brutal critique with actionable feedback.
    
    Each plan gets an adversarial review. Reviews can stop
    progress if fatal flaws are found.
    """
    reviewed_plan: Literal["A", "B"]
    overall: dict = Field(default_factory=dict)  # base_case, fatal_flaw, wrong_problem, score, ship_readiness, codebase_fit
    step_reviews: list[StepReview] = Field(default_factory=list)
    missing_steps: list[str] = Field(default_factory=list)
    assumption_audit: list[dict] = Field(default_factory=list)
    constraint_violations: list[str] = Field(default_factory=list)
    operational_gaps: OperationalReadiness
    effort_reassessment: dict = Field(default_factory=dict)  # planner_total, reviewer_estimate, reason
    blockers: list[Blocker] = Field(default_factory=list)
    strongest_surviving_element: str = Field(min_length=1)


# =============================================================================
# Phase 4: Synthesis (Phase 3 is transparent routing)
# =============================================================================

class Phase4Output(BaseModel):
    """Arbiter output: Merged plan from competing proposals.
    
    Arbiter synthesizes the best elements from both plans,
    resolves conflicts, and produces a unified plan.
    """
    merged_problem: str = Field(min_length=1)
    merged_approach: str = Field(min_length=1)
    merged_steps: list[PlanStep] = Field(default_factory=list)
    operational_readiness: OperationalReadiness
    traceability: dict = Field(default_factory=dict)  # constraints, criteria
    critical_path: list[str] = Field(default_factory=list)
    resolved_conflicts: list[str] = Field(default_factory=list)
    discarded_steps: list[str] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    dissent_log: list[dict] = Field(default_factory=list)  # alternative, why_rejected
    estimated_hours_80pct: float = Field(ge=0)
    merged_confidence: int = Field(ge=0, le=100)


# =============================================================================
# Phase 5: Red Team (Deep Mode)
# =============================================================================

class Attack(BaseModel):
    """Individual attack vector from red team analysis."""
    id: str
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    likelihood: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high", "critical"]
    affected_steps: list[str] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)


class Phase5Output(BaseModel):
    """Red team output: Stress-tested plan with attack scenarios.
    
    Red team exercises the merged plan under stress conditions
    to find latent risks before execution.
    """
    overall: dict = Field(default_factory=dict)  # attack_surface, most_vulnerable_area, fatal_flaw_found, fatal_flaw
    attacks: list[Attack] = Field(default_factory=list)
    cascading_failures: list[str] = Field(default_factory=list)
    timeline_stress: dict = Field(default_factory=dict)  # at_150_percent, at_200_percent, critical_deadline
    recommendations: list[str] = Field(default_factory=list)
    clean_bill_of_health: bool = False
    summary: str = Field(min_length=1)


# =============================================================================
# Phase 6: Decision
# =============================================================================

class StepEvaluation(BaseModel):
    """Per-step scoring from Phase 6 decision analysis."""
    step_id: str
    impact_score: float = Field(ge=0, le=100)
    feasibility_score: float = Field(ge=0, le=100)
    risk_adjusted_score: float = Field(ge=0, le=100)
    urgency_score: float = Field(ge=0, le=100)
    weighted_score: float = Field(ge=0, le=100)
    verdict: Literal["do", "conditional", "defer", "skip"]


class Penalty(BaseModel):
    """Penalties applied to raw plan score."""
    reason: str = Field(min_length=1)
    points: int


class Phase6Output(BaseModel):
    """Decision output: Go/No-Go verdict with evidence.
    
    Phase 6 is the executive decision point. Even a no-go
    must produce "monday_morning_actions".
    """
    evaluations: list[StepEvaluation] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    quick_wins: list[str] = Field(default_factory=list)
    minimum_viable_plan: dict = Field(default_factory=dict)  # steps, hours, covers_criteria, gaps
    full_plan: dict = Field(default_factory=dict)
    must_verify_first: list[str] = Field(default_factory=list)
    first_probes: list[str] = Field(default_factory=list)
    raw_plan_score: int
    penalties: list[Penalty] = Field(default_factory=list)
    adjusted_plan_score: int
    plan_verdict: Literal["go", "conditional_go", "no_go"]
    plan_condition: str | None = None
    constraint_compliance: dict = Field(default_factory=dict)  # status, violations
    criteria_coverage: dict = Field(default_factory=dict)
    monday_morning_actions: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    dissenting_note: str | None = None


# =============================================================================
# Phase 7: Change Sets (Deferred to implementation)
# =============================================================================

class ChangeSet(BaseModel):
    """Atomic change unit for execution."""
    id: str
    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    reversible: bool
    verification: list[str] = Field(default_factory=list)


class Phase7Output(BaseModel):
    """Implementation output: Ready-to-execute change sets.
    
    Phase 7 organizes the approved plan into discrete,
    verifiable change sets for safe execution.
    """
    change_sets: list[ChangeSet] = Field(default_factory=list)
    safe_first_change: dict = Field(default_factory=dict)  # goal, why_first, files
    verification_sequence: list[str] = Field(default_factory=list)
    release_notes: list[str] = Field(default_factory=list)


# =============================================================================
# Configuration Models
# =============================================================================

class WorkspaceContext(BaseModel):
    """Context for the workspace under analysis."""
    workspace: str
    branch_or_commit: str | None = None
    access_limitations: list[str] = Field(default_factory=list)


class AdversarialPlanConfig(BaseModel):
    """Configuration for an adversarial planning session.
    
    mode: auto (default) selects standard/deep based on task complexity
    task: The planning request from the user
    success_criteria: Specific, testable success conditions
    hard_constraints: Non-negotiable limits (time, cost, access)
    """
    mode: Literal["auto", "standard", "deep"] = "auto"
    context: WorkspaceContext
    task: str = Field(min_length=1)
    success_criteria: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)


# =============================================================================
# Session State
# =============================================================================

class PlanningSession(BaseModel):
    """Complete state for an adversarial planning session.
    
    Tracks progress through all phases and enables pause/resume.
    Each output field stores the result of its corresponding phase.
    """
    session_id: str
    config: AdversarialPlanConfig
    current_phase: str = "idle"
    mode_selected: Literal["standard", "deep"] | None = None
    phase_0a_output: Phase0AOutput | None = None
    phase_0b_output: Phase0BOutput | None = None
    plan_a: Phase1Output | None = None
    plan_b: Phase1Output | None = None
    review_a: Phase2Output | None = None
    review_b: Phase2Output | None = None
    synthesis: Phase4Output | None = None
    red_team: Phase5Output | None = None
    decision: Phase6Output | None = None
    change_sets: Phase7Output | None = None
    same_model_fallback: bool = False
    global_stop_reason: str | None = None
