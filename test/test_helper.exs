ExUnit.start()

# Configure test environment
Application.put_env(:mana, Mana.Plugin.Manager,
  plugins: [],
  backlog_ttl: 1_000,
  max_backlog_size: 10,
  auto_dismiss_errors: false
)
