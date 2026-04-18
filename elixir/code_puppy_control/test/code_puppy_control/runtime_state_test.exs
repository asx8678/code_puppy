defmodule CodePuppyControl.RuntimeStateTest do
  @moduledoc """
  Tests for the RuntimeState GenServer.
  """

  use CodePuppyControl.StatefulCase

  alias CodePuppyControl.RuntimeState

  describe "autosave_id" do
    test "get_current_autosave_id/0 returns a valid timestamp-based ID" do
      id = RuntimeState.get_current_autosave_id()
      assert is_binary(id)
      # Format should be YYYYMMDD_HHMMSS
      assert Regex.match?(~r/^\d{8}_\d{6}$/, id)
    end

    test "get_current_autosave_id/0 returns same ID on subsequent calls" do
      id1 = RuntimeState.get_current_autosave_id()
      id2 = RuntimeState.get_current_autosave_id()
      assert id1 == id2
    end

    test "rotate_autosave_id/0 generates a new ID" do
      id1 = RuntimeState.get_current_autosave_id()
      # Wait at least 1 second for different timestamp
      Process.sleep(1000)
      id2 = RuntimeState.rotate_autosave_id()

      assert is_binary(id2)
      assert id1 != id2
    end

    test "get_current_autosave_session_name/0 formats the session name correctly" do
      id = RuntimeState.get_current_autosave_id()
      session_name = RuntimeState.get_current_autosave_session_name()
      assert session_name == "auto_session_#{id}"
    end

    test "set_current_autosave_from_session_name/1 extracts ID from full session name" do
      set_id = RuntimeState.set_current_autosave_from_session_name("auto_session_20240115_143022")
      assert set_id == "20240115_143022"

      # Verify it was set
      current_id = RuntimeState.get_current_autosave_id()
      assert current_id == "20240115_143022"
    end

    test "set_current_autosave_from_session_name/1 handles raw ID without prefix" do
      set_id = RuntimeState.set_current_autosave_from_session_name("20240115_143022")
      assert set_id == "20240115_143022"

      current_id = RuntimeState.get_current_autosave_id()
      assert current_id == "20240115_143022"
    end

    test "reset_autosave_id/0 clears the autosave ID" do
      id1 = RuntimeState.get_current_autosave_id()
      assert is_binary(id1)

      :ok = RuntimeState.reset_autosave_id()

      # After reset, should generate a new ID
      # Wait for different timestamp
      Process.sleep(1000)
      id2 = RuntimeState.get_current_autosave_id()
      assert is_binary(id2)
      # ID should be different after reset
      assert id1 != id2
    end
  end

  describe "session_model" do
    test "get_session_model/0 returns nil when not set" do
      assert RuntimeState.get_session_model() == nil
    end

    test "set_session_model/1 sets the session model" do
      :ok = RuntimeState.set_session_model("claude-3-5-sonnet")
      assert RuntimeState.get_session_model() == "claude-3-5-sonnet"
    end

    test "set_session_model/1 with nil clears the model" do
      :ok = RuntimeState.set_session_model("claude-3-5-sonnet")
      assert RuntimeState.get_session_model() == "claude-3-5-sonnet"

      :ok = RuntimeState.set_session_model(nil)
      assert RuntimeState.get_session_model() == nil
    end

    test "reset_session_model/0 clears the session model" do
      :ok = RuntimeState.set_session_model("claude-3-5-sonnet")
      assert RuntimeState.get_session_model() == "claude-3-5-sonnet"

      :ok = RuntimeState.reset_session_model()
      assert RuntimeState.get_session_model() == nil
    end
  end

  describe "get_state/0" do
    test "returns the complete state struct" do
      state = RuntimeState.get_state()

      assert %RuntimeState{} = state
      assert %DateTime{} = state.session_start_time
    end

    test "state includes autosave_id and session_model" do
      RuntimeState.get_current_autosave_id()
      RuntimeState.set_session_model("test-model")

      state = RuntimeState.get_state()
      assert is_binary(state.autosave_id)
      assert state.session_model == "test-model"
    end
  end

  describe "process lifecycle" do
    test "process is registered with correct name" do
      pid = Process.whereis(RuntimeState)
      assert is_pid(pid)
      assert Process.alive?(pid)
    end
  end
end
