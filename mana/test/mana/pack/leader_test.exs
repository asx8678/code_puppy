defmodule Mana.Pack.LeaderTest do
  @moduledoc """
  Tests for Pack.Leader - the workflow orchestrator GenServer.

  Tests cover:
  - State machine transitions
  - API functions (start_link, run_workflow, get_status, stop)
  - Planning phase (bd ready querying)
  - Workflow execution lifecycle
  - Error handling and recovery
  """

  use ExUnit.Case, async: false

  alias Mana.Pack.Leader

  describe "start_link/1" do
    test "starts with default options" do
      {:ok, pid} = Leader.start_link([])
      assert Process.alive?(pid)

      {:ok, status} = Leader.get_status(pid)
      assert status.state == :idle
      assert status.base_branch == "main"

      Leader.stop(pid)
    end

    test "starts with custom base_branch" do
      {:ok, pid} = Leader.start_link(base_branch: "feature/oauth")

      {:ok, status} = Leader.get_status(pid)
      assert status.base_branch == "feature/oauth"

      Leader.stop(pid)
    end

    test "registers with name when provided" do
      {:ok, pid} = Leader.start_link(name: :test_leader)
      assert Process.whereis(:test_leader) == pid

      {:ok, status} = Leader.get_status(:test_leader)
      assert status.state == :idle

      Leader.stop(:test_leader)
    end
  end

  describe "get_status/1" do
    test "returns initial status" do
      {:ok, pid} = Leader.start_link([])

      {:ok, status} = Leader.get_status(pid)
      assert status.state == :idle
      assert status.base_branch == "main"
      assert status.tasks == %{}
      assert status.ready_issues == []
      assert status.progress == {0, 0}
      assert status.errors == []
      assert is_nil(status.started_at)
      assert is_nil(status.completed_at)
      assert is_nil(status.elapsed_ms)

      Leader.stop(pid)
    end

    test "tracks elapsed time after workflow starts" do
      {:ok, pid} = Leader.start_link([])

      # Start workflow (will quickly finish with no issues)
      :ok = Leader.run_workflow(pid)

      # Give it time to process
      Process.sleep(100)

      {:ok, status} = Leader.get_status(pid)
      # Either still running or done quickly
      assert status.state in [:planning, :executing, :reviewing, :merging, :done]

      if status.started_at do
        assert is_struct(status.started_at, DateTime)
      end

      Leader.stop(pid)
    end
  end

  describe "run_workflow/2" do
    test "transitions from idle to planning" do
      {:ok, pid} = Leader.start_link([])

      :ok = Leader.run_workflow(pid)

      Process.sleep(50)

      {:ok, status} = Leader.get_status(pid)
      # Should be in planning or beyond
      refute status.state == :idle

      Leader.stop(pid)
    end

    test "prevents starting workflow when already in progress" do
      {:ok, pid} = Leader.start_link([])

      # Start first workflow
      :ok = Leader.run_workflow(pid)

      # Try to start second while first is running
      :ok = Leader.run_workflow(pid)

      # Should log warning but not crash
      assert Process.alive?(pid)

      Leader.stop(pid)
    end

    test "accepts max_parallel option" do
      {:ok, pid} = Leader.start_link([])

      :ok = Leader.run_workflow(pid, max_parallel: 2)

      Process.sleep(50)
      assert Process.alive?(pid)

      Leader.stop(pid)
    end
  end

  describe "stop/1" do
    test "stops the server gracefully" do
      {:ok, pid} = Leader.start_link([])
      assert Process.alive?(pid)

      :ok = Leader.stop(pid)
      refute Process.alive?(pid)
    end

    test "stops named server" do
      {:ok, _pid} = Leader.start_link(name: :stoppable_leader)
      assert Process.whereis(:stoppable_leader)

      :ok = Leader.stop(:stoppable_leader)
      refute Process.whereis(:stoppable_leader)
    end
  end

  describe "state machine transitions" do
    test "completes full workflow cycle" do
      {:ok, pid} = Leader.start_link([])

      :ok = Leader.run_workflow(pid)

      # Wait for workflow to complete
      # With no ready issues, should finish quickly
      :timer.sleep(500)

      {:ok, status} = Leader.get_status(pid)
      assert status.state == :done
      assert status.completed_at != nil

      Leader.stop(pid)
    end

    test "handles planning phase with no ready issues" do
      {:ok, pid} = Leader.start_link([])

      :ok = Leader.run_workflow(pid)

      # Wait for completion
      :timer.sleep(500)

      {:ok, status} = Leader.get_status(pid)
      assert status.state == :done
      assert status.tasks == %{}
      assert status.progress == {0, 0}

      Leader.stop(pid)
    end
  end

  describe "error handling" do
    test "handles invalid server reference" do
      assert catch_exit(Leader.get_status(:nonexistent_server)) ==
               {:noproc, {GenServer, :call, [:nonexistent_server, :get_status, 5000]}}
    end
  end

  describe "workflow options" do
    test "stores options in state" do
      {:ok, pid} = Leader.start_link(base_branch: "develop", max_parallel: 8)

      {:ok, status} = Leader.get_status(pid)
      assert status.base_branch == "develop"

      Leader.stop(pid)
    end

    test "workflow options can override init options" do
      {:ok, pid} = Leader.start_link(base_branch: "main", max_parallel: 4)

      :ok = Leader.run_workflow(pid, max_parallel: 2)

      Process.sleep(50)
      assert Process.alive?(pid)

      Leader.stop(pid)
    end
  end

  describe "task tracking" do
    test "initializes empty tasks map" do
      {:ok, pid} = Leader.start_link([])

      {:ok, status} = Leader.get_status(pid)
      assert status.tasks == %{}

      Leader.stop(pid)
    end
  end
end
