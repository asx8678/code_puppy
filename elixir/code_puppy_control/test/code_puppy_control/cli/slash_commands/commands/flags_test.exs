defmodule CodePuppyControl.CLI.SlashCommands.Commands.FlagsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.Flags
  alias CodePuppyControl.WorkflowState

  # async: false because Registry and WorkflowState are named singletons.

  setup do
    # Start the Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    Registry.clear()

    # Start WorkflowState agent if not already running
    case Process.whereis(WorkflowState) do
      nil -> start_supervised!({WorkflowState, name: WorkflowState})
      _pid -> :ok
    end

    WorkflowState.reset()

    # Register /flags command
    :ok =
      Registry.register(
        CommandInfo.new(
          name: "flags",
          description: "Show current workflow flags and state",
          handler: &Flags.handle_flags/2,
          usage: "/flags [reset|set <flag>|clear <flag>]",
          category: "config"
        )
      )

    state = %{session_id: "test-session", running: true}
    {:ok, state: state}
  end

  describe "/flags (no args)" do
    test "shows workflow state header" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      assert output =~ "Workflow State"
    end

    test "shows all known flags" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      # Should show some flag names
      assert output =~ "did_generate_code"
      assert output =~ "did_execute_shell"
      assert output =~ "did_run_tests"
    end

    test "shows active count" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      assert output =~ "Active flags:"
    end

    test "shows active flag with check mark" do
      WorkflowState.set_flag(:did_generate_code)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      assert output =~ "✓"
    end

    test "shows inactive flag with circle" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      assert output =~ "○"
    end

    test "shows metadata when present" do
      WorkflowState.put_metadata("agent_name", "test-agent")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      assert output =~ "Metadata:"
      assert output =~ "agent_name: test-agent"
    end

    test "hides metadata section when empty" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags", %{})
        end)

      refute output =~ "Metadata:"
    end

    test "returns continue" do
      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, %{}} = Flags.handle_flags("/flags", %{})
      end)
    end
  end

  describe "/flags reset" do
    test "resets workflow state" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.put_metadata("key", "val")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags reset", %{})
        end)

      assert output =~ "Workflow state reset"
      refute WorkflowState.has_flag?(:did_generate_code)
      assert WorkflowState.metadata() == %{}
    end

    test "resets case-insensitively" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags RESET", %{})
        end)

      assert output =~ "Workflow state reset"
    end
  end

  describe "/flags set <flag>" do
    test "sets a known flag" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags set did_generate_code", %{})
        end)

      assert output =~ "Flag did_generate_code set"
      assert WorkflowState.has_flag?(:did_generate_code)
    end

    test "sets flag case-insensitively" do
      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags set DID_GENERATE_CODE", %{})
        end)

      assert WorkflowState.has_flag?(:did_generate_code)
      assert WorkflowState.has_flag?(:did_generate_code)
    end

    test "handles mixed case" do
      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags set Did_Run_Tests", %{})
        end)

      assert WorkflowState.has_flag?(:did_run_tests)
    end

    test "warns on unknown flag" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags set nonexistent_flag", %{})
        end)

      assert output =~ "Unknown flag"
      refute WorkflowState.has_flag?(:nonexistent_flag)
    end
  end

  describe "/flags clear <flag>" do
    test "clears a previously set flag" do
      WorkflowState.set_flag(:did_generate_code)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags clear did_generate_code", %{})
        end)

      assert output =~ "Flag did_generate_code cleared"
      refute WorkflowState.has_flag?(:did_generate_code)
    end

    test "clears flag case-insensitively" do
      WorkflowState.set_flag(:did_run_tests)

      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags clear DID_RUN_TESTS", %{})
        end)

      refute WorkflowState.has_flag?(:did_run_tests)
    end

    test "warns on unknown flag" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags clear nonexistent_flag", %{})
        end)

      assert output =~ "Unknown flag"
    end
  end

  describe "invalid usage" do
    test "shows usage for unknown subcommand" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags bogus", %{})
        end)

      assert output =~ "Usage:"
    end

    test "shows usage for set without flag name" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags set", %{})
        end)

      assert output =~ "Usage:"
    end

    test "shows usage for clear without flag name" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = Flags.handle_flags("/flags clear", %{})
        end)

      assert output =~ "Usage:"
    end

    test "returns continue even on invalid usage" do
      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, %{}} = Flags.handle_flags("/flags bogus", %{})
      end)
    end
  end

  describe "registration and dispatch" do
    test "/flags is registered and dispatchable" do
      assert {:ok, _} = Registry.get("flags")
    end

    test "/flags dispatches via Dispatcher" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:ok, {:continue, _}} = Dispatcher.dispatch("/flags", %{})
        end)

      assert output =~ "Workflow State"
    end

    test "/flags appears in all_names for tab completion" do
      names = Registry.all_names()
      assert "flags" in names
    end

    test "/flags appears in list_all" do
      commands = Registry.list_all()
      assert Enum.any?(commands, &(&1.name == "flags"))
    end

    test "/flags is in config category" do
      commands = Registry.list_by_category("config")
      flags_cmd = Enum.find(commands, &(&1.name == "flags"))
      assert flags_cmd != nil
      assert flags_cmd.category == "config"
    end

    test "/flags usage is correct" do
      {:ok, cmd} = Registry.get("flags")
      assert cmd.usage == "/flags [reset|set <flag>|clear <flag>]"
    end
  end
end
