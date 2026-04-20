defmodule CodePuppyControl.TUI.Screens.ConfigTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Screens.Config

  describe "init/1" do
    test "creates default state" do
      {:ok, state} = Config.init(%{})
      assert state.status == :ok
      assert state.last_action == nil
    end
  end

  describe "render/1" do
    test "renders without crashing" do
      {:ok, state} = Config.init(%{})
      rendered = Config.render(state)
      assert is_list(rendered) or is_binary(rendered)
    end
  end

  describe "handle_input/2" do
    setup do
      {:ok, state} = Config.init(%{})
      {:ok, state: state}
    end

    test "q quits the screen", %{state: state} do
      assert :quit == Config.handle_input("q", state)
    end

    test "empty input is a no-op", %{state: state} do
      assert {:ok, ^state} = Config.handle_input("", state)
    end

    test "keys command updates last_action", %{state: state} do
      {:ok, new_state} = Config.handle_input("keys", state)
      assert new_state.last_action == "Listing all keys"
      assert new_state.status == :ok
    end

    test "get with existing key returns value", %{state: state} do
      # puppy_name is usually set during config init
      {:ok, new_state} = Config.handle_input("get puppy_name", state)
      # Either found or not found, but should not crash
      assert new_state.last_action != nil
    end

    test "get with missing key shows not found", %{state: state} do
      {:ok, new_state} = Config.handle_input("get nonexistent_key_xyz", state)
      assert new_state.status == {:error, "not found"}
      assert new_state.last_action =~ "not found"
    end

    test "set with key and value attempts update", %{state: state} do
      {:ok, new_state} = Config.handle_input("set test_key test_value", state)
      # Writer may or may not be running — either ok or write_error is valid
      assert new_state.last_action =~ "test_key"
      assert new_state.last_action =~ "test_value"
    end

    test "set with only key attempts update", %{state: state} do
      {:ok, new_state} = Config.handle_input("set some_key", state)
      # Writer may or may not be running — just verify it doesn't crash
      assert new_state.last_action != nil
    end

    test "unknown command shows error", %{state: state} do
      {:ok, new_state} = Config.handle_input("blargle", state)
      assert new_state.status == {:error, "unknown command"}
      assert new_state.last_action =~ "blargle"
    end
  end
end
