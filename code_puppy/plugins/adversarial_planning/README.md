# Adversarial Planning Plugin

Evidence-first, isolated, execution-ready planning for high-stakes work.

## Overview

The Adversarial Planning system uses multiple specialized agents to:
1. **Discover evidence** before solutioning
2. **Generate isolated plans** from different perspectives  
3. **Adversarially review** to falsify weak claims
4. **Synthesize** only what survives scrutiny
5. **Red team** stress test (deep mode)
6. **Decide** go/conditional-go/no-go with full traceability

## Quick Start

```bash
# Start planning (auto-selects mode)
/ap Implement OAuth2 authentication with Google

# View progress
/ap-status

# Abort if needed
/ap-abort
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  /ap <task>                          │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│           AdversarialPlanningOrchestrator            │
│  • Mode selection (auto/standard/deep)               │
│  • Evidence tracking                                 │
│  • Session isolation                                 │
│  • Phase coordination                                │
└─────────────────────────────────────────────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    ▼                    ▼                    ▼
┌──────────┐      ┌───────────┐      ┌───────────┐
│Researcher│      │ Planner A │      │ Planner B │
│ (0A, 0B) │      │(conserv.) │      │(contrar.) │
└──────────┘      └───────────┘      └───────────┘
                         │
    ┌────────────────────┼────────────────────┐
    ▼                    ▼                    ▼
┌──────────┐      ┌───────────┐      ┌───────────┐
│ Reviewer │      │  Arbiter  │      │ Red Team  │
│  (Ph 2)  │      │(Ph 4,6,7) │      │  (Ph 5)   │
└──────────┘      └───────────┘      └───────────┘
```

## Phases

### Phase 0A: Environment & Evidence Discovery
- Inspect local artifacts
- Find existing patterns to reuse
- Surface contradictions
- Identify critical unknowns
- **Output**: Evidence pack, readiness assessment

### Phase 0B: Scope Lock
- Normalize the actual problem
- Preserve hard constraints
- Surface architecture-shaping unknowns
- **No solution bias** - planners see this, not a preferred approach

### Phase 1: Independent Planning
- Two planners work **in parallel, isolated**
- Planner A: Conservative (minimize blast radius)
- Planner B: Contrarian (challenge defaults)
- Plans must differ materially in 2+ dimensions

### Phase 2: Adversarial Review
- Reviewers **falsify** plans, not polish them
- Every issue needs trigger + mechanism + impact
- Blockers need repair path or kill recommendation

### Phase 3: Rebuttal (Deep mode / when needed)
- Planners can rebut criticism with **new evidence**
- Revise only affected steps
- Accept valid criticism

### Phase 4: Synthesis
- Arbiter merges **only what survived**
- Decision rules applied in order
- Strongest rejected alternative preserved in dissent log

### Phase 5: Red Team Stress Test (Deep mode)
- Attack across 10 dimensions:
  - Single point of failure
  - Invalid assumption
  - Timeline slip
  - Key person loss
  - Dependency failure
  - Edge case
  - Security/privacy
  - Migration/compatibility
  - Observability blind spot
  - Rare but real scenario

### Phase 6: Execution Decision
- Score each step (Impact 0.30, Feasibility 0.25, Risk 0.25, Urgency 0.20)
- Apply penalties:
  - Same-model fallback: -15
  - No local evidence: -15
  - Production without rollback: -20
- Verdict: **go** (≥75) / **conditional_go** (55-74) / **no_go** (<55)

### Phase 7: Change-Set Synthesis (Deep mode, go/conditional)
- Translate to reversible change sets
- Identify safe first change
- Verification sequence

## Evidence Standard

Every claim must be labeled:

| Class | Meaning | Can Support |
|-------|---------|-------------|
| **verified** | Directly confirmed (file, test, config, log) | Core steps, irreversible work |
| **inference** | Reasonable conclusion from verified facts | Reversible probes only |
| **assumption** | Not verified, stated explicitly | Must become verification task |
| **unknown** | Cannot be safely inferred | Must become blocker/gate |

## Non-Negotiable Rules

1. **Inspect before planning** - No solutioning before checking reality
2. **Isolate before synthesis** - Planners don't see each other's work
3. **Reuse before inventing** - Prefer existing patterns
4. **Read before write** - Discovery is autonomous; writes need approval
5. **Reversible before irreversible** - Reduce uncertainty first
6. **Unknowns remain visible** - Never hidden in prose
7. **Reviews must falsify** - Attack the plan, don't polish it
8. **Evidence must travel** - Claims need labels and sources
9. **Stop early when invalid** - Don't continue just to produce output
10. **Share structure, not chain-of-thought** - Only findings move between phases

## Programmatic Usage

```python
from code_puppy.plugins.adversarial_planning import (
    AdversarialPlanningOrchestrator,
    AdversarialPlanConfig,
    WorkspaceContext,
    render_session,
)

# Create config
config = AdversarialPlanConfig(
    mode="auto",  # or "standard" / "deep"
    context=WorkspaceContext(
        workspace="/path/to/project",
        branch_or_commit="main",
    ),
    task="Migrate database from PostgreSQL to MySQL",
    success_criteria=["Zero data loss", "< 1 hour downtime"],
    hard_constraints=["No schema changes to app layer"],
)

# Run planning
orchestrator = AdversarialPlanningOrchestrator(config)
session = await orchestrator.run()

# Render results
print(render_session(session, format="summary"))
# or: "full", "traceability", "json", "markdown"
```

## Output Formats

```python
from code_puppy.plugins.adversarial_planning import render_session

# Executive summary
render_session(session, format="summary")

# Full markdown report
render_session(session, format="full")

# Traceability matrix
render_session(session, format="traceability")

# JSON export
render_session(session, format="json")
```

## Testing

```bash
# Run all adversarial planning tests
pytest tests/test_adversarial_planning/ -v

# Run specific test file
pytest tests/test_adversarial_planning/test_orchestrator.py -v

# Run with coverage
pytest tests/test_adversarial_planning/ --cov=code_puppy.plugins.adversarial_planning
```

## Files

```
code_puppy/plugins/adversarial_planning/
├── __init__.py              # Public exports
├── register_callbacks.py    # Plugin registration
├── models.py                # Pydantic models (414 lines)
├── evidence.py              # Evidence tracking (416 lines)
├── orchestrator.py          # Phase orchestration (571 lines)
├── validators.py            # Exit gate validators (192 lines)
├── prompt_builders.py       # Phase prompts (423 lines)
├── commands.py              # Slash commands (168 lines)
├── tools.py                 # Tool registration (101 lines)
├── renderers.py             # Output rendering (453 lines)
├── agents/                  # Specialized agents
│   ├── __init__.py
│   ├── base_adversarial_agent.py
│   ├── ap_researcher.py
│   ├── ap_planner_a.py
│   ├── ap_planner_b.py
│   ├── ap_reviewer.py
│   ├── ap_arbiter.py
│   └── ap_red_team.py
└── prompts/                 # System prompts
    ├── shared_rules.py
    ├── researcher.py
    ├── planner_a.py
    ├── planner_b.py
    ├── reviewer.py
    ├── arbiter.py
    └── red_team.py
```

## Contributing

See main CONTRIBUTING.md. Key rules:
- All files under 600 lines
- Tests required for new features
- Evidence labeling in all agent outputs
- No circular imports (use lazy loading)
