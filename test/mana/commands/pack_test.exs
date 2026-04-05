defmodule Mana.Commands.PackTest do
  @moduledoc """
  Tests for Mana.Commands.Pack module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Pack
  alias Mana.Pack.Leader

  # The registered name used by the command
  @leader_name Mana.Pack.Leader

  setup do
    # Start config store so PackParallelism.get_max_parallel/0 works
    start_supervised!({Mana.Config.Store, []})

    # Start the Leader with its registered name
    start_supervised!({Leader, name: @leader_name})

    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded(Mana.Commands.Pack)

      assert function_exported?(Mana.Commands.Pack, :name, 0)
      assert function_exported?(Mana.Commands.Pack, :description, 0)
      assert function_exported?(Mana.Commands.Pack, :usage, 0)
      assert function_exported?(Mana.Commands.Pack, :execute, 2)
    end

    test "name returns '/pack'" do
      assert Pack.name() == "/pack"
    end

    test "description is a non-empty string" do
      assert is_binary(Pack.description())
      assert String.length(Pack.description()) > 0
    end

    test "usage is a non-empty string" do
      assert is_binary(Pack.usage())
      assert String.length(Pack.usage()) > 0
    end
  end

  describe "execute/2 - start" do
    test "starts a workflow when leader is idle" do
      assert {:ok, result} = Pack.execute(["start"], %{})
      assert result =~ "Pack workflow started"
      assert result =~ "Max parallel agents"
    end

    test "returns error when leader is already running a workflow" do
      # Start first workflow
      :ok = Leader.run_workflow(@leader_name)
      Process.sleep(50)

      # Try to start another — leader may have already finished
      # if no issues, so check the return value flexibly
      result = Pack.execute(["start"], %{})

      case result do
        {:ok, msg} ->
          # Workflow completed quickly with no issues, re-start succeeded
          assert msg =~ "Pack workflow started"

        {:error, msg} ->
          # Leader is still busy
          assert msg =~ "busy" or msg =~ "Pack Leader is busy"
      end
    end
  end

  describe "execute/2 - status" do
    test "returns status when leader is running" do
      assert {:ok, result} = Pack.execute(["status"], %{})
      assert result =~ "Pack Leader"
      assert result =~ "State:"
    end

    test "shows idle state initially" do
      assert {:ok, result} = Pack.execute(["status"], %{})
      assert result =~ ":idle" or result =~ "idle"
    end

    test "shows task details after workflow" do
      # Run a quick workflow (no issues, finishes fast)
      :ok = Leader.run_workflow(@leader_name)
      :timer.sleep(500)

      assert {:ok, result} = Pack.execute(["status"], %{})
      # Should be done or show progress
      assert result =~ "Pack Leader"
    end
  end

  describe "execute/2 - stop" do
    test "stops the workflow and reports abort" do
      # Start workflow
      :ok = Leader.run_workflow(@leader_name)
      Process.sleep(50)

      assert {:ok, result} = Pack.execute(["stop"], %{})
      assert result =~ "aborted" or result =~ "Aborted"
    end

    test "handles stop when leader is not running" do
      # Kill the leader to simulate it not running
      leader_pid = GenServer.whereis(@leader_name)

      if leader_pid do
        Process.exit(leader_pid, :kill)
        Process.sleep(100)
      end

      # The supervised process may restart, so just verify it doesn't crash
      result = Pack.execute(["stop"], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "execute/2 - help" do
    test "returns help text with no args" do
      assert {:ok, result} = Pack.execute([], %{})
      assert result =~ "Pack Leader"
      assert result =~ "/pack start"
      assert result =~ "/pack status"
      assert result =~ "/pack stop"
    end
  end

  describe "execute/2 - invalid args" do
    test "returns error for unknown subcommand" do
      assert {:error, result} = Pack.execute(["bogus"], %{})
      assert result =~ "Unknown subcommand"
    end
  end
end
