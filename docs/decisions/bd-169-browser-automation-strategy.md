# bd-169 — Browser automation strategy

- **Status**: Proposed
- **Date**: 2026-04-19
- **Owner**: migration-analyst-019da5
- **Related**: bd-132, bd-138, bd-169
- **Phase**: Phase 5 — API/Browser layer

## Executive summary

**Recommendation: choose Option 4 — drop browser tools entirely for Elixir v1, with explicit R6-style risk acceptance.**

The current Python browser layer is heavily shaped around Playwright and is larger than it first appears: `code_puppy/tools/browser/` contains 13 implementation files spanning web automation, screenshot/visual analysis, workflow persistence, and a separate browser-based terminal QA path. The current surface is primarily consumed by `qa-kitten` and `terminal-qa`, not by the core agent/runtime path. Wallaby does not provide close enough parity to justify a v1 rewrite, and ChromicPDF solves a much narrower problem than the one the current code addresses. If product stakeholders later decide browser automation is launch-critical, the fastest credible fallback is **Option 3 — keep a tiny Python Playwright service alive behind an Elixir-facing interface**. For v1, however, the cleanest and lowest-risk decision is to **not ship browser automation at all**.

## Current state

### What Python uses browser automation today

1. **`qa-kitten` is the primary browser-automation consumer** (`code_puppy/agents/agent_qa_kitten.py:33-78`) — exposes a large `browser_*` surface covering lifecycle, navigation, locators (role/text/label/placeholder/test-id/xpath), interactions, scripts, visual analysis, and workflow persistence. Positioned as a Playwright-powered browser automation/QA agent.
2. **Browser tool surface registered centrally** at `code_puppy/tools/__init__.py:139-183`.
3. **Per-agent browser sessions wired into agent invocation** (`code_puppy/tools/agent_tools.py:688-692, 961-964`) — session token `browser-<session_id>` set before sub-agent invoke, reset in finally. Browser layer is integrated into the runtime, not just a loose utility.
4. **Main browser manager is Playwright-native** (`code_puppy/tools/browser/browser_manager.py`) — async Playwright API, session-scoped managers, persistent browser profile dirs, plugin hook for custom browser types, global cleanup on exit.
5. **Separate terminal-browser subsystem also depends on Playwright** (`code_puppy/tools/browser/chromium_terminal_manager.py`) — used by `terminal-qa` and `terminal_*` tools, distinct from `qa-kitten`'s web-browser tools.
6. **Playwright is an explicit Python dependency** (`pyproject.toml:32` — `playwright>=1.58.0`).
7. **Substantial test investment** — `tests/tools/browser/` has 26 test files covering browser manager, control, locators, interactions, scripts, screenshots, workflows, terminal browser tools, and registry coverage.

### Browser/Playwright inventory by area

#### A. Agent usage

- **`qa-kitten`** (`code_puppy/agents/agent_qa_kitten.py`) — main consumer of `browser_*` tools.
- **`terminal-qa`** (`code_puppy/agents/agent_terminal_qa.py:35-61`) — explicitly does NOT use `browser_*` tools, uses `terminal_*` tools instead because terminal/TUI testing is keyboard-driven through a different browser manager. Still browser-backed, just a different tool family.
- **`qa-expert`** — mentions Playwright in prompt text as general QA knowledge, does not depend on runtime browser tooling.

#### B. Browser implementation scope

`code_puppy/tools/browser/` currently contains:

- `browser_manager.py` — session-aware Playwright browser manager
- `browser_control.py` — init / close / status / tabs
- `browser_navigation.py` — navigate / back / forward / reload / wait
- `browser_locators.py` — semantic and fallback element queries
- `browser_interactions.py` — clicking / typing / form interactions
- `browser_screenshot.py` — screenshots for visual analysis
- `browser_scripts.py` — execute JS / scroll / viewport / highlight
- `browser_workflows.py` — save/list/read browser workflows
- `chromium_terminal_manager.py` — terminal-specific browser manager
- `terminal_tools.py` — open / close terminal browser, server checks
- `terminal_command_tools.py` — send keys / run commands / wait for output
- `terminal_screenshot_tools.py` — terminal screenshots / image loading / comparisons
- `__init__.py`

This is not a single helper file — it is a **subsystem**.

#### C. Lifecycle / state model

