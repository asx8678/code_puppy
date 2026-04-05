defmodule Mana.Commands.CoreTest do
  @moduledoc """
  Tests for Mana.Commands.Core module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.{Core, Registry}
  alias Mana.Config.Store, as: ConfigStore
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

    # Start required services
    start_supervised!({ConfigStore, []})
    start_supervised!({Registry, []})
    start_supervised!({Store, []})

    # Register core commands
    Core.register_all()

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

  describe "Help command" do
    test "/help lists all commands" do
      assert {:ok, text} = Registry.dispatch("/help", [], %{})
      assert text =~ "Available commands:"
      assert text =~ "/help"
      assert text =~ "/exit"
      assert text =~ "/clear"
    end

    test "/help <command> shows command details" do
      assert {:ok, text} = Registry.dispatch("/help", ["exit"], %{})
      assert text =~ "Command: /exit"
      assert text =~ "Description:"
      assert text =~ "Usage:"
    end

    test "/help with slash prefix works" do
      assert {:ok, text} = Registry.dispatch("/help", ["/exit"], %{})
      assert text =~ "Command: /exit"
    end

    test "/help unknown command returns error" do
      assert {:error, "Unknown command: unknown"} = Registry.dispatch("/help", ["unknown"], %{})
    end
  end

  describe "Exit command" do
    test "/exit returns exit signal" do
      assert {:ok, {:exit, "Goodbye!"}} = Registry.dispatch("/exit", [], %{})
    end

    test "/exit with custom message" do
      assert {:ok, {:exit, "See you later"}} = Registry.dispatch("/exit", ["See", "you", "later"], %{})
    end
  end

  describe "Clear command" do
    test "/clear clears active session" do
      session_id = Store.create_session()

      # Add some messages using string keys (JSON-compatible)
      Store.append(session_id, %{"role" => "user", "content" => "Hello"})
      Store.append(session_id, %{"role" => "assistant", "content" => "Hi there"})

      assert {:ok, text} = Registry.dispatch("/clear", [], %{session_id: session_id})
      assert text =~ "cleared"

      # Verify session is empty
      assert Store.get_history(session_id) == []
    end

    test "/clear with no session returns error" do
      assert {:error, "No active session to clear"} = Registry.dispatch("/clear", [], %{})
    end
  end

  describe "Set command" do
    test "/set stores configuration value" do
      assert {:ok, "Set my_key to my_value"} = Registry.dispatch("/set", ["my_key", "my_value"], %{})

      # Verify it was stored
      assert ConfigStore.get(:my_key, nil) == "my_value"
    end

    test "/set without enough args returns error" do
      assert {:error, "Usage: /set <key> <value>"} = Registry.dispatch("/set", ["key"], %{})
      assert {:error, "Usage: /set <key> <value>"} = Registry.dispatch("/set", [], %{})
    end
  end

  describe "Show command" do
    test "/show displays configured value" do
      ConfigStore.put(:test_show_key, "test_value")

      assert {:ok, "test_show_key = \"test_value\""} = Registry.dispatch("/show", ["test_show_key"], %{})
    end

    test "/show for unset key" do
      assert {:ok, "unset_key is not a known config key"} = Registry.dispatch("/show", ["unset_key"], %{})
    end

    test "/show without args returns error" do
      assert {:error, "Usage: /show <key>"} = Registry.dispatch("/show", [], %{})
    end
  end

  describe "Cd command" do
    test "/cd with no args shows current directory" do
      cwd = File.cwd!()
      assert {:ok, text} = Registry.dispatch("/cd", [], %{})
      assert text =~ cwd
    end

    test "/cd changes directory" do
      temp_dir = System.tmp_dir!()
      assert {:ok, text} = Registry.dispatch("/cd", [temp_dir], %{})
      # macOS uses /private/var for temp dirs, so just check it changed
      assert text =~ "Changed directory to:"
      # macOS may add /private prefix to temp dirs
      assert String.ends_with?(File.cwd!(), Path.expand(temp_dir))
    end

    test "/cd to invalid directory returns error" do
      assert {:error, "Not a directory: /this/path/does/not/exist"} =
               Registry.dispatch("/cd", ["/this/path/does/not/exist"], %{})
    end
  end

  describe "Sessions command" do
    test "/sessions lists all sessions" do
      # Create some sessions
      id1 = Store.create_session()
      id2 = Store.create_session()

      assert {:ok, text} = Registry.dispatch("/sessions", [], %{})
      assert text =~ "Available sessions:"
      assert text =~ id1
      assert text =~ id2
      assert text =~ "(active)"
    end

    test "/sessions with no sessions" do
      assert {:ok, "No sessions available."} = Registry.dispatch("/sessions", [], %{})
    end
  end

  describe "Session command" do
    test "/session shows active session" do
      id = Store.create_session()

      assert {:ok, text} = Registry.dispatch("/session", [], %{})
      assert text =~ id
    end

    test "/session with no active session" do
      assert {:ok, "No active session. Use '/session new' to create one."} =
               Registry.dispatch("/session", [], %{})
    end

    test "/session new creates new session" do
      assert {:ok, text} = Registry.dispatch("/session", ["new"], %{})
      assert text =~ "Created new session:"
      assert text =~ "session_"
    end

    test "/session <id> switches to existing session" do
      id1 = Store.create_session()
      # Create another session to make sure id1 is not active
      _id2 = Store.create_session()

      # Switch back to id1
      assert {:ok, text} = Registry.dispatch("/session", [id1], %{})
      assert text =~ "Switched to session: #{id1}"
    end

    test "/session with invalid id returns error" do
      assert {:error, "Session not found: nonexistent"} =
               Registry.dispatch("/session", ["nonexistent"], %{})
    end
  end

  describe "register_all/0" do
    test "all core commands are registered" do
      commands = Registry.list_commands()

      assert "/help" in commands
      assert "/exit" in commands
      assert "/clear" in commands
      assert "/set" in commands
      assert "/show" in commands
      assert "/cd" in commands
      assert "/sessions" in commands
      assert "/session" in commands
    end
  end
end
