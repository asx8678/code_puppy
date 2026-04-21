defmodule CodePuppyControl.ApplicationWiringTest do
  @moduledoc """
  Direct runtime coverage for application supervision wiring.

  Verifies that key processes (WorkflowState, SlashCommands.Registry)
  are startable and reachable in application context.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.WorkflowState
  alias CodePuppyControl.CLI.SlashCommands.Registry

  describe "WorkflowState supervision wiring" do
    test "WorkflowState can be started under a supervisor" do
      # Simulate the Application child_spec entry
      case start_supervised({WorkflowState, name: WorkflowState}) do
        {:ok, pid} ->
          assert is_pid(pid)
          assert Process.whereis(WorkflowState) == pid

        {:error, {:already_started, pid}} ->
          # Already started by a prior test — still proves it's startable
          assert is_pid(pid)
          assert Process.whereis(WorkflowState) == pid
      end
    end

    test "WorkflowState is functional after supervised start" do
      start_supervised({WorkflowState, name: WorkflowState})
      WorkflowState.reset()

      WorkflowState.set_flag(:did_generate_code)
      assert WorkflowState.has_flag?(:did_generate_code)

      WorkflowState.reset()
      refute WorkflowState.has_flag?(:did_generate_code)
    end
  end

  describe "SlashCommands.Registry + builtin wiring" do
    setup do
      case Process.whereis(Registry) do
        nil -> start_supervised!({Registry, []})
        _pid -> :ok
      end

      Registry.clear()
      :ok
    end

    test "register_builtin_commands/0 makes /flags dispatchable" do
      :ok = Registry.register_builtin_commands()

      assert {:ok, cmd} = Registry.get("flags")
      assert cmd.name == "flags"
    end

    test "/flags handler is invocable after registration" do
      # Start WorkflowState for the handler
      case Process.whereis(WorkflowState) do
        nil -> start_supervised!({WorkflowState, name: WorkflowState})
        _pid -> :ok
      end

      WorkflowState.reset()
      :ok = Registry.register_builtin_commands()

      {:ok, cmd} = Registry.get("flags")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = cmd.handler.("/flags", %{})
        end)

      assert output =~ "Workflow State"
    end
  end
end
