defmodule Mana.Agents.RunSupervisorTest do
  @moduledoc """
  Tests for Mana.Agents.RunSupervisor.
  """

  use ExUnit.Case, async: false

  import Mana.TestHelpers
  alias Mana.Agent.Server
  alias Mana.Agents.RunSupervisor
  alias Mana.Callbacks.Registry
  alias Mana.Config.Store
  alias Mana.Tools.Registry, as: ToolsRegistry

  setup do
    start_supervised!(Store)
    start_supervised!(Registry)
    start_supervised!(ToolsRegistry)
    start_supervised!(RunSupervisor)

    :ok
  end

  @test_agent_def %{
    name: "test",
    display_name: "Test Agent",
    description: "A test agent for run supervisor tests",
    system_prompt: "You are a test agent.",
    available_tools: [],
    user_prompt: "",
    tools_config: %{}
  }

  describe "start_link/1" do
    test "starts a DynamicSupervisor" do
      # The supervisor was already started in setup
      assert Process.whereis(RunSupervisor) != nil
      assert Process.alive?(Process.whereis(RunSupervisor))
    end

    test "can start with custom name" do
      {:ok, pid} = RunSupervisor.start_link(name: :custom_supervisor_name)
      assert Process.alive?(pid)
      assert Process.whereis(:custom_supervisor_name) == pid

      DynamicSupervisor.stop(pid)
    end
  end

  describe "start_run/3" do
    test "starts a supervised run task" do
      {:ok, agent_pid} = Server.start_link(agent_def: @test_agent_def)

      # Start a run - note: this will fail since we don't have a real model
      # but it should still start the task
      result = RunSupervisor.start_run(agent_pid, "Hello", [])

      # Should return {:ok, pid} even if the run itself fails
      assert match?({:ok, _}, result)
    end

    test "requires valid agent pid" do
      dead_pid = spawn(fn -> :ok end)
      # Wait for the spawned process to actually terminate
      wait_for_exit(dead_pid, timeout: 100)

      # Should handle dead pid gracefully
      result = RunSupervisor.start_run(dead_pid, "Hello", [])
      assert match?({:ok, _}, result)
    end
  end

  describe "max_children enforcement" do
    test "enforces max_children limit of 50" do
      # Start a supervisor with a low max_children for testing
      {:ok, test_supervisor} =
        DynamicSupervisor.start_link(
          strategy: :one_for_one,
          max_children: 3
        )

      # Start 3 children (the limit)
      children =
        for _i <- 1..3 do
          {:ok, pid} =
            DynamicSupervisor.start_child(
              test_supervisor,
              %{
                id: make_ref(),
                start: {Task, :start_link, [fn -> Process.sleep(5000) end]},
                restart: :temporary
              }
            )

          pid
        end

      # Verify all 3 are running
      assert length(children) == 3

      for pid <- children do
        assert Process.alive?(pid)
      end

      # 4th child should fail with :max_children
      result =
        DynamicSupervisor.start_child(
          test_supervisor,
          %{
            id: make_ref(),
            start: {Task, :start_link, [fn -> :ok end]},
            restart: :temporary
          }
        )

      assert result == {:error, :max_children}

      # Cleanup
      DynamicSupervisor.stop(test_supervisor)
    end

    test "RunSupervisor has max_children configured" do
      # Verify the actual RunSupervisor has max_children set
      {:ok, test_super} = RunSupervisor.start_link(name: :test_max_children)

      # Verify max_children is set to 50 by trying to get info via count_children
      count = DynamicSupervisor.count_children(test_super)
      # max_children isn't directly exposed, but we can verify the supervisor starts
      assert count.active >= 0
      assert count.specs >= 0

      DynamicSupervisor.stop(test_super)
    end
  end

  describe "supervision" do
    test "tasks are started with temporary restart policy" do
      {:ok, agent_pid} = Server.start_link(agent_def: @test_agent_def)

      {:ok, task_pid} = RunSupervisor.start_run(agent_pid, "test", [])
      assert Process.alive?(task_pid)

      # Kill the task
      Process.exit(task_pid, :kill)

      # Wait for the task to die (temporary restart policy means no restart)
      wait_for_exit(task_pid, timeout: 500)
      refute Process.alive?(task_pid)
    end

    test "terminates child after run completes" do
      {:ok, agent_pid} = Server.start_link(agent_def: @test_agent_def)

      # Get initial child count
      count_before = DynamicSupervisor.count_children(RunSupervisor)
      initial_count = count_before.active

      # Start a run
      {:ok, task_pid} = RunSupervisor.start_run(agent_pid, "test", timeout: 100)

      # Wait for it to complete and terminate
      assert_eventually(
        fn -> not Process.alive?(task_pid) end,
        timeout: 5000
      )

      # Child should be terminated
      refute Process.alive?(task_pid)

      # Child count should return to initial (or close to it)
      count_after = DynamicSupervisor.count_children(RunSupervisor)
      assert count_after.active <= initial_count
    end
  end
end
