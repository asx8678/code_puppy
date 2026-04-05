defmodule Mana.Commands.SchedulerTest do
  @moduledoc """
  Tests for Mana.Commands.Scheduler module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Scheduler
  alias Mana.Scheduler.{Job, Store}

  setup do
    # Start Config.Store for dependencies
    start_supervised!({Mana.Config.Store, []})

    # Point scheduler at a temp directory
    tmp_dir = Path.join(System.tmp_dir!(), "mana_scheduler_test_#{:erlang.unique_integer([:positive])}")
    File.mkdir_p!(tmp_dir)

    original_dir = Application.get_env(:mana, :data_dir)
    Application.put_env(:mana, :data_dir, tmp_dir)

    on_exit(fn ->
      Application.put_env(:mana, :data_dir, original_dir)
      File.rm_rf!(tmp_dir)
    end)

    {:ok, tmp_dir: tmp_dir}
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded(Scheduler)

      assert function_exported?(Scheduler, :name, 0)
      assert function_exported?(Scheduler, :description, 0)
      assert function_exported?(Scheduler, :usage, 0)
      assert function_exported?(Scheduler, :execute, 2)
    end

    test "name returns '/scheduler'" do
      assert Scheduler.name() == "/scheduler"
    end

    test "description is a non-empty string" do
      assert is_binary(Scheduler.description())
      assert String.length(Scheduler.description()) > 0
    end

    test "usage mentions subcommands" do
      usage = Scheduler.usage()
      assert usage =~ "list"
      assert usage =~ "create"
      assert usage =~ "delete"
    end
  end

  describe "execute/2 — list" do
    test "shows message when no jobs exist" do
      assert {:ok, text} = Scheduler.execute([], %{})
      assert text =~ "No scheduled jobs" or text =~ "scheduled jobs" or text =~ "Name"
    end

    test "list subcommand same as no args" do
      assert {:ok, _} = Scheduler.execute(["list"], %{})
    end
  end

  describe "execute/2 — create" do
    test "creates a new job" do
      name = "test-job-#{:erlang.unique_integer([:positive])}"
      args = [name, ~s(--schedule="*/5 * * * *"), ~s(--agent="code-puppy"), ~s(--prompt="Hello")]

      assert {:ok, text} = Scheduler.execute(["create" | args], %{})
      assert text =~ "Created job"
      assert text =~ name
    end

    test "rejects duplicate job name" do
      name = "dup-job-#{:erlang.unique_integer([:positive])}"
      args = [name, ~s(--schedule="*/5 * * * *"), ~s(--agent="code-puppy"), ~s(--prompt="Hello")]
      Scheduler.execute(["create" | args], %{})

      assert {:error, msg} = Scheduler.execute(["create" | args], %{})
      assert msg =~ "already exists"
    end

    test "requires a name" do
      assert {:error, msg} = Scheduler.execute(["create"], %{})
      assert msg =~ "Usage" or msg =~ "name"
    end

    test "requires schedule option" do
      name = "sched-opt-#{:erlang.unique_integer([:positive])}"
      assert {:error, msg} = Scheduler.execute(["create", name, ~s(--agent="a"), ~s(--prompt="p")], %{})
      assert msg =~ "schedule"
    end

    test "requires agent option" do
      name = "agent-opt-#{:erlang.unique_integer([:positive])}"
      assert {:error, msg} = Scheduler.execute(["create", name, ~s(--schedule="* * * * *"), ~s(--prompt="p")], %{})
      assert msg =~ "agent"
    end

    test "requires prompt option" do
      name = "prompt-opt-#{:erlang.unique_integer([:positive])}"

      assert {:error, msg} =
               Scheduler.execute(["create", name, ~s(--schedule="* * * * *"), ~s(--agent="a")], %{})

      assert msg =~ "prompt"
    end
  end

  describe "execute/2 — delete" do
    test "deletes an existing job" do
      name = "del-job-#{:erlang.unique_integer([:positive])}"
      create_job!(name)

      assert {:ok, text} = Scheduler.execute(["delete", name], %{})
      assert text =~ "Deleted"
      assert text =~ name
    end

    test "returns error for nonexistent job" do
      assert {:error, msg} = Scheduler.execute(["delete", "no-such-job"], %{})
      assert msg =~ "not found"
    end
  end

  describe "execute/2 — toggle" do
    test "toggles a job from enabled to disabled" do
      name = "toggle-job-#{:erlang.unique_integer([:positive])}"
      create_job!(name)

      assert {:ok, text} = Scheduler.execute(["toggle", name], %{})
      assert text =~ "disabled" or text =~ "enabled"
    end

    test "returns error for nonexistent job" do
      assert {:error, msg} = Scheduler.execute(["toggle", "no-such-job"], %{})
      assert msg =~ "not found"
    end
  end

  describe "execute/2 — run" do
    test "manually triggers a job" do
      name = "manual-job-#{:erlang.unique_integer([:positive])}"
      create_job!(name)

      assert {:ok, text} = Scheduler.execute(["run", name], %{})
      assert text =~ "triggered" or text =~ "Manually"
      assert text =~ name
    end

    test "returns error for nonexistent job" do
      assert {:error, msg} = Scheduler.execute(["run", "no-such-job"], %{})
      assert msg =~ "not found"
    end
  end

  describe "execute/2 — unknown subcommand" do
    test "returns error for unknown subcommand" do
      assert {:error, msg} = Scheduler.execute(["explode"], %{})
      assert msg =~ "Usage"
    end
  end

  # ---------------------------------------------------------------------------
  # Test helpers
  # ---------------------------------------------------------------------------

  defp create_job!(name) do
    job =
      Job.new(%{
        name: name,
        schedule: "*/5 * * * *",
        agent: "test-agent",
        prompt: "test prompt"
      })

    {:ok, _} = Store.put(job)
    job
  end
end
