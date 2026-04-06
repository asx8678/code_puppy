defmodule Mana.Plugin.HookTest do
  use ExUnit.Case

  alias Mana.Plugin.Hook

  describe "all_hooks/0" do
    test "returns a list of all hook phases" do
      hooks = Hook.all_hooks()
      assert is_list(hooks)
      assert :startup in hooks
      assert :shutdown in hooks
      assert :agent_run_start in hooks
      assert :agent_run_end in hooks
      assert :pre_tool_call in hooks
      assert :post_tool_call in hooks
    end

    test "contains only atom keys" do
      hooks = Hook.all_hooks()
      assert Enum.all?(hooks, &is_atom/1)
    end
  end

  describe "valid?/1" do
    test "returns true for valid hook phases" do
      assert Hook.valid?(:startup)
      assert Hook.valid?(:shutdown)
      assert Hook.valid?(:agent_run_start)
      assert Hook.valid?(:agent_run_end)
      assert Hook.valid?(:pre_tool_call)
      assert Hook.valid?(:post_tool_call)
      assert Hook.valid?(:stream_event)
    end

    test "returns false for invalid hook phases" do
      refute Hook.valid?(:invalid_hook)
      refute Hook.valid?(:some_random_thing)
      refute Hook.valid?("startup")
      refute Hook.valid?(123)
    end
  end

  describe "async?/1" do
    test "returns true for async hooks" do
      assert Hook.async?(:startup)
      assert Hook.async?(:shutdown)
      assert Hook.async?(:invoke_agent)
      assert Hook.async?(:agent_run_start)
      assert Hook.async?(:agent_run_end)
      assert Hook.async?(:pre_tool_call)
      assert Hook.async?(:post_tool_call)
      assert Hook.async?(:stream_event)
      assert Hook.async?(:run_shell_command)
    end

    test "returns false for sync hooks" do
      refute Hook.async?(:register_tools)
      refute Hook.async?(:register_agents)
      refute Hook.async?(:load_prompt)
      refute Hook.async?(:edit_file)
      refute Hook.async?(:create_file)
      refute Hook.async?(:file_permission)
    end
  end

  describe "callback_signature/1" do
    test "returns string signatures for all hooks" do
      Hook.all_hooks()
      |> Enum.each(fn hook ->
        sig = Hook.callback_signature(hook)
        assert is_binary(sig)
        assert String.length(sig) > 0
      end)
    end

    test "returns generic signature for unknown hooks" do
      assert Hook.callback_signature(:unknown) == "() -> any()"
    end
  end
end
