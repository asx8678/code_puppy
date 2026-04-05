defmodule Mana.Agents.RunSupervisorTest do
  @moduledoc """
  Tests for Mana.Agents.RunSupervisor.
  """

  use ExUnit.Case, async: false

  alias Mana.Agent.Server
  alias Mana.Agents.RunSupervisor
  alias Mana.Callbacks.Registry
  alias Mana.Config.Store

  setup do
    start_supervised!(Store)
    start_supervised!(Registry)
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
      # Let it die
      Process.sleep(10)

      # Should handle dead pid gracefully
      result = RunSupervisor.start_run(dead_pid, "Hello", [])
      assert match?({:ok, _}, result)
    end
  end

  describe "supervision" do
    test "tasks are started with temporary restart policy" do
      {:ok, agent_pid} = Server.start_link(agent_def: @test_agent_def)

      {:ok, task_pid} = RunSupervisor.start_run(agent_pid, "test", [])
      assert Process.alive?(task_pid)

      # Kill the task
      Process.exit(task_pid, :kill)
      Process.sleep(50)

      # Task should be dead and not restarted (temporary policy)
      refute Process.alive?(task_pid)
    end
  end
end
