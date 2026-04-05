defmodule Mana.Application do
  @moduledoc """
  OTP Application module for the Mana plugin system.

  Starts the supervision tree with all core GenServers.
  """

  use Application

  require Logger

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
          # 5. Shell.Executor — shell command execution
          {Mana.Config.Store, []},
          {Mana.Plugin.Manager, []},
          {Mana.Callbacks.Registry, []},
          {Mana.MessageBus, []},
          {Mana.Shell.Executor, []},
          # 6. Models.Registry — provider dispatch
          {Mana.Models.Registry, []},
          # 7. Commands.Registry — slash command dispatch
          {Mana.Commands.Registry, []},
          # 8. Session.Store — session history
          {Mana.Session.Store, []},
          # 9. Agents.Registry — agent discovery
          {Mana.Agents.Registry, []},
          # 10. Agents.RunSupervisor — supervised agent runs
          {Mana.Agents.RunSupervisor, []},
          # 11. RateLimiter — per-model rate limiting
          {Mana.RateLimiter, []},
          # 12. TTSR Registry — stream watcher session registry
          {Registry, keys: :unique, name: Mana.TTSR.Registry}
        ]
      else
        []
      end

    opts = [strategy: :rest_for_one, name: Mana.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
