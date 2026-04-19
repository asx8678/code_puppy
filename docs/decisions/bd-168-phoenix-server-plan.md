# bd-168 — Phoenix HTTP API & WebSocket Server Plan: Python → Elixir

- **Status**: Proposed
- **Date**: 2026-04-19
- **Owner**: planning-agent-019da7
- **Related**: bd-138, bd-132, bd-181, bd-169
- **Phase**: Phase 5 — HTTP API & WebSocket

## Executive summary

**Recommendation: 5-wave phased port of the Python FastAPI server to Phoenix.** The Python side has 7 source files, 6 HTTP routes, 3 WebSocket endpoints, and middleware for CORS/auth/rate-limiting. The Elixir side already has a Phoenix skeleton with `/health`, `/api/runs/*`, `/api/mcp/*`, and 3 channels (from bd-185 and earlier migration work). Wave 1 (this deliverable) adds the root `/` info endpoint + documents the full mapping. It does NOT add auth, PTY, or new channels — those are later waves. Each wave is a separate bd issue; bd-168 closes when Wave 1 lands.

## Current state

### Python FastAPI footprint (7 source files, 6 routes)

| File | Responsibility |
|---|---|
| `code_puppy/api/app.py` | FastAPI app factory: `GET /`, `GET /terminal`, `GET /health`, CORS + timeout middleware, lifespan cleanup |
| `code_puppy/api/websocket.py` | `WS /ws/events` (PubSub + history replay), `WS /ws/terminal` (PTY binary streaming), `WS /ws/health` (echo) |
| `code_puppy/api/security.py` | CORS origin allow-list, bearer token auth (`require_api_access`), auth-failure rate limiting (5/min/IP) |
| `code_puppy/api/pty_manager.py` | PTY session management: create/write/resize/close, backpressure-aware output callback |
| `code_puppy/api/schemas.py` | Pydantic `BaseModel` request/response schemas |
| `code_puppy/api/routers/sessions.py` | `/api/sessions` — session CRUD |
| `code_puppy/api/routers/config.py` | `/api/config` — runtime configuration |
| `code_puppy/api/routers/agents.py` | `/api/agents` — agent management |
| `code_puppy/api/routers/commands.py` | `/api/commands` — slash-command execution |

### Elixir Phoenix skeleton (already exists)

| Module | Status |
|---|---|
| `CodePuppyControlWeb.Endpoint` | ✅ Running — plug pipeline, socket `/socket` |
| `CodePuppyControlWeb.Router` | ✅ Running — `/health`, `/api/runs/*`, `/api/mcp/*` |
| `CodePuppyControlWeb.HealthController` | ✅ Running — richer than Python (worker/run counts) |
| `CodePuppyControlWeb.RunController` | ✅ Running — create/show/delete/execute/history |
| `CodePuppyControlWeb.MCPController` | ✅ Running — index/create/show/delete/call_tool/restart |
| `CodePuppyControlWeb.UserSocket` | ✅ Running — channel transport |
| `CodePuppyControlWeb.RunChannel` | ✅ Running — run event streaming |
| `CodePuppyControlWeb.SessionChannel` | ✅ Running — session events |

### What is MISSING from the Elixir side

