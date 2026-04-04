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
          {Mana.Config.Store, []},
          {Mana.Plugin.Manager, []},
          {Mana.Callbacks.Registry, []},
          {Mana.MessageBus, []}
        ]
      else
        []
      end

    opts = [strategy: :one_for_one, name: Mana.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
