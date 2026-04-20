# bd-230 Planning Agent Decision — 2026-04-20

## Python source of truth
**File:** `code_puppy/agents/agent_planning.py`
**Size:** 7019 bytes, 171 lines
**Class:** `PlanningAgent(BaseAgent)` — name `"planning-agent"`
**Tools:** 7 — `list_files`, `read_file`, `grep`, `ask_user_question`, `list_agents`, `invoke_agent`, `list_or_search_skills`
**System prompt:** ~140 lines (incl. 5-step planning process, output format template, agent delegation mapping)

## Usage in Python codebase
**User-facing:** YES — first-class agent via `/plan` and `/planning` shortcuts
- `code_puppy/plugins/agent_shortcuts/register_callbacks.py` — `/plan` → `planning-agent`
- `code_puppy/command_line/colors_menu.py:62` — listed in agent menu
- `code_puppy/command_line/onboarding_slides.py:152` — shown in onboarding
- `code_puppy/agents/agent_scheduler.py:90` — listed in scheduler agent catalogue

**Internal invocations:** 0 — no `invoke_agent("planning-agent")` calls found. Purely user-invoked.

## Elixir current state
**Catalogue entry:** NO — no `planning.ex` exists
**Any scaffolding:** NO — grep of `elixir/code_puppy_control/` returns zero agent-related hits for "planning"
**Existing Elixir agents (8):** code_puppy, code_reviewer, code_scout, pack_leader, python_programmer, qa_expert, qa_kitten, security_auditor

## Recommendation: DEFER (post-v1)

**Rationale:** The planning agent IS a real user-facing agent — it's wired into shortcuts, onboarding, and the agent menu. It's not dead code. However:

1. **No internal dependencies** — nothing programmatically invokes it; only users do via `/plan`
2. **Medium complexity** — 7 tools, large prompt with delegation logic; would be ~200-300 lines of Elixir
3. **Functional overlap** — `code-puppy` and `pack-leader` already handle planning implicitly
4. **User workaround** — users can switch to the Python agent runtime for `/plan` during v1

If PORT: ~1 day effort → `elixir/.../agents/planning.ex` (200-300 lines, similar to code_scout.ex at 316 lines)
If DEFER: close bd-230 as "deferred-post-v1", file bd-xxx for v1.1 port, update MIGRATION_MAP.md

**Action items for DEFER:**
- Close bd-230 with label `deferred-post-v1`
- File new issue bd-xxx: "Port planning-agent to Elixir (v1.1)"
- Add note to MIGRATION_MAP.md: `planning-agent` excluded from v1 Elixir runtime, Python fallback available
- Keep `agent_shortcuts` `/plan` working via Python agent manager fallback
