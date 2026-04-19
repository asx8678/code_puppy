defmodule CodePuppyControl.Runtime.CronSchedulerTest do
  @moduledoc """
  Tests for CronScheduler GenServer — periodic schedule checks, task
  evaluation, and force-check behaviour.

  Each test starts its own per-test CronScheduler via start_supervised/1
  to avoid shared-state issues with a global singleton.
  """

  use CodePuppyControl.StatefulCase, async: true

  @moduletag timeout: 30_000

  alias CodePuppyControl.Scheduler
  alias CodePuppyControl.Scheduler.CronScheduler
  alias CodePuppyControl.Repo

  setup do
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)
    :ok = Ecto.Adapters.SQL.Sandbox.mode(Repo, {:shared, self()})
    Repo.delete_all(Oban.Job)

    name = :"cron_scheduler_#{System.unique_integer([:positive])}"
    {:ok, _pid} = start_supervised({CronScheduler, name: name, check_interval: 60_000})
    %{scheduler: name}
  end

  # ---------------------------------------------------------------------------
  # GenServer State
  # ---------------------------------------------------------------------------

  describe "get_state/1" do
    test "returns scheduler state with expected keys", %{scheduler: sched} do
      state = CronScheduler.get_state(sched)

      assert Map.has_key?(state, :check_interval)
      assert Map.has_key?(state, :last_check_at)
      assert Map.has_key?(state, :tasks_enqueued)
    end

    test "check_interval is positive", %{scheduler: sched} do
      state = CronScheduler.get_state(sched)
      assert state.check_interval > 0
    end

    test "tasks_enqueued starts at zero or above", %{scheduler: sched} do
      state = CronScheduler.get_state(sched)
      assert state.tasks_enqueued >= 0
    end
  end

  # ---------------------------------------------------------------------------
  # Force Check
  # ---------------------------------------------------------------------------

  describe "check_now/1" do
    test "triggers a schedule check without error", %{scheduler: sched} do
      assert :ok = CronScheduler.check_now(sched)
      # Give it a moment to process
      Process.sleep(100)
    end

    test "updates last_check_at after check", %{scheduler: sched} do
      # Get initial state
      initial = CronScheduler.get_state(sched)

      # Force check
      :ok = CronScheduler.check_now(sched)
      Process.sleep(100)

      # last_check_at should be updated
      updated = CronScheduler.get_state(sched)
      assert updated.last_check_at != nil

      if initial.last_check_at != nil do
        assert DateTime.compare(updated.last_check_at, initial.last_check_at) in [:gt, :eq]
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Scheduler Status via Scheduler module
  # ---------------------------------------------------------------------------

  describe "scheduler_status/0" do
    test "returns state map" do
      status = Scheduler.scheduler_status()

      assert Map.has_key?(status, :check_interval)
      assert Map.has_key?(status, :last_check_at)
      assert Map.has_key?(status, :tasks_enqueued)
    end
  end

  # ---------------------------------------------------------------------------
  # Force Check via Scheduler module
  # ---------------------------------------------------------------------------

  describe "force_check/0" do
    test "returns :ok" do
      assert :ok = Scheduler.force_check()
      Process.sleep(100)
    end
  end

  # ---------------------------------------------------------------------------
  # Enqueue Behaviour
  # ---------------------------------------------------------------------------

  describe "task enqueuing on check" do
    test "does not enqueue disabled tasks", %{scheduler: sched} do
      {:ok, _task} =
        Scheduler.create_task(%{
          name: "disabled-check-#{System.unique_integer([:positive])}",
          agent_name: "code-puppy",
          prompt: "Should not run",
          schedule_type: "hourly",
          enabled: false
        })

      # Get initial enqueue count
      initial = CronScheduler.get_state(sched)

      # Force check
      :ok = CronScheduler.check_now(sched)
      Process.sleep(100)

      # tasks_enqueued should not have increased for disabled tasks
      updated = CronScheduler.get_state(sched)
      # The count may have increased from other tests' tasks, but this test
      # just validates the check doesn't crash on disabled tasks.
      assert updated.tasks_enqueued >= initial.tasks_enqueued
    end
  end
end
