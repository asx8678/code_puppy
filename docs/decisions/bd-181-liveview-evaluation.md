# bd-181 — Phoenix LiveView evaluation for optional web UI

- **Status**: Proposed
- **Date**: 2026-04-19
- **Owner**: planning-agent-019da7
- **Related**: bd-132, bd-138, bd-168, bd-169
- **Phase**: Phase 5 — API/Browser layer

## Executive summary

**Recommendation: B (defer LiveView to Phase 6+).**

Code Puppy's user base is TUI-first (Textual). There is zero evidence of user demand for a browser-based UI. The headless FastAPI server was explicitly minimal — no web UI was ever shipped there. LiveView is the lowest-cost frontend option the stack will ever have (Phoenix is already in place after bd-168), but Phase 5 is already carrying the full Phoenix server migration plus the browser-automation strategy decision. Adding LiveView scope now risks bd-168 delivery. Defer costs nothing, preserves the option, and lets the decision be revisited with real user signal.

## Current state

### What exists today
- Python app is TUI-only (Textual).
- Headless FastAPI server serves REST + WebSocket for remote control — no browser UI.
- Elixir side: Phoenix endpoint exists with 3 controllers (`run`, `mcp`, `health`) + 3 channels (`run`, `session`, `user_socket`). **No LiveView deps in mix.exs.**
- No user-facing web UI exists anywhere in the project.

### What bd-168 will add
- Phoenix routes replacing FastAPI endpoints (native Router + Plug, not a port).
- PTY / Channels for streaming.
- Once Phoenix is in place, `phoenix_live_view ~> 0.20` is a ~5-line mix.exs change away. The structural enabler is bd-168 itself.

### The LiveView proposition
LiveView offers server-rendered, real-time HTML over WebSocket — no separate JavaScript SPA, no API contract to maintain, no build toolchain beyond esbuild/tailwind. For Code Puppy, the imagined UIs would be:

1. **Health dashboard**: System status, agent session counts, scheduler state — read-only, auto-updating.
2. **Run monitor**: Active runs with live streaming output, similar to what the TUI shows but in a browser.
3. **Session browser**: List/reconnect to running sessions, view history.

These are useful but not essential for v1. They are monitoring/convenience features, not core functionality.

## Options evaluated

### Option A — Ship minimal LiveView in Phase 5

**Scope**: A minimal dashboard LiveView showing health status, active runs, and live log streaming. Auth via same mechanism as REST (token or session). Layout + asset pipeline (esbuild/tailwind) wired into the Phoenix endpoint.

Concrete deliverables:
- `mix.exs`: add `:phoenix_live_view`, `:phoenix_live_reload` (dev), `:esbuild`, `:tailwind`
- `router.ex`: `live "/", DashboardLive` + `live "/runs/:id", RunLive`
- `layout.ex`: root layout with sidebar nav, tailwind classes
- `dashboard_live.ex`: health metrics, session count, scheduler state (LiveView reads from ETS/PubSub)
- `run_live.ex`: live-streaming output view (subscribes to same PubSub topic as the Channel)
- `auth`: token-based session or shared secret for dev; proper auth for production (scope TBD)
- Asset pipeline: `assets/` directory with `app.js`, `app.css`, tailwind config, esbuild config

**Complexity**: ~1–2 weeks of focused work on top of bd-168. The Phoenix endpoint must be extended with LiveView router, a layout module, and at least 2–3 LiveView modules. Asset compilation (esbuild + tailwind) must be wired into the release pipeline. Auth model needs design (even if minimal). This is not "free" — it's a meaningful scope addition to a phase that is already the largest single migration in the project.

**Pros**:
- Ships a tangible, interactive web UI alongside v1 — useful for demos and remote monitoring.
- LiveView over Channels means no separate SPA framework — the Elixir team owns the full stack.
- Once the layout + asset pipeline is wired, adding new LiveViews is cheap.

