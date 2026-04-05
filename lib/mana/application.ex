defmodule Mana.Application do
  @moduledoc """
  OTP Application module for the Mana plugin system.

  Starts the supervision tree with all core GenServers.
  """

  use Application

  require Logger

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
          # 12. RateLimiter — per-model rate limiting
          {Mana.RateLimiter, []},
          # 13. OAuth.RefreshManager — serialized token refresh
          {Mana.OAuth.RefreshManager, []},
          # 14. TTSR Registry — stream watcher session registry
          {Registry, keys: :unique, name: Mana.TTSR.Registry},
          # 15. TTSR Watcher Supervisor — supervised stream watchers
          {DynamicSupervisor, strategy: :one_for_one, name: Mana.TTSR.WatcherSupervisor},
          # 16. TTSR Watcher Cleanup — periodic cleanup of stale watchers
          {Mana.TTSR.WatcherCleanup, []}
        ]
      else
        []
      end

    children = children ++ web_endpoint_children()

    opts = [strategy: :rest_for_one, name: Mana.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
