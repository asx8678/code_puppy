import Config

# Test environment configuration

config :logger,
  level: :warning

config :logger, :console, format: "$message\n"

# Don't auto-start the manager in tests - we start it manually per test
config :mana, :start_manager, false