**Cons**:
- Expands Phase 5 scope when bd-168 is already a large migration (full Phoenix server replacing FastAPI + PTY + security middleware).
- No user demand signal — we'd be building on speculation.
- Asset pipeline (esbuild, tailwind) adds build-time complexity and release size. The Elixir release would grow by ~2–5 MB for compiled JS/CSS assets, and the Docker image would need a Node.js build step or pre-compiled assets.
- Auth model must be designed now rather than deferred with everything else. Even a minimal token-based approach requires decisions about session lifetime, CSRF protection for LiveView sockets, and whether WebSocket reconnection carries state.
- Maintenance: LiveView deps, JS hooks, and CSS are ongoing cost even if nobody uses the UI. Every Phoenix upgrade must also verify LiveView compatibility.
- Testing burden: LiveView tests require a different harness (`Phoenix.LiveViewTest`) than controller/channel tests. The team would need to learn and maintain two test patterns.
- Opportunity cost: 1–2 weeks on LiveView is 1–2 weeks not spent on bd-168 delivery, bug fixes, or Phase 6 planning.

### Option B — Defer to Phase 6+

**What "defer" means concretely**: Ship bd-168 with REST controllers + Channels only. File a follow-up bd issue for Phase 6+: "Revisit LiveView after v1 ships." Record explicit revisit criteria (see Follow-up actions). No LiveView deps added to mix.exs in Phase 5. No asset pipeline. No auth model for browser sessions.

The Phoenix app shipped in bd-168 should follow standard conventions (endpoint, router, controllers, channels) so that LiveView integrates trivially later. No special structural work is needed — just don't do anything weird.

**Pros**:
- Zero cost to Phase 5. bd-168 ships faster.
- LiveView can be added post-v1 with zero migration cost — Phoenix is already there, just add the dep and wire the router.
- Decisions about auth, layout, and asset pipeline are made later with more context (e.g., if v1 users actually ask for a web dashboard).
- Avoids speculative UI work when the TUI is the primary interface.

**Cons**:
- If a user asks for a web UI before Phase 6, the answer is "not yet" — but this is the same answer today, so nothing changes.
- Small risk that deferred decisions about Phoenix app structure (e.g., router layout, endpoint config) might need adjustment later. In practice, LiveView integrates cleanly into any existing Phoenix app — this risk is negligible.
- Follow-up issue must be filed and tracked. If it falls off the backlog, the option effectively dies without a decision.

### Option C — Drop (REST-only web UI if ever needed)

**Rationale**: TUI is the primary interface. REST + Channels are sufficient for external clients (IDEs, CI, scripting). No web UI roadmap exists. If a browser UI is ever needed, a lightweight SPA or even a static HTML page with JS over the existing Channels would suffice without LiveView.

**Pros**:
- Eliminates LiveView from the roadmap entirely. No dep weight, no asset pipeline, no JS build step.
- Simplest possible stack: TUI + REST + Channels. Done.

**Cons**:
- Too aggressive. LiveView is genuinely the cheapest web UI the stack will ever have — Phoenix is already there. Dropping it forecloses the lowest-effort path to a browser UI.
- If user demand for a web dashboard materializes (and it likely will for team/enterprise use), we'd be choosing between a from-scratch SPA (much more work) and backtracking on this decision (awkward).
- The "drop" framing makes it harder to reconsider than "defer." A deferred option is still open; a dropped one needs to be re-proposed.

## Comparison table

| Dimension | A: Ship LiveView | B: Defer | C: Drop |
|---|---|---|---|
| Phase 5 effort | ~1–2 weeks | 0 | 0 |
| Ongoing maintenance | Medium (deps, assets, JS hooks) | None | None |
| External user demand | None today — speculative | None today — honest | None today — consistent |
| Dep weight | phoenix_live_view + phoenix_live_reload + esbuild + tailwind (~5 deps) | None | None |
| Risk if we skip it | Low — can add later | None — planned | User might request it |
| Blocks bd-168? | Yes — needs coordinated scope | No | No |
| Reversibility | N/A (already shipped) | Trivial — add dep + router | Moderate — re-open decision |
| Future web-UI cost | Baseline (already done) | Low (add dep + LiveViews) | High (SPA or backtrack) |
| Phase 5 risk | Scope expansion on bd-168 | None | None |
| Test complexity | LiveViewTest + ChannelTest | ChannelTest only | ChannelTest only |

