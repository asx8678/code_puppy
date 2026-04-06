defmodule Mana.Scheduler.SupervisorTest do
  use ExUnit.Case, async: false

  alias Mana.Scheduler.Supervisor, as: SchedulerSupervisor

  test "starts and stops cleanly" do
    {:ok, pid} = SchedulerSupervisor.start_link([])

    assert Process.alive?(pid)

    # Should have one child (the Runner)
    children = Supervisor.which_children(pid)
    assert length(children) == 1

    # The runner should be alive
    [{_, runner_pid, :worker, _}] = children
    assert runner_pid != :undefined
    assert Process.alive?(runner_pid)

    GenServer.stop(pid, :normal, 5_000)
  end
end
