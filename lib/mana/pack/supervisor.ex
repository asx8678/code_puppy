defmodule Mana.Pack.Supervisor do
  @moduledoc """
  Supervisor for the Pack multi-agent workflow system.

  Starts `Mana.Pack.Leader` under a `:one_for_one` strategy so that
  the leader can be restarted independently of the rest of the
  application supervision tree.
  """

  use Supervisor

  @doc """
  Starts the Pack supervisor.
  """
  @spec start_link(keyword()) :: Supervisor.on_start()
  def start_link(opts \\ []) do
    Supervisor.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    children = [
      {Mana.Pack.Leader, name: Mana.Pack.Leader}
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end
end