Behavior that would all need design decisions in Elixir:

- session-scoped managers via context variables
- persistent browser profiles for web automation
- ephemeral contexts for terminal browser automation
- atexit/global cleanup
- plugin-driven custom browser type registration
- workflow persistence to disk for browser task reuse

#### D. Tests and expectations

Tests imply intended behavior includes lazy initialization, multi-page/tab support, locator strictness and fallback handling, screenshot capture for model-visible analysis, browser state cleanup and persistence, separate terminal automation behavior, and tool registration coverage. A replacement is not just "open a page and click a button" — the behavior envelope is much broader.

### Existing migration guidance is inconsistent

There is already a strategy conflict in the repo:

- **`MIGRATION_MAP.md:340-356, 576`** — marks `tools/browser/*` as **DROP-V1**, rationale: "Playwright, not v1"
- **`docs/THIN_SHELL_CONTRACT.md:166`** — describes `tools/browser/` as **"Likely Retain — Playwright is Python-native"**

bd-169 should resolve that contradiction.

## Option comparison

| Option | Feature coverage | Maintenance burden | Elixir-nativeness | Time-to-v1 | Agent/tool impact |
|---|---|---:|---:|---:|---|
| **1. Wallaby** | **Partial**. Covers basic browser interaction but not a close match for the current Playwright-shaped surface: rich semantic locators, current screenshot/visual-analysis workflow, and the existing terminal-browser split would all need redesign. | **Medium-High**. New Elixir/browser stack plus redesign work. | **High** | **Slow** | High impact. `qa-kitten` tool semantics would change; terminal tools likely need a separate decision anyway. |
| **2. ChromicPDF** | **Low**. Useful for rendering/print/PDF-style use cases, but does not replace interactive browsing, locators, clicking, typing, waiting, workflow persistence, or terminal-browser testing. | **Low-Medium** | **High** | **Fast** only if scope is radically reduced | Extreme impact. Does not actually replace current browser automation. |
| **3. Tiny Python Port** | **High**. Best match to the current surface because Playwright stays alive. Existing behavior and tests are more portable operationally than semantically. | **Medium**. Hybrid runtime, service boundary, deployment and security overhead. | **Low** | **Fastest if browser automation is mandatory** | Lowest product impact. `qa-kitten` and browser tools can keep roughly the same contract. |
| **4. Drop browser tools entirely (R6 risk accept)** | **None in v1** | **Lowest** | **Highest** | **Fastest overall** | Highest feature loss. `qa-kitten` becomes unavailable in v1; `terminal-qa` likely also affected unless explicitly carved out. |

## Risks by option

### Option 1 — Wallaby

- **Parity risk**: current Python tools are Playwright-shaped, not generic browser-automation-shaped.
- **Redesign risk**: semantic locators, screenshots-for-analysis, and workflow persistence would all need a new contract.
- **Terminal split risk**: the current terminal browser path is already distinct; Wallaby does not automatically solve that.
- **Schedule risk**: this is the most "rewrite-y" path for a non-core feature set.

### Option 2 — ChromicPDF

- **Wrong-problem risk**: it solves rendering/PDF capture, not browser interaction.
- **False-comfort risk**: it may create the appearance of "browser support" while dropping the capabilities that matter.
- **Agent mismatch risk**: `qa-kitten` would lose its defining value proposition.

### Option 3 — Tiny Python Port

- **Hybrid-runtime risk**: introduces a permanent Python operational footprint into an Elixir migration.
- **Boundary/security risk**: needs a clear protocol, sandboxing assumptions, timeouts, and lifecycle management.
- **Ownership risk**: can become "temporary forever."
- **But**: if browser automation is a hard requirement, this is still the most realistic option.

### Option 4 — Drop browser tools entirely (R6 risk accept)

- **Capability loss risk**: no `qa-kitten` browser automation in v1.
- **Testing workflow risk**: users lose automated browser QA and browser-based terminal tooling unless explicitly retained elsewhere.
- **Expectation-management risk**: docs, demos, prompts, and migration trackers must say this clearly.
- **Governance risk**: the repo currently does NOT appear to have an explicit R6 record; if we choose this path, the risk acceptance must be documented rather than implied.

## Recommendation

**Choose Option 4 for v1: drop browser automation entirely, and document that decision explicitly.**

