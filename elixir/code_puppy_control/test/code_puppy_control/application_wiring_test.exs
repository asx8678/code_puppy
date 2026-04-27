defmodule CodePuppyControl.ApplicationWiringTest do
  @moduledoc """
  Direct runtime coverage for application supervision wiring.

  Verifies that key processes (WorkflowState, SlashCommands.Registry,
  Callbacks.Registry) are startable and reachable in application context.
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

  describe "Callbacks.Registry supervision wiring (regression code_puppy-mmk.6)" do
    # Regression: Callbacks.Registry was not added to the application supervision
    # tree, so callbacks could not be triggered without manually starting the
    # registry. This test verifies that under normal app supervision (without
    # manual start), callback checks work.

    test "Callbacks.Registry is supervised and callback registration works" do
      # The registry should already be started by the application supervisor
      pid = Process.whereis(CodePuppyControl.Callbacks.Registry)
      assert pid != nil, "Callbacks.Registry should be supervised by the application"
      assert is_pid(pid)

      # Verify we can register and trigger without any manual start
      test_cb = fn -> :test_result end
      CodePuppyControl.Callbacks.register(:startup, test_cb)

      try do
        result = CodePuppyControl.Callbacks.trigger(:startup)
        assert result == :test_result
      after
        CodePuppyControl.Callbacks.unregister(:startup, test_cb)
      end
    end

    test "security callback check works without manual registry start" do
      # This specifically exercises the code path where Security.check/2
      # triggers the run_shell_command callback via the supervised registry.
      # If the registry is not supervised, this would crash.
      result =
        CodePuppyControl.Tools.CommandRunner.Security.check("echo supervision_test")

      # Must return a proper map (not crash)
      assert is_map(result)
      assert Map.has_key?(result, :allowed)
    end
  end
end