## Recommendation: B

Defer LiveView to Phase 6+. The evidence is clear:

1. **TUI-primary user base**: Every current Code Puppy user interacts through the Textual TUI. The headless FastAPI server was designed for programmatic access (IDE integrations, CI, scripting), not browser sessions. There is no user demand signal for a web UI — no feature requests, no GitHub issues, no Slack threads.

2. **Phase 5 is already big**: bd-168 (Phoenix server migration) is the largest single migration in the rewrite project. It replaces the entire FastAPI layer with native Phoenix controllers, channels, PTY management, and security middleware. Adding LiveView on top of that scope is a delivery risk with no upside for v1.

3. **LiveView is cheap to add later**: Once Phoenix is running (bd-168), adding LiveView is `{:phoenix_live_view, "~> 0.20"}` in mix.exs plus a router line. The structural enabler is bd-168, and it works whether or not LiveView is present. There is zero migration cost to adding it post-v1.

4. **Option C (drop) is too aggressive**: LiveView is the lowest-cost browser UI the stack will ever have. Dropping it forecloses the cheapest path to a feature that team/enterprise users will likely want eventually. Defer keeps the option open without spending anything now.

5. **The FastAPI precedent confirms the pattern**: The Python FastAPI server was deliberately headless — REST + WebSocket for programmatic access, no browser UI. The Phoenix replacement (bd-168) should match that scope. Adding LiveView would be scope creep relative to the system it replaces.

## Follow-up actions

- [ ] File new bd issue: "Revisit LiveView in Phase 6+ after v1 ships" — a placeholder with explicit revisit criteria:
  - **Criterion 1**: ≥3 users request a web dashboard or browser-based monitoring UI.
  - **Criterion 2**: Team/enterprise deployment scenario emerges where TUI-only is insufficient.
  - **Criterion 3**: Phase 6 scope allows it without crowding higher-priority items.
- [ ] Record this decision in bd-181 (update status to "decided — deferred").
- [ ] Ensure bd-168 Phoenix app structure does not preclude LiveView addition later (standard Phoenix endpoint + router layout is sufficient — no special work needed).
- [ ] Document in bd-168 that `phoenix_live_view` is explicitly NOT in Phase 5 scope, so future developers don't assume it was overlooked.

## R-risk acceptance

- **R7-Low**: Deferring LiveView means users who want a browser-based UI have no first-party option until Phase 6+ ships (timeline TBD, likely post-v1). Acceptable because: (a) no current user has requested a web UI, (b) the TUI is the primary interface and remains fully functional, (c) REST + Channels cover all programmatic access needs, and (d) LiveView can be added with zero migration cost whenever the demand materializes.

- **R8-Low**: If a future Phase 6+ adds LiveView, the Phoenix app structure from bd-168 must not have made assumptions that complicate LiveView integration (e.g., custom endpoint pipelines that skip the LiveView socket). Mitigated by using standard Phoenix project conventions in bd-168. Risk is low because standard Phoenix apps are LiveView-ready by default.

## References

- bd-169 — Browser automation strategy decision (sibling: evaluating whether to keep/drop browser tools entirely)
- bd-168 — Phoenix server migration (the enabler for LiveView; must ship first)
- bd-138 — Phase 5 task definition (HTTP API, WebSocket & Browser Automation)
- bd-132 — Epic: Rewrite Code Puppy from Python to Pure Elixir
- Phoenix LiveView docs: https://hexdocs.pm/phoenix_live_view
- Phoenix LiveView hex.pm: https://hex.pm/packages/phoenix_live_view
- Code Puppy current Phoenix web layer: `elixir/code_puppy_control/lib/code_puppy_control_web/` (3 controllers, 3 channels, 0 LiveViews)
