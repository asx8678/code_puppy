import Config

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :code_puppy_control, CodePuppyControlWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base:
    "test_secret_key_base_that_is_at_least_64_bytes_long_123456789012345678901234567890",
  pubsub_server: CodePuppyControl.PubSub,
  server: false

# Print only warnings and errors during test
config :logger, level: :warning

# Python worker script for testing (mock path)
config :code_puppy_control, :python_worker_script, "/tmp/mock_python_worker.py"

# WebSocket auth secret for testing
config :code_puppy_control, :websocket_secret, "test_websocket_secret_for_testing"

# Ensure Oban config exists for tests
# Use :inline mode for testing and disable PostgreSQL-specific features
config :code_puppy_control, Oban,
  engine: Oban.Engines.Basic,
  peer: false,
  queues: false,
  repo: CodePuppyControl.Repo,
  notifier: Oban.Notifiers.Isolated,
  testing: :inline

# Initialize plugs at runtime for faster test compilation
config :phoenix, :plug_init_mode, :runtime

# File-based database for testing (in-memory causes migration issues with SQLite)
config :code_puppy_control, CodePuppyControl.Repo,
  database: System.get_env("PUP_TEST_DB", "priv/repo/test.db"),
  pool_size: 1,
  pool: Ecto.Adapters.SQL.Sandbox
