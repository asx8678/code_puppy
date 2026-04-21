defmodule CodePuppyControl.CLI.SlashCommands.Commands.SessionTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State, as: AgentState
  alias CodePuppyControl.CLI.SlashCommands.Commands.Session
  alias CodePuppyControl.REPL.Loop

  # Unique session key per test to avoid cross-test state pollution
  defp unique_key(prefix) do
    rand = :rand.uniform(1_000_000)
    {"#{prefix}-#{rand}", "test-agent-#{rand}"}
  end

  defp make_state(session_id, agent_name \\ "test-agent") do
    %Loop{
      agent: agent_name,
      model: "gpt-4",
      session_id: session_id,
      running: true
    }
  end

  defp sample_messages(count) do
    for i <- 1..count do
      %{"role" => "user", "parts" => [%{"content" => "message #{i}"}]}
    end
  end

  # ── /compact ───────────────────────────────────────────────────────────

  describe "/compact" do
    test "with no session_id prints error" do
      state = make_state(nil)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      assert output =~ "No active session"
      assert output =~ IO.ANSI.red()
    end

    test "with empty history prints warning" do
      {session_id, agent_name} = unique_key("compact-empty")
      state = make_state(session_id, agent_name)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      assert output =~ "No history to compact"
      assert output =~ IO.ANSI.yellow()
    end

    test "with history compacts and writes back" do
      {session_id, agent_name} = unique_key("compact-real")
      state = make_state(session_id, agent_name)

      # Create enough messages to trigger meaningful compaction
      messages =
        [%{"role" => "system", "parts" => [%{"content" => "You are helpful."}]}] ++
          sample_messages(20)

      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      # Should show compaction result
      assert output =~ "Compacted"
      assert output =~ IO.ANSI.green()

      # Verify history was actually written back
      final_messages = AgentState.get_messages(session_id, agent_name)
      assert is_list(final_messages)
      # Compaction should reduce or maintain message count
      assert length(final_messages) <= length(messages)
    end

    test "output includes compaction stats" do
      {session_id, agent_name} = unique_key("compact-stats")
      state = make_state(session_id, agent_name)

      messages =
        [%{"role" => "system", "parts" => [%{"content" => "sys"}]}] ++
          sample_messages(30)

      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_compact("/compact", state)
        end)

      # Stats should include at least one of these fields
      assert output =~ "dropped=" or output =~ "truncated=" or
               output =~ "summarize_candidates="
    end
  end

  # ── /truncate ──────────────────────────────────────────────────────────

  describe "/truncate" do
    test "with no argument prints usage error" do
      state = make_state("any")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate", state)
        end)

      assert output =~ "Usage"
      assert output =~ IO.ANSI.red()
    end

    test "with invalid number prints error" do
      state = make_state("any")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate abc", state)
        end)

      assert output =~ "Invalid number"
      assert output =~ IO.ANSI.red()
    end

    test "with zero prints invalid number error" do
      state = make_state("any")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 0", state)
        end)

      assert output =~ "Invalid number"
    end

    test "with negative number prints invalid number error" do
      state = make_state("any")

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate -5", state)
        end)

      assert output =~ "Invalid number"
    end

    test "with no session_id prints error" do
      state = make_state(nil)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 5", state)
        end)

      assert output =~ "No active session"
      assert output =~ IO.ANSI.red()
    end

    test "with empty history prints warning" do
      {session_id, agent_name} = unique_key("truncate-empty")
      state = make_state(session_id, agent_name)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 5", state)
        end)

      assert output =~ "No history to truncate"
      assert output =~ IO.ANSI.yellow()
    end

    test "with history shorter than N prints nothing-to-do message" do
      {session_id, agent_name} = unique_key("truncate-short")
      state = make_state(session_id, agent_name)

      messages = sample_messages(3)
      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 10", state)
        end)

      assert output =~ "already has 3 messages"
      assert output =~ "Nothing to truncate"
    end

    test "truncates to N messages, keeping system message" do
      {session_id, agent_name} = unique_key("truncate-real")
      state = make_state(session_id, agent_name)

      system_msg = %{"role" => "system", "parts" => [%{"content" => "You are helpful."}]}
      messages = [system_msg | sample_messages(9)]
      # 1 system + 9 user = 10 messages
      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 4", state)
        end)

      assert output =~ "Truncated"
      assert output =~ "10 → 4 messages"
      assert output =~ IO.ANSI.green()

      # Verify actual state: system message + 3 most recent
      final = AgentState.get_messages(session_id, agent_name)
      assert length(final) == 4
      assert hd(final) == system_msg
      # Last 3 should be the last 3 from original
      assert List.last(final) == List.last(messages)
    end

    test "with N=1 keeps only system message" do
      {session_id, agent_name} = unique_key("truncate-n1")
      state = make_state(session_id, agent_name)

      system_msg = %{"role" => "system", "parts" => [%{"content" => "sys"}]}
      messages = [system_msg | sample_messages(5)]
      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 1", state)
        end)

      assert output =~ "Truncated"
      assert output =~ IO.ANSI.green()

      final = AgentState.get_messages(session_id, agent_name)
      assert length(final) == 1
      assert hd(final) == system_msg
    end

    test "with history exactly N messages prints nothing-to-do" do
      {session_id, agent_name} = unique_key("truncate-exact")
      state = make_state(session_id, agent_name)

      messages = sample_messages(5)
      AgentState.set_messages(session_id, agent_name, messages)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Session.handle_truncate("/truncate 5", state)
        end)

      assert output =~ "already has 5 messages"
    end
  end
end
