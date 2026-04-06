defmodule Mana.Scheduler.StoreTest do
  use ExUnit.Case, async: false

  alias Mana.Scheduler.{Job, Store}

  # Use a temp dir to avoid polluting real config
  setup do
    # Store the original env
    _original_home = System.get_env("HOME")
    tmp_dir = Path.join(System.tmp_dir!(), "mana_scheduler_test_#{:rand.uniform(1_000_000)}")
    File.mkdir_p!(tmp_dir)

    # Override for Mana.Config.Paths
    System.put_env("XDG_DATA_HOME", Path.join([tmp_dir, ".local", "share"]))

    on_exit(fn ->
      System.put_env("XDG_DATA_HOME", "")
      File.rm_rf!(tmp_dir)
    end)

    {:ok, tmp_dir: tmp_dir}
  end

  describe "list/0" do
    test "returns empty list when no jobs file exists" do
      assert {:ok, []} = Store.list()
    end
  end

  describe "put/1 and get/1" do
    test "stores and retrieves a job" do
      job = Job.new(name: "test-job", schedule: "1h", agent: "code-puppy", prompt: "Hello")

      assert {:ok, stored} = Store.put(job)
      assert stored.id != nil
      assert stored.name == "test-job"

      assert {:ok, retrieved} = Store.get(stored.id)
      assert retrieved.name == "test-job"
      assert retrieved.schedule == "1h"
      assert retrieved.agent == "code-puppy"
      assert retrieved.prompt == "Hello"
    end

    test "generates ID when none provided" do
      job = %Job{name: "no-id", schedule: "30m", agent: "bot", prompt: "test"}
      assert {:ok, stored} = Store.put(job)
      assert stored.id != nil
      assert String.length(stored.id) == 8
    end

    test "updates existing job with same ID" do
      job = Job.new(name: "update-test", schedule: "1h", agent: "bot", prompt: "v1")
      {:ok, stored} = Store.put(job)

      updated = %{stored | prompt: "v2", schedule: "30m"}
      {:ok, _stored2} = Store.put(updated)

      assert {:ok, retrieved} = Store.get(stored.id)
      assert retrieved.prompt == "v2"
      assert retrieved.schedule == "30m"

      # Only one job stored
      {:ok, all} = Store.list()
      assert length(all) == 1
    end
  end

  describe "delete/1" do
    test "deletes an existing job" do
      job = Job.new(name: "to-delete", schedule: "1h", agent: "bot", prompt: "bye")
      {:ok, stored} = Store.put(job)

      assert :ok = Store.delete(stored.id)
      assert {:error, :not_found} = Store.get(stored.id)
    end

    test "returns not_found for unknown ID" do
      assert {:error, :not_found} = Store.delete("nonexistent")
    end
  end

  describe "round-trip persistence" do
    test "DateTime fields survive JSON serialization" do
      now = ~U[2024-06-15 09:30:00Z]

      job = Job.new(name: "round-trip", schedule: "1h", agent: "bot", prompt: "test")
      job = %{job | last_run: now, last_status: :success, last_exit_code: 0}

      {:ok, stored} = Store.put(job)
      {:ok, retrieved} = Store.get(stored.id)

      assert retrieved.last_run == now
      assert retrieved.last_status == :success
      assert retrieved.last_exit_code == 0
    end

    test "multiple jobs persist and list correctly" do
      j1 = Job.new(name: "job1", schedule: "30m", agent: "a", prompt: "p1")
      j2 = Job.new(name: "job2", schedule: "1h", agent: "b", prompt: "p2")

      {:ok, s1} = Store.put(j1)
      {:ok, s2} = Store.put(j2)

      {:ok, all} = Store.list()
      assert length(all) == 2

      ids = Enum.map(all, & &1.id) |> Enum.sort()
      assert ids == [s1.id, s2.id] |> Enum.sort()
    end
  end
end
