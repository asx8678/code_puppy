defmodule CodePuppyControl.Runtime.RunManagerTest do
  @moduledoc """
  Tests for Run.Manager — run lifecycle coordination.

  These tests focus on the Manager's API contract. Since start_run requires
  a Python worker, we test the error paths and state-query paths directly.
  Full lifecycle is covered in integration tests.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.Run.{Manager, State, Supervisor}

  # ---------------------------------------------------------------------------
  # Run.State (unit-level)
  # ---------------------------------------------------------------------------

  describe "Run.State safe_status_atom/1" do
    alias CodePuppyControl.Run.State

    test "converts valid string statuses" do
      assert State.safe_status_atom("starting") == :starting
      assert State.safe_status_atom("running") == :running
      assert State.safe_status_atom("completed") == :completed
      assert State.safe_status_atom("failed") == :failed
      assert State.safe_status_atom("cancelled") == :cancelled
      assert State.safe_status_atom("paused") == :paused
      assert State.safe_status_atom("pending") == :pending
    end

    test "returns :unknown for invalid string" do
      assert State.safe_status_atom("exploding") == :unknown
      assert State.safe_status_atom("") == :unknown
    end

    test "passes through valid atoms" do
      assert State.safe_status_atom(:running) == :running
      assert State.safe_status_atom(:completed) == :completed
    end

    test "returns :unknown for invalid atoms" do
      assert State.safe_status_atom(:exploding) == :unknown
    end

    test "handles non-string, non-atom input" do
      assert State.safe_status_atom(123) == :unknown
      assert State.safe_status_atom(nil) == :unknown
    end
  end

  # ---------------------------------------------------------------------------
  # Run.Supervisor
  # ---------------------------------------------------------------------------

  describe "Run.Supervisor.run_count/0" do
    test "returns a non-negative integer" do
      count = Supervisor.run_count()
      assert is_integer(count) and count >= 0
    end
  end

  describe "Run.Supervisor.terminate_run/1" do
    test "returns not_found for nonexistent run" do
      assert {:error, :not_found} = Supervisor.terminate_run("nonexistent-run-99999")
    end
  end

  # ---------------------------------------------------------------------------
  # Manager — error paths
  # ---------------------------------------------------------------------------

  describe "Manager.get_run/1" do
    test "returns not_found for nonexistent run" do
      assert {:error, :not_found} = Manager.get_run("nonexistent-run-99999")
    end
  end

  describe "Manager.cancel_run/2" do
    test "returns not_found for nonexistent run" do
      assert {:error, :not_found} = Manager.cancel_run("nonexistent-run-99999")
    end
  end

  describe "Manager.list_runs/1" do
    test "returns a list" do
      result = Manager.list_runs()
      assert is_list(result)
    end
  end

  describe "Manager.list_runs_with_details/1" do
    test "returns a list" do
      result = Manager.list_runs_with_details()
      assert is_list(result)
    end
  end

  describe "Manager.delete_run/1" do
    test "returns not_found for nonexistent run" do
      assert {:error, :not_found} = Manager.delete_run("nonexistent-run-99999")
    end
  end
end
