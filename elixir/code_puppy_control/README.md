# CodePuppyControl

Elixir Phoenix control plane for the code_puppy project.

## Architecture

This application serves as the control plane for managing Python agent workers:

- **Phoenix API** - HTTP API for run management and tool execution
- **Registry** - Process registry for run and worker tracking
- **PubSub** - Event distribution across processes
- **Oban** - Job scheduling for background tasks
- **Python Workers** - Port-based communication with Python processes

## Directory Structure

```
lib/code_puppy_control/
├── application.ex          # OTP supervision tree
├── protocol.ex             # JSON-RPC encoding/decoding
├── request_tracker.ex      # Prompt correlation
├── python_worker/
│   ├── port.ex            # GenServer owning Python Port
│   └── supervisor.ex      # DynamicSupervisor for workers
├── run/
│   ├── registry.ex        # Run registry
│   ├── state.ex           # Run state GenServer
│   └── supervisor.ex      # DynamicSupervisor for runs
└── web/
    ├── endpoint.ex        # Phoenix endpoint
    ├── router.ex          # API routes
    └── controllers/
        ├── run_controller.ex    # Run management
        └── health_controller.ex  # Health checks
```

## Quick Start

```bash
# Install dependencies
mix deps.get

# Setup database (SQLite)
mix ecto.setup

# Run tests
mix test

# Start the server
mix phx.server
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/runs` | POST | Create new run |
| `/api/runs/:id` | GET | Get run status |
| `/api/runs/:id` | DELETE | Stop run |
| `/api/runs/:id/execute` | POST | Execute tool |
| `/api/runs/:id/history` | GET | Get history |

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY_BASE` | Phoenix secret key | Production |
| `DATABASE_PATH` | SQLite database path | Production |
| `PYTHON_WORKER_SCRIPT` | Path to Python worker | Production |

### Dual-Home Config Isolation

Elixir pup-ex uses a **separate home directory** from Python pup to prevent config
corruption during the migration. See [ADR-003](../../docs/adr/ADR-003-dual-home-config-isolation.md)
for full design.

| Runtime | Home directory | Status |
|---------|---------------|--------|
| Elixir pup-ex | `~/.code_puppy_ex/` (or `PUP_EX_HOME`) | ✅ Read + write |
| Python pup | `~/.code_puppy/` (legacy) | 📖 Read-only via explicit import |

**Runtime enforcement:** All filesystem writes go through `CodePuppyControl.Config.Isolation`.
Any attempt to write under `~/.code_puppy/` raises `IsolationViolation` — no exceptions.

#### First-time setup

If you're a user with an existing `~/.code_puppy/` from Python pup:

```bash
# Copy non-sensitive settings over (dry-run by default)
mix pup_ex.import              # shows what WOULD be copied
mix pup_ex.import --confirm    # actually copies

# Verify isolation health
mix pup_ex.doctor              # reports ✅ ISOLATED on healthy setup
```

The importer copies an **allowlist** of non-sensitive files only:
- `extra_models.json`, user additions in `models.json`
- `[ui]` section of `puppy.cfg`
- `agents/` and `skills/` directories

**Never copied:** OAuth tokens, sessions, API keys, `dbos_store.sqlite`, command history.
Re-authenticate with `mix pup_ex.auth.login` (OAuth scaffolding; full flow in bd-166).

#### Relevant environment variables

| Variable | Purpose | Default |
|----------|---------|--------|
| `PUP_EX_HOME` | Override Elixir home directory | `~/.code_puppy_ex/` |
| `PUP_HOME` | **Deprecated** — logs a warning; use `PUP_EX_HOME` | — |
| `PUPPY_HOME` | **Legacy** — logs a warning; use `PUP_EX_HOME` | — |

## Development

### IEx Session

```bash
iex -S mix

# Check running workers
CodePuppyControl.PythonWorker.Supervisor.list_workers()

# Check active runs
CodePuppyControl.Run.Supervisor.list_runs()

# Start a run
CodePuppyControl.Run.Supervisor.start_run("test-run-1", %{})
```

### JSON-RPC Protocol

The control plane uses JSON-RPC 2.0 with Content-Length framing:

```
Content-Length: 47\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize"}
```

See `lib/code_puppy_control/protocol.ex` for encoding/decoding functions.

### Running Isolation Gates

The 5 CI gates from ADR-003 are consolidated in a dedicated test file:

```bash
mix gates.isolation
```

This runs the 8 gate tests (GATE-1 through GATE-5) in under a second. The gates
also run automatically on every PR that touches config, pup_ex tasks, or the
workflow itself (see `.github/workflows/elixir-isolation-gates.yml`).

## License

Same as the main code_puppy project.
