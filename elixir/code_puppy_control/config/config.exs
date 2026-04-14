import Config

config :code_puppy_control,
  ecto_repos: [CodePuppyControl.Repo],
  generators: [timestamp_type: :utc_datetime]

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

config :code_puppy_control, Oban,
  engine: Oban.Engines.Basic,
  notifier: {Oban.Notifiers.Poll, []},
  queues: [python_workers: 5],
  repo: CodePuppyControl.Repo

import_config "#{config_env()}.exs"
