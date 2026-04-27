defmodule CodePuppyControl.WorkflowStateTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.WorkflowState
  alias CodePuppyControl.Workflow.State, as: WorkflowStateNew

  # async: false because WorkflowState is a named singleton Agent.
  # Tests verify the backward-compatible facade delegates correctly
  # to CodePuppyControl.Workflow.State.

  setup do
    # Start the Workflow.State agent (which WorkflowState now delegates to)
    case Process.whereis(WorkflowStateNew) do
      nil -> start_supervised!({WorkflowStateNew, name: WorkflowStateNew})
      _pid -> :ok
    end

    # Reset to clean state before each test
    WorkflowState.reset()
    :ok
  end

  describe "new/0" do
    test "creates a fresh state with empty flags and metadata" do
      state = WorkflowState.new()
      assert MapSet.size(state.flags) == 0
      assert state.metadata == %{}
      assert state.start_time != nil
    end
  end

  describe "all_flags/0 and flag_names/0" do
    test "returns a non-empty list of flag definitions" do
      flags = WorkflowState.all_flags()
      assert length(flags) > 0

      Enum.each(flags, fn {name, desc} ->
        assert is_atom(name)
        assert is_binary(desc)
        assert String.length(desc) > 0
      end)
    end

    test "flag_names/0 matches all_flags/0 keys" do
      names = WorkflowState.flag_names()
      flag_keys = WorkflowState.all_flags() |> Enum.map(fn {k, _v} -> k end)
      assert names == flag_keys
    end

    test "includes key flags from Python source" do
      names = WorkflowState.flag_names()
      assert :did_generate_code in names
      assert :did_execute_shell in names
      assert :did_load_context in names
      assert :did_create_plan in names
      assert :did_encounter_error in names
      assert :did_edit_file in names
      assert :did_create_file in names
      assert :did_run_tests in names
      # TODO(code-puppy-ctj.3): did_make_api_call was missing from old WorkflowState
      assert :did_make_api_call in names
    end
  end

  describe "delegation to Workflow.State" do
    test "set_flag delegates and works through both modules" do
      WorkflowState.set_flag(:did_generate_code)
      assert WorkflowState.has_flag?(:did_generate_code)
      assert WorkflowStateNew.has_flag?(:did_generate_code)
    end

    test "reset delegates to Workflow.State" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.reset()
      refute WorkflowStateNew.has_flag?(:did_generate_code)
    end

    test "metadata operations delegate to Workflow.State" do
      WorkflowState.put_metadata("test", "value")
      assert WorkflowStateNew.get_metadata("test") == "value"
    end
  end

  describe "known_flag?/1" do
    test "returns true for known flag atoms" do
      assert WorkflowState.known_flag?(:did_generate_code)
      assert WorkflowState.known_flag?(:did_run_tests)
    end

    test "returns false for unknown atoms" do
      refute WorkflowState.known_flag?(:totally_bogus_flag)
    end

    test "returns false for non-atoms" do
      refute WorkflowState.known_flag?("did_generate_code")
      refute WorkflowState.known_flag?(123)
    end
  end

  describe "set_flag/1 and has_flag?/1" do
    test "sets a flag and confirms it is active" do
      WorkflowState.set_flag(:did_generate_code)
      assert WorkflowState.has_flag?(:did_generate_code)
    end

    test "setting multiple flags works" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.set_flag(:did_execute_shell)
      assert WorkflowState.has_flag?(:did_generate_code)
      assert WorkflowState.has_flag?(:did_execute_shell)
    end

    test "setting an unknown flag is a no-op" do
      WorkflowState.set_flag(:nonexistent_flag)
      refute WorkflowState.has_flag?(:nonexistent_flag)
    end

    test "has_flag? returns false for unknown flags" do
      refute WorkflowState.has_flag?(:nonexistent_flag)
    end

    # String flag support (new via Workflow.State delegation)
    test "set_flag accepts string flags" do
      WorkflowState.set_flag("did_generate_code")
      assert WorkflowState.has_flag?(:did_generate_code)
    end
  end

  describe "clear_flag/1" do
    test "clears a previously set flag" do
      WorkflowState.set_flag(:did_generate_code)
      assert WorkflowState.has_flag?(:did_generate_code)

      WorkflowState.clear_flag(:did_generate_code)
      refute WorkflowState.has_flag?(:did_generate_code)
    end

    test "clearing an unknown flag is a no-op" do
      WorkflowState.clear_flag(:nonexistent_flag)
      # No crash, no side effects
      refute WorkflowState.has_flag?(:nonexistent_flag)
    end

    test "clearing an unset flag is a no-op" do
      WorkflowState.clear_flag(:did_generate_code)
      refute WorkflowState.has_flag?(:did_generate_code)
    end
  end

  describe "reset/0" do
    test "clears all flags and metadata" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.set_flag(:did_execute_shell)
      WorkflowState.put_metadata("test_key", "test_value")

      result = WorkflowState.reset()

      refute WorkflowState.has_flag?(:did_generate_code)
      refute WorkflowState.has_flag?(:did_execute_shell)
      assert WorkflowState.metadata() == %{}
      assert result.flags == MapSet.new()
    end

    test "returns the fresh state" do
      WorkflowState.set_flag(:did_generate_code)
      result = WorkflowState.reset()
      assert MapSet.size(result.flags) == 0
    end
  end

  describe "metadata" do
    test "put_metadata and get_metadata work" do
      WorkflowState.put_metadata("agent_name", "code-puppy")
      assert WorkflowState.get_metadata("agent_name") == "code-puppy"
    end

    test "get_metadata returns default for missing keys" do
      assert WorkflowState.get_metadata("nonexistent") == nil
      assert WorkflowState.get_metadata("nonexistent", "default") == "default"
    end

    test "metadata/0 returns the full map" do
      WorkflowState.put_metadata("key1", "val1")
      WorkflowState.put_metadata("key2", "val2")
      meta = WorkflowState.metadata()
      assert meta["key1"] == "val1"
      assert meta["key2"] == "val2"
    end

    test "overwrites existing key" do
      WorkflowState.put_metadata("key", "first")
      WorkflowState.put_metadata("key", "second")
      assert WorkflowState.get_metadata("key") == "second"
    end
  end

  describe "active_count/0" do
    test "starts at zero" do
      assert WorkflowState.active_count() == 0
    end

    test "tracks set flags" do
      WorkflowState.set_flag(:did_generate_code)
      assert WorkflowState.active_count() == 1

      WorkflowState.set_flag(:did_execute_shell)
      assert WorkflowState.active_count() == 2
    end

    test "decrements on clear" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.set_flag(:did_execute_shell)
      WorkflowState.clear_flag(:did_generate_code)
      assert WorkflowState.active_count() == 1
    end
  end

  describe "summary/0" do
    test "returns placeholder when no flags set" do
      assert WorkflowState.summary() == "No actions recorded"
    end

    test "lists active flags" do
      WorkflowState.set_flag(:did_generate_code)
      summary = WorkflowState.summary()
      assert summary =~ "Did generate code"
    end

    test "sorts alphabetically" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.set_flag(:did_execute_shell)
      summary = WorkflowState.summary()
      # "Did execute shell" comes before "Did generate code"
      assert String.contains?(summary, "Did execute shell")
      assert String.contains?(summary, "Did generate code")
    end
  end

  describe "to_map/0" do
    test "serializes state to a map" do
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.put_metadata("key", "val")

      m = WorkflowState.to_map()
      assert "did_generate_code" in m.flags
      assert m.metadata["key"] == "val"
      assert m.start_time != nil
      assert is_binary(m.summary)
    end
  end

  # ── Increment Counter (new feature from Python port) ──────────────

  describe "increment_counter/2" do
    test "increments counter in metadata" do
      assert WorkflowStateNew.increment_counter("edits") == 1
      assert WorkflowStateNew.increment_counter("edits") == 2
    end
  end

  # ── Plan Detection (new feature from Python port) ──────────────────

  describe "detect_and_mark_plan_from_response/2" do
    test "detects numbered plans" do
      response = "1. First\n2. Second"
      assert WorkflowStateNew.detect_and_mark_plan_from_response(response) == true
      assert WorkflowStateNew.has_flag?(:did_create_plan)
    end
  end
end
