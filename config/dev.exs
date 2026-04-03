import Config

# Development environment configuration

config :logger,
  level: :debug

config :logger, :console,
  format: "$time [$level] $metadata$message\n",
  metadata: [:request_id, :plugin, :hook],
  colors: [info: :green, error: :red, warning: :yellow]

# Plugin Manager dev settings
config :mana, Mana.Plugin.Manager,
  backlog_ttl: 5_000,
  max_backlog_size: 50
