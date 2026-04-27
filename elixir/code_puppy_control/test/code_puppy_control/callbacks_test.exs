defmodule CodePuppyControl.CallbacksTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Callbacks

  setup do
    # Clear all callbacks before each test for isolation
    Callbacks.clear()
    :ok
  end

  describe "register/2" do
    test "registers a callback for a known hook" do
      fun = fn -> "hello" end
      assert :ok = Callbacks.register(:load_prompt, fun)
      assert [^fun] = Callbacks.get_callbacks(:load_prompt)
    end

    test "raises ArgumentError for unknown hooks" do
      assert_raise ArgumentError, ~r/Unknown hook/, fn ->
        Callbacks.register(:nonexistent, fn -> :ok end)
      end
    end

    test "idempotent registration" do
      fun = fn -> :ok end
      :ok = Callbacks.register(:startup, fun)
      :ok = Callbacks.register(:startup, fun)

      assert [^fun] = Callbacks.get_callbacks(:startup)
    end
  end

  describe "unregister/2" do
    test "removes a callback and returns true" do
      fun = fn -> :ok end
      Callbacks.register(:startup, fun)

      assert true = Callbacks.unregister(:startup, fun)
      assert [] = Callbacks.get_callbacks(:startup)
    end

    test "returns false when callback not found" do
      fun = fn -> :ok end
      assert false == Callbacks.unregister(:startup, fun)
    end
  end

  describe "trigger/2 with :concat_str merge (load_prompt)" do
    test "concatenates string results" do
      Callbacks.register(:load_prompt, fn -> "## Section 1" end)
      Callbacks.register(:load_prompt, fn -> "## Section 2" end)

      result = Callbacks.trigger(:load_prompt)
      assert result == "## Section 1\n## Section 2"
    end

    test "returns nil when no callbacks registered" do
      assert nil == Callbacks.trigger(:load_prompt)
    end

    test "filters out nil callback results" do
      Callbacks.register(:load_prompt, fn -> "instructions" end)
      Callbacks.register(:load_prompt, fn -> nil end)

      result = Callbacks.trigger(:load_prompt)
      assert result == "instructions"
    end
  end

  describe "trigger/2 with :extend_list merge" do
    test "flattens list results" do
      Callbacks.register(:custom_command_help, fn -> [{"woof", "emit woof"}] end)
      Callbacks.register(:custom_command_help, fn -> [{"echo", "echo text"}] end)

      result = Callbacks.trigger(:custom_command_help)
      assert [{"woof", "emit woof"}, {"echo", "echo text"}] = result
    end
  end

  describe "trigger/2 with :noop merge" do
    test "collects results as-is for single callback" do
      Callbacks.register(:startup, fn -> :started end)

      result = Callbacks.trigger(:startup)
      assert :started = result
    end

    test "returns list of results for multiple callbacks" do
      Callbacks.register(:startup, fn -> :first end)
      Callbacks.register(:startup, fn -> :second end)

      result = Callbacks.trigger(:startup)
      assert [:first, :second] = result
    end
  end

  describe "trigger/2 error handling" do
    test "replaces crashed callbacks with :callback_failed" do
      Callbacks.register(:startup, fn -> :ok end)
      Callbacks.register(:startup, fn -> raise "boom" end)
      Callbacks.register(:startup, fn -> :also_ok end)

      result = Callbacks.trigger(:startup)
      assert is_list(result)
      assert :ok in result
      assert :also_ok in result
      assert :callback_failed in result
    end

    test "host process does not crash on callback error" do
      Callbacks.register(:startup, fn -> raise "boom" end)

      # Should not raise - single callback with :noop merge returns value directly
      result = Callbacks.trigger(:startup)
      assert result == :callback_failed
    end

    test "handles throw in callback" do
      Callbacks.register(:startup, fn -> throw(:whoops) end)

      result = Callbacks.trigger(:startup)
      assert result == :callback_failed
    end

    test "handles exit in callback" do
      Callbacks.register(:startup, fn -> exit(:kaboom) end)

      result = Callbacks.trigger(:startup)
      assert result == :callback_failed
    end
  end

  describe "trigger/2 with args" do
    test "passes arguments to callbacks" do
      Callbacks.register(:custom_command, fn cmd, name -> {:handled, cmd, name} end)

      result = Callbacks.trigger(:custom_command, ["/echo hello", "echo"])
      assert {:handled, "/echo hello", "echo"} = result
    end
  end

  describe "trigger_async/2" do
    test "executes callbacks concurrently" do
      Callbacks.register(:stream_event, fn _type, _data, _session -> :ok end)

      # Single callback with :noop merge returns value directly
      assert {:ok, :ok} = Callbacks.trigger_async(:stream_event, ["token", %{}, nil])
    end

    test "returns {:error, :not_async} for non-async hooks" do
      assert {:error, :not_async} = Callbacks.trigger_async(:startup)
    end

    test "returns {:ok, nil} when no callbacks registered" do
      assert {:ok, nil} = Callbacks.trigger_async(:stream_event, ["token", %{}, nil])
    end
  end

  describe "count_callbacks/1" do
    test "returns 0 when no callbacks" do
      assert 0 = Callbacks.count_callbacks(:startup)
    end

    test "returns correct count" do
      Callbacks.register(:startup, fn -> :a end)
      Callbacks.register(:startup, fn -> :b end)

      assert 2 = Callbacks.count_callbacks(:startup)
    end

    test "counts all with :all" do
      Callbacks.register(:startup, fn -> :a end)
      Callbacks.register(:shutdown, fn -> :b end)

      assert 2 = Callbacks.count_callbacks(:all)
    end
  end

  describe "active_hooks/0" do
    test "returns empty list when no callbacks" do
      assert [] = Callbacks.active_hooks()
    end

    test "returns hooks with registered callbacks" do
      Callbacks.register(:startup, fn -> :ok end)
      Callbacks.register(:shutdown, fn -> :ok end)

      hooks = Callbacks.active_hooks()
      assert :startup in hooks
      assert :shutdown in hooks
    end
  end

  describe "on/2 (Python-compatible alias)" do
    test "on/2 delegates to trigger/2" do
      Callbacks.register(:load_prompt, fn -> "## via on" end)

      result = Callbacks.on(:load_prompt)
      assert result == "## via on"
    end

    test "on/2 passes args to callbacks" do
      Callbacks.register(:custom_command, fn cmd, name -> {:handled, cmd, name} end)

      result = Callbacks.on(:custom_command, ["/echo hello", "echo"])
      assert {:handled, "/echo hello", "echo"} = result
    end

    test "on/2 returns nil when no callbacks" do
      assert nil == Callbacks.on(:load_prompt)
    end
  end

  describe "clear/1" do
    test "clears all callbacks" do
      Callbacks.register(:startup, fn -> :ok end)
      Callbacks.register(:shutdown, fn -> :ok end)

      assert :ok = Callbacks.clear()
      assert 0 = Callbacks.count_callbacks(:all)
    end

    test "clears specific hook" do
      Callbacks.register(:startup, fn -> :ok end)
      Callbacks.register(:shutdown, fn -> :ok end)

      assert :ok = Callbacks.clear(:startup)
      assert 0 = Callbacks.count_callbacks(:startup)
      assert 1 = Callbacks.count_callbacks(:shutdown)
    end
  end

  describe "trigger_raw/2" do
    test "returns empty list when no callbacks registered" do
      assert [] = Callbacks.trigger_raw(:startup)
    end

    test "returns raw results list without merging" do
      Callbacks.register(:load_prompt, fn -> "section 1" end)
      Callbacks.register(:load_prompt, fn -> "section 2" end)

      # trigger merges to "section 1\nsection 2", trigger_raw returns list
      assert ["section 1", "section 2"] = Callbacks.trigger_raw(:load_prompt)
    end

    test "preserves :callback_failed sentinel in raw results (fail-closed)" do
      Callbacks.register(:startup, fn -> :ok end)
      Callbacks.register(:startup, fn -> raise "boom" end)
      Callbacks.register(:startup, fn -> nil end)

      results = Callbacks.trigger_raw(:startup)
      assert is_list(results)
      assert length(results) == 3
      assert :ok in results
      assert :callback_failed in results
      assert nil in results
    end

    test "preserves :callback_failed even when mixed with %{blocked: false}" do
      # This is the exact scenario that broke fail-closed in Security.callback_check:
      # Callbacks.trigger(:noop merge) would drop :callback_failed, returning
      # only %{blocked: false}. trigger_raw preserves both.
      Callbacks.register(:run_shell_command, fn _ctx, _cmd, _cwd ->
        raise "security error"
      end)

      Callbacks.register(:run_shell_command, fn _ctx, _cmd, _cwd ->
        %{blocked: false}
      end)

      results = Callbacks.trigger_raw(:run_shell_command, [%{}, "ls", "/tmp"])
      assert length(results) == 2
      assert :callback_failed in results
      assert %{blocked: false} in results

      # With trigger(:noop merge), the :callback_failed would be discarded
      # and %{blocked: false} would be the sole return — losing the failure.
      merged = Callbacks.trigger(:run_shell_command, [%{}, "ls", "/tmp"])
      assert merged == %{blocked: false}
    end

    test "passes args to callbacks" do
      Callbacks.register(:custom_command, fn cmd, name -> {:handled, cmd, name} end)

      assert [{:handled, "/echo hello", "echo"}] =
               Callbacks.trigger_raw(:custom_command, ["/echo hello", "echo"])
    end
  end
end
