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

## License

Same as the main code_puppy project.
