import Config

# Mana Plugin System Configuration
#
# This file configures the Mana plugin system. For production,
# use config/runtime.exs to load secrets and environment-specific config.

config :logger,
  level: :info

config :logger, :console,
  format: "$time [$level] $message\n",
  metadata: [:request_id, :plugin]

# Plugin Manager Configuration
config :mana, Mana.Plugin.Manager,
  # Plugin loading strategy:
  # - :discover - Auto-discover modules in Mana.Plugins namespace
  # - Module atoms - Explicitly load specific modules
  plugins: [:discover],

  # Backlog configuration for events that fire before listeners register
  # TTL in milliseconds for buffered events
  backlog_ttl: 30_000,
  # Maximum number of events to buffer per hook
  max_backlog_size: 100,

  # Error handling
  # If true, failed plugin loads are logged but don't stop system startup
  auto_dismiss_errors: true,

  # Plugin-specific configurations
  plugin_configs: %{
    # Example:
    # Mana.Plugins.Logger => %{
    #   level: :info,
    #   log_tool_calls: true,
    #   log_stream_events: false
    # }
  }

# Additional namespaces to search for plugins
config :mana,
  plugin_namespaces: [Mana.Plugins]

# Import environment-specific config
import_config "#{config_env()}.exs"
