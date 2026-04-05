defmodule Mana.Commands.SessionTest do
  @moduledoc """
  Tests for Mana.Commands.Session and related session management commands.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Compact
  alias Mana.Commands.Load
  alias Mana.Commands.Save
  alias Mana.Commands.Session
  alias Mana.Commands.Truncate
  alias Mana.Session.Store, as: SessionStore

  setup do
    # Start required GenServers
    start_supervised!({SessionStore, []})

    :ok
  end

  describe "Session command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Session, :name, 0)
      assert function_exported?(Session, :description, 0)
      assert function_exported?(Session, :usage, 0)
      assert function_exported?(Session, :execute, 2)
    end

    test "name returns '/session'" do
      assert Session.name() == "/session"
    end

    test "description returns expected string" do
      assert Session.description() == "Manage conversation sessions"
    end

    test "usage returns expected string" do
      assert Session.usage() == "/session [list|new|delete <id>]"
    end
  end

  describe "Session.execute/2 - list" do
    test "returns list of sessions" do
      # Create a session
      session_id = SessionStore.create_session()

      assert {:ok, result} = Session.execute(["list"], %{})
      assert result =~ "Sessions:"
      assert result =~ session_id
    end

    test "marks active session" do
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      assert {:ok, result} = Session.execute(["list"], %{})
      assert result =~ "(active)"
    end
  end

  describe "Session.execute/2 - new" do
    test "creates a new session" do
      assert {:ok, result} = Session.execute(["new"], %{})
      assert result =~ "Created session:"
      assert result =~ "session_"
    end

    test "new session becomes active" do
      {:ok, result} = Session.execute(["new"], %{})
      [_, session_id] = String.split(result, ": ")

      assert SessionStore.active_session() == String.trim(session_id)
    end
  end

  describe "Session.execute/2 - delete" do
    test "deletes an existing session" do
      # Create a session first
      session_id = SessionStore.create_session()

      assert {:ok, result} = Session.execute(["delete", session_id], %{})
      assert result == "Deleted session: #{session_id}"

      # Verify it's gone
      refute session_id in SessionStore.list_sessions()
    end
  end

  describe "Session.execute/2 - usage" do
    test "returns usage when called with no args" do
      assert {:ok, result} = Session.execute([], %{})
      assert result == "Usage: #{Session.usage()}"
    end

    test "returns usage when called with invalid args" do
      assert {:ok, result} = Session.execute(["invalid"], %{})
      assert result == "Usage: #{Session.usage()}"
    end
  end

  describe "Save command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Mana.Commands.Save, :name, 0)
      assert function_exported?(Mana.Commands.Save, :description, 0)
      assert function_exported?(Mana.Commands.Save, :usage, 0)
      assert function_exported?(Mana.Commands.Save, :execute, 2)
    end

    test "name returns '/save'" do
      assert Mana.Commands.Save.name() == "/save"
    end

    test "description returns expected string" do
      assert Mana.Commands.Save.description() == "Save current session"
    end

    test "usage returns expected string" do
      assert Mana.Commands.Save.usage() == "/save"
    end
  end

  describe "Save.execute/2" do
    test "saves current session" do
      # Create and activate a session
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      # Add some messages
      SessionStore.append(session_id, %{role: "user", content: "Hello"})

      assert {:ok, result} = Mana.Commands.Save.execute([], %{})
      assert result == "Session saved."
    end

    test "returns error when no active session" do
      # Ensure no active session
      SessionStore.set_active_session(nil)

      assert {:error, message} = Mana.Commands.Save.execute([], %{})
      assert message == "No active session to save"
    end
  end

  describe "Load command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Mana.Commands.Load, :name, 0)
      assert function_exported?(Mana.Commands.Load, :description, 0)
      assert function_exported?(Mana.Commands.Load, :usage, 0)
      assert function_exported?(Mana.Commands.Load, :execute, 2)
    end

    test "name returns '/load'" do
      assert Mana.Commands.Load.name() == "/load"
    end

    test "description returns expected string" do
      assert Mana.Commands.Load.description() == "Load a saved session"
    end

    test "usage returns expected string" do
      assert Mana.Commands.Load.usage() == "/load <session_id>"
    end
  end

  describe "Load.execute/2" do
    test "loads an existing session" do
      # Create, populate and save a session
      session_id = SessionStore.create_session()
      SessionStore.append(session_id, %{role: "user", content: "Test message"})
      :ok = SessionStore.save(session_id)

      # Clear the session from memory (but keep on disk)
      SessionStore.clear(session_id)

      assert {:ok, result} = Mana.Commands.Load.execute([session_id], %{})
      assert result == "Loaded session: #{session_id}"

      # Verify it's active
      assert SessionStore.active_session() == session_id
    end

    test "returns usage when called with no args" do
      assert {:ok, result} = Mana.Commands.Load.execute([], %{})
      assert result == "Usage: #{Mana.Commands.Load.usage()}"
    end

    test "returns error for non-existent session" do
      assert {:error, message} = Mana.Commands.Load.execute(["nonexistent-session-12345"], %{})
      assert message =~ "Failed to load session"
    end
  end

  describe "Compact command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Mana.Commands.Compact, :name, 0)
      assert function_exported?(Mana.Commands.Compact, :description, 0)
      assert function_exported?(Mana.Commands.Compact, :usage, 0)
      assert function_exported?(Mana.Commands.Compact, :execute, 2)
    end

    test "name returns '/compact'" do
      assert Mana.Commands.Compact.name() == "/compact"
    end

    test "description returns expected string" do
      assert Mana.Commands.Compact.description() == "Compact conversation history via summarization"
    end

    test "usage returns expected string" do
      assert Mana.Commands.Compact.usage() == "/compact"
    end
  end

  describe "Compact.execute/2" do
    setup do
      # Start the ModelsRegistry needed for summarization
      start_supervised!({Mana.Models.Registry, []})
      :ok
    end

    test "returns error when no active session" do
      SessionStore.set_active_session(nil)

      assert {:error, message} = Mana.Commands.Compact.execute([], %{})
      assert message == "No active session"
    end

    test "handles empty session" do
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      assert {:ok, result} = Mana.Commands.Compact.execute([], %{})
      assert result == "No messages to compact."
    end

    @tag :skip
    test "compacts session with messages" do
      # Skipped - requires full ModelsRegistry for summarization
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      # Add several messages
      for i <- 1..15 do
        SessionStore.append(session_id, %{role: "user", content: "Message #{i}"})
        SessionStore.append(session_id, %{role: "assistant", content: "Response #{i}"})
      end

      result = Mana.Commands.Compact.execute([], %{})

      # Should return success with compaction stats
      assert {:ok, message} = result
      assert message =~ "Compacted"
    end
  end

  describe "Truncate command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Mana.Commands.Truncate, :name, 0)
      assert function_exported?(Mana.Commands.Truncate, :description, 0)
      assert function_exported?(Mana.Commands.Truncate, :usage, 0)
      assert function_exported?(Mana.Commands.Truncate, :execute, 2)
    end

    test "name returns '/truncate'" do
      assert Mana.Commands.Truncate.name() == "/truncate"
    end

    test "description returns expected string" do
      assert Mana.Commands.Truncate.description() == "Truncate conversation to last N messages"
    end

    test "usage returns expected string" do
      assert Mana.Commands.Truncate.usage() == "/truncate <count>"
    end
  end

  describe "Truncate.execute/2" do
    test "returns error when no active session" do
      SessionStore.set_active_session(nil)

      assert {:error, message} = Mana.Commands.Truncate.execute(["10"], %{})
      assert message == "No active session"
    end

    test "truncates session to specified count" do
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      # Add several messages
      for i <- 1..10 do
        SessionStore.append(session_id, %{role: "user", content: "Message #{i}"})
      end

      assert {:ok, result} = Mana.Commands.Truncate.execute(["5"], %{})
      assert result == "Truncated to 5 messages (removed 5)."

      # Verify only 5 remain
      history = SessionStore.get_history(session_id)
      assert length(history) == 5
    end

    test "returns error for invalid count" do
      session_id = SessionStore.create_session()
      SessionStore.set_active_session(session_id)

      assert {:error, message} = Mana.Commands.Truncate.execute(["invalid"], %{})
      assert message =~ "Invalid count"
    end

    test "returns usage when called with no args" do
      assert {:ok, result} = Mana.Commands.Truncate.execute([], %{})
      assert result == "Usage: #{Mana.Commands.Truncate.usage()}"
    end
  end
end
