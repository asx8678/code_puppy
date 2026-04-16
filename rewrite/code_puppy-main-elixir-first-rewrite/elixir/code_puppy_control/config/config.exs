import Config

config :code_puppy_control,
  ecto_repos: [CodePuppyControl.Repo],
  generators: [timestamp_type: :utc_datetime]

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

# Oban configuration with SQLite support
config :code_puppy_control, Oban,
  engine: Oban.Engines.Lite,
  queues: [default: 10, scheduled: 5],
  repo: CodePuppyControl.Repo,
  plugins: [
    # Prune completed jobs older than 7 days
    {Oban.Plugins.Pruner, max_age: 60 * 60 * 24 * 7},
    # Rescue orphaned jobs after 30 minutes
    {Oban.Plugins.Lifeline, rescue_after: :timer.minutes(30)}
  ]

import_config "#{config_env()}.exs"
