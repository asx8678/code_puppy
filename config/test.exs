import Config

# Test environment configuration

config :logger,
  level: :warning

config :logger, :console, format: "$message\n"

# Don't auto-start the supervision tree in tests - we start processes manually per test
config :mana, :auto_start, false
