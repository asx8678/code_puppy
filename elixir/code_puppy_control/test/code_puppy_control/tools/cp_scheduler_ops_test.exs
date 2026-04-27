defmodule CodePuppyControl.Tools.CpSchedulerOpsTest do
  @moduledoc """
  Tests for the CpSchedulerOps Tool-behaviour wrappers.

  Boundary and invariant tests for the Phase E port of scheduler_tools.py.
  Verifies:
  - Each cp_ wrapper has the correct name and description
  - Parameters match the Python tool signatures
  - Invoke delegates correctly to SchedulerTools
  - Agent alias mapping (Python `agent` → Elixir `agent_name`)
  - Error cases return formatted strings
  """

  use CodePuppyControl.StatefulCase

  alias CodePuppyControl.Tools.CpSchedulerOps
  alias CodePuppyControl.Scheduler
  alias CodePuppyControl.Repo

  setup do
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)
    :ok = Ecto.Adapters.SQL.Sandbox.mode(Repo, {:shared, self()})
    Repo.delete_all(Oban.Job)
    :ok
  end

  # ── Name and Description ──────────────────────────────────────────────

  describe "tool names" do
    test "CpSchedulerListTasks name" do
      assert CpSchedulerOps.CpSchedulerListTasks.name() == :cp_scheduler_list_tasks
    end

    test "CpSchedulerCreateTask name" do
      assert CpSchedulerOps.CpSchedulerCreateTask.name() == :cp_scheduler_create_task
    end

    test "CpSchedulerDeleteTask name" do
      assert CpSchedulerOps.CpSchedulerDeleteTask.name() == :cp_scheduler_delete_task
    end

    test "CpSchedulerToggleTask name" do
      assert CpSchedulerOps.CpSchedulerToggleTask.name() == :cp_scheduler_toggle_task
    end

    test "CpSchedulerStatus name" do
      assert CpSchedulerOps.CpSchedulerStatus.name() == :cp_scheduler_status
    end

    test "CpSchedulerRunTask name" do
      assert CpSchedulerOps.CpSchedulerRunTask.name() == :cp_scheduler_run_task
    end

    test "CpSchedulerViewLog name" do
      assert CpSchedulerOps.CpSchedulerViewLog.name() == :cp_scheduler_view_log
    end

    test "CpSchedulerForceCheck name" do
      assert CpSchedulerOps.CpSchedulerForceCheck.name() == :cp_scheduler_force_check
    end
  end

  describe "descriptions" do
    test "all tools have non-empty descriptions" do
      tools = [
        CpSchedulerOps.CpSchedulerListTasks,
        CpSchedulerOps.CpSchedulerCreateTask,
        CpSchedulerOps.CpSchedulerDeleteTask,
        CpSchedulerOps.CpSchedulerToggleTask,
        CpSchedulerOps.CpSchedulerStatus,
        CpSchedulerOps.CpSchedulerRunTask,
        CpSchedulerOps.CpSchedulerViewLog,
        CpSchedulerOps.CpSchedulerForceCheck
      ]

      for tool <- tools do
        desc = tool.description()
        assert is_binary(desc) and desc != "", "Tool #{inspect(tool)} has empty description"
      end
    end
  end

  # ── Parameter Schema ──────────────────────────────────────────────────

  describe "parameters" do
    test "CpSchedulerCreateTask has required name and prompt" do
      params = CpSchedulerOps.CpSchedulerCreateTask.parameters()
      assert params["type"] == "object"
      assert "name" in params["required"]
      assert "prompt" in params["required"]
      assert Map.has_key?(params["properties"], "agent")
      assert Map.has_key?(params["properties"], "model")
      assert Map.has_key?(params["properties"], "schedule_type")
      assert Map.has_key?(params["properties"], "schedule_value")
      assert Map.has_key?(params["properties"], "working_directory")
    end

    test "CpSchedulerDeleteTask requires task_id" do
      params = CpSchedulerOps.CpSchedulerDeleteTask.parameters()
      assert "task_id" in params["required"]
    end

    test "CpSchedulerToggleTask requires task_id" do
      params = CpSchedulerOps.CpSchedulerToggleTask.parameters()
      assert "task_id" in params["required"]
    end

    test "CpSchedulerRunTask requires task_id" do
      params = CpSchedulerOps.CpSchedulerRunTask.parameters()
      assert "task_id" in params["required"]
    end

    test "CpSchedulerViewLog requires task_id" do
      params = CpSchedulerOps.CpSchedulerViewLog.parameters()
      assert "task_id" in params["required"]
      assert Map.has_key?(params["properties"], "lines")
    end

    test "CpSchedulerListTasks takes no required params" do
      params = CpSchedulerOps.CpSchedulerListTasks.parameters()
      assert params["required"] == []
    end

    test "CpSchedulerStatus takes no required params" do
      params = CpSchedulerOps.CpSchedulerStatus.parameters()
      assert params["required"] == []
    end

    test "CpSchedulerForceCheck takes no required params" do
      params = CpSchedulerOps.CpSchedulerForceCheck.parameters()
      assert params["required"] == []
    end
  end

  # ── Invoke Delegation ─────────────────────────────────────────────────

  describe "invoke delegation" do
    test "CpSchedulerListTasks delegates to SchedulerTools.list_tasks" do
      {:ok, result} = CpSchedulerOps.CpSchedulerListTasks.invoke(%{}, %{})
      assert Map.has_key?(result, :output)
      assert result.output =~ "Scheduler Status"
    end

    test "CpSchedulerCreateTask creates task and returns output" do
      attrs = %{
        "name" => "cp-test-task",
        "prompt" => "Test prompt for cp wrapper",
        "agent" => "code-puppy",
        "schedule_type" => "hourly"
      }

      {:ok, result} = CpSchedulerOps.CpSchedulerCreateTask.invoke(attrs, %{})
      assert Map.has_key?(result, :output)
      assert result.output =~ "Task Created Successfully"
      assert result.output =~ "cp-test-task"
    end

    test "CpSchedulerCreateTask maps 'agent' to 'agent_name' (Python compat)" do
      attrs = %{
        "name" => "agent-compat-task",
        "prompt" => "Test agent compat",
        "agent" => "security-auditor"
      }

      {:ok, result} = CpSchedulerOps.CpSchedulerCreateTask.invoke(attrs, %{})
      assert result.output =~ "security-auditor"
    end

    test "CpSchedulerDeleteTask returns not found for missing task" do
      {:ok, result} = CpSchedulerOps.CpSchedulerDeleteTask.invoke(%{"task_id" => "-999"}, %{})
      assert result.output =~ "Task not found"
    end

    test "CpSchedulerToggleTask returns not found for missing task" do
      {:ok, result} = CpSchedulerOps.CpSchedulerToggleTask.invoke(%{"task_id" => "nonexistent"}, %{})
      assert result.output =~ "Task not found"
    end

    test "CpSchedulerStatus returns running status" do
      {:ok, result} = CpSchedulerOps.CpSchedulerStatus.invoke(%{}, %{})
      assert Map.has_key?(result, :output)
      assert result.output =~ "Scheduler"
    end

    test "CpSchedulerRunTask returns not found for missing task" do
      {:ok, result} = CpSchedulerOps.CpSchedulerRunTask.invoke(%{"task_id" => "-999"}, %{})
      assert result.output =~ "Task not found"
    end

    test "CpSchedulerViewLog returns not found for missing task" do
      {:ok, result} = CpSchedulerOps.CpSchedulerViewLog.invoke(%{"task_id" => "-999"}, %{})
      assert result.output =~ "Task not found"
    end

    test "CpSchedulerForceCheck triggers check" do
      {:ok, result} = CpSchedulerOps.CpSchedulerForceCheck.invoke(%{}, %{})
      assert Map.has_key?(result, :output)
      assert result.output =~ "Schedule check triggered"
    end
  end

  # ── Full workflow ─────────────────────────────────────────────────────

  describe "full scheduler workflow via cp_ wrappers" do
    test "create → list → toggle → delete" do
      # Create
      {:ok, create_result} =
        CpSchedulerOps.CpSchedulerCreateTask.invoke(
          %{"name" => "workflow-test", "prompt" => "Workflow test", "agent" => "code-puppy"},
          %{}
        )

      assert create_result.output =~ "Task Created Successfully"

      # List (should include the new task)
      {:ok, list_result} = CpSchedulerOps.CpSchedulerListTasks.invoke(%{}, %{})
      assert list_result.output =~ "workflow-test"

      # Toggle (disable it)
      {:ok, toggle_result} =
        CpSchedulerOps.CpSchedulerToggleTask.invoke(%{"task_id" => "workflow-test"}, %{})

      # Toggle can enable or disable; just verify it works
      assert toggle_result.output =~ "workflow-test"

      # Delete by name
      {:ok, delete_result} =
        CpSchedulerOps.CpSchedulerDeleteTask.invoke(%{"task_id" => "workflow-test"}, %{})

      assert delete_result.output =~ "Deleted task"
    end
  end

  # ── Output shape invariant ────────────────────────────────────────────

  describe "output shape invariant" do
    test "all cp_ scheduler tools return {:ok, %{output: string}}" do
      # Tools that take no args
      for tool <- [
            CpSchedulerOps.CpSchedulerListTasks,
            CpSchedulerOps.CpSchedulerStatus,
            CpSchedulerOps.CpSchedulerForceCheck
          ] do
        result = tool.invoke(%{}, %{})
        assert {:ok, %{output: output}} = result
        assert is_binary(output)
      end
    end
  end
end
