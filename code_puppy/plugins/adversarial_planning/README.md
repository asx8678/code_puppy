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

> 📚 **New to adversarial planning?** Start with the [quick guide in the main README](../../../README.md#adversarial-planning-quick-guide-️) for a beginner-friendly overview and command cheat sheet—including an example model-to-role mapping you can use as a starting point.

```bash
# Start planning (auto-selects mode)
/ap Implement OAuth2 authentication with Google

# View progress
/ap-status

# Abort if needed
/ap-abort
```

## How It Works: The Flow Diagram

```
USER INPUT: /ap <task>
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ PHASE 0A: EVIDENCE DISCOVERY                                  │
│ ap-researcher                                                 │
│ • list_files, read_file, grep your codebase                   │
│ • Classify: VERIFIED / INFERENCE / ASSUMPTION / UNKNOWN       │
│ • Produce: Evidence pack with file:line references          │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│ PHASE 0B: SCOPE LOCK                                          │
│ • Normalize the problem (no solution bias yet)               │
│ • Preserve hard constraints                                    │
│ • Surface critical unknowns                                    │
└──────────────────────────────────────────────────────────────┘
       │
       ├──►┌─────────────────────┐     ┌─────────────────────┐
       │   │ ap-planner-a        │     │ ap-planner-b        │
       │   │ (Conservative)      │     │ (Contrarian)        │
       │   │                     │     │                     │
       │   │ • Proven patterns   │◄───►│ • Challenge defaults│
       │   │ • Min blast radius  │ ╳   │ • Seek alternatives │
       │   │ • Full reversibility│     │ • Materially diff.  │
       │   │                     │     │                     │
       │   └─────────────────────┘     └─────────────────────┘
       │              │                         │
       │              ▼                         ▼
       │   ┌─────────────────────┐     ┌─────────────────────┐
       │   │ ap-reviewer reviews │     │ ap-reviewer reviews │
       │   │ Plan A:             │     │ Plan B:             │
       │   │ • Verify evidence   │     │ • Verify evidence   │
       │   │ • Find fatal flaws  │     │ • Find fatal flaws  │
       │   │ • Identify missing  │     │ • Identify missing  │
       │   │   steps             │     │   steps             │
       │   │ • Check assumptions │     │ • Check assumptions │
       │   └─────────────────────┘     └─────────────────────┘
       │              │                         │
       │              └───────────┬───────────┘
       │                          ▼
       │             ┌─────────────────────────┐
       │             │   BOTH REVIEWS FEED     │
       │             │   INTO NEXT PHASE       │
       │             └─────────────────────────┘
       │                          │
       ▼                          ▼
┌──────────────────────────────────────────────────────────────┐
│ PHASE 4: SYNTHESIS (ap-arbiter)                               │
│                                                               │
│ Decision Rules (applied in order):                          │
│   1. Verified facts > Inference                              │
│   2. Include reviewer-added missing steps                    │
│   3. Simpler > Complex (when impact similar)                 │
│   4. More reversible > Less reversible                       │
│   5. Existing patterns > Bespoke                             │
│   6. Unresolved unknowns = Blockers                          │
│                                                               │
│ Output: Merged plan with:                                    │
│   • source_plan tracking (A/B/reviewer/merged)                │
│   • resolved_conflicts with reasoning                        │
│   • dissent_log (preserved rejected alternative)             │
└──────────────────────────────────────────────────────────────┘
       │
       ├──► Standard mode jumps to Phase 6 ─────────────────┐
       │                                                     │
       ▼                                                     │
┌──────────────────────────────────────────────────────────┐│
│ PHASE 5: RED TEAM (ap-red-team) — Deep mode only         ││
│                                                          ││
│ Attacks merged plan across 10 dimensions:                ││
│   1. Single point of failure                             ││
│   2. Invalid assumptions                                 ││
│   3. Timeline stress (150%, 200%)                      ││
│   4. Key person loss                                   ││
│   5. Dependency failure                                ││
│   6. Edge cases                                        ││
│   7. Security/privacy                                  ││
│   8. Migration/compatibility                           ││
│   9. Observability blind spots                         ││
│  10. Rare but real scenarios                           ││
│                                                          ││
│ Finds cascading failures, produces priority-ordered    ││
│ mitigations.                                             ││
└──────────────────────────────────────────────────────────┘│
       │                                                    │
       ▼                                                    │
┌──────────────────────────────────────────────────────────┐│
│ PHASE 6: EXECUTION DECISION (ap-arbiter)                 ││
│                                                          ││
│ Scoring:                                                 ││
│   Score = (Impact × 0.30) + (Feasibility × 0.25)       ││
│           + (Risk × 0.25) + (Urgency × 0.20)           ││
│                                                          ││
│ Penalties:                                               ││
│   - Same-model fallback: -15                             ││
│   - No local evidence: -15                               ││
│   - Production w/o rollback: -20                       ││
│                                                          ││
│ Verdict:                                                 ││
│   • go (≥75)          → Execute                          ││
│   • conditional_go (55-74) → Execute w/ conditions     ││
│   • no_go (<55)       → Do not execute                 ││
│                                                          ││
│ Output: Verdict + adjusted score + execution order     ││
└──────────────────────────────────────────────────────────┘│
       │                                                    │
       ▼                                                    │
┌──────────────────────────────────────────────────────────┐│
│ PHASE 7: CHANGE-SET SYNTHESIS — Deep mode, go only       ││
│                                                          ││
│ Translate plan to reversible change sets with:           ││
│   • Safe first change                                    ││
│   • Verification sequence                                ││
│   • Rollback plan per step                               ││
└──────────────────────────────────────────────────────────┘│
       │                                                    │
       └──────────────────────┬─────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                        OUTPUT TO USER                          │
│ • Final verdict (go / conditional_go / no_go)                │
│ • Adjusted score with penalties                                │
│ • Execution order (if go/conditional_go)                     │
│ • Quick wins                                                   │
│ • Monday morning actions                                       │
│ • Blockers or conditions                                       │
└──────────────────────────────────────────────────────────────┘
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

## Per-Agent Deep Dive

### ap-researcher (Phase 0A) — The Fact-Finder

**Plain-English explanation:**
Think of the researcher as a detective who investigates your codebase before anyone starts planning. It reads your files, checks your configs, and separates what we actually know from what we're just guessing. This prevents the classic "I think this will work" mistake that sinks projects.

**Process:**
1. **Explore** — Lists your directory structure to understand the layout
2. **Read configs** — Checks pyproject.toml, package.json, etc. to understand your tech stack
3. **Read entry points** — Finds main.py, app.py, index.js to understand how things work
4. **Search for patterns** — Uses grep to find existing implementations of similar features
5. **Classify everything** — Labels each finding as verified, inferred, assumed, or unknown

**Concrete example:**
You want to add OAuth2 login to your app. Before anyone starts coding, the researcher discovers:
- **Verified**: You're using FastAPI with SQLAlchemy (from pyproject.toml)
- **Inference**: Auth is currently session-based (from reading auth middleware)
- **Unknown**: Whether users have Google accounts in the database
- **Critical**: You don't have OAuth credentials set up yet — this blocks planning

**Why it matters:**
The researcher catches expensive surprises early. Finding out you're missing OAuth credentials AFTER you've planned the migration is a costly mistake. Finding it before planning means you can add "set up Google OAuth app" as a prerequisite step.

**Output:**
```json
{
  "readiness": "ready | limited | blocked",
  "evidence": [
    {
      "id": "EV1",
      "class": "verified",
      "claim": "App uses FastAPI with SQLAlchemy",
      "source": {"kind": "file", "locator": "pyproject.toml:12-18"}
    }
  ],
  "critical_unknowns": [
    {
      "id": "UNK1",
      "question": "Do we have OAuth credentials configured?",
      "why_it_matters": "Can't implement OAuth without credentials"
    }
  ]
}
```

---

### ap-planner-a (Phase 1) — The Safe Planner

**Plain-English explanation:**
This is your "what would a cautious senior engineer recommend?" planner. It chooses the path of least resistance — proven patterns, small changes, and the ability to undo anything if it goes wrong. When in doubt, it picks the boring option that has worked before.

**Core principles:**
1. **Minimize blast radius** — Touch fewer files rather than more. A 5-line change beats a 500-line change.
2. **Maximize reversibility** — Every step should be undoable in under 30 minutes. Feature flags are your friend.
3. **Reuse existing patterns** — If your codebase already has a way of doing something, use that. Don't invent new solutions.
4. **Include early de-risking** — Test the risky parts before committing to the full implementation.
5. **Sequence for safety** — Do safe things first. Validation happens before rollout.

**Concrete example:**
You want to migrate from REST to GraphQL. Planner A suggests:
- Add GraphQL endpoint alongside existing REST (don't remove REST yet)
- Migrate one endpoint at a time
- Use feature flag to switch traffic gradually
- Rollback: flip flag back to REST (30 seconds)

Each step cites the researcher's evidence (e.g., "we already use feature flags [EV3]").

**Output:** Plan A with detailed steps, risks, mitigations, rollback plan, 80th percentile effort estimate.

**Isolation rule:** Never sees Plan B. Cannot be influenced by alternative approaches.

---

### ap-planner-b (Phase 1) — The Alternative Planner

**Plain-English explanation:**
This planner is the devil's advocate. While Planner A says "use what works," Planner B asks "is there a fundamentally better way?" It's willing to take more risk if the payoff is significantly better. The key constraint: it MUST produce a materially different plan, not just the same plan with different words.

**Core principles:**
1. **Challenge the obvious** — Question "how it's always done." Newer frameworks or different architectures might be worth it.
2. **Seek better outcome/risk ratio** — 2× risk for 10× benefit? Worth considering. 2× risk for 1.2× benefit? Not worth it.
3. **Consider dismissed alternatives** — What would a startup do? What are newer teams doing that you're not?
4. **Question constraints** — "Must use Python" — really, or just preferred? "Can't change the database" — technical limit or political?
5. **Optimize for long-term** — Short-term pain for a solution that lasts 5 years instead of needing another rewrite in 2.

**Material difference requirement:** Must differ from conservative approach in ≥2 dimensions (tech, sequencing, rollout, risk posture, etc.)

**Concrete example:**
Same GraphQL migration. Planner B suggests:
- Skip the gradual migration — replace REST entirely with a complete rewrite
- Use Apollo Federation to split the API into microservices
- Accept 2 weeks of higher risk for a cleaner long-term architecture
- Rollback requires database restore (harder but cleaner result)

Planner B is NOT just saying "do the same thing but slower." It fundamentally rethinks the approach.

**Output:** Plan B that genuinely explores alternatives.

**Isolation rule:** Never sees Plan A. Cannot anchor on first solution.

---

### ap-reviewer (Phase 2) — The Plan Attacker

**Plain-English explanation:**
The reviewer is a prosecutor whose job is to prove the plan wrong. It doesn't give polite feedback — it attacks every claim, looking for missing steps, wrong assumptions, and unrealistic estimates. If there's a hole in the plan, the reviewer finds it.

**Attack protocol:**
For every claim, verify:
- **Is it supported by evidence?** — Does that file actually exist at that path?
- **Is the problem correctly understood?** — Are we solving the right problem or a symptom?
- **Are assumptions actually true?** — Search the codebase to verify assumed patterns exist.
- **What steps are missing?** — Forgotten monitoring? No rollback plan? Missing tests?
- **Is effort realistic?** — Planners almost always underestimate by 1.5-2×.

**For every issue:**
- **Trigger** → What causes it?
- **Mechanism** → How exactly does it fail?
- **Impact** → Why does this matter?
- **Repair path** → How to fix, OR
- **Kill recommendation** → If unfixable

**Concrete example:**
The planner said "Step 3: migrate database." The reviewer responds:
- ❌ The migration plan doesn't have a rollback script
- ❌ The evidence cited (EV4) doesn't actually show the current schema
- ❌ "Effort: 4 hours" is unrealistic — schema changes need testing, validation time
- ✅ Strongest surviving element: using feature flags for gradual rollout

**Output:** Step verdicts (accept/modify/reject), blockers with severity, fatal flaws, missing steps, effort reassessment.

**Philosophy:** "Your job is to FALSIFY the plan, not polish its narrative."

---

### ap-arbiter (Phases 4, 6, 7) — The Judge

**Plain-English explanation:**
The arbiter is the judge who decides what survives. It doesn't create a compromise — it keeps only the parts of the plans that survived review and discards the rest. Then it decides: should we execute this plan, execute with conditions, or stop entirely?

**Phase 4 — Synthesis:**
Merges ONLY what survived adversarial review. Applies decision rules in order:
1. **Verified facts > Inference** — What we know beats what we guess
2. **Include reviewer-added missing steps** — The reviewer found gaps; fill them
3. **Simpler > Complex** — When outcomes are similar, pick the simpler path
4. **More reversible > Less reversible** — Easy rollback is valuable
5. **Existing patterns > Bespoke** — Match what's already in the codebase
6. **Unresolved unknowns = Blockers** — Don't proceed blindly

**Concrete example:**
After review, the arbiter merges:
- Planner A's gradual migration approach (safe)
- Planner B's use of Apollo Federation (better architecture)
- Reviewer's added monitoring steps (were missing)
- Rejected: Planner B's "skip rollback plan" (too risky)

Conflict documented: "Chose gradual migration (A) over big-bang (B) because Rule 4 — reversible is safer."

**Conflict resolution:** Documents every choice:
```
"Chose A's approach for auth because Rule 1 (verified evidence from EV3).
Rejected B's OIDC because no verified identity provider configured."
```

**Dissent log:** Preserves strongest rejected alternative for future reference.

**Phase 6 — Decision:**
Scores merged plan and renders verdict:
```
Score = (Impact × 0.30) + (Feasibility × 0.25)
        + (Risk × 0.25) + (Urgency × 0.20)
        - penalties

Penalties:
  - Same-model fallback: -15
  - No local evidence: -15
  - Production w/o rollback: -20

Verdict: go (≥75) / conditional_go (55-74) / no_go (<55)
```

**Concrete example:**
The merged GraphQL plan scores 82:
- Impact 85 × 0.30 = 25.5
- Feasibility 80 × 0.25 = 20
- Risk 70 × 0.25 = 17.5 (lower risk = better)
- Urgency 75 × 0.20 = 15
- Total: 78
- Penalty: -0 (we have local evidence and rollback plan)
- Final: 78 → **go**

**Phase 7 — Change-Set Synthesis:**
Translates plan to reversible change sets with safe first change and verification sequence.

---

### ap-red-team (Phase 5) — The Disaster Simulator

**Plain-English explanation:**
The red team runs a disaster simulation on your plan. It systematically asks "what if everything goes wrong?" — server outages, security breaches, key people leaving, edge cases, even unlikely events that could still happen. It finds the failure modes before production does.

**Attack vectors:**

| # | Dimension | Question Asked |
|---|-----------|----------------|
| 1 | Single point of failure | What one thing kills the entire plan? |
| 2 | Invalid assumption | What if key assumptions are wrong? |
| 3 | Timeline slip | What happens at 150%? 200% timeline? |
| 4 | Key person loss | What if someone critical leaves? |
| 5 | Dependency failure | What if an external service fails? |
| 6 | Edge case | What inputs weren't considered? |
| 7 | Security/privacy | What could be exploited? |
| 8 | Migration/compatibility | What breaks during upgrades? |
| 9 | Observability blind spot | What failures go undetected? |
| 10 | Rare but real | What unlikely event hurts if it happens? |

**Concrete example:**
The GraphQL migration plan is stress-tested:
- **SPOF:** The auth service is a single point of failure (if it dies, everything fails)
- **Invalid assumption:** Assumes all clients can handle GraphQL — what if legacy mobile apps can't?
- **Timeline slip:** At 200% timeline, the team loses focus and technical debt piles up
- **Security:** The new GraphQL endpoint might expose internal fields — need review

**Cascading failure analysis:**
Traces chains: "If X fails, then Y fails because Z"

**Output:** Attack scenarios, resilience assessment, priority-ordered recommendations, fatal flaw flag.

**Clean bill of health:** Only `true` if no fatal flaws found after all 10 vectors probed.

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
