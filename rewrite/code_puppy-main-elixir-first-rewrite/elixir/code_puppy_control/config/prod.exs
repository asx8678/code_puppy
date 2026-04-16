import Config

config :code_puppy_control, CodePuppyControlWeb.Endpoint,
  http: [ip: {0, 0, 0, 0}, port: 4000],
  secret_key_base: {:system, "SECRET_KEY_BASE"},
  server: true

config :logger, level: :info

config :code_puppy_control, CodePuppyControl.Repo,
  database: {:system, "DATABASE_PATH"},
  pool_size: 10
