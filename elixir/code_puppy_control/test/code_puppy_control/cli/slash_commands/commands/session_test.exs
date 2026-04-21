defmodule CodePuppyControl.CLI.SlashCommands.Commands.SessionTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.Commands.Session
  alias CodePuppyControl.REPL.Loop

  setup do
    state = %Loop{
      agent: "code-puppy",
      model: "gpt-4",
      session_id: "test-session",
      running: true
    }

    {:ok, state: state}
  end

  describe "/compact" do
    test "prints stub warning and returns continue", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      assert output =~ "not yet implemented"
      assert output =~ "summarization"
    end

    test "stub warning is visible (uses yellow color)", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      assert output =~ IO.ANSI.yellow()
    end
  end

  describe "/truncate" do
    test "with valid number prints stub warning and returns continue", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 5", state)
        end)

      # Stub: prints not-yet-implemented warning
      assert output =~ "not yet implemented"
      assert output =~ "message history"
    end

    test "with no argument prints usage error", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate", state)
        end)

      assert output =~ "Usage"
      assert output =~ IO.ANSI.red()
    end

    test "with invalid number prints error", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate abc", state)
        end)

      assert output =~ "Invalid number"
      assert output =~ IO.ANSI.red()
    end

    test "with zero prints invalid number error", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 0", state)
        end)

      # 0 is not > 0, so it's invalid
      assert output =~ "Invalid number"
    end

    test "with negative number prints invalid number error", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate -5", state)
        end)

      assert output =~ "Invalid number"
    end

    test "stub warning is visible (uses yellow color)", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 10", state)
        end)

      assert output =~ IO.ANSI.yellow()
    end
  end
end
