defmodule CodePuppyControl.REPL.LoopTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.REPL.{History, Loop}

  # Start a fresh History GenServer for each test.
  # async: false because we share the registered name and disk file.
  setup do
    case Process.whereis(History) do
      nil -> :ok
      pid -> GenServer.stop(pid, :shutdown, 5000)
    end

    # Wipe the history file so tests start clean
    File.rm(History.history_path())

    {:ok, _pid} = History.start_link()

    on_exit(fn ->
      try do
        case Process.whereis(History) do
          nil -> :ok
          pid -> GenServer.stop(pid, :shutdown, 5000)
        end
      catch
        :exit, _ -> :ok
      end

      File.rm(History.history_path())
    end)

    :ok
  end

  describe "is_slash_command?/1" do
    test "detects slash commands" do
      assert Loop.is_slash_command?("/help")
      assert Loop.is_slash_command?("/quit")
      assert Loop.is_slash_command?("/model gpt-4")
      assert Loop.is_slash_command?("/agent code-puppy")
    end

    test "non-slash input is not a command" do
      refute Loop.is_slash_command?("hello world")
      refute Loop.is_slash_command?("explain this code")
      refute Loop.is_slash_command?("")
    end
  end

  describe "is_shell_passthrough?/1" do
    test "detects shell passthrough" do
      assert Loop.is_shell_passthrough?("!git status")
      assert Loop.is_shell_passthrough?("!ls -la")
    end

    test "regular input is not passthrough" do
      refute Loop.is_shell_passthrough?("git status")
      refute Loop.is_shell_passthrough?("/help")
    end
  end

  describe "handle_input/2 — slash commands" do
    setup do
      state = %Loop{
        agent: "code-puppy",
        model: "gpt-4",
        session_id: "test-session",
        running: true
      }

      {:ok, state: state}
    end

    test "/quit halts the loop", %{state: state} do
      assert {:halt, new_state} = Loop.handle_input("/quit", state)
      refute new_state.running
    end

    test "/exit halts the loop", %{state: state} do
      assert {:halt, new_state} = Loop.handle_input("/exit", state)
      refute new_state.running
    end

    test "/help continues the loop", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("/help", state)
        end)

      assert output =~ "Available commands"
      assert output =~ "/quit"
      assert output =~ "/help"
    end

    test "/model shows current model", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("/model", state)
        end)

      assert output =~ "gpt-4"
    end

    test "/model <name> switches model", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, new_state} = Loop.handle_input("/model claude-sonnet-4", state)
          assert new_state.model == "claude-sonnet-4"
        end)

      assert output =~ "Switching model"
    end

    test "/agent shows current agent", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("/agent", state)
        end)

      assert output =~ "code-puppy"
    end

    test "/agent <name> switches agent", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, new_state} = Loop.handle_input("/agent qa-kitten", state)
          assert new_state.agent == "qa-kitten"
        end)

      assert output =~ "Switching agent"
    end

    test "/clear continues the loop", %{state: state} do
      assert {:continue, ^state} = Loop.handle_input("/clear", state)
    end

    test "/history shows empty history", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("/history", state)
        end)

      assert output =~ "no history"
    end

    test "unknown slash command shows error", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("/bogus", state)
        end)

      assert output =~ "Unknown command"
    end
  end

  describe "handle_input/2 — regular input" do
    setup do
      state = %Loop{
        agent: "code-puppy",
        model: "gpt-4",
        session_id: "test-session",
        running: true
      }

      {:ok, state: state}
    end

    test "blank input continues without recording", %{state: state} do
      assert {:continue, ^state} = Loop.handle_input("   ", state)
    end

    test "non-blank input is recorded in history", %{state: state} do
      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _new_state} = Loop.handle_input("explain this code", state)
          assert History.all() == ["explain this code"]
        end)
    end

    test "duplicate consecutive input is not re-recorded", %{state: state} do
      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          # Pre-seed history
          History.add("hello")
          # Same input again
          assert {:continue, _} = Loop.handle_input("hello", state)
          # Should not duplicate
          assert History.all() == ["hello"]
        end)
    end

    test "shell passthrough continues the loop", %{state: state} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("!echo hello", state)
        end)

      assert output =~ "hello"
    end
  end

  describe "handle_input/2 — history accumulation" do
    setup do
      state = %Loop{
        agent: "code-puppy",
        model: "gpt-4",
        session_id: "test-session",
        running: true
      }

      {:ok, state: state}
    end

    test "multiple inputs build up history", %{state: state} do
      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          {:continue, _s1} = Loop.handle_input("first prompt", state)
          {:continue, _s2} = Loop.handle_input("second prompt", state)
          # History is most-recent-first
          assert History.all() == ["second prompt", "first prompt"]
        end)
    end
  end
end
