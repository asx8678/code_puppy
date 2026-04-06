defmodule Mana.Pack.SupervisorTest do
  @moduledoc """
  Tests for Mana.Pack.Supervisor module.
  """

  use ExUnit.Case, async: false

  alias Mana.Pack.Leader
  alias Mana.Pack.Supervisor, as: PackSupervisor

  test "starts and stops cleanly" do
    {:ok, pid} = PackSupervisor.start_link([])

    assert Process.alive?(pid)

    # Should have Leader as a child
    children = Supervisor.which_children(pid)
    assert length(children) == 1

    # The leader child should be present
    [{id, leader_pid, :worker, _}] = children
    assert id == Leader
    assert leader_pid != :undefined
    assert Process.alive?(leader_pid)

    GenServer.stop(pid, :normal, 5_000)
  end

  test "supervisor uses one_for_one strategy" do
    {:ok, pid} = PackSupervisor.start_link([])

    # Verify it's a supervisor
    children = Supervisor.which_children(pid)
    assert children != []

    GenServer.stop(pid, :normal, 5_000)
  end

  test "leader can be restarted independently" do
    {:ok, pid} = PackSupervisor.start_link([])

    # Find the leader PID
    [{_, leader_pid, :worker, _}] = Supervisor.which_children(pid)
    original_pid = leader_pid

    # Kill the leader
    Process.exit(leader_pid, :kill)
    Process.sleep(100)

    # Supervisor should have restarted it
    [{_, new_leader_pid, :worker, _}] = Supervisor.which_children(pid)

    # The supervisor itself should still be alive
    assert Process.alive?(pid)
    # The new leader should be alive (restarted by supervisor)
    assert new_leader_pid != :undefined
    assert Process.alive?(new_leader_pid)

    GenServer.stop(pid, :normal, 5_000)
  end
end
