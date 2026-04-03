defmodule Mana.Application do
  @moduledoc """
  Application supervisor for the Mana plugin system.

  Starts the plugin manager and any other required services.
  """

  use Application

  require Logger

  @impl true
  def start(_type, _args) do
    children =
      if Application.get_env(:mana, :start_manager, true) do
        [
          # Plugin manager - the core service
          Mana.Plugin.Manager
        ]
      else
        []
      end

    opts = [strategy: :one_for_one, name: Mana.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
