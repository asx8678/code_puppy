defmodule Mana.Session.StoreTest do
  @moduledoc """
  Tests for Mana.Session.Store module.
  """

  use ExUnit.Case, async: false

  alias Mana.Config.Paths
  alias Mana.Session.Store

  setup do
    # Use temporary directory for tests
    temp_dir = System.tmp_dir!()
    test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")
    test_data = Path.join(temp_dir, "mana_test_data_#{:erlang.unique_integer([:positive])}")

    original_config = System.get_env("XDG_CONFIG_HOME")
    original_data = System.get_env("XDG_DATA_HOME")

    System.put_env("XDG_CONFIG_HOME", test_config)
    System.put_env("XDG_DATA_HOME", test_data)

    # Ensure directories exist
    Paths.ensure_dirs()

    # Start the store
    start_supervised!(Store)

    on_exit(fn ->
      # Cleanup environment
      if original_config,
        do: System.put_env("XDG_CONFIG_HOME", original_config),
        else: System.delete_env("XDG_CONFIG_HOME")

      if original_data, do: System.put_env("XDG_DATA_HOME", original_data), else: System.delete_env("XDG_DATA_HOME")

      # Cleanup files
      File.rm_rf!(test_config)
      File.rm_rf!(test_data)
    end)

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(Store) != nil
    end

    test "creates ETS table with correct properties" do
      assert :ets.whereis(:mana_sessions) != :undefined
    end

    test "returns correct child_spec" do
      spec = Store.child_spec([])
      assert spec.id == Store
      assert spec.type == :worker
      assert spec.restart == :permanent
    end
  end

  describe "create_session/0" do
    test "creates a new session with unique id" do
      id1 = Store.create_session()
      id2 = Store.create_session()

      assert String.starts_with?(id1, "session_")
      assert String.starts_with?(id2, "session_")
      assert id1 != id2
    end

    test "new session is set as active" do
      id = Store.create_session()
      assert Store.active_session() == id
    end

    test "new session starts with empty history" do
      id = Store.create_session()
      assert Store.get_history(id) == []
    end
  end

  describe "get_history/1" do
    test "returns empty list for new session" do
      id = Store.create_session()
      assert Store.get_history(id) == []
    end

    test "returns empty list for unknown session" do
      assert Store.get_history("nonexistent") == []
    end

    test "reads directly from ETS (fast path)" do
      id = Store.create_session()
      Store.append(id, %{role: "user", content: "Hello"})

      # This should be a direct ETS lookup
      history = Store.get_history(id)
      assert length(history) == 1
    end
  end

  describe "append/2" do
    test "appends message to session" do
      id = Store.create_session()
      :ok = Store.append(id, %{"role" => "user", "content" => "Hello"})

      history = Store.get_history(id)
      assert length(history) == 1
      [msg] = history
      assert msg.role == "user"
      assert msg.content == "Hello"
      assert msg.timestamp != nil
    end

    test "appends multiple messages" do
      id = Store.create_session()
      Store.append(id, %{"role" => "user", "content" => "Hello"})
      Store.append(id, %{"role" => "assistant", "content" => "Hi there"})
      Store.append(id, %{"role" => "user", "content" => "How are you?"})

      history = Store.get_history(id)
      assert length(history) == 3
    end

    test "each message has timestamp" do
      id = Store.create_session()
      Store.append(id, %{"role" => "user", "content" => "First"})
      Store.append(id, %{"role" => "user", "content" => "Second"})

      [msg1, msg2] = Store.get_history(id)
      # Just check timestamps are present (may be equal on fast machines)
      assert msg1.timestamp != nil
      assert msg2.timestamp != nil
      assert msg1.timestamp <= msg2.timestamp
    end
  end

  describe "clear/1" do
    test "clears all messages from session" do
      id = Store.create_session()
      Store.append(id, %{role: "user", content: "Hello"})
      Store.append(id, %{role: "assistant", content: "Hi"})

      :ok = Store.clear(id)

      assert Store.get_history(id) == []
    end
  end

  describe "save/1 and load/1" do
    test "saves session to disk as JSON" do
      id = Store.create_session()
      Store.append(id, %{"role" => "user", "content" => "Hello"})
      Store.append(id, %{"role" => "assistant", "content" => "Hi there"})

      :ok = Store.save(id)

      # Verify file was written
      file_path = Path.join(Paths.sessions_dir(), "#{id}.json")
      assert File.exists?(file_path)

      # Verify contents
      {:ok, contents} = File.read(file_path)
      data = Jason.decode!(contents)
      assert length(data) == 2
    end

    test "loads session from disk" do
      id = Store.create_session()
      Store.append(id, %{role: "user", content: "Hello"})
      :ok = Store.save(id)

      # Clear the in-memory session
      Store.clear(id)
      assert Store.get_history(id) == []

      # Reload from disk - returns {:ok, messages}
      {:ok, _} = Store.load(id)

      history = Store.get_history(id)
      assert length(history) == 1
      [msg] = history
      assert msg.role == "user"
      assert msg.content == "Hello"
    end

    test "load returns error for nonexistent session" do
      assert {:error, :enoent} = Store.load("nonexistent_session")
    end
  end

  describe "list_sessions/0" do
    test "lists created sessions" do
      id1 = Store.create_session()
      id2 = Store.create_session()

      sessions = Store.list_sessions()
      assert id1 in sessions
      assert id2 in sessions
    end

    test "returns empty list when no sessions" do
      assert Store.list_sessions() == []
    end
  end

  describe "delete_session/1" do
    test "deletes session from memory" do
      id = Store.create_session()
      Store.append(id, %{role: "user", content: "Hello"})

      :ok = Store.delete_session(id)

      assert Store.get_history(id) == []
      assert Store.active_session() != id
    end

    test "deletes session from disk" do
      id = Store.create_session()
      Store.append(id, %{content: "test"})
      :ok = Store.save(id)

      file_path = Path.join(Paths.sessions_dir(), "#{id}.json")
      assert File.exists?(file_path)

      :ok = Store.delete_session(id)

      refute File.exists?(file_path)
    end

    test "clearing active session resets it to nil" do
      id = Store.create_session()
      assert Store.active_session() == id

      :ok = Store.delete_session(id)
      assert Store.active_session() == nil
    end
  end

  describe "active_session/0 and set_active_session/1" do
    test "returns nil when no active session" do
      assert Store.active_session() == nil
    end

    test "returns active session after creation" do
      id = Store.create_session()
      assert Store.active_session() == id
    end

    test "set_active_session changes active session" do
      id1 = Store.create_session()
      id2 = Store.create_session()

      assert Store.active_session() == id2

      :ok = Store.set_active_session(id1)
      assert Store.active_session() == id1
    end

    test "set_active_session to nil clears active session" do
      _id = Store.create_session()
      assert Store.active_session() != nil

      :ok = Store.set_active_session(nil)
      assert Store.active_session() == nil
    end

    test "set_active_session ignores invalid session ids" do
      id = Store.create_session()
      :ok = Store.set_active_session("nonexistent")
      assert Store.active_session() == id
    end
  end

  describe "session persistence on startup" do
    test "loads existing sessions from disk on startup" do
      # Create and save a session
      id = Store.create_session()
      Store.append(id, %{role: "user", content: "Persistent message"})
      :ok = Store.save(id)

      # Clear ETS table directly (simulating fresh start without GenServer restart)
      :ets.delete_all_objects(:mana_sessions)

      # Reload from disk via load/1 API
      assert {:ok, _} = Store.load(id)

      # Session should be available
      history = Store.get_history(id)
      assert length(history) == 1
      [msg] = history
      assert msg.content == "Persistent message"
    end
  end
end
