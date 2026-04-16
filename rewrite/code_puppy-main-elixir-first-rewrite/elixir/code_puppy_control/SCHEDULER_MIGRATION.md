# Scheduler Migration to Oban - Migration Guide

## Overview

This migration replaces the Python-based scheduler daemon with an Elixir/Oban implementation that uses SQLite for persistence instead of JSON files and PID file management.

## Changes Made

### 1. Database Schema (Migrations)

Three migrations were added to `priv/repo/migrations/`:

- **`20250414000001_create_oban_jobs.exs`** - Creates the Oban jobs table for job queuing
- **`20250414000002_create_scheduled_tasks.exs`** - Creates the scheduled_tasks table for user-defined tasks
- **`20250414000003_create_oban_meta.exs`** - Creates the Oban meta table for SQLite coordination

### 2. Scheduler Modules

New modules in `lib/code_puppy_control/scheduler/`:

- **`Task`** - Ecto schema with validations for:
  - Cron expressions (using Crontab library)
  - Interval formats (30s, 5m, 1h, 2d)
  - Required fields (name, agent_name, prompt)

- **`Worker`** - Oban.Worker that:
  - Executes tasks via `Run.Manager`
  - Handles timeouts (5 minute default)
  - Retries up to 3 times
  - Updates task status (running → success/failed/cancelled)

- **`CronScheduler`** - GenServer that:
  - Checks schedules every 60 seconds
  - Enqueues due tasks via Oban
  - Can be manually triggered with `Scheduler.force_check/0`

- **`Scheduler`** - Public API for:
  - CRUD operations on tasks
  - Manual task execution
  - Task history queries
  - Statistics

### 3. Configuration Updates

**`config/config.exs`:**
```elixir
config :code_puppy_control, Oban,
  engine: Oban.Engines.Lite,  # SQLite-compatible engine
  queues: [default: 10, scheduled: 5],
  plugins: [
    {Oban.Plugins.Pruner, max_age: 60 * 60 * 24 * 7},
    {Oban.Plugins.Lifeline, rescue_after: :timer.minutes(30)}
  ]
```

**`mix.exs`:** Added `{:crontab, "~> 1.1"}` dependency.

**`lib/code_puppy_control/application.ex`:** Added to supervision tree:
- `{Oban, Application.fetch_env!(:code_puppy_control, Oban)}`
- `{CodePuppyControl.Scheduler.CronScheduler, []}`

## Usage

### Running Migrations

```bash
cd elixir/code_puppy_control
mix deps.get
mix ecto.create
mix ecto.migrate
```

### Creating Scheduled Tasks

```elixir
# Create an hourly task
{:ok, task} = CodePuppyControl.Scheduler.create_task(%{
  name: "hourly-sync",
  agent_name: "sync-agent",
  prompt: "Sync data with remote API",
  schedule_type: "hourly"
})

# Create a cron-scheduled daily task
{:ok, task} = CodePuppyControl.Scheduler.create_task(%{
  name: "daily-report",
  agent_name: "reporter",
  prompt: "Generate daily report",
  schedule_type: "cron",
  schedule: "0 9 * * *"  # 9 AM daily
})

# Create an interval task
{:ok, task} = CodePuppyControl.Scheduler.create_task(%{
  name: "frequent-check",
  agent_name: "checker",
  prompt: "Check system status",
  schedule_type: "interval",
  schedule_value: "30m"  # Every 30 minutes
})
```

### Managing Tasks

```elixir
# List all tasks
tasks = CodePuppyControl.Scheduler.list_tasks()

# Disable a task
{:ok, _} = CodePuppyControl.Scheduler.disable_task(task)

# Run a task immediately
{:ok, job} = CodePuppyControl.Scheduler.run_task_now(task)

# Get task history
history = CodePuppyControl.Scheduler.get_task_history(task.id, limit: 10)

# Get statistics
stats = CodePuppyControl.Scheduler.statistics()
```

### Forcing a Schedule Check

```elixir
# Manually trigger schedule evaluation
CodePuppyControl.Scheduler.force_check()

# Get scheduler state
state = CodePuppyControl.Scheduler.CronScheduler.get_state()
```

## Migration from Python Scheduler

If migrating from the Python scheduler:

1. **Task Data:** Python tasks used JSON storage. You'll need to re-create tasks via the Elixir API.
2. **PID Files:** No longer needed - Oban handles process management.
3. **Logs:** Task execution logs are now stored in the database and accessible via `Scheduler.get_task_history/2`.

## Testing

Run scheduler tests:

```bash
cd elixir/code_puppy_control
mix test test/code_puppy_control/scheduler/
```

## Architecture Differences from Python

| Feature | Python Scheduler | Oban Scheduler |
|---------|------------------|----------------|
| Persistence | JSON files | SQLite via Ecto |
| Process Mgmt | PID files | Oban supervised workers |
| Scheduling | Manual loop | GenServer + Oban |
| Cron Support | Limited | Full via crontab lib |
| History | Log files | Oban jobs table |
| Crash Recovery | Manual reconciliation | Oban.Plugins.Lifeline |
| Concurrency | Sequential | Configurable queues |

## Troubleshooting

### Jobs not running?

1. Check Oban is configured: `Application.fetch_env!(:code_puppy_control, Oban)`
2. Verify queue is running: `Oban.check_queue(queue: :scheduled)`
3. Check job state in database: `Repo.all(Oban.Job)`

### Cron expressions not working?

Crontab library syntax uses standard cron format:
- `* * * * *` - Every minute
- `0 * * * *` - Every hour
- `0 9 * * *` - 9 AM daily
- `0 9 * * 1` - 9 AM Mondays

## Future Enhancements

- Add Phoenix LiveView UI for task management
- Add webhook notifications for task completion
- Add metrics/monitoring for scheduler health
- Support for task dependencies and DAGs
