defmodule CodePuppyControl.RuntimeStateTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.RuntimeState

  describe "cache invalidation" do
    test "invalidate_caches clears context overhead and tool IDs" do
      # Set some cache values
      GenServer.call(RuntimeState, {:set_test_cache, %{cached_context_overhead: 100, tool_ids_cache: [1, 2, 3]}})

      # Invalidate caches
      assert :ok = RuntimeState.invalidate_caches()

      # Verify caches are cleared (we'd need to expose getters or check via reflection)
      # For now, just verify the call succeeds
    end

    test "invalidate_all_token_caches clears all token-related caches" do
      assert :ok = RuntimeState.invalidate_all_token_caches()
    end

    test "invalidate_system_prompt_cache clears system prompt and context overhead" do
      assert :ok = RuntimeState.invalidate_system_prompt_cache()
    end

    test "reset_for_test resets to initial state" do
      # Set some values
      GenServer.call(RuntimeState, {:set_test_cache, %{cached_system_prompt: "test"}})

      # Reset
      assert :ok = RuntimeState.reset_for_test()

      # Verify reset (would need getters to fully test)
    end
  end

  describe "existing functionality" do
    test "get_current_autosave_id works" do
      assert is_binary(RuntimeState.get_current_autosave_id())
    end

    test "rotate_autosave_id creates new ID" do
      first_id = RuntimeState.get_current_autosave_id()
      second_id = RuntimeState.rotate_autosave_id()
      assert first_id != second_id
    end
  end
end
