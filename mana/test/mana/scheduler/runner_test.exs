defmodule Mana.Scheduler.RunnerTest do
  use ExUnit.Case, async: false

  alias Mana.Scheduler.{Job, Runner, Store}

  setup do
    # Use a temp dir to avoid polluting real config
    tmp_dir = Path.join(System.tmp_dir!(), "mana_scheduler_runner_test_#{:rand.uniform(1_000_000)}")
    File.mkdir_p!(tmp_dir)
    System.put_env("XDG_DATA_HOME", Path.join([tmp_dir, ".local", "share"]))

    # Start the runner with a long tick interval (we'll use force_tick)
    {:ok, runner_pid} = Runner.start_link(tick_interval: 300_000, enabled: false)

    on_exit(fn ->
      System.put_env("XDG_DATA_HOME", "")
      if Process.alive?(runner_pid), do: GenServer.stop(runner_pid, :normal, 5_000)
      File.rm_rf!(tmp_dir)
    end)

    {:ok, runner_pid: runner_pid}
  end

  describe "start_link/1" do
    test "starts successfully", %{runner_pid: pid} do
      assert Process.alive?(pid)
    end
  end

  describe "get_state/0" do
    test "returns runner state" do
      state = Runner.get_state()
      assert Map.has_key?(state, :tick_interval)
      assert Map.has_key?(state, :enabled)
      assert Map.has_key?(state, :runs_started)
    end
  end

  describe "enable/0 and disable/0" do
    test "toggles enabled state" do
      Runner.disable()
      state = Runner.get_state()
      refute state.enabled

      Runner.enable()
      state = Runner.get_state()
      assert state.enabled
    end
  end

  describe "force_tick/0" do
    test "does not crash with no jobs" do
      Runner.force_tick()
      # Should not crash
      state = Runner.get_state()
      assert state.runs_started == 0
    end

    test "detects and fires due jobs", %{runner_pid: runner_pid} do
      # Create a job that's due (interval schedule, never run)
      job = Job.new(name: "due-job", schedule: "1h", agent: "test-agent", prompt: "Hello")
      {:ok, stored} = Store.put(job)

      # Force a tick
      Runner.force_tick()

      # Wait a bit for async operations
      Process.sleep(100)

      # Verify the job's last_run was updated
      {:ok, updated} = Store.get(stored.id)
      assert updated.last_run != nil
      # Status may be :running or :success depending on task scheduling
      assert updated.last_status in [:running, :success]

      # Verify runner state
      state = Runner.get_state()
      assert state.runs_started >= 1

      # Cleanup
      if Process.alive?(runner_pid), do: GenServer.stop(runner_pid, :normal, 5_000)
    end

    test "skips disabled jobs" do
      job = Job.new(name: "disabled-job", schedule: "1h", agent: "test-agent", prompt: "Hello")
      job = %{job | enabled: false}
      {:ok, _stored} = Store.put(job)

      Runner.force_tick()
      Process.sleep(50)

      state = Runner.get_state()
      assert state.runs_started == 0
    end
  end
end
