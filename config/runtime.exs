import Config

# Runtime configuration for production
#
# This file is evaluated at runtime (on startup) and can access
# environment variables and other runtime-only information.

if config_env() == :prod do
  # Production logging
  log_level =
    case System.get_env("MANA_LOG_LEVEL", "info") do
      "debug" -> :debug
      "info" -> :info
      "warning" -> :warning
      "error" -> :error
      _ -> :info
    end

  config :logger,
    level: log_level,
    backends: [:console]

  config :logger, :console,
    format: "$time [$level] $message\n",
    metadata: [:request_id]

  # Plugin configuration from environment
  plugin_list =
    case System.get_env("MANA_PLUGINS") do
      nil ->
        [:discover]

      "" ->
        [:discover]

      plugins ->
        plugins
        |> String.split(",")
        |> Enum.map(&String.trim/1)
        |> Enum.map(fn module_str ->
          case Code.ensure_compiled(String.to_atom("Elixir.#{module_str}")) do
            {:module, module} -> module
            _ -> nil
          end
        end)
        |> Enum.reject(&is_nil/1)
    end

  config :mana, Mana.Plugin.Manager,
    plugins: plugin_list,
    backlog_ttl: String.to_integer(System.get_env("MANA_BACKLOG_TTL", "30000")),
    max_backlog_size: String.to_integer(System.get_env("MANA_MAX_BACKLOG", "100"))
end
