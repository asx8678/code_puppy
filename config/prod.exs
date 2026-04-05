import Config

config :mana, Mana.Web.Endpoint,
  url: [host: {:system, "HOST"}],
  http: [ip: {0, 0, 0, 0}, port: 4000],
  server: true,
  secret_key_base: {:system, "SECRET_KEY_BASE"}

config :logger, level: :info
