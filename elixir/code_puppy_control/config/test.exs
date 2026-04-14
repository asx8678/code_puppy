import Config

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :code_puppy_control, CodePuppyControlWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "test_secret_key_base_that_is_at_least_64_bytes_long_123456789012345678901234567890",
  server: false

# Print only warnings and errors during test
config :logger, level: :warning

# Initialize plugs at runtime for faster test compilation
config :phoenix, :plug_init_mode, :runtime

# In-memory database for testing
config :code_puppy_control, CodePuppyControl.Repo,
  database: ":memory:",
  pool_size: 1,
  pool: Ecto.Adapters.SQL.Sandbox

# Oban testing configuration
config :code_puppy_control, Oban,
  engine: Oban.Engines.Basic,
  notifier: {Oban.Notifiers.Poll, []},
  queues: false,
  repo: CodePuppyControl.Repo
