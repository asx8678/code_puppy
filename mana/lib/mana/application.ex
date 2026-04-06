defmodule Mana.Application do
  @moduledoc """
  OTP Application module for the Mana plugin system.

  Starts the supervision tree with all core GenServers.

  ## Headless/Container Mode

  This application gracefully handles headless environments where
  standard IO devices may not be available (e.g., containers, systemd,
  detached mode). It detects missing TTY and configures fallbacks
  to prevent crashes from Logger/IO operations.
  """

  use Application

  require Logger

  @doc """
  Checks if the application is running in a headless environment.

  Returns true if standard_error device is not available, indicating
  a container, detached, or non-TTY environment.
  """
  @spec headless?() :: boolean()
  def headless? do
    not tty_available?() or
      System.get_env("MANA_HEADLESS") == "true" or
      System.get_env("CONTAINER") == "true"
  end

  @doc """
  Checks if a TTY (terminal) is available for IO operations.

  Uses `:io.columns/1` which returns `{:error, _}` when there is no TTY.
  This is more reliable than checking for specific process registrations
  because it directly tests whether the IO device can handle terminal ops.
  """
  @spec tty_available?() :: boolean()
  def tty_available? do
    case :io.columns(:standard_error) do
      {:ok, _} -> true
      {:error, _} -> false
    end
  rescue
    ArgumentError -> false
  end

  @doc """
  Configures Logger for headless environments.

  When running without a TTY, Logger backends that write to
  standard_error will crash. This configures a safe fallback.
  """
  @spec configure_headless_logging() :: :ok
  def configure_headless_logging do
    try do
      Logger.remove_backend(:console)
    rescue
      _ -> :ok
    end

    :ok
  end

  # Web endpoint configuration - only start when server: true
  defp web_endpoint_children do
    endpoint_config = Application.get_env(:mana, Mana.Web.Endpoint, [])

    if endpoint_config[:server] do
      [
        # Phoenix web endpoint - serves HTTP requests
        {Mana.Web.Endpoint, []}
      ]
    else
      []
    end
  end

  @impl true
  def start(_type, _args) do
    # Check for headless environment and configure fallbacks
    if headless?() do
      configure_headless_logging()
    end

    # Attach telemetry handler for session metrics
    Mana.TelemetryHandler.attach()

    children =
      if Application.get_env(:mana, :auto_start, true) do
        [
          # Supervision tree start order:
          # 1. Config.Store — needed by everything
          # 2. Plugin.Manager — hooks for lifecycle
          # 3. Callbacks.Registry — callback dispatch
          # 4. MessageBus — message routing
          # 5. Tools.Registry — tool registration and execution
          {Mana.Tools.Registry, []},
          # 6. Shell.Executor — shell command execution
          {Mana.Shell.Executor, []},
          {Mana.Plugin.Manager, []},
          {Mana.Callbacks.Registry, []},
          {Mana.MessageBus, []},
          # 6. Models.Registry — provider dispatch
          {Mana.Models.Registry, []},
          # 7. Commands.Registry — slash command dispatch
          {Mana.Commands.Registry, []},
          # 8. Session.Store — session history
          {Mana.Session.Store, []},
          # 9. Agents.Registry — agent discovery
          {Mana.Agents.Registry, []},
          # 10. TaskSupervisor — async agent execution (needed by RunSupervisor)
          {Task.Supervisor, name: Mana.TaskSupervisor},
          # 11. Agents.RunSupervisor — supervised agent runs
          {Mana.Agents.RunSupervisor, []},
          # 12. Pack.Supervisor — multi-agent workflow orchestrator (uses RunSupervisor)
          {Mana.Pack.Supervisor, []},
          # 13. RateLimiter — per-model rate limiting
          {Mana.RateLimiter, []},
          # 14. OAuth.RefreshManager — serialized token refresh
          {Mana.OAuth.RefreshManager, []},
          # 15. TTSR Registry — stream watcher session registry
          {Registry, keys: :unique, name: Mana.TTSR.Registry},
          # 16. TTSR Watcher Supervisor — supervised stream watchers
          {DynamicSupervisor, strategy: :one_for_one, name: Mana.TTSR.WatcherSupervisor},
          # 17. TTSR Watcher Cleanup — periodic cleanup of stale watchers
          {Mana.TTSR.WatcherCleanup, []}
        ]
      else
        []
      end

    children = children ++ web_endpoint_children()

    opts = [strategy: :rest_for_one, name: Mana.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    Mana.Web.Endpoint.config_change(changed, removed)
    :ok
  end
end
