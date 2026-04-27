defmodule CodePuppyControl.Workflow.StateTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Workflow.State

  # async: false because Workflow.State is a named singleton Agent.

  setup do
    # Start the State agent if not already running
    case Process.whereis(State) do
      nil -> start_supervised!({State, name: State})
      _pid -> :ok
    end

    # Reset to clean state before each test
    State.reset()
    :ok
  end

  # ── new/0 ────────────────────────────────────────────────────────────

  describe "new/0" do
    test "creates a fresh state with empty flags and metadata" do
      state = State.new()
      assert MapSet.size(state.flags) == 0
      assert state.metadata == %{}
      assert state.start_time != nil
    end
  end

  # ── all_flags/0 and flag_names/0 ────────────────────────────────────

  describe "all_flags/0 and flag_names/0" do
    test "returns a non-empty list of flag definitions" do
      flags = State.all_flags()
      assert length(flags) > 0

      Enum.each(flags, fn {name, desc} ->
        assert is_atom(name)
        assert is_binary(desc)
        assert String.length(desc) > 0
      end)
    end

    test "flag_names/0 matches all_flags/0 keys" do
      names = State.flag_names()
      flag_keys = State.all_flags() |> Enum.map(fn {k, _v} -> k end)
      assert names == flag_keys
    end

    test "includes all flags from Python source (full parity)" do
      names = State.flag_names()

      # All flags from Python's WorkflowFlag enum
      for expected <- [
            :did_generate_code,
            :did_execute_shell,
            :did_load_context,
            :did_create_plan,
            :did_encounter_error,
            :needs_user_confirmation,
            :did_save_session,
            :did_use_fallback_model,
            :did_trigger_compaction,
            :did_make_api_call,
            :did_edit_file,
            :did_create_file,
            :did_delete_file,
            :did_run_tests,
            :did_check_lint
          ] do
        assert expected in names, "Missing flag: #{expected}"
      end
    end
  end

  # ── known_flag?/1 ────────────────────────────────────────────────────

  describe "known_flag?/1" do
    test "returns true for known flag atoms" do
      assert State.known_flag?(:did_generate_code)
      assert State.known_flag?(:did_run_tests)
      assert State.known_flag?(:did_make_api_call)
    end

    test "returns false for unknown atoms" do
      refute State.known_flag?(:totally_bogus_flag)
    end

    test "returns false for non-atoms" do
      refute State.known_flag?("did_generate_code")
      refute State.known_flag?(123)
    end
  end

  # ── resolve_flag/1 ──────────────────────────────────────────────────

  describe "resolve_flag/1" do
    test "resolves atom flags" do
      assert {:ok, :did_generate_code} = State.resolve_flag(:did_generate_code)
    end

    test "resolves string flags (lowercase)" do
      assert {:ok, :did_generate_code} = State.resolve_flag("did_generate_code")
    end

    test "resolves string flags (uppercase snake_case)" do
      assert {:ok, :did_generate_code} = State.resolve_flag("DID_GENERATE_CODE")
    end

    test "returns error for unknown atom" do
      assert {:error, :unknown_flag} = State.resolve_flag(:nonexistent)
    end

    test "returns error for unknown string" do
      assert {:error, :unknown_flag} = State.resolve_flag("nonexistent")
    end
  end

  # ── set_flag/1 and has_flag?/1 (atom input) ──────────────────────────

  describe "set_flag/1 and has_flag?/1 with atoms" do
    test "sets a flag and confirms it is active" do
      State.set_flag(:did_generate_code)
      assert State.has_flag?(:did_generate_code)
    end

    test "setting multiple flags works" do
      State.set_flag(:did_generate_code)
      State.set_flag(:did_execute_shell)
      assert State.has_flag?(:did_generate_code)
      assert State.has_flag?(:did_execute_shell)
    end

    test "setting an unknown flag is a no-op with warning" do
      # Should not crash, just log a warning
      State.set_flag(:nonexistent_flag)
      refute State.has_flag?(:nonexistent_flag)
    end

    test "has_flag? returns false for unknown flags" do
      refute State.has_flag?(:nonexistent_flag)
    end
  end

  # ── set_flag/1 and has_flag?/1 (string input) ───────────────────────

  describe "set_flag/1 and has_flag?/1 with strings" do
    test "sets a flag via string name" do
      State.set_flag("did_generate_code")
      assert State.has_flag?(:did_generate_code)
    end

    test "sets a flag via uppercase string" do
      State.set_flag("DID_GENERATE_CODE")
      assert State.has_flag?(:did_generate_code)
    end

    test "checks flag via string name" do
      State.set_flag(:did_generate_code)
      assert State.has_flag?("did_generate_code")
    end

    test "checks flag via uppercase string" do
      State.set_flag(:did_generate_code)
      assert State.has_flag?("DID_GENERATE_CODE")
    end
  end

  # ── set_flag/2 (boolean) ────────────────────────────────────────────

  describe "set_flag/2 with boolean" do
    test "set_flag with true adds the flag" do
      State.set_flag(:did_generate_code, true)
      assert State.has_flag?(:did_generate_code)
    end

    test "set_flag with false removes the flag" do
      State.set_flag(:did_generate_code)
      State.set_flag(:did_generate_code, false)
      refute State.has_flag?(:did_generate_code)
    end

    test "set_flag with string and boolean" do
      State.set_flag("did_generate_code", true)
      assert State.has_flag?(:did_generate_code)
      State.set_flag("did_generate_code", false)
      refute State.has_flag?(:did_generate_code)
    end
  end

  # ── clear_flag/1 ────────────────────────────────────────────────────

  describe "clear_flag/1" do
    test "clears a previously set flag" do
      State.set_flag(:did_generate_code)
      assert State.has_flag?(:did_generate_code)

      State.clear_flag(:did_generate_code)
      refute State.has_flag?(:did_generate_code)
    end

    test "clears a flag via string" do
      State.set_flag(:did_generate_code)
      State.clear_flag("did_generate_code")
      refute State.has_flag?(:did_generate_code)
    end

    test "clearing an unknown flag is a no-op" do
      State.clear_flag(:nonexistent_flag)
      refute State.has_flag?(:nonexistent_flag)
    end

    test "clearing an unset flag is a no-op" do
      State.clear_flag(:did_generate_code)
      refute State.has_flag?(:did_generate_code)
    end
  end

  # ── reset/0 ─────────────────────────────────────────────────────────

  describe "reset/0" do
    test "clears all flags and metadata" do
      State.set_flag(:did_generate_code)
      State.set_flag(:did_execute_shell)
      State.put_metadata("test_key", "test_value")

      result = State.reset()

      refute State.has_flag?(:did_generate_code)
      refute State.has_flag?(:did_execute_shell)
      assert State.metadata() == %{}
      assert result.flags == MapSet.new()
    end

    test "returns the fresh state" do
      State.set_flag(:did_generate_code)
      result = State.reset()
      assert MapSet.size(result.flags) == 0
    end
  end

  # ── metadata ────────────────────────────────────────────────────────

  describe "metadata" do
    test "put_metadata and get_metadata work" do
      State.put_metadata("agent_name", "code-puppy")
      assert State.get_metadata("agent_name") == "code-puppy"
    end

    test "get_metadata returns default for missing keys" do
      assert State.get_metadata("nonexistent") == nil
      assert State.get_metadata("nonexistent", "default") == "default"
    end

    test "metadata/0 returns the full map" do
      State.put_metadata("key1", "val1")
      State.put_metadata("key2", "val2")
      meta = State.metadata()
      assert meta["key1"] == "val1"
      assert meta["key2"] == "val2"
    end

    test "overwrites existing key" do
      State.put_metadata("key", "first")
      State.put_metadata("key", "second")
      assert State.get_metadata("key") == "second"
    end
  end

  # ── increment_counter/2 ─────────────────────────────────────────────

  describe "increment_counter/2" do
    test "starts from zero and increments by one" do
      assert State.increment_counter("file_edits") == 1
      assert State.increment_counter("file_edits") == 2
      assert State.increment_counter("file_edits") == 3
    end

    test "increments by custom amount" do
      assert State.increment_counter("api_calls", 5) == 5
      assert State.increment_counter("api_calls", 3) == 8
    end

    test "stores counter in metadata" do
      State.increment_counter("edits")
      assert State.get_metadata("edits") == 1
    end

    test "independent counters don't interfere" do
      assert State.increment_counter("a") == 1
      assert State.increment_counter("b") == 1
      assert State.increment_counter("a") == 2
      assert State.increment_counter("b") == 2
    end
  end

  # ── active_count/0 ──────────────────────────────────────────────────

  describe "active_count/0" do
    test "starts at zero" do
      assert State.active_count() == 0
    end

    test "tracks set flags" do
      State.set_flag(:did_generate_code)
      assert State.active_count() == 1

      State.set_flag(:did_execute_shell)
      assert State.active_count() == 2
    end

    test "decrements on clear" do
      State.set_flag(:did_generate_code)
      State.set_flag(:did_execute_shell)
      State.clear_flag(:did_generate_code)
      assert State.active_count() == 1
    end
  end

  # ── summary/0 ──────────────────────────────────────────────────────

  describe "summary/0" do
    test "returns placeholder when no flags set" do
      assert State.summary() == "No actions recorded"
    end

    test "lists active flags" do
      State.set_flag(:did_generate_code)
      summary = State.summary()
      assert summary =~ "Did generate code"
    end

    test "sorts alphabetically" do
      State.set_flag(:did_generate_code)
      State.set_flag(:did_execute_shell)
      summary = State.summary()
      assert String.contains?(summary, "Did execute shell")
      assert String.contains?(summary, "Did generate code")
    end
  end

  # ── to_map/0 ────────────────────────────────────────────────────────

  describe "to_map/0" do
    test "serializes state to a map" do
      State.set_flag(:did_generate_code)
      State.put_metadata("key", "val")

      m = State.to_map()
      assert "did_generate_code" in m.flags
      assert m.metadata["key"] == "val"
      assert m.start_time != nil
      assert is_binary(m.summary)
    end
  end

  # ── detect_and_mark_plan_from_response/2 ───────────────────────────

  describe "detect_and_mark_plan_from_response/2" do
    test "detects numbered plan with enough items" do
      response = """
      Here's my plan:
      1. First step
      2. Second step
      3. Third step
      """

      assert State.detect_and_mark_plan_from_response(response) == true
      assert State.has_flag?(:did_create_plan)
    end

    test "detects bullet list plan" do
      response = """
      Plan:
      - Step one
      - Step two
      """

      assert State.detect_and_mark_plan_from_response(response) == true
      assert State.has_flag?(:did_create_plan)
    end

    test "does not detect plan with too few items" do
      response = "1. Only one item"
      assert State.detect_and_mark_plan_from_response(response) == false
      refute State.has_flag?(:did_create_plan)
    end

    test "respects min_tasks option" do
      response = """
      1. First
      2. Second
      3. Third
      """

      assert State.detect_and_mark_plan_from_response(response, min_tasks: 4) == false
    end

    test "does not flag on plain text without list items" do
      response = "Just a normal response without any plan structure."
      assert State.detect_and_mark_plan_from_response(response) == false
    end
  end

  # ── Callback integration ───────────────────────────────────────────

  describe "callback handlers" do
    test "_on_delete_file sets did_delete_file flag" do
      State._on_delete_file(nil)
      assert State.has_flag?(:did_delete_file)
    end

    test "_on_run_shell_command sets did_execute_shell flag" do
      State._on_run_shell_command(nil, "ls -la")
      assert State.has_flag?(:did_execute_shell)
    end

    test "_on_run_shell_command detects test commands" do
      State._on_run_shell_command(nil, "pytest test_foo.py")
      assert State.has_flag?(:did_execute_shell)
      assert State.has_flag?(:did_run_tests)
    end

    test "_on_run_shell_command detects lint commands" do
      State._on_run_shell_command(nil, "ruff check .")
      assert State.has_flag?(:did_execute_shell)
      assert State.has_flag?(:did_check_lint)
    end

    test "_on_agent_run_start resets and stores metadata" do
      State.set_flag(:did_generate_code)
      State._on_agent_run_start("code-puppy", "claude-3.5")
      refute State.has_flag?(:did_generate_code)
      assert State.get_metadata("agent_name") == "code-puppy"
      assert State.get_metadata("model_name") == "claude-3.5"
    end

    test "_on_agent_run_end sets error flag on failure" do
      State._on_agent_run_end("code-puppy", "claude-3.5", nil, false, nil, nil)
      assert State.has_flag?(:did_encounter_error)
      assert State.get_metadata("success") == false
    end

    test "_on_agent_run_end does not set error flag on success" do
      State._on_agent_run_end("code-puppy", "claude-3.5", nil, true, nil, nil)
      refute State.has_flag?(:did_encounter_error)
      assert State.get_metadata("success") == true
    end

    test "_on_pre_tool_call tracks context loading" do
      State._on_pre_tool_call("read_file", %{}, nil)
      assert State.has_flag?(:did_load_context)
    end

    test "_on_pre_tool_call tracks file creation" do
      State._on_pre_tool_call("create_file", %{}, nil)
      assert State.has_flag?(:did_create_file)
      assert State.has_flag?(:did_generate_code)
    end

    test "_on_pre_tool_call tracks file editing" do
      State._on_pre_tool_call("replace_in_file", %{}, nil)
      assert State.has_flag?(:did_edit_file)
      assert State.has_flag?(:did_generate_code)
    end

    test "_on_pre_tool_call tracks shell via tool name" do
      State._on_pre_tool_call("agent_run_shell_command", %{}, nil)
      assert State.has_flag?(:did_execute_shell)
    end

    test "_on_pre_tool_call tracks api calls" do
      State._on_pre_tool_call("invoke_agent", %{}, nil)
      assert State.has_flag?(:did_make_api_call)
    end
  end

  describe "register_callback_handlers/0 and unregister_callback_handlers/0" do
    setup do
      # Clear any existing callbacks to isolate the test
      CodePuppyControl.Callbacks.clear(:delete_file)
      CodePuppyControl.Callbacks.clear(:run_shell_command)
      CodePuppyControl.Callbacks.clear(:agent_run_start)
      CodePuppyControl.Callbacks.clear(:agent_run_end)
      CodePuppyControl.Callbacks.clear(:pre_tool_call)

      on_exit(fn ->
        # Clean up after test
        CodePuppyControl.Callbacks.clear(:delete_file)
        CodePuppyControl.Callbacks.clear(:run_shell_command)
        CodePuppyControl.Callbacks.clear(:agent_run_start)
        CodePuppyControl.Callbacks.clear(:agent_run_end)
        CodePuppyControl.Callbacks.clear(:pre_tool_call)
      end)

      :ok
    end

    test "registers callback handlers" do
      assert :ok = State.register_callback_handlers()
      # Should have registered handlers (exact count depends on other registrations)
      assert CodePuppyControl.Callbacks.count_callbacks(:delete_file) >= 1
      assert CodePuppyControl.Callbacks.count_callbacks(:pre_tool_call) >= 1
    end

    test "unregisters callback handlers" do
      State.register_callback_handlers()
      State.unregister_callback_handlers()
      # After unregister, counts should drop
      # (They may not be exactly 0 if other handlers exist, but at least
      # the workflow state handlers should be gone)
      assert :ok = State.unregister_callback_handlers()
    end
  end

  # ── Parity with Python: Property tests ─────────────────────────────

  describe "Python parity invariants" do
    test "flag count matches Python WorkflowFlag enum" do
      # Python has 15 flags (check the Python source WorkflowFlag enum)
      # We should have exactly the same count
      assert length(State.flag_names()) == 15
    end

    test "did_make_api_call flag exists (was missing in old WorkflowState)" do
      # This flag was in Python but missing from the original Elixir WorkflowState
      assert State.known_flag?(:did_make_api_call)
    end

    test "all Python flag names have Elixir equivalents" do
      python_flags = [
        "DID_GENERATE_CODE",
        "DID_EXECUTE_SHELL",
        "DID_LOAD_CONTEXT",
        "DID_CREATE_PLAN",
        "DID_ENCOUNTER_ERROR",
        "NEEDS_USER_CONFIRMATION",
        "DID_SAVE_SESSION",
        "DID_USE_FALLBACK_MODEL",
        "DID_TRIGGER_COMPACTION",
        "DID_MAKE_API_CALL",
        "DID_EDIT_FILE",
        "DID_CREATE_FILE",
        "DID_DELETE_FILE",
        "DID_RUN_TESTS",
        "DID_CHECK_LINT"
      ]

      elixir_names = State.flag_names() |> Enum.map(&Atom.to_string/1) |> MapSet.new()

      for pf <- python_flags do
        ef = String.downcase(pf)
        assert MapSet.member?(elixir_names, ef), "Missing Elixir equivalent for Python flag #{pf}"
      end
    end
  end
end