### Why this is the right v1 call

1. **The current browser layer is sizable and specialized** — 13 implementation files, broad feature surface, a separate terminal-browser branch, large dedicated test suite.
2. **The current design is deeply tied to Playwright** — current tool contracts, prompts, and behaviors assume Playwright-style semantics; a direct Elixir-native replacement would not be small.
3. **Wallaby is not a clean semantic replacement** — it may be a usable Elixir browser library, but it is not a low-friction translation target for the existing `qa-kitten`/browser tool surface.
4. **ChromicPDF does not solve the problem being asked** — it is a narrow rendering/document tool, not interactive browser automation.
5. **If browser support becomes mandatory, the thin Python service is the best fallback** — it preserves the current behavior model and avoids a forced redesign under deadline pressure.
6. **The migration plan already trends toward DROP-V1** — bd-169 should formalize and justify that position, not leave it as an undocumented assumption.

### Decision statement

For **Elixir v1**, browser automation is **out of scope**.

That includes, unless explicitly carved out by PM/EM:

- `qa-kitten` browser automation
- `browser_*` tools
- browser workflow persistence
- browser profile management
- plugin-registered custom browser types
- browser-based terminal tooling that still depends on Playwright

If stakeholders later decide browser automation is required before launch, the next decision should not be "build Wallaby parity." It should be **"stand up a tiny Python Playwright service with a narrow Elixir-facing contract."**

## Migration path

If this recommendation is adopted:

### 1. Get explicit product sign-off

- Confirm that browser automation is **not** a v1 requirement.
- Record this as the R6-style risk acceptance referenced by the issue.
- Make the acceptance explicit in migration tracking docs, not just implied by file tags.

### 2. Resolve the documentation conflict

Update migration planning docs so they all say the same thing:

- `MIGRATION_MAP.md` already says **DROP-V1**
- `docs/THIN_SHELL_CONTRACT.md` currently suggests **Likely Retain**

These need to converge on one answer.

### 3. Mark the unsupported surface clearly

Document that Elixir v1 does NOT include:

- `qa-kitten` browser automation
- `browser_*` runtime tools
- browser workflow persistence
- Playwright-backed browser profile behavior
- custom browser-type plugin hooks
- browser-backed terminal QA, if that is included in the same scope decision

### 4. Split terminal-browser tooling if necessary

Make an explicit call on whether `terminal_*` tooling belongs in the same drop decision. The current codebase treats it as distinct from `browser_*`, but both rely on Playwright. If PM wants browser-based terminal QA in v1, that should be tracked as a separate exception or follow-up issue, not hidden inside the web browser decision.

### 5. Define the contingency path now, but do not build it

If a late-stage requirement emerges, the fallback should be:

- a tiny Python Playwright service
- narrow contract
- one deployment boundary
- explicit timeout and lifecycle rules
- no attempt to re-create the entire current Python subsystem inside Elixir under schedule pressure

### 6. Revisit after v1 with real usage data

- If low demand: keep it dropped
- If moderate/high demand: implement the thin Python service
- Only consider a fully Elixir-native redesign after there is evidence that the capability is strategically important enough to justify the semantic rewrite

## Open questions needing PM / human sign-off

1. Does bd-169 cover both `browser_*` and `terminal_*` tooling, or only `qa-kitten`-style web automation?
2. Is `qa-kitten` required for any internal demos, operator workflows, or launch criteria?
3. Should terminal-browser QA be treated as a separate decision because it supports TUI/CLI validation rather than web-page automation?
4. Is there a sanctioned escape hatch for operators, such as the existing Playwright MCP server path, even if Elixir v1 does not ship browser tools directly?
5. Do we want to preserve the browser-type plugin extension point in the long-term architecture, or remove it entirely from the v1 design?
6. Where will the explicit R6 risk acceptance be recorded, since the repo currently does not appear to contain a formal R6 entry?
7. If product leadership rejects Option 4, do we agree now that Option 3 is the fallback, rather than re-opening the question around Wallaby?

## Final decision

**Option 4 for v1: Drop browser automation for Elixir v1**

**Risk R6 accepted:** Users requiring browser automation must stay on Python version or use external tooling.

**Option 3 only if product says browser automation is mandatory before release.**

**Revisit:** Post-v1 browser automation revisit tracked in **bd-209**.
