defmodule CodePuppyControl.Runtime.RuntimeStateTest do
  @moduledoc """
  Tests for RuntimeState GenServer — runtime-only session state.

  Validates autosave ID lifecycle, session model caching, and reset operations.
  async: false because RuntimeState is a named singleton.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.RuntimeState

  setup do
    CodePuppyControl.TestSupport.Reset.ensure_gen_server_started(RuntimeState)
    RuntimeState.reset_autosave_id()
    RuntimeState.reset_session_model()
    # Flush casts
    Process.sleep(50)
    :ok
  end

  # ---------------------------------------------------------------------------
  # Autosave ID
  # ---------------------------------------------------------------------------

  describe "get_current_autosave_id/0" do
    test "generates an autosave ID on first access" do
      id = RuntimeState.get_current_autosave_id()
      assert is_binary(id)
      assert String.length(id) > 0
    end

    test "returns same ID on subsequent calls" do
      id1 = RuntimeState.get_current_autosave_id()
      id2 = RuntimeState.get_current_autosave_id()
      assert id1 == id2
    end

    test "ID matches YYYYMMDD_HHMMSS format" do
      id = RuntimeState.get_current_autosave_id()
      assert Regex.match?(~r/^\d{8}_\d{6}$/, id)
    end
  end

  describe "rotate_autosave_id/0" do
    test "generates a new ID different from current" do
      old_id = RuntimeState.get_current_autosave_id()
      # Sleep to ensure the timestamp changes (format is YYYYMMDD_HHMMSS)
      Process.sleep(1100)
      new_id = RuntimeState.rotate_autosave_id()
      assert new_id != old_id
    end

    test "subsequent get returns the rotated ID" do
      new_id = RuntimeState.rotate_autosave_id()
      assert RuntimeState.get_current_autosave_id() == new_id
    end
  end

  describe "get_current_autosave_session_name/0" do
    test "returns auto_session_ prefixed name" do
      name = RuntimeState.get_current_autosave_session_name()
      id = RuntimeState.get_current_autosave_id()
      assert name == "auto_session_#{id}"
    end
  end

  describe "set_current_autosave_from_session_name/1" do
    test "extracts ID from auto_session_ prefixed name" do
      RuntimeState.set_current_autosave_from_session_name("auto_session_20250101_120000")
      assert RuntimeState.get_current_autosave_id() == "20250101_120000"
    end

    test "uses full name as ID when no prefix" do
      RuntimeState.set_current_autosave_from_session_name("custom-id-123")
      assert RuntimeState.get_current_autosave_id() == "custom-id-123"
    end
  end

  describe "reset_autosave_id/0" do
    test "clears the autosave ID" do
      _ = RuntimeState.get_current_autosave_id()
      :ok = RuntimeState.reset_autosave_id()
      Process.sleep(50)

      # After reset, next access generates a new ID
      new_id = RuntimeState.get_current_autosave_id()
      assert is_binary(new_id)
    end
  end

  # ---------------------------------------------------------------------------
  # Session Model
  # ---------------------------------------------------------------------------

  describe "get_session_model/0" do
    test "returns nil when not set" do
      assert RuntimeState.get_session_model() == nil
    end
  end

  describe "set_session_model/1" do
    test "sets the session model name" do
      :ok = RuntimeState.set_session_model("claude-sonnet-4")
      Process.sleep(50)
      assert RuntimeState.get_session_model() == "claude-sonnet-4"
    end

    test "can be set to nil" do
      :ok = RuntimeState.set_session_model("test")
      Process.sleep(50)
      :ok = RuntimeState.set_session_model(nil)
      Process.sleep(50)
      assert RuntimeState.get_session_model() == nil
    end
  end

  describe "reset_session_model/0" do
    test "clears the session model" do
      :ok = RuntimeState.set_session_model("to-reset")
      Process.sleep(50)
      :ok = RuntimeState.reset_session_model()
      Process.sleep(50)
      assert RuntimeState.get_session_model() == nil
    end
  end

  # ---------------------------------------------------------------------------
  # State Introspection
  # ---------------------------------------------------------------------------

  describe "get_state/0" do
    test "returns full state struct" do
      state = RuntimeState.get_state()

      assert Map.has_key?(state, :autosave_id)
      assert Map.has_key?(state, :session_model)
      assert Map.has_key?(state, :session_start_time)
    end

    test "session_start_time is a DateTime" do
      state = RuntimeState.get_state()
      assert %DateTime{} = state.session_start_time
    end
  end
end
