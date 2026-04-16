# AP Contract Ownership

## Canonical Owner: Runtime Models + Orchestrator Parse Boundary

The **enforced acceptance boundary** is `model_validate()` in 
`AdversarialPlanningOrchestrator._parse_phase_output()` (orchestrator.py:471-488).

All prompt text, agent OUTPUT_SCHEMA strings, and documentation **MUST conform** 
to the Pydantic models defined in `models.py`.

### Why This Matters
- Role prompts and OUTPUT_SCHEMA already disagreed before this decision
- Only `model_validate()` actually enforces acceptance at runtime
- Prompts can guide LLM output, but models are the final arbiter

## Phase Contracts

### Phase 2 (Review)
| Field | Model | Type/Values |
|-------|-------|-------------|
| `overall.ship_readiness` | Phase2Output | `not_ready` / `needs_work` / `ready_with_caveats` / `ready` |
| `overall.wrong_problem` | Phase2Output | `str \| None` (NOT boolean) |

### Phase 4 (Synthesis)  
| Field | Model | Type/Values |
|-------|-------|-------------|
| `merged_steps[].id` | PlanStep | Pattern: `^[ABM]\d+` (A=PlanA, B=PlanB, M=Merged) |
| `merged_steps[].source_plan` | PlanStep | Optional: `A` / `B` / `merged` |
| `merged_steps[].survival_reason` | PlanStep | Optional: `str` |

### Phase 6 (Decision)
| Field | Model | Type/Values |
|-------|-------|-------------|
| `plan_verdict` | Phase6Output | `go` / `conditional_go` / `no_go` |
| `step_evaluations[].verdict` | StepEvaluation | `do` / `conditional` / `defer` / `skip` |

## Alignment Checklist

When modifying AP contracts:
1. ✅ Update `models.py` FIRST (source of truth)
2. ✅ Update agent OUTPUT_SCHEMA to match models
3. ✅ Update role prompts to match OUTPUT_SCHEMA  
4. ✅ Update test fixtures to use valid values
5. ✅ Update README to document actual behavior

## Extension Points

- Custom penalties: Extend `_apply_penalties()` in `orchestrator.py`
- Custom evidence sources: Extend `EvidenceSource.kind` enum
- Custom step categories: Extend `PlanStep.category` literal
