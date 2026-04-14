import Config

config :code_puppy_control,
  ecto_repos: [CodePuppyControl.Repo],
  generators: [timestamp_type: :utc_datetime]

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

# Oban is currently disabled - the Postgres notifier is not compatible with SQLite
# To re-enable, switch to PostgreSQL or configure with SQLite-compatible notifier
# config :code_puppy_control, Oban,
#   engine: Oban.Engines.Basic,
#   queues: [default: 10],
#   repo: CodePuppyControl.Repo

import_config "#{config_env()}.exs"
