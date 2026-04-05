ExUnit.start(exclude: [:external])

Code.require_file("support/test_helpers.ex", __DIR__)

# Configure test environment
Application.put_env(:mana, Mana.Plugin.Manager,
  plugins: [],
  backlog_ttl: 1_000,
  max_backlog_size: 10,
  auto_dismiss_errors: false
)

# Start the TaskSupervisor for tests that need supervised async tasks
{:ok, _task_supervisor} = Task.Supervisor.start_link(name: Mana.TaskSupervisor)

# Start the OAuth RefreshManager for tests that need token refresh serialization
# This prevents race conditions during concurrent token refresh operations
{:ok, _refresh_manager} = Mana.OAuth.RefreshManager.start_link()