- Root `/` info endpoint (Python returns an HTML landing page; we'll return JSON)
- `/terminal` redirect or page serve (low priority — terminal is a WebSocket concern)
- WebSocket channels: `EventsChannel`, `TerminalChannel`, `HealthChannel`
- 4 resource routers: sessions, config, agents, commands
- Auth/CORS/rate-limit plug pipeline
- PTY port/erlexec integration
- Pydantic → Ecto changeset or plain-map request validation

## Explicit NON-port cases (drop)

These Python patterns have no Elixir analog and should NOT be ported:

| Python concept | Why drop | Elixir replacement |
|---|---|---|
| Pydantic `response_model` decorators | Elixir is dynamically typed at the boundary | Jason encoding + typed structs internally |
| `Depends()` dependency injection | Functional pipeline, not DI | Plug pipeline (`plug :auth`, `plug :rate_limit`) |
| `BackgroundTasks` | BEAM processes already handle async work | `Task.Supervisor` + `Task.async` |
| `APIRouter` grouping | Phoenix scopes serve the same purpose | `scope "/api", Router` in `router.ex` |
| Starlette middleware stack | Plug pipeline replaces the entire concept | `plug` declarations in pipeline/scope |
| `asynccontextmanager` lifespan | BEAM supervision tree handles lifecycle | `Application.start/2` + supervisor children |
| Python context managers for auth | Single-responsibility plugs replace this | `Plug.Builder` pipeline |
| HTML template for `GET /` | API-only server; UI is a separate concern | JSON info endpoint |

## Mapping table: FastAPI → Phoenix

| FastAPI concept | Phoenix equivalent | Status in this repo |
|---|---|---|
| `FastAPI()` app | `Phoenix.Endpoint` | ✅ exists (`endpoint.ex`) |
| `APIRouter()` | `scope "/api", Router` | ✅ exists |
| `@app.get("/")` | `get "/", Controller, :action` | ⚠️ missing root route (Wave 1) |
| `@app.get("/health")` | `get "/health", HealthController, :index` | ✅ exists |
| `@app.get("/terminal")` | `get "/terminal", TerminalController, :index` | ⚠️ missing (Wave 3, low priority) |
| `@app.websocket("/ws/events")` | `channel "events:*", EventsChannel` | ⚠️ partial (socket exists, channel missing — Wave 3) |
| `@app.websocket("/ws/terminal")` | `channel "terminal:*", TerminalChannel` | ⚠️ missing (depends on Wave 4 PTY) |
| `@app.websocket("/ws/health")` | `channel "health:*", HealthChannel` | ⚠️ missing (Wave 3) |
| `async def endpoint()` | `def action(conn, params)` | — (controllers are sync; LLM calls use Task) |
| Pydantic `BaseModel` | Ecto schemaless changesets or plain maps | — (decision deferred to Wave 2) |
| `Depends(get_current_user)` | Plug auth in pipeline | ⚠️ missing (Wave 5) |
| `CORSMiddleware` | `CORSPlug` | ⚠️ missing (Wave 5) |
| `TimeoutMiddleware` | Plug timeout or Cowboy idle timeout | ⚠️ missing (Wave 5) |
| Auth-failure rate limit | `Hammer` or `PlugAttack` | ⚠️ missing (Wave 5) |
| PTY manager (`pty_manager.py`) | `Port.open/2` + GenServer wrapper | ⚠️ missing (Wave 4) |

## Proposed 5-wave plan

### Wave 1 — Infrastructure (THIS DELIVERABLE)

**Scope**: Root info endpoint + security plug pipeline scaffold + this mapping document.

**Deliverables**:
- `InfoController` — `GET /` returns `{app, version, status, endpoints}`
- Security plug pipeline scaffold (empty plugs for auth/CORS/rate-limit, just establish the structure)
- This decision document

**Exit criteria**: InfoController test passes; no regressions; ~50 LOC added.

**bd-168 closes here.**

### Wave 2 — REST resources

**Scope**: Port the 4 API routers (`sessions`, `config`, `agents`, `commands`) as Phoenix controllers.

**Why second**: These are the most mechanical port — straightforward CRUD patterns. Request/response schemas built with Ecto schemaless changesets + Jason. No WebSocket or PTY dependency.

**Key decisions**:
- Ecto changesets vs plain maps for request validation (recommend changesets for parity with Python's Pydantic validation)
- Router namespace: `/api/sessions`, `/api/config`, `/api/agents`, `/api/commands` (match Python path structure)

**Estimated scope**: ~200–300 LOC across 4 controllers + 4 test files + schema helpers.

**New bd issue after Wave 1 closes.**

### Wave 3 — WebSocket channels

**Scope**: 3 new Phoenix channels replacing the Python WebSocket endpoints.

| Channel | Replaces | Purpose |
|---|---|---|
| `EventsChannel` | `WS /ws/events` | Subscribes to `Phoenix.PubSub` events topic; supports session history replay |
| `TerminalChannel` | `WS /ws/terminal` | Proxies PTY bytes (depends on Wave 4 for PTY manager) |
| `HealthChannel` | `WS /ws/health` | Broadcasts periodic health status on PubSub |

**Why third**: EventsChannel and HealthChannel are self-contained. TerminalChannel depends on Wave 4 but the channel scaffold can land here with a stub PTY callback.

**Estimated scope**: ~250–400 LOC across 3 channels + 3 test files.

**New bd issue.**

### Wave 4 — PTY manager

**Scope**: `CodePuppyControl.PTY.Manager` GenServer wrapping OS PTY.

**Why fourth**: This is the most OS-intensive wave. Python uses `pty` + `fcntl` for non-blocking I/O; Elixir uses `Port.open/2` with `{:spawn_executable, ...}` or the `erlexec` hex package.

**Key decisions**:
- `Port.open/2` vs `erlexec` — `Port.open/2` is stdlib and sufficient for most use cases; `erlexec` adds supervisable OS processes with kill groups.
- Terminal resize: Python uses `fcntl.ioctl(TIOCSWINSZ)`. Elixir uses `:os.cmd/1` with `stty` or a thin NIF. The `erlexec` package handles this natively.
- Binary streaming: Python sends base64-encoded JSON in legacy mode, raw binary in modern mode. Elixir channels send binary terms natively — no base64 needed.

**Estimated scope**: ~150–250 LOC for GenServer + port communication protocol + 1 test file.

**New bd issue.**

### Wave 5 — Security middleware

**Scope**: Auth, CORS, rate limiting, timeout — the full defense-in-depth stack matching Python's `api/security.py`.

**Components**:
- **Auth plug**: Token-based, matches Python's `require_api_access` model (loopback bypass + `CODE_PUPPY_API_TOKEN` env var + constant-time comparison). Applied to mutating routes only.
- **CORS plug**: `CORSPlug` with localhost origin allow-list, matching Python's `get_allowed_origins()`.
- **Rate limit plug**: `Hammer` (ETS-backed, no Redis needed) or `PlugAttack`. 5 auth failures per minute per IP, matching Python's `AUTH_RATE_LIMIT_MAX_FAILURES`.
- **Timeout plug**: Plug-level timeout or Cowboy idle timeout for hanging requests (Python uses `asyncio.wait_for` with 30s default).
- **Origin enforcement for WebSocket**: `UserSocket.connect/3` callback validates Origin header, matching Python's `_reject_untrusted_origin`.

**Why last**: Security can be added incrementally to an already-running API. The loopback-only deployment model means the surface area is already constrained. This wave locks down the perimeter.

**Estimated scope**: ~200–300 LOC across 3 plugs + auth module + 3 test files.

**New bd issue.**

### Wave summary

| Wave | Scope | Estimated LOC | New deps? | New bd issue |
|---|---|---|---|---|
| 1 | Infrastructure (root endpoint + scaffold) | ~50 | No | bd-168 |
| 2 | REST resources (4 controllers) | ~200–300 | No | To be filed |
| 3 | WebSocket channels (3 channels) | ~250–400 | No | To be filed |
| 4 | PTY manager | ~150–250 | Maybe `erlexec` | To be filed |
| 5 | Security middleware | ~200–300 | Maybe `hammer` or `cors_plug` | To be filed |

## Decisions deferred to follow-up waves

| Decision | Deferred to | Rationale |
|---|---|---|
| `Port.open/2` vs `erlexec` for PTY | Wave 4 | Requires OS-level prototyping; both approaches are viable |
| Ecto changesets vs plain maps for request validation | Wave 2 | Schemaless changesets add structure but increase boilerplate; evaluate per-controller |
| Auth model: shared secret vs JWT vs token | Wave 5 | Must match Python `api/security.py` for dual-run parity (bd-177); shared secret (env var) is most likely |
| CORS: `CORSPlug` lib vs hand-rolled plug | Wave 5 | `CORSPlug` is trivial; hand-rolled gives more control over the origin allow-list logic |
| Rate limiting: `Hammer` vs `PlugAttack` | Wave 5 | Both are ETS-backed; `Hammer` has better docs, `PlugAttack` is more flexible |
| Terminal HTML page (`GET /terminal`) | Wave 3+ | API-only server; terminal UI is likely a separate SPA, not a server-rendered page |

## Risks & mitigations

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-Medium | PTY is OS-specific (BSD PTY vs Linux `openpty`) | Medium | Medium | Use `erlexec` or a thin NIF for cross-platform PTY; test on macOS + Linux in CI |
| R-Medium | Phoenix startup order — endpoint must come up before PTY manager or agent loop | Medium | High | Strict supervision tree order enforced in `application.ex`; PTY manager is `rest_for_one` under endpoint |
| R-Low | WebSocket auth differs from REST (Phoenix socket `:connect` callback vs plug pipeline) | Low | Medium | Share a single `CodePuppyControlWeb.Auth` module; socket `connect/3` calls `Auth.verify_token/1` |
| R-Low | Double-shipping (Python FastAPI + Elixir Phoenix simultaneously during transition) | Low | Low | Dual-run validation (bd-177); feature-flag via `enable_elixir_control` in `puppy.cfg` |
| R-Low | Binary frame protocol differs between Python WebSocket and Phoenix channels | Low | Medium | Phoenix channels use JSON framing by default; for binary PTY output, use `push` with binary payload or a raw WebSocket endpoint alongside the channel |

## Dependencies this wave adds

**NONE.** All Wave 1 work uses Phoenix + Plug that are already in `mix.exs`.

## Follow-up actions

- [ ] Close bd-168 after Wave 1 lands (this session).
- [ ] File 4 new bd issues (one per wave) after bd-168 closes.
- [ ] Security plug scaffold: create empty plugs in Wave 1 so Wave 5 just fills in the logic.
- [ ] Coordinate with bd-177 (dual-run validation) to ensure both servers can run simultaneously during Waves 2–5.

## References

- bd-138 — Phase tracking
- bd-132 — Phase 5 task definition
- bd-181 — LiveView evaluation decision doc (format reference)
- bd-169 — Related server work
- bd-185 — Initial Phoenix skeleton landing
- bd-177 — Dual-run validation
- bd-174 — Test suite porting plan (format reference for this doc)
- Python source: `code_puppy/api/app.py`, `code_puppy/api/websocket.py`, `code_puppy/api/security.py`
- Elixir source: `elixir/code_puppy_control/lib/code_puppy_control_web/`
